#!/usr/bin/env python3
"""Download official CoS PDFs listed in cos_sources.json into sources/."""

from __future__ import annotations

import json
import ssl
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "cos_sources.json"
STALE = [
    "cos_2023_24.pdf",
    "cos_24_rules.pdf",
    "curriculum_2025.pdf",
    "ug_rules.pdf",
    "pg_rules.pdf",
]


def download(url: str, dest: Path) -> None:
    print(f"Downloading {dest.name} ...")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(url, context=ctx, timeout=120) as resp:
            data = resp.read()
    except ssl.SSLError:
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(url, context=ctx, timeout=120) as resp:
            data = resp.read()
    if len(data) < 10_000:
        raise SystemExit(f"Suspiciously small download for {dest.name}: {len(data)} bytes")
    dest.write_bytes(data)
    print(f"  wrote {dest} ({len(data):,} bytes)")


def main() -> None:
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for name in STALE:
        path = HERE / name
        if path.exists():
            path.unlink()
            print(f"Deleted stale {name}")

    for entry in entries:
        dest = HERE / entry["file"]
        if dest.exists() and dest.stat().st_size > 10_000:
            print(f"Skip existing {dest.name} ({dest.stat().st_size:,} bytes)")
            continue
        download(entry["source_url"], dest)

    print("Done.")


if __name__ == "__main__":
    main()
