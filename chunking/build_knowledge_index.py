#!/usr/bin/env python3
"""
Build the hybrid `knowledge` Qdrant collection from CoS PDFs + curriculum JSON.

Usage (from backend/, Qdrant running):
  python chunking/build_knowledge_index.py
  python chunking/build_knowledge_index.py --recreate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from chunking.pdf_chunker import PDFSectionChunker, Payload  # noqa: E402
from backend.knowledge_service import (  # noqa: E402
    ensure_knowledge_collection,
    upsert_knowledge_payloads,
)


def load_dotenv() -> None:
    env_path = BACKEND_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def cos_pdf_payloads() -> list[Payload]:
    manifest = json.loads((BACKEND_ROOT / "sources" / "cos_sources.json").read_text())
    chunker = PDFSectionChunker()
    out: list[Payload] = []
    for entry in manifest:
        path = BACKEND_ROOT / "sources" / entry["file"]
        if not path.exists():
            print(f"[skip] missing {path.name}")
            continue
        print(f"[chunk] {path.name} generation={entry['generation']}")
        payloads = chunker.process_pdf(
            str(path),
            source_url=entry["source_url"],
            generation=entry["generation"],
            doc_type=entry.get("doc_type") or "rule",
            extra_metadata={"label": entry.get("label")},
        )
        print(f"  -> {len(payloads)} chunks")
        out.extend(payloads)
    return out


def curriculum_web_payloads() -> list[Payload]:
    out: list[Payload] = []
    course_dir = BACKEND_ROOT / "sources" / "curriculum_2025" / "courses"
    for path in sorted(course_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        code = data.get("code", path.stem)
        name = data.get("name") or ""
        desc = data.get("description") or ""
        clos = data.get("learning_outcomes") or []
        clo_txt = "\n".join(f"- {c}" for c in clos)
        content = (
            f"[Course {code} {name}]\n{desc}\n"
            f"Credits: {data.get('credits')}\n"
            f"Learning outcomes:\n{clo_txt}"
        ).strip()
        out.append(
            Payload(
                content=content,
                metadata={
                    "generation": "2025",
                    "doc_type": "course",
                    "course_code": code,
                    "section_path": [f"{code}: {name}"],
                    "section_title": f"{code}: {name}",
                    "section_level": 1,
                    "source_url": data.get("source_url"),
                    "source_name": "curriculum.iitd.ac.in",
                    "academic_unit": data.get("academic_unit"),
                },
            )
        )

    prog_dir = BACKEND_ROOT / "sources" / "curriculum_2025" / "programmes"
    for path in sorted(prog_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        code = data.get("code", path.stem)
        name = data.get("name") or ""
        reqs = data.get("credit_requirements") or []
        req_lines = ", ".join(
            f"{r.get('category')}={r.get('credits_or_units')}" for r in reqs
        )
        preview = data.get("raw_text_preview") or ""
        content = (
            f"[Programme {code} {name}]\n"
            f"Degree type: {data.get('degree_type')}\n"
            f"Credit requirements: {req_lines}\n"
            f"{preview[:2500]}"
        )
        out.append(
            Payload(
                content=content,
                metadata={
                    "generation": "2025",
                    "doc_type": "programme",
                    "programme_code": code,
                    "section_path": [f"Programme {code}"],
                    "section_title": name or code,
                    "section_level": 1,
                    "source_url": data.get("source_url"),
                    "source_name": "curriculum.iitd.ac.in",
                },
            )
        )
    print(f"[curriculum web] {len(out)} course/programme chunks")
    return out


def courses_iitd_payloads() -> list[Payload]:
    """Chunk course descriptions scraped from courses.iitd.ac.in."""
    out: list[Payload] = []
    course_dir = BACKEND_ROOT / "sources" / "courses_iitd" / "courses"
    if not course_dir.is_dir():
        print("[courses.iitd] no sources/courses_iitd/courses — skip")
        return out

    seen: set[str] = set()
    for path in sorted(course_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        code = (data.get("code") or "").upper()
        if not code or code in seen:
            continue
        seen.add(code)
        name = data.get("name") or ""
        desc = (data.get("description") or "").strip()
        if not desc and not name:
            continue
        clos = data.get("learning_outcomes") or []
        clo_txt = "\n".join(f"- {c}" for c in clos)
        hours = data.get("hours") or {}
        content = (
            f"[Course {code} {name}]\n"
            f"Department: {data.get('department') or ''}\n"
            f"Credits: {data.get('credits')}  "
            f"L-T-P: {hours.get('lecture')}-{hours.get('tutorial')}-{hours.get('practical')}\n"
            f"Prerequisites: {data.get('prereq') or 'None'}\n"
            f"Overlap/precluded: {data.get('overlap') or 'None'}\n"
            f"Description:\n{desc}\n"
            f"Learning outcomes:\n{clo_txt}"
        ).strip()
        # One primary chunk; splitter not needed for typical course pages
        generation = data.get("generation") or (
            "2025" if sum(ch.isdigit() for ch in code) >= 4 else "legacy"
        )
        out.append(
            Payload(
                content=content,
                metadata={
                    "generation": generation,
                    "doc_type": "course",
                    "course_code": code,
                    "section_path": [f"{code}: {name}"],
                    "section_title": f"{code}: {name}",
                    "section_level": 1,
                    "source_url": data.get("source_url"),
                    "source_name": "courses.iitd.ac.in",
                    "source": "courses_iitd",
                    "department": data.get("department"),
                },
            )
        )
    print(f"[courses.iitd] {len(out)} course description chunks")
    return out


def legacy_programme_payloads() -> list[Payload]:
    out: list[Payload] = []
    prog_dir = BACKEND_ROOT / "sources" / "programme_structures"
    for path in sorted(prog_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        code = data.get("code", path.stem)
        content = json.dumps(data, indent=2)[:4000]
        out.append(
            Payload(
                content=f"[Legacy programme {code}]\n{content}",
                metadata={
                    "generation": "legacy",
                    "doc_type": "programme",
                    "programme_code": code,
                    "section_path": [f"Programme {code}"],
                    "section_title": data.get("name") or code,
                    "section_level": 1,
                    "source_name": path.name,
                },
            )
        )
    print(f"[legacy programmes] {len(out)} chunks")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--skip-pdfs", action="store_true")
    parser.add_argument("--skip-web", action="store_true")
    parser.add_argument("--skip-courses-iitd", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    ensure_knowledge_collection(recreate=args.recreate)

    payloads: list[Payload] = []
    if not args.skip_pdfs:
        payloads.extend(cos_pdf_payloads())
    if not args.skip_web:
        payloads.extend(curriculum_web_payloads())
        payloads.extend(legacy_programme_payloads())
    if not args.skip_courses_iitd:
        payloads.extend(courses_iitd_payloads())

    print(f"Upserting {len(payloads)} payloads…")
    n = upsert_knowledge_payloads(payloads)
    print(f"Done. Upserted {n} points into knowledge collection.")


if __name__ == "__main__":
    main()
