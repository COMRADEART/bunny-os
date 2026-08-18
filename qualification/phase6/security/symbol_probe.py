#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 6 section 4 -- are the *named vulnerable functions* in the shipped binaries?

The grype database records, for each of the eight qualified advisories, the
import path and the specific symbols that carry the vulnerability. That is a far
more specific question than "is the module present", and it is the question an
independent reviewer needs answered before any disposition can be argued.

Method: read the binary's bytes and look for each symbol in the form the Go
linker actually writes it. A Go symbol for a method on an unexported type is
written ``<import path>.(*hostKeyDB).IsRevoked``, not ``hostKeyDB.IsRevoked``,
so both spellings are searched and both results are reported. Searching only
the database's spelling would report every symbol absent, which is how an
absence gets manufactured.

No shell pipeline is used anywhere in this file, deliberately. The Phase 5
probe's ``strings -a … | grep -qF …`` under ``set -o pipefail`` reported NO for
strings that were present: grep short-circuits on the first match, strings dies
of SIGPIPE, and pipefail promotes 141 to the pipeline status, so the test could
only ever answer NO. See PIPEFAIL_CORRECTION.md.
"""

from __future__ import annotations

import json
import pathlib
import re

OUTPUT = pathlib.Path("/out/symbols.json")

#: advisory -> (import path, [symbols]) exactly as the database records them.
ADVISORIES = {
    "GHSA-5cgq-3rg8-m6cv": ("golang.org/x/crypto/ssh/knownhosts", [
        "hostKeyDB.IsRevoked",
    ]),
    "GHSA-89gr-r52h-f8rx": ("golang.org/x/crypto/ssh", [
        "CertChecker.Authenticate", "CertChecker.CheckCert", "CertChecker.CheckHostKey",
        "Certificate.Verify", "Dial", "NewClientConn", "NewServerConn",
        "connection.serverAuthenticate", "skECDSAPublicKey.Verify", "skEd25519PublicKey.Verify",
    ]),
    "GHSA-f5wc-c3c7-36mc": ("golang.org/x/crypto/ssh/agent", [
        "client.Add", "keyring.Add",
    ]),
    "GHSA-jppx-rxg9-jmrx": ("golang.org/x/crypto/ssh/agent", [
        "keyring.Add",
    ]),
    "GHSA-rm3j-f69w-wqmq": ("golang.org/x/crypto/ssh", [
        "Dial", "NewClientConn", "NewServerConn", "Session.CombinedOutput", "Session.Output",
        "Session.Run", "Session.Shell", "Session.Start", "channel.Write",
        "channel.WriteExtended", "curve25519sha256.Client", "curve25519sha256.Server",
        "dhGEXSHA.Client", "dhGEXSHA.Server", "dhGroup.Client", "dhGroup.Server",
        "ecdh.Client", "ecdh.Server", "extChannel.Write",
        "mlkem768WithCurve25519sha256.Client", "mlkem768WithCurve25519sha256.Server",
    ]),
    "GHSA-vgwf-h737-ff37": ("golang.org/x/crypto/ssh", [
        "Client.Listen", "Client.ListenTCP", "Client.ListenUnix", "Dial", "NewClientConn",
        "NewServerConn", "Session.CombinedOutput", "Session.Output", "Session.RequestPty",
        "Session.RequestSubsystem", "Session.Run", "Session.SendRequest", "Session.Setenv",
        "Session.Shell", "Session.Signal", "Session.Start", "Session.WindowChange",
        "channel.SendRequest", "channel.handlePacket", "mux.SendRequest",
        "mux.handleGlobalPacket", "tcpListener.Close", "unixListener.Close",
    ]),
    "GHSA-x527-x647-q7gg": ("golang.org/x/crypto/ssh", [
        "NewServerConn", "connection.serverAuthenticate",
    ]),
    "GHSA-p77j-4mvh-x3m3": ("google.golang.org/grpc", [
        "Server.Serve", "Server.ServeHTTP", "Server.handleStream",
    ]),
}

BINARIES = ("/usr/bin/podman", "/usr/bin/skopeo", "/usr/sbin/podman", "/usr/sbin/skopeo")

#: Go writes build info as tab-separated ``dep\t<path>\t<version>\t<sum>`` lines,
#: and that is what a scanner matches a version-range advisory against. A byte
#: search for a package path says the code is linked; it says nothing about the
#: version, and the version is half the question. Measuring only one of the two
#: is how a binary that carries vulnerable-looking code at a *fixed* version gets
#: reported as exposed, and how one that carries a vulnerable *version* with the
#: affected code absent gets reported the same way.
BUILD_INFO = re.compile(rb"(?:dep|=>)\t([a-zA-Z0-9._/\-]+)\t(v[0-9][^\t\n\x00]*)")

#: Fixed versions the Critical advisories name, so presence can be compared
#: against them rather than eyeballed.
FIXED_VERSIONS = {
    "golang.org/x/crypto": "v0.52.0",
    "google.golang.org/grpc": "v1.73.0",
}


def spellings(import_path: str, symbol: str) -> list[str]:
    """Every form the Go linker might write this symbol as.

    ``Type.Method`` in the database becomes ``path.Type.Method`` for a value
    receiver and ``path.(*Type).Method`` for a pointer receiver. A bare
    ``Function`` becomes ``path.Function``.
    """
    if "." in symbol:
        type_name, method = symbol.rsplit(".", 1)
        return [
            f"{import_path}.{type_name}.{method}",
            f"{import_path}.(*{type_name}).{method}",
        ]
    return [f"{import_path}.{symbol}"]


def main() -> int:
    report = {}
    for target in BINARIES:
        path = pathlib.Path(target)
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        packages = sorted(set(
            match.decode()
            for match in re.findall(rb"golang\.org/x/crypto/ssh[a-z0-9/]*", data)
        ))
        modules = {}
        for match in BUILD_INFO.finditer(data):
            modules.setdefault(match.group(1).decode(), set()).add(match.group(2).decode())
        modules = {name: sorted(values) for name, values in modules.items()}

        per_advisory = {}
        for advisory, (import_path, symbols) in sorted(ADVISORIES.items()):
            package_present = data.count(import_path.encode()) > 0
            module_root = next(
                (name for name in sorted(modules, key=len, reverse=True)
                 if import_path == name or import_path.startswith(name + "/")),
                None,
            )
            embedded = modules.get(module_root, []) if module_root else []
            found, absent = [], []
            for symbol in symbols:
                hit = next(
                    (form for form in spellings(import_path, symbol)
                     if data.count(form.encode()) > 0),
                    None,
                )
                (found if hit else absent).append(
                    {"symbol": symbol, "linkerForm": hit} if hit else symbol
                )
            per_advisory[advisory] = {
                "importPath": import_path,
                "importPathPresent": package_present,
                "module": module_root,
                "embeddedVersions": embedded,
                "fixedVersion": FIXED_VERSIONS.get(module_root),
                "symbolsNamed": len(symbols),
                "symbolsPresent": len(found),
                "present": found,
                "absent": absent,
            }
        report[target] = {
            "bytes": len(data),
            "sshPackagePathsPresent": packages,
            "buildInfoModuleCount": len(modules),
            "buildInfoVersionsOfInterest": {
                name: modules.get(name, [])
                for name in ("golang.org/x/crypto", "google.golang.org/grpc",
                             "golang.org/x/net", "golang.org/x/text", "golang.org/x/mod")
            },
            "advisories": per_advisory,
        }

    for target, entry in sorted(report.items()):
        print("== %s (%d bytes) ==" % (target, entry["bytes"]))
        print("   x/crypto ssh package paths present: %d" % len(entry["sshPackagePathsPresent"]))
        print("   build-info versions: %s" % json.dumps(entry["buildInfoVersionsOfInterest"]))
        for advisory, detail in sorted(entry["advisories"].items()):
            print("   %-24s import=%-3s version=%-10s fixed=%-9s symbols %d/%d" % (
                advisory,
                "YES" if detail["importPathPresent"] else "no",
                ",".join(detail["embeddedVersions"]) or "-",
                detail["fixedVersion"] or "-",
                detail["symbolsPresent"], detail["symbolsNamed"],
            ))
            if detail["present"]:
                names = ", ".join(item["symbol"] for item in detail["present"][:6])
                print("        present: %s%s" % (
                    names, " …" if len(detail["present"]) > 6 else "",
                ))
        print()

    document = {
        "schemaVersion": 1,
        "record": "phase6-symbol-measurement",
        "method": "byte search of the shipped binary for each database-named symbol, in both Go linker spellings; no shell pipeline",
        "binaries": report,
        "whatThisEstablishes": (
            "Whether the specific functions the advisory names are linked into the shipped "
            "binary. A symbol that is present is compiled in; it is not thereby reachable "
            "from any Bunny-controlled input, and this measurement does not claim it is."
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print("wrote %s" % OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
