#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 6 section 4 -- measure Bunny's exposure to each Critical/High finding.

Runs INSIDE a container from the subject artifact's image. Produces facts, not
verdicts. Every fact is one an independent reviewer can re-derive from the same
image with the same commands, which is what section 5 requires of the package.

The distinction this file is built around: a scanner reports that a vulnerable
*version* of something is present. That is not the same as the vulnerable
*code path* being present, and neither is the same as it being reachable. This
probe answers the first two -- presence of the package, and presence of the
named vulnerable import inside each shipped binary -- and refuses to guess at
the third.

It deliberately does not assign dispositions. Section 4 forbids claiming
NOT_APPLICABLE merely because Bunny does not intentionally invoke a component,
and a probe that emitted dispositions would be doing exactly that.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

OUTPUT = pathlib.Path("/out/exposure.json")
SEARCH_ROOTS = ("/usr/bin", "/usr/sbin", "/usr/libexec", "/usr/lib64", "/usr/lib")

#: Advisories whose database record names the vulnerable import paths. Taken
#: verbatim from qualification/phase5/security/route/advisory-symbol-qualifiers.txt,
#: which was produced from the grype database, not written by hand.
QUALIFIED = {
    "GHSA-5cgq-3rg8-m6cv": ["golang.org/x/crypto/ssh/knownhosts"],
    "GHSA-89gr-r52h-f8rx": ["golang.org/x/crypto/ssh"],
    "GHSA-f5wc-c3c7-36mc": ["golang.org/x/crypto/ssh/agent"],
    "GHSA-jppx-rxg9-jmrx": ["golang.org/x/crypto/ssh/agent"],
    "GHSA-rm3j-f69w-wqmq": ["golang.org/x/crypto/ssh"],
    "GHSA-vgwf-h737-ff37": ["golang.org/x/crypto/ssh"],
    "GHSA-x527-x647-q7gg": ["golang.org/x/crypto/ssh"],
    "GHSA-p77j-4mvh-x3m3": ["google.golang.org/grpc"],
}

#: Module paths the Critical/High set names, so the probe can report which
#: binary carries which module regardless of whether the advisory is qualified.
MODULES = (
    "golang.org/x/crypto",
    "golang.org/x/net",
    "golang.org/x/text",
    "golang.org/x/mod",
    "google.golang.org/grpc",
    "go.opentelemetry.io/otel",
    "github.com/moby/buildkit",
    "github.com/docker/docker",
    "github.com/containers/podman/v5",
    "github.com/opencontainers/selinux",
    "github.com/sigstore/fulcio",
)

#: RPM-delivered packages the Critical/High set names.
RPM_PACKAGES = (
    "sqlite-libs", "curl", "libcurl", "fuse-overlayfs",
    "libldb", "libsmbclient", "libwbclient", "samba-client-libs", "samba-common",
    "kernel", "kernel-core", "kernel-modules",
)


def run(argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def is_elf(path: pathlib.Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"\x7fELF"
    except OSError:
        return False


def go_binaries():
    """Every ELF file large enough to plausibly be a Go binary.

    The size floor is a search optimisation, not a judgement: a Go binary that
    carries a whole module graph is never small. It is recorded in the output so
    a reviewer can see what the sweep could not have found.
    """
    found = []
    for root in SEARCH_ROOTS:
        base = pathlib.Path(root)
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            try:
                if not path.is_file() or path.is_symlink():
                    continue
                size = path.stat().st_size
            except OSError:
                continue
            if size < 2_000_000 or not is_elf(path):
                continue
            found.append((str(path), size))
    return sorted(set(found))


def contains(path: str, needle: str) -> bool:
    """Does this binary carry the literal string anywhere in its bytes?

    grep -c on a fixed string. A Go binary embeds its import paths, so absence
    of the string is strong evidence the package was not linked in. Presence is
    weaker: it shows the package is compiled in, not that it is called.
    """
    result = run(["/usr/bin/grep", "-c", "-a", "-F", needle, path])
    return result.returncode == 0 and result.stdout.strip() not in ("", "0")


def main() -> int:
    binaries = go_binaries()
    print("Go-candidate binaries found: %d" % len(binaries))

    binary_report = []
    for path, size in binaries:
        modules = [module for module in MODULES if contains(path, module)]
        if not modules:
            continue
        binary_report.append({"path": path, "bytes": size, "modulesPresent": modules})
        print("  %-40s %10d  %s" % (path, size, ", ".join(modules)))

    print()
    print("=== qualified advisories: is the named vulnerable import present? ===")
    qualified_report = {}
    for advisory, imports in sorted(QUALIFIED.items()):
        per_advisory = []
        for entry in binary_report:
            carriers = [name for name in imports if contains(entry["path"], name)]
            per_advisory.append({
                "binary": entry["path"],
                "importsPresent": carriers,
                "carriesVulnerableImport": bool(carriers),
            })
        carrying = [item["binary"] for item in per_advisory if item["carriesVulnerableImport"]]
        qualified_report[advisory] = {
            "vulnerableImports": imports,
            "binariesExamined": len(per_advisory),
            "binariesCarryingImport": carrying,
            "perBinary": per_advisory,
        }
        print("  %-24s %-42s carried by: %s" % (
            advisory, ",".join(imports),
            ", ".join(carrying) if carrying else "NONE of the examined binaries",
        ))

    print()
    print("=== rpm packages named by Critical/High findings ===")
    rpm_report = {}
    for package in RPM_PACKAGES:
        result = run(["/usr/bin/rpm", "-q", "--qf",
                      "%{NAME}|%{EPOCH}|%{VERSION}|%{RELEASE}|%{ARCH}\n", package])
        installed = result.returncode == 0
        rpm_report[package] = {
            "installed": installed,
            "record": result.stdout.strip() if installed else None,
        }
        print("  %-20s %s" % (package, result.stdout.strip() if installed else "NOT INSTALLED"))

    print()
    print("=== python distributions named by Critical/High findings ===")
    python_report = {}
    for name in ("protobuf", "google.protobuf"):
        hits = []
        for root in ("/usr/lib/python3.14/site-packages", "/usr/lib64/python3.14/site-packages",
                     "/usr/lib/python3.13/site-packages", "/usr/lib64/python3.13/site-packages"):
            base = pathlib.Path(root)
            if base.is_dir():
                hits += [str(p) for p in base.glob(name.replace(".", "/") + "*")]
        python_report[name] = hits
        print("  %-20s %s" % (name, hits if hits else "not found on the system path"))

    print()
    print("=== does the image ship an ssh client or server at all? ===")
    ssh_presence = {}
    for candidate in ("/usr/bin/ssh", "/usr/sbin/sshd", "/usr/bin/ssh-agent",
                      "/usr/bin/scp", "/usr/bin/sftp"):
        ssh_presence[candidate] = pathlib.Path(candidate).exists()
        print("  %-24s %s" % (candidate, "present" if ssh_presence[candidate] else "absent"))

    document = {
        "schemaVersion": 1,
        "record": "phase6-exposure-measurement",
        "method": "container from the subject artifact image, fixed-string search of shipped ELF binaries",
        "searchRoots": list(SEARCH_ROOTS),
        "elfSizeFloorBytes": 2_000_000,
        "elfSizeFloorNote": (
            "A search optimisation, not a judgement. Recorded so a reviewer can see what "
            "the sweep could not have found."
        ),
        "goCandidateBinaries": len(binaries),
        "binariesCarryingNamedModules": binary_report,
        "qualifiedAdvisories": qualified_report,
        "rpmPackages": rpm_report,
        "pythonDistributions": python_report,
        "sshPresence": ssh_presence,
        "whatThisDoesNotEstablish": [
            "Presence of an import shows the package was linked in, not that it is called.",
            "Absence of an import is strong evidence the code path is not in the binary, and is still not a disposition.",
            "Nothing here measures reachability from a Bunny-controlled input.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print()
    print("wrote %s" % OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
