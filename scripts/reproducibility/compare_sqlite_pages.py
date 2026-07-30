#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare two SQLite databases page by page and say which structures differ.

``cmp`` answers "these files differ" and a digest answers "these files differ".
Neither says whether the difference is a header counter, one table's leaf pages,
an index built in a different order, or an overflow chain — and those have
different causes and different fixes.

A page is classified from its own bytes, using the B-tree page header layout:

    offset 0   page type      0x02 interior index, 0x05 interior table,
                              0x0a leaf index,     0x0d leaf table
    offset 1   first freeblock
    offset 3   cell count
    offset 5   start of the cell content area
    offset 7   fragmented free bytes
    offset 8   right-most child pointer (interior pages only)

and attributed to a named table or index through the ``dbstat`` virtual table,
which is SQLite's own page-to-object map. Deriving that mapping by walking root
pages was the alternative; ``dbstat`` is built into the pinned library, is
maintained with the file format, and does not have to be re-verified whenever the
format changes.

Cell ordering is compared explicitly. Two pages holding the same cells in a
different order are the signature of a different insertion order, and that is a
different defect from two pages holding different cells.
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

PAGE_TYPE = {
    0x02: "interior-index",
    0x05: "interior-table",
    0x0A: "leaf-index",
    0x0D: "leaf-table",
    0x00: "unused-or-free",
}


def _u16(raw: bytes, offset: int) -> int:
    return struct.unpack_from(">H", raw, offset)[0]


def _u32(raw: bytes, offset: int) -> int:
    return struct.unpack_from(">I", raw, offset)[0]


def read_pages(path: Path) -> tuple[int, int, list[bytes]]:
    raw = path.read_bytes()
    if len(raw) < 100 or raw[:16] != b"SQLite format 3\x00":
        raise SystemExit(f"BLOCKED: {path} is not a SQLite database")
    page_size = _u16(raw, 16)
    if page_size == 1:
        page_size = 65536
    reserved = raw[20]
    count = len(raw) // page_size
    pages = [raw[index * page_size : (index + 1) * page_size] for index in range(count)]
    return page_size, reserved, pages


def describe_page(page: bytes, number: int, page_size: int, reserved: int) -> dict[str, Any]:
    """Parse whatever this page's own bytes say about it.

    Page 1 carries the 100-byte file header before its B-tree header, so every
    offset on that page is shifted. Getting that wrong would classify the schema
    root as a page of an unknown type on every database ever inspected.
    """
    offset = 100 if number == 1 else 0
    if len(page) <= offset:
        return {"pageNumber": number, "type": "truncated"}

    flag = page[offset]
    kind = PAGE_TYPE.get(flag, f"non-btree(0x{flag:02x})")
    record: dict[str, Any] = {
        "pageNumber": number,
        "type": kind,
        "sha256": hashlib.sha256(page).hexdigest(),
    }

    if flag not in (0x02, 0x05, 0x0A, 0x0D):
        # A page that is not a B-tree page is a freelist page, an overflow page
        # or a pointer map. Its four leading bytes are the next-page pointer for
        # the first two, which is worth recording because a differing overflow
        # chain and a differing freelist look identical at the digest level.
        record["leadingPointer"] = _u32(page, 0) if len(page) >= 4 else None
        return record

    first_freeblock = _u16(page, offset + 1)
    cell_count = _u16(page, offset + 3)
    content_start = _u16(page, offset + 5)
    fragmented = page[offset + 7]
    header_length = 12 if flag in (0x02, 0x05) else 8
    if flag in (0x02, 0x05):
        record["rightmostChild"] = _u32(page, offset + 8)

    pointer_array = offset + header_length
    cell_offsets = [
        _u16(page, pointer_array + 2 * index) for index in range(cell_count)
    ]

    # Walk the freeblock chain rather than trusting the first pointer alone: a
    # single freeblock and a chain of three sum to the same free space and mean
    # different things about how the page was filled.
    freeblocks = []
    cursor = first_freeblock
    guard = 0
    while cursor and guard < 4096:
        if cursor + 4 > len(page):
            break
        next_block = _u16(page, cursor)
        size = _u16(page, cursor + 2)
        freeblocks.append({"offset": cursor, "size": size})
        cursor = next_block
        guard += 1

    usable = page_size - reserved
    record.update(
        {
            "firstFreeblock": first_freeblock,
            "cellCount": cell_count,
            "contentAreaStart": content_start if content_start else 65536,
            "fragmentedFreeBytes": fragmented,
            "freeblocks": freeblocks,
            "freeblockBytes": sum(item["size"] for item in freeblocks),
            "cellOffsets": cell_offsets,
            # The pointer array is stored in key order; the content area is
            # filled from the end. Two pages whose cell *content* is identical
            # but whose offsets differ were written in a different order.
            "cellOffsetsSorted": cell_offsets == sorted(cell_offsets, reverse=True),
            "unusedBytes": max(0, (content_start if content_start else 65536) - (pointer_array + 2 * cell_count)),
            "usableSize": usable,
        }
    )

    cells = []
    for index, cell_offset in enumerate(cell_offsets):
        end = min(len(page), cell_offset + 64)
        cells.append(
            {
                "index": index,
                "offset": cell_offset,
                "prefixSha256": hashlib.sha256(page[cell_offset:end]).hexdigest(),
            }
        )
    record["cells"] = cells
    return record


def page_map(path: Path) -> dict[int, dict[str, Any]]:
    """Attribute each page to a schema object using SQLite's own ``dbstat``."""
    uri = f"file:{path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        try:
            rows = connection.execute(
                "SELECT name, path, pageno, pagetype, ncell, payload, unused, mx_payload, pgoffset,"
                " pgsize FROM dbstat ORDER BY pageno"
            ).fetchall()
        except sqlite3.Error as error:
            # DBSTAT_VTAB is a compile-time option. Its absence is reported
            # rather than worked around, because a page report that silently
            # stopped naming objects would read as "no object owns this page".
            return {-1: {"dbstatUnavailable": str(error)}}
    finally:
        connection.close()

    mapping: dict[int, dict[str, Any]] = {}
    for name, tree_path, pageno, pagetype, ncell, payload, unused, mx_payload, pgoffset, pgsize in rows:
        mapping[int(pageno)] = {
            "object": name,
            "treePath": tree_path,
            "dbstatPageType": pagetype,
            "ncell": ncell,
            "payload": payload,
            "unused": unused,
            "maxPayload": mx_payload,
            "pageOffset": pgoffset,
            "pageSize": pgsize,
        }
    return mapping


def btree_depth(pages: list[bytes], page_size: int, root: int) -> int | None:
    """Descend the leftmost spine of a B-tree to get its depth."""
    depth = 0
    current = root
    seen = set()
    while 1 <= current <= len(pages) and current not in seen:
        seen.add(current)
        page = pages[current - 1]
        offset = 100 if current == 1 else 0
        if len(page) <= offset:
            return None
        flag = page[offset]
        depth += 1
        if flag in (0x0A, 0x0D):
            return depth
        if flag not in (0x02, 0x05):
            return None
        cell_count = _u16(page, offset + 3)
        if cell_count == 0:
            current = _u32(page, offset + 8)
            continue
        first_cell = _u16(page, offset + 12)
        if first_cell + 4 > len(page):
            return None
        current = _u32(page, first_cell)
    return None


def compare(first: Path, second: Path) -> dict[str, Any]:
    first_size, first_reserved, first_pages = read_pages(first)
    second_size, second_reserved, second_pages = read_pages(second)

    first_map = page_map(first)
    second_map = page_map(second)

    header_fields: dict[str, Any] = {}
    for name, offset, width in (
        ("pageSize", 16, 2),
        ("writeVersion", 18, 1),
        ("readVersion", 19, 1),
        ("reservedBytes", 20, 1),
        ("fileChangeCounter", 24, 4),
        ("databaseSizeInPages", 28, 4),
        ("firstFreelistTrunkPage", 32, 4),
        ("freelistPageCount", 36, 4),
        ("schemaCookie", 40, 4),
        ("schemaFormat", 44, 4),
        ("defaultCacheSize", 48, 4),
        ("largestRootBTreePage", 52, 4),
        ("textEncoding", 56, 4),
        ("userVersion", 60, 4),
        ("incrementalVacuum", 64, 4),
        ("applicationId", 68, 4),
        ("versionValidFor", 92, 4),
        ("sqliteVersionNumber", 96, 4),
    ):
        def read(raw: bytes) -> int:
            chunk = raw[offset : offset + width]
            if width == 1:
                return chunk[0]
            if width == 2:
                return struct.unpack(">H", chunk)[0]
            return struct.unpack(">I", chunk)[0]

        left, right = read(first_pages[0]), read(second_pages[0])
        header_fields[name] = {"a": left, "b": right, "match": left == right}

    common = min(len(first_pages), len(second_pages))
    differing: list[dict[str, Any]] = []
    for number in range(1, common + 1):
        left, right = first_pages[number - 1], second_pages[number - 1]
        if left == right:
            continue
        left_record = describe_page(left, number, first_size, first_reserved)
        right_record = describe_page(right, number, second_size, second_reserved)
        attribution = first_map.get(number, {}) or second_map.get(number, {})

        classification = "content"
        if number == 1:
            classification = "page-1-header-or-schema"
        elif left_record.get("type") != right_record.get("type"):
            classification = "page-type"
        elif left_record.get("cellCount") != right_record.get("cellCount"):
            classification = "cell-count"
        elif left_record.get("cellOffsets") != right_record.get("cellOffsets"):
            left_cells = {cell["prefixSha256"] for cell in left_record.get("cells", [])}
            right_cells = {cell["prefixSha256"] for cell in right_record.get("cells", [])}
            classification = (
                "cell-order-only" if left_cells == right_cells else "cell-offsets-and-content"
            )
        else:
            left_cells = [cell["prefixSha256"] for cell in left_record.get("cells", [])]
            right_cells = [cell["prefixSha256"] for cell in right_record.get("cells", [])]
            if left_cells == right_cells:
                classification = "cell-payload-beyond-prefix-or-free-space"
            else:
                changed = [
                    index for index, (x, y) in enumerate(zip(left_cells, right_cells)) if x != y
                ]
                classification = "cell-content"
                left_record["changedCellIndexes"] = changed[:64]

        differing.append(
            {
                "pageNumber": number,
                "classification": classification,
                "object": attribution.get("object"),
                "treePath": attribution.get("treePath"),
                "a": left_record,
                "b": right_record,
            }
        )

    # Per-object rollup: which named table or index owns the differing pages.
    by_object: dict[str, dict[str, Any]] = {}
    for entry in differing:
        key = str(entry["object"] or "unattributed")
        bucket = by_object.setdefault(
            key, {"differingPages": 0, "pageNumbers": [], "classifications": {}}
        )
        bucket["differingPages"] += 1
        if len(bucket["pageNumbers"]) < 200:
            bucket["pageNumbers"].append(entry["pageNumber"])
        bucket["classifications"][entry["classification"]] = (
            bucket["classifications"].get(entry["classification"], 0) + 1
        )

    depths: dict[str, Any] = {}
    uri = f"file:{first.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        roots = connection.execute(
            "SELECT type, name, rootpage FROM sqlite_schema WHERE rootpage > 0 ORDER BY name"
        ).fetchall()
    finally:
        connection.close()
    for kind, name, root in roots:
        depths[str(name)] = {
            "type": kind,
            "rootPage": root,
            "depthA": btree_depth(first_pages, first_size, int(root)),
            "depthB": btree_depth(second_pages, second_size, int(root)),
        }

    overflow_a = sorted(
        number
        for number, record in first_map.items()
        if number > 0 and record.get("dbstatPageType") == "overflow"
    )
    overflow_b = sorted(
        number
        for number, record in second_map.items()
        if number > 0 and record.get("dbstatPageType") == "overflow"
    )

    return {
        "schemaVersion": 1,
        "a": {"path": str(first), "pageSize": first_size, "pageCount": len(first_pages)},
        "b": {"path": str(second), "pageSize": second_size, "pageCount": len(second_pages)},
        "header": header_fields,
        "headerMatch": all(field["match"] for field in header_fields.values()),
        "pageCountMatch": len(first_pages) == len(second_pages),
        "differingPageCount": len(differing),
        "identicalPageCount": common - len(differing),
        "byObject": dict(sorted(by_object.items())),
        "btreeDepths": depths,
        "btreeDepthsMatch": all(
            entry["depthA"] == entry["depthB"] for entry in depths.values()
        ),
        "overflowPages": {
            "a": overflow_a,
            "b": overflow_b,
            "match": overflow_a == overflow_b,
        },
        "differingPages": differing,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="compare_sqlite_pages")
    parser.add_argument("--first", required=True, type=Path)
    parser.add_argument("--second", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--max-detail",
        type=int,
        default=200,
        help="how many differing pages to record in full; the rollup always covers all of them",
    )
    args = parser.parse_args()

    for path in (args.first, args.second):
        if not path.is_file():
            raise SystemExit(f"BLOCKED: database does not exist: {path}")

    report = compare(args.first, args.second)
    detail = report["differingPages"]
    report["differingPagesTruncatedTo"] = args.max_detail
    report["differingPages"] = detail[: args.max_detail]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(
        f"pages: {report['a']['pageCount']} vs {report['b']['pageCount']}, "
        f"{report['differingPageCount']} differing, {report['identicalPageCount']} identical"
    )
    print(f"header fields match: {report['headerMatch']}")
    print(f"b-tree depths match: {report['btreeDepthsMatch']}")
    for name, bucket in report["byObject"].items():
        kinds = ", ".join(f"{k}×{v}" for k, v in sorted(bucket["classifications"].items()))
        print(f"  {name}: {bucket['differingPages']} pages ({kinds})")
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
