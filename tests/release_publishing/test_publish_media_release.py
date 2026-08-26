"""The media release publisher, and every way a release could lie.

A release page is the last place an unverified byte should ever stand: it is the
one artifact this project ships with a download button attached. So the tests
here exercise three things with equal weight — that a fully qualified tree flows
end to end (split, upload, resume, verify, publish) against a recording fake of
the GitHub API; that each way a tree could lie (a tampered medium, a failed boot
verdict, provenance from another commit, an unmanifested second ISO, a stale
RELEASE-SHA256SUMS) ends in a refusal before anything is written to GitHub; and
that the resume rules hold against GitHub's real semantics — drafts are invisible
to the by-tag lookup, an interrupted run is adopted rather than duplicated, and
an already-published release is never rewritten in place.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build/scripts/publish_media_release.py"

_loader = SourceFileLoader("publish_media_release", str(SCRIPT))
_spec = spec_from_loader(_loader.name, _loader)
pub = module_from_spec(_spec)
_loader.exec_module(pub)

COMMIT = "e906a48793d74544b39c14cc3e35e0654f5311e2"
OTHER_COMMIT = "f" * 40
ISO_NAME = "bunny-os-0.3.0-live.test1234-x86_64.iso"
ISO_SUBDIR = "bootc-fedora-44-bootc-generic-iso-x86_64"
REPO = "example/bunny-os"

EXPECTED_ASSETS = {f"{ISO_NAME}.part-{i:02d}" for i in range(3)} | {
    "BUNNY-MANIFEST.json", "provenance.json", "boot-artifacts.json",
    "iso-digest.txt", "SHA256SUMS", "RELEASE-SHA256SUMS",
}


def pseudo_bytes(count: int) -> bytes:
    """Deterministic content whose blocks are not all alike."""
    out = bytearray()
    block = b"\x00"
    while len(out) < count:
        block = hashlib.sha256(block).digest() * 64
        out += block
    return bytes(out[:count])


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_tree(root: Path, iso: bytes, *, boot_status: str = "PASS",
              provenance_commit: str | None = None,
              drop_evidence: tuple[str, ...] = (),
              extra_iso: bool = False) -> Path:
    """Build a media tree the way build-live-image.sh leaves one behind."""
    (root / ISO_SUBDIR).mkdir(parents=True)
    rel_iso = f"{ISO_SUBDIR}/{ISO_NAME}"
    (root / rel_iso).write_bytes(iso)
    if extra_iso:
        (root / "other.iso").write_bytes(b"not the medium")

    provenance = {
        "schemaVersion": 1,
        "profile": "live",
        "sourceCommit": provenance_commit or COMMIT,
        "sourceDateEpoch": 1750000000,
        "recordedAt": "2026-08-17T13:36:00Z",
        "baseImage": "localhost/bunny-os-retained-base@" + "b" * 64,
        "imageReference": "localhost/bunny-os-live:test",
        "archiveOnly": False,
        "diskImages": [rel_iso],
        "buildModeNote": "Full build.",
        "tools": {"podman": "podman version 5.8.4", "imageBuilder": "{}"},
        "builder": {
            "distribution": "Fedora Linux 44", "kernel": "6.14.0",
            "virtualization": "wsl", "architecture": "x86_64",
            "cpuCount": "8", "containerStorageDriver": "overlay",
            "bootId": "00000000-0000-0000-0000-000000000000",
        },
        "artifacts": [{"path": rel_iso, "size": len(iso), "sha256": sha(iso)}],
        "reproducibility": {"repeatedBuildComparisonPerformed": False},
    }
    boot = {
        "status": boot_status,
        "checks": [{"check": "grub-entry-names-kernel", "status": boot_status, "detail": "d"}],
    }
    payloads = {
        "provenance.json": json.dumps(provenance, indent=2).encode(),
        "boot-artifacts.json": json.dumps(boot, indent=1).encode(),
        "iso-digest.txt": f"{sha(iso)}  /root/bunny-os/build/out/live/{rel_iso}\n".encode(),
    }
    for name in drop_evidence:
        payloads.pop(name, None)
    for name, blob in payloads.items():
        (root / name).write_bytes(blob)
    sums = "".join(f"{sha(blob)}  {name}\n" for name, blob in sorted(payloads.items()))
    sums += f"{sha(iso)}  {rel_iso}\n"
    # write_bytes, never write_text: a text-mode write turns every \n into
    # \r\n on Windows and the file stops being the bytes whose digest the
    # manifest records.
    (root / "SHA256SUMS").write_bytes(sums.encode("utf-8"))

    entries = []
    critical_names = {"SHA256SUMS", "provenance.json"}
    for name, blob in list(payloads.items()) + [("SHA256SUMS", sums.encode()), (rel_iso, iso)]:
        entries.append({"path": name, "sha256": sha(blob), "critical": name in critical_names})
    manifest = {
        "schemaVersion": 1,
        "imageVersion": "0.3.0-live.test1234",
        "sourceCommit": COMMIT,
        "files": sorted(entries, key=lambda e: e["path"]),
    }
    (root / "BUNNY-MANIFEST.json").write_bytes(json.dumps(manifest, indent=2).encode("utf-8"))
    return root


def manifest_extra_file(tree: Path, rel: str, blob: bytes) -> None:
    """Add a file to an existing fixture tree and pin it in its manifest."""
    (tree / rel).write_bytes(blob)
    manifest = json.loads((tree / "BUNNY-MANIFEST.json").read_text())
    manifest["files"].append({"path": rel, "sha256": sha(blob), "critical": False})
    (tree / "BUNNY-MANIFEST.json").write_text(json.dumps(manifest))


def seed_asset(state: dict, release: dict, name: str, data: bytes) -> dict:
    """Plant an already-uploaded asset on a release, the way a dead run would."""
    state["next_id"] += 1
    record = {"id": state["next_id"], "name": name, "size": len(data),
              "digest": f"sha256:{sha(data)}"}
    release["assets"][name] = record
    return record


class FakeTransport:
    """The GitHub API as a small in-memory state machine.

    Records every asset body it receives so tests can compare uploaded bytes
    with local ones, and supports fault injection per phase. Two behaviors
    mirror the real API deliberately: GET /releases/tags/{tag} never matches a
    draft release (only the plain list does), and upload can be made to return
    server statuses, not just drop connections.
    """

    def __init__(self, state: dict):
        self.state = state
        self.calls: list[tuple] = []
        self.upload_bodies: dict[str, bytes] = {}
        self.attempts: dict[str, int] = {}
        self.fail_uploads_remaining = 0
        self.upload_status_queue: list[tuple[int, dict | None]] = []
        self.corrupt_uploaded_size = False
        self.corrupt_uploaded_digest = False

    def api(self, method: str, path: str, payload=None):
        self.calls.append((method, path))
        repo_path = f"/repos/{REPO}"
        if method == "GET" and path.startswith(f"{repo_path}/commits/"):
            commit = path.rsplit("/", 1)[1]
            return (200, {"sha": commit}) if commit in self.state["commits"] else (404, {"message": "no commit"})
        if method == "GET" and path.startswith(f"{repo_path}/git/ref/tags/"):
            tag = path.rsplit("/", 1)[1]
            if tag in self.state["tags"]:
                return 200, {"ref": f"refs/tags/{tag}",
                             "object": {"type": "commit", "sha": self.state["tags"][tag]}}
            return 404, {"message": "no ref"}
        if method == "POST" and path == f"{repo_path}/git/refs":
            ref, sha = payload["ref"], payload["sha"]
            tag = ref.rsplit("/", 1)[1]
            if tag in self.state["tags"]:
                return 422, {"message": "Reference already exists"}
            self.state["tags"][tag] = sha
            return 201, {"ref": ref, "object": {"type": "commit", "sha": sha}}
        if method == "GET" and path.startswith(f"{repo_path}/releases/tags/"):
            # Upstream semantics: this endpoint returns only the *published*
            # release for a tag; drafts are invisible here and reachable only
            # through the plain release list below.
            tag = path.rsplit("/", 1)[1]
            for release in self.state["releases"]:
                if release["tag_name"] == tag and not release.get("draft"):
                    return 200, release
            return 404, {"message": "not found"}
        if method == "GET" and path.startswith(f"{repo_path}/releases?"):
            return 200, list(self.state["releases"])
        if method == "POST" and path == f"{repo_path}/releases":
            release = {
                "id": self._next_id(), "tag_name": payload["tag_name"],
                "body": payload.get("body"), "draft": payload.get("draft", True),
                "prerelease": payload.get("prerelease"),
                "html_url": f"https://github.com/{REPO}/releases/x", "assets": {},
            }
            release["_target"] = payload.get("target_commitish")
            self.state["releases"].append(release)
            return 201, release
        if method == "GET" and "/assets?" in path:
            assets = sorted(self._release_by_id(path)["assets"].values(), key=lambda a: a["id"])
            return 200, assets
        if method == "DELETE" and "/releases/assets/" in path:
            asset_id = int(path.rsplit("/", 1)[1])
            for release in self.state["releases"]:
                for name, asset in list(release["assets"].items()):
                    if asset["id"] == asset_id:
                        del release["assets"][name]
                        return 204, None
            return 404, None
        if method == "PATCH" and path.startswith(f"{repo_path}/releases/"):
            release = self._release_by_id(path)
            release.update({k: v for k, v in (payload or {}).items()
                            if k in ("body", "draft", "prerelease")})
            return 200, release
        return 500, {"message": f"fake transport has no route for {method} {path}"}

    def _release_by_id(self, path: str) -> dict:
        segment = path.split("/releases/")[1].split("/")[0].split("?")[0]
        for release in self.state["releases"]:
            if release["id"] == int(segment):
                return release
        raise AssertionError(f"unknown release id in {path}")

    def _next_id(self) -> int:
        self.state["next_id"] += 1
        return self.state["next_id"]

    def upload(self, release_id: int, asset: dict):
        self.attempts[asset["name"]] = self.attempts.get(asset["name"], 0) + 1
        if self.fail_uploads_remaining > 0:
            self.fail_uploads_remaining -= 1
            raise OSError("connection dropped mid-flight")
        if self.upload_status_queue:
            status, body = self.upload_status_queue.pop(0)
            return status, body
        if "source" in asset:
            with open(asset["source"], "rb") as handle:
                handle.seek(asset["offset"])
                data = handle.read(asset["size"])
        else:
            data = Path(asset["path"]).read_bytes()
        self.upload_bodies[asset["name"]] = data
        size = len(data) - 1 if self.corrupt_uploaded_size else len(data)
        digest_hex = sha(data)
        if self.corrupt_uploaded_digest:
            # Same length, wrong value: exercises the digest arm of
            # verification with the size arm still agreeing.
            digest_hex = ("0" if digest_hex[0] != "0" else "1") + digest_hex[1:]
        record = {"id": self._next_id(), "name": asset["name"], "size": size,
                  "digest": f"sha256:{digest_hex}"}
        for release in self.state["releases"]:
            if release["id"] == release_id:
                release["assets"][asset["name"]] = record
        return 201, record


def fresh_state() -> dict:
    return {"commits": {COMMIT}, "tags": {}, "releases": [], "next_id": 100}


class PublisherEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.iso = pseudo_bytes(2500 * 1024)
        self.tree = make_tree(Path(self.tmp.name, "tree"), self.iso)
        self.work = Path(self.tmp.name, "work")
        self.state = fresh_state()
        self.transport: FakeTransport | None = None

    def _invoke(self, extra: list[str], *, tree: Path | None = None,
                transport: FakeTransport | None = None,
                part_mib: int | None = None) -> None:
        """Run main() against one fake transport, returning what main returns."""
        transport = transport or FakeTransport(self.state)
        self.transport = transport

        def factory(token, repo):
            return transport

        argv = ["--tree", str(tree or self.tree), "--repo", REPO,
                "--part-mib", str(part_mib if part_mib is not None else 1),
                "--work-dir", str(self.work)] + extra
        # The fake ignores the credential; pinning it here keeps the suite
        # independent of whatever GH_TOKEN the invoking shell happens to have.
        with mock.patch.dict(os.environ, {"GH_TOKEN": "fake-token"}):
            with mock.patch.object(pub, "GithubTransport", factory):
                pub.main(argv)

    def run_publish(self, extra: list[str] | None = None, *, tree: Path | None = None,
                    transport: FakeTransport | None = None) -> int:
        transport = transport or FakeTransport(self.state)
        self.transport = transport

        def factory(token, repo):
            return transport

        argv = ["--tree", str(tree or self.tree), "--repo", REPO,
                "--part-mib", "1", "--work-dir", str(self.work)] + (extra or [])
        with mock.patch.dict(os.environ, {"GH_TOKEN": "fake-token"}):
            with mock.patch.object(pub, "GithubTransport", factory):
                return pub.main(argv)

    def invoke_expecting(self, code: int, extra: list[str], *, tree: Path | None = None,
                         transport: FakeTransport | None = None) -> None:
        with self.assertRaises(SystemExit) as caught:
            self.run_publish(extra, tree=tree, transport=transport)
        self.assertEqual(caught.exception.code, code)

    def test_full_flow_creates_drafts_uploads_verifies_and_publishes(self):
        code = self.run_publish([])
        self.assertEqual(code, 0)
        release = self.state["releases"][0]
        self.assertEqual(release["tag_name"], "0.3.0-live.test1234")
        self.assertEqual(release["_target"], COMMIT)
        # Draft at creation; published only after every asset verified.
        self.assertFalse(release["draft"])
        self.assertTrue(release["prerelease"])
        self.assertEqual(set(release["assets"]), EXPECTED_ASSETS)
        # Uploaded part bytes equal the split bytes, and reassemble to the medium.
        part_zero = self.transport.upload_bodies[f"{ISO_NAME}.part-00"]
        self.assertEqual(len(part_zero), 1024 * 1024)
        joined = b"".join(self.transport.upload_bodies[f"{ISO_NAME}.part-{i:02d}"] for i in range(3))
        self.assertEqual(hashlib.sha256(joined).hexdigest(), hashlib.sha256(self.iso).hexdigest())
        # Every RELEASE-SHA256SUMS line describes the asset actually uploaded.
        sums = self.transport.upload_bodies["RELEASE-SHA256SUMS"].decode()
        for line in sums.strip().splitlines():
            digest, name = line.split(maxsplit=1)
            blob = self.transport.upload_bodies[name]
            self.assertEqual(hashlib.sha256(blob).hexdigest(), digest, f"sums entry wrong for {name}")
        # The notes carry the rejoin command and the pinned commit.
        self.assertIn("cat \\", release["body"])
        self.assertIn(COMMIT, release["body"])
        self.assertIn(f"'{ISO_NAME}.part-02' > '{ISO_NAME}'", release["body"])
        # The tag ref was created before the release, so GitHub never gets to
        # substitute its untagged-<slug> placeholder at publish time.
        self.assertEqual(self.state["tags"]["0.3.0-live.test1234"], COMMIT)

    def test_tag_ref_is_created_before_the_release_is(self):
        code = self.run_publish([])
        self.assertEqual(code, 0)
        calls = self.transport.calls
        ref_post = calls.index(("POST", f"/repos/{REPO}/git/refs"))
        release_post = calls.index(("POST", f"/repos/{REPO}/releases"))
        self.assertLess(ref_post, release_post,
                        "the tag must exist before any release can claim it")

    def test_raced_tag_pointing_elsewhere_is_refused(self):
        state = fresh_state()
        state["tags"]["0.3.0-live.test1234"] = OTHER_COMMIT
        transport = FakeTransport(state)
        publisher = pub.Publisher({"repo": REPO}, transport)
        with self.assertRaises(SystemExit) as caught:
            publisher.ensure_tag("0.3.0-live.test1234", COMMIT)
        self.assertEqual(caught.exception.code, 2)

    def test_single_asset_below_threshold_is_not_split(self):
        small_tree = Path(self.tmp.name, "small")
        small_iso = pseudo_bytes(512 * 1024)
        make_tree(small_tree, small_iso)
        code = self.run_publish([], tree=small_tree)
        self.assertEqual(code, 0)
        release = self.state["releases"][0]
        self.assertIn(ISO_NAME, release["assets"])
        self.assertNotIn(f"{ISO_NAME}.part-00", release["assets"])
        self.assertEqual(len(self.transport.upload_bodies[ISO_NAME]), len(small_iso))
        self.assertNotIn(".part-", release["body"])
        self.assertIn("sha256sum -c RELEASE-SHA256SUMS", release["body"])

    def test_dry_run_makes_no_network_calls_and_needs_no_token(self):
        transport = FakeTransport(self.state)
        transport.api = mock.MagicMock(side_effect=AssertionError("dry-run touched the network"))
        transport.upload = mock.MagicMock(side_effect=AssertionError("dry-run uploaded"))

        def factory(token, repo):
            return transport

        with mock.patch.object(pub, "GithubTransport", factory):
            code = pub.main(["--tree", str(self.tree), "--repo", REPO,
                             "--part-mib", "1", "--work-dir", str(self.work), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(self.state["releases"], [])

    def test_evidence_named_like_a_part_stays_out_of_the_rejoin_command(self):
        tree = make_tree(Path(self.tmp.name, "part-tree"), pseudo_bytes(2500 * 1024))
        manifest_extra_file(tree, "builder.part-notes.txt", b"harmless build log")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            pub.main(["--tree", str(tree), "--repo", REPO, "--part-mib", "1",
                      "--work-dir", str(self.work), "--dry-run"])
        notes = buffer.getvalue()
        self.assertIn("cat \\", notes, "the split branch should still render")
        # Shell lines are single-quoted; the evidence line is backticked prose.
        self.assertNotIn("'builder.part-notes.txt'", notes)
        self.assertIn("`builder.part-notes.txt`", notes)

    def test_rerun_skips_identical_and_replaces_changed_on_a_draft(self):
        self.run_publish(["--stay-draft"])
        release = self.state["releases"][0]
        before_ids = {name: asset["id"] for name, asset in release["assets"].items()}
        # A stale copy of one evidence file sits on the draft.
        release["assets"]["iso-digest.txt"]["size"] += 1
        code = self.run_publish([])
        self.assertEqual(code, 0)
        self.assertFalse(release["draft"])
        after_ids = {name: asset["id"] for name, asset in release["assets"].items()}
        self.assertNotEqual(after_ids["iso-digest.txt"], before_ids["iso-digest.txt"],
                            "changed asset was not replaced")
        self.assertEqual(after_ids["SHA256SUMS"], before_ids["SHA256SUMS"],
                         "identical asset was re-uploaded instead of skipped")

    def test_identical_rerun_of_a_published_release_changes_nothing(self):
        self.run_publish([])
        release = self.state["releases"][0]
        before_ids = {name: asset["id"] for name, asset in release["assets"].items()}
        code = self.run_publish([])
        self.assertEqual(code, 0)
        self.assertFalse(release["draft"])
        after_ids = {name: asset["id"] for name, asset in release["assets"].items()}
        self.assertEqual(after_ids, before_ids, "identical rerun mutated assets")
        mutating = [call for call in self.transport.calls if call[0] != "GET"]
        self.assertEqual(mutating, [],
                         "identical rerun wrote to a public release instead of verifying read-only")

    def test_divergent_rerun_of_a_published_release_is_refused(self):
        self.run_publish([])
        release = self.state["releases"][0]
        before_ids = {name: asset["id"] for name, asset in release["assets"].items()}
        # A different --part-mib plans different parts: replacements, a missing
        # tail and stranded orphans — everything an in-place rewrite would mean.
        self.invoke_expecting(2, ["--part-mib", "2"])
        after_ids = {name: asset["id"] for name, asset in release["assets"].items()}
        self.assertEqual(after_ids, before_ids, "refusal must precede any mutation")
        mutating = [call for call in self.transport.calls if call[0] != "GET"]
        self.assertEqual(mutating, [])

    def test_orphaned_assets_are_deleted_when_resuming(self):
        self.run_publish(["--stay-draft"])
        release = self.state["releases"][0]
        # Leftovers of an earlier attempt with a smaller --part-mib, plus a
        # foreign file nobody plans: none may survive to a published page.
        seed_asset(self.state, release, f"{ISO_NAME}.part-99", b"stale tail part")
        seed_asset(self.state, release, "notes-from-an-old-run.txt", b"junk")
        code = self.run_publish([])
        self.assertEqual(code, 0)
        self.assertFalse(release["draft"])
        self.assertEqual(set(release["assets"]), EXPECTED_ASSETS,
                         "unplanned assets survived the republish")

    def test_interrupted_run_is_adopted_not_duplicated(self):
        self.run_publish(["--stay-draft"])
        draft = self.state["releases"][0]
        draft_id = draft["id"]
        # Simulate a dead run's damage on the surviving draft.
        draft["assets"][f"{ISO_NAME}.part-01"]["size"] += 1
        del draft["assets"]["provenance.json"]
        seed_asset(self.state, draft, f"{ISO_NAME}.part-99", b"orphan of a dead scheme")
        code = self.run_publish([])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.state["releases"]), 1,
                         "rerunning an interrupted run minted a second release")
        self.assertEqual(draft["id"], draft_id)
        self.assertFalse(draft["draft"])
        self.assertEqual(set(draft["assets"]), EXPECTED_ASSETS)

    def test_run_that_dies_mid_upload_leaves_a_resumable_draft(self):
        dying = FakeTransport(self.state)
        dying.upload_status_queue = [(502, None)] * pub.UPLOAD_ATTEMPTS
        with mock.patch("time.sleep"):
            self.invoke_expecting(4, [], transport=dying)
        self.assertEqual(len(self.state["releases"]), 1)
        self.assertTrue(self.state["releases"][0]["draft"],
                        "a run that died must leave a draft nobody can download")
        # Rerunning picks the same draft up and finishes the job.
        code = self.run_publish([])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.state["releases"]), 1)
        release = self.state["releases"][0]
        self.assertFalse(release["draft"])
        self.assertEqual(set(release["assets"]), EXPECTED_ASSETS)

    def test_upload_retries_after_a_dropped_connection(self):
        transport = FakeTransport(self.state)
        transport.fail_uploads_remaining = 1

        with mock.patch.dict(os.environ, {"GH_TOKEN": "fake-token"}), \
             mock.patch.object(pub, "GithubTransport", lambda t, r: transport), \
             mock.patch("time.sleep"):
            code = pub.main(["--tree", str(self.tree), "--repo", REPO,
                             "--part-mib", "1", "--work-dir", str(self.work)])
        self.assertEqual(code, 0)
        self.assertIn("RELEASE-SHA256SUMS", self.state["releases"][0]["assets"])

    def test_transient_5xx_is_retried_until_success(self):
        transport = FakeTransport(self.state)
        transport.upload_status_queue = [(503, None)]
        with mock.patch.dict(os.environ, {"GH_TOKEN": "fake-token"}), \
             mock.patch.object(pub, "GithubTransport", lambda t, r: transport), \
             mock.patch("time.sleep"):
            code = pub.main(["--tree", str(self.tree), "--repo", REPO,
                             "--part-mib", "1", "--work-dir", str(self.work)])
        self.assertEqual(code, 0)
        # Assets upload in sorted order; the first one ate the transient fault.
        first_name = min(EXPECTED_ASSETS)
        self.assertEqual(transport.attempts[first_name], 2,
                         "a transient 503 must cost exactly one retry")

    def test_permanent_4xx_aborts_after_one_attempt(self):
        transport = FakeTransport(self.state)
        transport.upload_status_queue = [(422, {"message": "name already exists"})] * 10
        with mock.patch.dict(os.environ, {"GH_TOKEN": "fake-token"}), \
             mock.patch.object(pub, "GithubTransport", lambda t, r: transport), \
             mock.patch("time.sleep"):
            self.invoke_expecting(4, [], transport=transport)
        first_name = min(EXPECTED_ASSETS)
        self.assertEqual(transport.attempts[first_name], 1,
                         "client mistakes must not burn the retry budget")
        release = self.state["releases"][0]
        self.assertTrue(release["draft"])

    def test_persistent_5xx_exhausts_the_retry_budget(self):
        transport = FakeTransport(self.state)
        transport.upload_status_queue = [(502, None)] * (pub.UPLOAD_ATTEMPTS + 2)
        with mock.patch.dict(os.environ, {"GH_TOKEN": "fake-token"}), \
             mock.patch.object(pub, "GithubTransport", lambda t, r: transport), \
             mock.patch("time.sleep"):
            self.invoke_expecting(4, [], transport=transport)
        first_name = min(EXPECTED_ASSETS)
        self.assertEqual(transport.attempts[first_name], pub.UPLOAD_ATTEMPTS)

    def test_verification_failure_leaves_the_release_a_draft(self):
        transport = FakeTransport(self.state)
        transport.corrupt_uploaded_size = True
        self.invoke_expecting(5, [], transport=transport)
        release = self.state["releases"][0]
        self.assertTrue(release["draft"], "a failed verification must never publish")

    def test_digest_corruption_fails_verification_even_at_equal_size(self):
        transport = FakeTransport(self.state)
        transport.corrupt_uploaded_digest = True
        self.invoke_expecting(5, [], transport=transport)
        release = self.state["releases"][0]
        self.assertTrue(release["draft"])

    def test_same_size_wrong_digest_is_replaced_not_skipped(self):
        self.run_publish(["--stay-draft"])
        release = self.state["releases"][0]
        before_ids = {name: asset["id"] for name, asset in release["assets"].items()}
        release["assets"]["SHA256SUMS"]["digest"] = "sha256:" + "0" * 64
        code = self.run_publish([])
        self.assertEqual(code, 0)
        self.assertFalse(release["draft"])
        after_ids = {name: asset["id"] for name, asset in release["assets"].items()}
        self.assertNotEqual(after_ids["SHA256SUMS"], before_ids["SHA256SUMS"],
                            "right-size wrong-digest asset was skipped instead of replaced")

    def test_stay_draft_leaves_the_release_unpublished(self):
        code = self.run_publish(["--stay-draft"])
        self.assertEqual(code, 0)
        release = self.state["releases"][0]
        self.assertTrue(release["draft"])
        self.assertEqual(set(release["assets"]), EXPECTED_ASSETS)

    def test_stable_marks_prerelease_false(self):
        code = self.run_publish(["--stable"])
        self.assertEqual(code, 0)
        release = self.state["releases"][0]
        self.assertFalse(release["draft"])
        self.assertFalse(release["prerelease"], "--stable must reach the release")

    def test_stable_flips_prerelease_when_resuming_a_draft(self):
        self.run_publish(["--stay-draft"])
        release = self.state["releases"][0]
        self.assertTrue(release["prerelease"])
        code = self.run_publish(["--stable"])
        self.assertEqual(code, 0)
        self.assertFalse(release["draft"])
        self.assertFalse(release["prerelease"],
                         "--stable on the resume path must still reach the release")

    def test_missing_token_exits_3_without_touching_network(self):
        transport = FakeTransport(self.state)
        transport.api = mock.MagicMock(side_effect=AssertionError("network touched without token"))

        def factory(token, repo):
            return transport

        saved = {k: os.environ.pop(k) for k in ("GH_TOKEN", "BUNNY_GITHUB_TOKEN") if k in os.environ}
        try:
            with mock.patch.object(pub, "GithubTransport", factory):
                with self.assertRaises(SystemExit) as caught:
                    pub.main(["--tree", str(self.tree), "--repo", REPO,
                              "--part-mib", "1", "--work-dir", str(self.work)])
        finally:
            os.environ.update(saved)
        self.assertEqual(caught.exception.code, 3)

    def test_whitespace_only_token_exits_3(self):
        transport = FakeTransport(self.state)
        transport.api = mock.MagicMock(side_effect=AssertionError("network touched on blank token"))

        def factory(token, repo):
            return transport

        with mock.patch.dict(os.environ, {"GH_TOKEN": "   "}):
            with mock.patch.object(pub, "GithubTransport", factory):
                with self.assertRaises(SystemExit) as caught:
                    pub.main(["--tree", str(self.tree), "--repo", REPO,
                              "--part-mib", "1", "--work-dir", str(self.work)])
        self.assertEqual(caught.exception.code, 3)

    def test_part_mib_zero_is_refused_before_any_network_or_hashing(self):
        transport = FakeTransport(self.state)
        transport.api = mock.MagicMock(side_effect=AssertionError("network touched on bad flag"))

        def factory(token, repo):
            return transport

        with mock.patch.dict(os.environ, {"GH_TOKEN": "fake-token"}):
            with mock.patch.object(pub, "GithubTransport", factory):
                with self.assertRaises(SystemExit) as caught:
                    pub.main(["--tree", str(self.tree), "--repo", REPO,
                              "--part-mib", "0", "--work-dir", str(self.work)])
        self.assertEqual(caught.exception.code, 2)


class PublisherRefusals(unittest.TestCase):
    """Every way a tree could lie, and the refusal each one earns."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def refuses(self, tree: Path, state: dict | None = None) -> FakeTransport:
        transport = FakeTransport(state or fresh_state())

        def factory(token, repo):
            return transport

        with mock.patch.dict(os.environ, {"GH_TOKEN": "fake-token"}):
            with mock.patch.object(pub, "GithubTransport", factory):
                with self.assertRaises(SystemExit) as caught:
                    pub.main(["--tree", str(tree), "--repo", REPO,
                              "--part-mib", "10", "--work-dir", str(Path(self.tmp.name, "w"))])
        self.assertEqual(caught.exception.code, 2)
        # The suite docstring promises these fire before anything is written;
        # reads are fine (commit/tag lookups), writes never are.
        mutating = [call for call in transport.calls if call[0] != "GET"]
        self.assertEqual(mutating, [], "a tree-lie refusal must fire before any mutating call")
        return transport

    def test_tampered_medium_is_refused(self):
        tree = make_tree(Path(self.tmp.name, "tree"), pseudo_bytes(300 * 1024))
        iso = next((tree / ISO_SUBDIR).glob("*.iso"))
        iso.write_bytes(iso.read_bytes()[:-1] + b"\xff")
        self.refuses(tree)

    def test_manifest_digest_drift_is_refused(self):
        tree = make_tree(Path(self.tmp.name, "tree"), pseudo_bytes(300 * 1024))
        manifest = json.loads((tree / "BUNNY-MANIFEST.json").read_text())
        manifest["files"][0]["sha256"] = "0" * 64
        (tree / "BUNNY-MANIFEST.json").write_text(json.dumps(manifest))
        self.refuses(tree)

    def test_failed_boot_verdict_is_refused(self):
        tree = make_tree(Path(self.tmp.name, "tree"), pseudo_bytes(300 * 1024), boot_status="FAIL")
        self.refuses(tree)

    def test_provenance_from_another_commit_is_refused(self):
        tree = make_tree(Path(self.tmp.name, "tree"), pseudo_bytes(300 * 1024),
                         provenance_commit=OTHER_COMMIT)
        self.refuses(tree)

    def test_unmanifested_second_medium_is_refused(self):
        tree = make_tree(Path(self.tmp.name, "tree"), pseudo_bytes(300 * 1024), extra_iso=True)
        self.refuses(tree)

    def test_missing_boot_evidence_is_refused(self):
        tree = make_tree(Path(self.tmp.name, "tree"), pseudo_bytes(300 * 1024),
                         drop_evidence=("boot-artifacts.json",))
        self.refuses(tree)

    def test_absent_tree_is_refused(self):
        self.refuses(Path(self.tmp.name, "does-not-exist"))

    def test_tag_pointing_elsewhere_is_refused(self):
        tree = make_tree(Path(self.tmp.name, "tree"), pseudo_bytes(300 * 1024))
        state = fresh_state()
        # The tag the release would use already exists, naming another commit.
        state["tags"]["0.3.0-live.test1234"] = OTHER_COMMIT
        transport = self.refuses(tree, state)
        self.assertEqual(state["releases"], [], "another commit's tag must never be adopted")
        self.assertNotIn(("POST", f"/repos/{REPO}/releases"), transport.calls)

    def test_candidate_commit_not_on_origin_is_refused(self):
        tree = make_tree(Path(self.tmp.name, "tree"), pseudo_bytes(300 * 1024))
        state = fresh_state()
        state["commits"] = set()  # nothing pushed yet
        self.refuses(tree, state)

    def test_duplicate_asset_names_are_refused(self):
        tree = make_tree(Path(self.tmp.name, "tree"), pseudo_bytes(300 * 1024))
        clash = f"{ISO_SUBDIR}/boot-artifacts.json"
        payload = (tree / "boot-artifacts.json").read_bytes()
        manifest_extra_file(tree, clash, payload)
        self.refuses(tree)

    def test_tree_carrying_its_own_release_sha256sums_is_refused(self):
        tree = make_tree(Path(self.tmp.name, "tree"), pseudo_bytes(300 * 1024))
        # A prior release's sums file, archived beside a new medium: the
        # manifest writer pins it automatically, so this is a realistic tree.
        manifest_extra_file(tree, "RELEASE-SHA256SUMS", b"stale prior-release sums")
        self.refuses(tree)


class TransportUnit(unittest.TestCase):
    """The real transport's wiring, offline."""

    def test_api_passes_a_timeout_to_urlopen(self):
        captured = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"ok": true}'

        def fake_urlopen(request, timeout=None):
            captured["timeout"] = timeout
            return FakeResponse()

        with mock.patch.object(pub.urllib.request, "urlopen", fake_urlopen):
            status, body = pub.GithubTransport("t", REPO).api("GET", "/repos/x/y/commits/abc")
        self.assertEqual(captured["timeout"], pub.API_TIMEOUT,
                         "metadata calls without a timeout hang forever on a stalled connection")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True})

    def test_upload_connection_tunnels_through_a_configured_proxy(self):
        transport = pub.GithubTransport("t", REPO)
        proxies = {"https": "http://proxy.example:3128"}
        with mock.patch.object(pub.urllib.request, "getproxies", lambda: proxies):
            connection = transport._upload_connection()
        try:
            self.assertEqual(connection.host, "proxy.example")
            self.assertEqual(connection.port, 3128)
            self.assertEqual(getattr(connection, "_tunnel_host", ""), pub.GITHUB_UPLOAD_HOST,
                             "uploads must reach the upload host through the proxy tunnel")
        finally:
            connection.close()

    def test_upload_connection_goes_direct_without_a_proxy(self):
        transport = pub.GithubTransport("t", REPO)
        with mock.patch.object(pub.urllib.request, "getproxies", lambda: {}):
            connection = transport._upload_connection()
        try:
            self.assertEqual(connection.host, pub.GITHUB_UPLOAD_HOST)
            self.assertIsNone(getattr(connection, "_tunnel_host", None),
                              "no proxy configured must mean no tunnel")
        finally:
            connection.close()


class SplitMechanics(unittest.TestCase):
    """Ranges are arithmetic; digests must still match the bytes they name."""

    def test_exact_multiple_yields_no_empty_tail_part(self):
        with tempfile.TemporaryDirectory() as tmp:
            medium = Path(tmp, "m.iso")
            medium.write_bytes(pseudo_bytes(4 * 1024))
            parts = pub.plan_medium_parts(medium, 4 * 1024, 1024)
            self.assertEqual([p["size"] for p in parts], [1024, 1024, 1024, 1024])
            self.assertEqual([p["offset"] for p in parts], [0, 1024, 2048, 3072])
            self.assertEqual([p["name"] for p in parts],
                             [f"m.iso.part-{i:02d}" for i in range(4)])

    def test_more_than_ninety_nine_parts_widen_their_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            medium = Path(tmp, "m.iso")
            medium.write_bytes(pseudo_bytes(150 * 100))
            parts = pub.plan_medium_parts(medium, 150 * 100, 100)
            self.assertEqual(len(parts), 150)
            self.assertTrue(all(len(p["name"]) == len("m.iso.part-150") for p in parts))

    def test_ranges_and_digests_describe_the_real_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            medium = Path(tmp, "m.iso")
            content = pseudo_bytes(2500)
            medium.write_bytes(content)
            parts = pub.plan_medium_parts(medium, len(content), 1000)
            rebuilt = b"".join(content[p["offset"]:p["offset"] + p["size"]] for p in parts)
            self.assertEqual(rebuilt, content)
            for part in parts:
                chunk = content[part["offset"]:part["offset"] + part["size"]]
                self.assertEqual(part["sha256"], hashlib.sha256(chunk).hexdigest())


if __name__ == "__main__":
    unittest.main()
