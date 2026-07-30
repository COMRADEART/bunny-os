#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Diff the RPM header blobs stored in two rpm sqlite databases, tag by tag.

``Packages.blob`` in rpm's sqlite backend is an exported RPM header. Reporting
that fifty of them differ says nothing actionable; reporting that they differ in
``INSTALLTIME`` and nowhere else names the defect and its fix. This parses the
header's own on-disk structure, which is stable and documented:

    uint32   number of index entries
    uint32   size of the data section
    entry[]  { uint32 tag; uint32 type; int32 offset; uint32 count } × n
    data[]   the values, referenced by offset

Nothing is written back. The parser is read-only by construction and is used for
diagnosis, never as a step in producing an artifact — reconstructing a header
outside rpm's own code path is exactly what ADR-028 rejected, and this tool
exists so that decision does not have to be revisited blind.

Tag numbers are resolved to names through rpm's own Python bindings when they
are present, and fall back to a table of the tags this project has had to reason
about. An unknown tag is reported by number rather than dropped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import sys
from typing import Any

REFUSED = 2

TYPE_NAMES = {
    0: "NULL",
    1: "CHAR",
    2: "INT8",
    3: "INT16",
    4: "INT32",
    5: "INT64",
    6: "STRING",
    7: "BIN",
    8: "STRING_ARRAY",
    9: "I18NSTRING",
}

TYPE_WIDTH = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8}

#: The tags this project has had cause to name. Anything absent is reported by
#: number, which is still a usable diagnosis.
FALLBACK_TAGS = {
    62: "HEADERSIGNATURES",
    63: "HEADERIMMUTABLE",
    100: "HEADERI18NTABLE",
    257: "SIGSIZE",
    261: "SIGMD5",
    262: "SIGGPG",
    267: "DSAHEADER",
    268: "RSAHEADER",
    269: "SHA1HEADER",
    273: "SHA256HEADER",
    1000: "NAME",
    1001: "VERSION",
    1002: "RELEASE",
    1003: "EPOCH",
    1004: "SUMMARY",
    1005: "DESCRIPTION",
    1006: "BUILDTIME",
    1007: "BUILDHOST",
    1008: "INSTALLTIME",
    1009: "SIZE",
    1010: "DISTRIBUTION",
    1011: "VENDOR",
    1014: "LICENSE",
    1015: "PACKAGER",
    1016: "GROUP",
    1020: "URL",
    1021: "OS",
    1022: "ARCH",
    1027: "OLDFILENAMES",
    1028: "FILESIZES",
    1029: "FILESTATES",
    1030: "FILEMODES",
    1033: "FILERDEVS",
    1034: "FILEMTIMES",
    1035: "FILEDIGESTS",
    1036: "FILELINKTOS",
    1037: "FILEFLAGS",
    1039: "FILEUSERNAME",
    1040: "FILEGROUPNAME",
    1044: "SOURCERPM",
    1045: "FILEVERIFYFLAGS",
    1046: "ARCHIVESIZE",
    1047: "PROVIDENAME",
    1048: "REQUIREFLAGS",
    1049: "REQUIRENAME",
    1050: "REQUIREVERSION",
    1064: "RPMVERSION",
    1080: "CHANGELOGTIME",
    1081: "CHANGELOGNAME",
    1082: "CHANGELOGTEXT",
    1090: "OBSOLETENAME",
    1095: "FILEDEVICES",
    1096: "FILEINODES",
    1097: "FILELANGS",
    1112: "PROVIDEFLAGS",
    1113: "PROVIDEVERSION",
    1114: "OBSOLETEFLAGS",
    1115: "OBSOLETEVERSION",
    1116: "DIRINDEXES",
    1117: "BASENAMES",
    1118: "DIRNAMES",
    1122: "OPTFLAGS",
    1124: "PAYLOADFORMAT",
    1125: "PAYLOADCOMPRESSOR",
    1126: "PAYLOADFLAGS",
    1127: "INSTALLCOLOR",
    1128: "INSTALLTID",
    1131: "RHNPLATFORM",
    1132: "PLATFORM",
    1140: "FILECOLORS",
    1141: "FILECLASS",
    1142: "CLASSDICT",
    1143: "FILEDEPENDSX",
    1144: "FILEDEPENDSN",
    1145: "DEPENDSDICT",
    1146: "SOURCEPKGID",
    1156: "PRETRANS",
    1157: "POSTTRANS",
    1177: "FILEDIGESTALGO",
    5011: "FILEDIGESTALGO",
    5017: "ORDERNAME",
    5046: "RECOMMENDNAME",
    5049: "SUGGESTNAME",
    5052: "SUPPLEMENTNAME",
    5055: "ENHANCENAME",
    5062: "INSTFILENAMES",
    5092: "PAYLOADDIGEST",
    5093: "PAYLOADDIGESTALGO",
    5097: "MODULARITYLABEL",
    5098: "PAYLOADDIGESTALT",
    5062 + 1: "FILENLINKS",
}


def tag_names() -> dict[int, str]:
    names = dict(FALLBACK_TAGS)
    try:
        import rpm  # type: ignore

        for number, name in getattr(rpm, "tagnames", {}).items():
            names[int(number)] = str(name)
    except Exception:
        pass
    return names


def parse_header(blob: bytes) -> dict[int, dict[str, Any]]:
    """Decode an exported RPM header into {tag: {type, count, value}}."""
    if len(blob) < 8:
        raise ValueError("header blob shorter than its own length prefix")
    count, data_length = struct.unpack_from(">II", blob, 0)
    index_end = 8 + count * 16
    if index_end + data_length > len(blob):
        raise ValueError(
            f"header claims {count} entries and {data_length} data bytes, "
            f"which exceeds the {len(blob)}-byte blob"
        )
    data = blob[index_end : index_end + data_length]

    entries: dict[int, dict[str, Any]] = {}
    for position in range(count):
        tag, kind, offset, item_count = struct.unpack_from(">IIiI", blob, 8 + position * 16)
        entries[tag] = {
            "type": kind,
            "typeName": TYPE_NAMES.get(kind, f"unknown({kind})"),
            "count": item_count,
            "offset": offset,
            "indexPosition": position,
            "value": _decode_value(data, kind, offset, item_count),
        }
    return entries


def _decode_value(data: bytes, kind: int, offset: int, count: int) -> Any:
    if offset < 0 or offset > len(data):
        return {"unreadable": f"offset {offset} outside {len(data)}-byte data section"}
    if kind in (6, 8, 9):
        values = []
        cursor = offset
        for _ in range(count if kind != 6 else 1):
            end = data.find(b"\x00", cursor)
            if end < 0:
                values.append({"unterminated": data[cursor : cursor + 64].hex()})
                break
            values.append(data[cursor:end].decode("utf-8", "replace"))
            cursor = end + 1
        return values[0] if kind == 6 and values else values
    if kind == 7:
        raw = data[offset : offset + count]
        return {
            "binLength": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "hex": raw.hex() if len(raw) <= 64 else None,
        }
    width = TYPE_WIDTH.get(kind)
    if width is None:
        return {"undecodable": f"type {kind}"}
    formats = {1: ">B", 2: ">b", 3: ">h", 4: ">i", 5: ">q"}
    fmt = formats[kind]
    values = []
    for index in range(count):
        start = offset + index * width
        if start + width > len(data):
            values.append({"truncated": True})
            break
        values.append(struct.unpack_from(fmt, data, start)[0])
    return values


def load_packages(path: Path) -> dict[int, bytes]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT hnum, blob FROM Packages ORDER BY hnum").fetchall()
    finally:
        connection.close()
    return {int(hnum): bytes(blob) for hnum, blob in rows}


def _summarise(value: Any, limit: int) -> Any:
    if isinstance(value, list) and len(value) > limit:
        return value[:limit] + [f"... {len(value) - limit} more"]
    return value


def compare(first: Path, second: Path, *, sample_values: int) -> dict[str, Any]:
    left = load_packages(first)
    right = load_packages(second)
    names = tag_names()

    shared = sorted(set(left) & set(right))
    only_left = sorted(set(left) - set(right))
    only_right = sorted(set(right) - set(left))

    differing: list[dict[str, Any]] = []
    tag_frequency: dict[str, int] = {}
    parse_failures: list[dict[str, Any]] = []

    for hnum in shared:
        if left[hnum] == right[hnum]:
            continue
        try:
            left_header = parse_header(left[hnum])
            right_header = parse_header(right[hnum])
        except ValueError as error:
            parse_failures.append({"hnum": hnum, "error": str(error)})
            continue

        name = left_header.get(1000, {}).get("value", f"hnum-{hnum}")
        version = left_header.get(1001, {}).get("value", "")
        release = left_header.get(1002, {}).get("value", "")

        tags = sorted(set(left_header) | set(right_header))
        changed = []
        for tag in tags:
            left_entry = left_header.get(tag)
            right_entry = right_header.get(tag)
            if left_entry == right_entry:
                continue
            label = names.get(tag, f"tag-{tag}")
            tag_frequency[label] = tag_frequency.get(label, 0) + 1
            changed.append(
                {
                    "tag": tag,
                    "name": label,
                    "type": (left_entry or right_entry or {}).get("typeName"),
                    "a": _summarise((left_entry or {}).get("value"), sample_values),
                    "b": _summarise((right_entry or {}).get("value"), sample_values),
                    "presentInA": left_entry is not None,
                    "presentInB": right_entry is not None,
                }
            )

        # An index reordering with identical values would produce identical tag
        # values and a different blob, so it is checked explicitly rather than
        # inferred from an empty `changed` list.
        left_order = [entry["tag"] for entry in sorted(left_header.values(), key=lambda e: e["indexPosition"])] if False else [
            tag for tag, entry in sorted(left_header.items(), key=lambda item: item[1]["indexPosition"])
        ]
        right_order = [
            tag for tag, entry in sorted(right_header.items(), key=lambda item: item[1]["indexPosition"])
        ]

        differing.append(
            {
                "hnum": hnum,
                "package": f"{name}-{version}-{release}",
                "blobLengthA": len(left[hnum]),
                "blobLengthB": len(right[hnum]),
                "blobLengthMatch": len(left[hnum]) == len(right[hnum]),
                "changedTags": changed,
                "changedTagCount": len(changed),
                "indexOrderMatches": left_order == right_order,
                "onlyIndexOrderDiffers": not changed and left_order != right_order,
            }
        )

    return {
        "schemaVersion": 1,
        "a": str(first),
        "b": str(second),
        "packageCountA": len(left),
        "packageCountB": len(right),
        "packageCountMatch": len(left) == len(right),
        "hnumsOnlyInA": only_left,
        "hnumsOnlyInB": only_right,
        "identicalHeaders": len(shared) - len(differing) - len(parse_failures),
        "differingHeaders": len(differing),
        "parseFailures": parse_failures,
        "changedTagFrequency": dict(sorted(tag_frequency.items(), key=lambda item: -item[1])),
        "differingPackages": differing,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="diff_rpm_headers")
    parser.add_argument("--first", required=True, type=Path)
    parser.add_argument("--second", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sample-values", type=int, default=8)
    args = parser.parse_args()

    for path in (args.first, args.second):
        if not path.is_file():
            raise SystemExit(f"BLOCKED: database does not exist: {path}")

    report = compare(args.first, args.second, sample_values=args.sample_values)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(
        f"{report['packageCountA']} vs {report['packageCountB']} headers, "
        f"{report['differingHeaders']} differing, {report['identicalHeaders']} identical"
    )
    if report["changedTagFrequency"]:
        print("tags that differ, by how many packages carry the difference:")
        for name, count in report["changedTagFrequency"].items():
            print(f"    {name:24} {count}")
    for entry in report["differingPackages"][:10]:
        tags = ", ".join(item["name"] for item in entry["changedTags"]) or "(index order only)"
        print(f"    {entry['package']}: {tags}")
    if len(report["differingPackages"]) > 10:
        print(f"    ... {len(report['differingPackages']) - 10} more")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(REFUSED) from None
        raise
