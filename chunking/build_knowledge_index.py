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
import re
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from chunking.pdf_chunker import PDFSectionChunker, Payload  # noqa: E402
from backend.knowledge_service import (  # noqa: E402
    ensure_knowledge_collection,
    upsert_knowledge_payloads,
)


SECTION_INDEX_PATH = BACKEND_ROOT / "sources" / "cos_section_index.json"


def _looks_like_noisy_header(title: str) -> bool:
    t = " ".join((title or "").split())
    if not t:
        return True
    if len(t) <= 2:
        return True
    if re.fullmatch(r"\d+", t):
        return True
    if re.fullmatch(r"p(?:age)?\.?\s*\d+", t, flags=re.I):
        return True
    lower = t.lower()
    if lower in {"contents", "table of contents"}:
        return True
    if "http://" in lower or "https://" in lower or "link:" in lower:
        return True
    if "indian institute of technology delhi" in lower:
        return True
    if re.fullmatch(r"[}=®\"'`~|\\/_\-\s]+", t):
        return True
    return False


def _is_relevant_cos_header(source_name: str, section_path: list[Any], title: str) -> bool:
    text = " ".join(str(p) for p in [*section_path, title])
    if "course_descriptions" in source_name:
        return bool(re.search(r"\b[A-Z]{2}[A-Z]\d{3,4}\b", title or ""))
    if re.search(r"\b\d+(?:\.\d+)*\s+[A-Za-z]", text):
        return True
    if re.search(r"\bTable\s+\d+", text, flags=re.I):
        return True
    return False


def _build_section_entries(
    payloads: list[Payload],
    *,
    source_name: str,
    source_url: str | None,
    generation: str,
    doc_type: str,
    label: str | None,
) -> list[dict[str, Any]]:
    sections: dict[int, dict[str, Any]] = {}
    order: list[int] = []
    for payload in payloads:
        meta = payload.metadata or {}
        header_id = meta.get("header_id")
        if header_id is None:
            continue
        try:
            hid = int(header_id)
        except (TypeError, ValueError):
            continue
        title = meta.get("section_title") or ""
        section_path = meta.get("section_path") or meta.get("headers") or []
        if _looks_like_noisy_header(str(title)):
            continue
        if not _is_relevant_cos_header(source_name, section_path, str(title)):
            continue
        if hid not in sections:
            order.append(hid)
            section_ref = f"{source_name}#h{hid}"
            sections[hid] = {
                "section_ref": section_ref,
                "source_name": source_name,
                "source_url": source_url,
                "generation": generation,
                "doc_type": doc_type,
                "label": label,
                "header_id": hid,
                "section_path": section_path,
                "section_title": title,
                "section_level": meta.get("section_level"),
                "page_start": meta.get("page_start") or meta.get("page"),
                "page_end": meta.get("page_end") or meta.get("page"),
                "chunk_count": 0,
            }
        section = sections[hid]
        section["chunk_count"] += 1
        page_start = meta.get("page_start") or meta.get("page")
        page_end = meta.get("page_end") or meta.get("page")
        if page_start:
            section["page_start"] = min(section["page_start"] or page_start, page_start)
        if page_end:
            section["page_end"] = max(section["page_end"] or page_end, page_end)
    return [sections[hid] for hid in order]


def _write_cos_section_index(entries: list[dict[str, Any]]) -> None:
    by_generation: dict[str, dict[str, Any]] = {}
    for entry in entries:
        gen = entry["generation"]
        source_name = entry["source_name"]
        gen_bucket = by_generation.setdefault(gen, {"documents": {}})
        doc = gen_bucket["documents"].setdefault(
            source_name,
            {
                "source_name": source_name,
                "source_url": entry.get("source_url"),
                "label": entry.get("label"),
                "doc_type": entry.get("doc_type"),
                "sections": [],
            },
        )
        doc["sections"].append(entry)
    SECTION_INDEX_PATH.write_text(json.dumps(by_generation, indent=2), encoding="utf-8")
    print(f"[cos sections] wrote {SECTION_INDEX_PATH.relative_to(BACKEND_ROOT)}")


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
    section_entries: list[dict[str, Any]] = []
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
        section_entries.extend(
            _build_section_entries(
                payloads,
                source_name=path.name,
                source_url=entry.get("source_url"),
                generation=entry["generation"],
                doc_type=entry.get("doc_type") or "rule",
                label=entry.get("label"),
            )
        )
        out.extend(payloads)
    _write_cos_section_index(section_entries)
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
