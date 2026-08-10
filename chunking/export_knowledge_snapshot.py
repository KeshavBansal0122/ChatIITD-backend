#!/usr/bin/env python3
"""
Export the local Qdrant `knowledge` collection to snapshots/knowledge.snapshot
for VPS / docker-compose restore via qdrant-init.

Usage (Qdrant running, collection already built):
  QDRANT_URL=http://localhost:6333 python chunking/export_knowledge_snapshot.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

BACKEND_ROOT = Path(__file__).resolve().parent.parent
OUT = BACKEND_ROOT / "snapshots" / "knowledge.snapshot"
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333").rstrip("/")
COLLECTION = os.environ.get("QDRANT_KNOWLEDGE_COLLECTION", "knowledge")


def main() -> None:
    # Create snapshot on server
    r = requests.post(f"{QDRANT_URL}/collections/{COLLECTION}/snapshots", timeout=120)
    r.raise_for_status()
    name = r.json()["result"]["name"]
    print(f"Created server snapshot: {name}")

    # Download
    url = f"{QDRANT_URL}/collections/{COLLECTION}/snapshots/{name}"
    for _ in range(30):
        dl = requests.get(url, timeout=300)
        if dl.status_code == 200 and len(dl.content) > 1000:
            break
        time.sleep(1)
    else:
        raise SystemExit(f"Failed to download snapshot {name}: HTTP {dl.status_code}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(dl.content)
    print(f"Wrote {OUT} ({len(dl.content):,} bytes)")

    # Best-effort cleanup on server
    try:
        requests.delete(url, timeout=60)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
