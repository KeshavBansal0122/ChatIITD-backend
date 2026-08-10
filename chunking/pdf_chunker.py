"""
Header-aware PDF section chunker with page + section metadata.

Uses font-size hierarchy for headers and recursive character splitting under each section.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pymupdf as fitz
from pydantic import BaseModel, Field

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:  # pragma: no cover
    RecursiveCharacterTextSplitter = None  # type: ignore


class Payload(BaseModel):
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class _SimpleRecursiveSplitter:
    def __init__(self, chunk_size: int = 300, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = ["\n\n", "\n", ". ", " ", ""]

    def split_text(self, text: str) -> List[str]:
        if len(text) <= self.chunk_size:
            return [text] if text.strip() else []
        return self._split(text, self.separators)

    def _split(self, text: str, seps: List[str]) -> List[str]:
        if not text:
            return []
        if len(text) <= self.chunk_size or not seps:
            return [text]
        sep = seps[0]
        parts = text.split(sep) if sep else list(text)
        chunks: List[str] = []
        buf = ""
        for part in parts:
            candidate = part if not buf else (buf + sep + part if sep else buf + part)
            if len(candidate) <= self.chunk_size:
                buf = candidate
                continue
            if buf:
                chunks.extend(self._split(buf, seps[1:]))
            if len(part) > self.chunk_size:
                chunks.extend(self._split(part, seps[1:]))
                buf = ""
            else:
                buf = part
        if buf:
            chunks.extend(self._split(buf, seps[1:]))
        out: List[str] = []
        for c in chunks:
            c = c.strip()
            if not c:
                continue
            if out and len(c) < self.chunk_overlap:
                out[-1] = (out[-1] + " " + c).strip()
            else:
                out.append(c)
        return out


class PDFSectionChunker:
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 80):
        if RecursiveCharacterTextSplitter is not None:
            self.text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=["\n\n", "\n", ". ", " ", ""],
                keep_separator=False,
            )
        else:
            self.text_splitter = _SimpleRecursiveSplitter(chunk_size, chunk_overlap)

    def get_font_statistics(self, doc) -> Dict[str, Any]:
        font_sizes: List[float] = []
        for page in doc:
            blocks = page.get_text("dict")["blocks"]
            for b in blocks:
                if b["type"] != 0:
                    continue
                for line in b["lines"]:
                    max_s = max((s["size"] for s in line["spans"]), default=0)
                    if max_s > 0:
                        font_sizes.append(max_s)
        if not font_sizes:
            try:
                if len(doc) > 0:
                    tp = doc[0].get_textpage_ocr(flags=3, language="eng", dpi=300)
                    for b in tp.extractDICT()["blocks"]:
                        if b["type"] != 0:
                            continue
                        for line in b["lines"]:
                            max_s = max((s["size"] for s in line["spans"]), default=0)
                            if max_s > 0:
                                font_sizes.append(max_s)
            except Exception:
                pass
        if not font_sizes:
            return {"body_size": 11.0}
        rounded = [round(s, 1) for s in font_sizes]
        body_size = Counter(rounded).most_common(1)[0][0]
        return {"body_size": body_size}

    def _is_valid_chunk(self, content: str) -> bool:
        if not content or not content.strip():
            return False
        ascii_content = content.encode("ascii", "replace").decode("ascii")
        return (ascii_content.count("?") / max(len(content), 1)) <= 0.2

    def _section_fields(self, headers: List[str], header_id: int) -> Dict[str, Any]:
        path = headers or ["Introduction"]
        return {
            "headers": path,
            "section_path": path,
            "section_title": path[-1],
            "section_level": len(path),
            "header_id": header_id,
        }

    def _create_payloads_from_section(
        self,
        content: str,
        headers: List[str],
        header_id: int,
        base_metadata: Dict[str, Any],
    ) -> List[Payload]:
        if not content:
            return []
        chunks = self.text_splitter.split_text(content)
        payloads: List[Payload] = []
        section = self._section_fields(headers, header_id)
        prefix = " > ".join(section["section_path"])
        for i, chunk in enumerate(chunks):
            if not self._is_valid_chunk(chunk):
                continue
            metadata = {**base_metadata, **section, "type": "text", "chunk_index": i}
            if "page_start" in metadata and "page" not in metadata:
                metadata["page"] = metadata["page_start"]
            body = f"[{prefix}]\n{chunk}" if prefix else chunk
            payloads.append(Payload(content=body, metadata=metadata))
        return payloads

    def process_pdf(
        self,
        file_path: str,
        *,
        source_url: Optional[str] = None,
        generation: Optional[str] = None,
        doc_type: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Payload]:
        """Parse PDF with font-size header hierarchy + recursive splits."""
        doc = fitz.open(file_path)
        stats = self.get_font_statistics(doc)
        body_size = stats["body_size"]
        header_threshold = body_size + 0.5

        doc_meta: Dict[str, Any] = {
            "source_file": str(file_path),
            "source_name": Path(file_path).name,
        }
        if source_url:
            doc_meta["source_url"] = source_url
        if generation:
            doc_meta["generation"] = generation
        if doc_type:
            doc_meta["doc_type"] = doc_type
        if extra_metadata:
            doc_meta.update(extra_metadata)

        payloads: List[Payload] = []
        header_id_counter = 0
        header_stack: List[Tuple[str, float, int]] = []
        current_content_buffer: List[str] = []
        buffer_page_start: Optional[int] = None
        buffer_page_end: Optional[int] = None

        def flush_text() -> None:
            nonlocal current_content_buffer, buffer_page_start, buffer_page_end
            full_content = "\n".join(current_content_buffer).strip()
            if full_content:
                headers = [h[0] for h in header_stack] or ["Introduction"]
                hid = header_stack[-1][2] if header_stack else -1
                meta = {
                    **doc_meta,
                    "page_start": buffer_page_start or 1,
                    "page_end": buffer_page_end or buffer_page_start or 1,
                    "page": buffer_page_start or 1,
                }
                payloads.extend(
                    self._create_payloads_from_section(full_content, headers, hid, meta)
                )
            current_content_buffer = []
            buffer_page_start = None
            buffer_page_end = None

        def append_text(text: str, page_num: int) -> None:
            nonlocal buffer_page_start, buffer_page_end
            if buffer_page_start is None:
                buffer_page_start = page_num
            buffer_page_end = page_num
            current_content_buffer.append(text)

        for page_num, page in enumerate(doc, start=1):
            text = page.get_text()
            if len(text.strip()) < 50:
                try:
                    tp = page.get_textpage_ocr(flags=3, language="eng", dpi=300)
                    text_blocks = tp.extractDICT()["blocks"]
                except Exception:
                    text_blocks = page.get_text("dict")["blocks"]
            else:
                text_blocks = page.get_text("dict")["blocks"]

            tables = page.find_tables().tables
            elements: List[Tuple[str, float, Any]] = []
            for table in tables:
                elements.append(("table", table.bbox[1], table))
            for b in text_blocks:
                if b["type"] != 0:
                    continue
                b_rect = fitz.Rect(b["bbox"])
                if any(b_rect.intersects(fitz.Rect(t.bbox)) for t in tables):
                    continue
                elements.append(("text", b["bbox"][1], b))
            elements.sort(key=lambda x: x[1])

            for el_type, _, el in elements:
                if el_type == "table":
                    flush_text()
                    table_data = el.extract() or []
                    table_id = hashlib.md5(str(table_data).encode()).hexdigest()[:8]
                    headers = [h[0] for h in header_stack] or ["Introduction"]
                    hid = header_stack[-1][2] if header_stack else -1
                    section = self._section_fields(headers, hid)
                    for row_idx, row in enumerate(table_data):
                        clean_cells = [
                            str(cell).replace("\n", " ").strip()
                            for cell in row
                            if str(cell).strip()
                        ]
                        if not clean_cells:
                            continue
                        row_content = " | ".join(clean_cells)
                        if not self._is_valid_chunk(row_content):
                            continue
                        prefix = " > ".join(section["section_path"])
                        payloads.append(
                            Payload(
                                content=f"[{prefix}]\n{row_content}",
                                metadata={
                                    **doc_meta,
                                    **section,
                                    "page": page_num,
                                    "page_start": page_num,
                                    "page_end": page_num,
                                    "type": "table_row",
                                    "table_id": table_id,
                                    "row_index": row_idx,
                                    "chunk_index": row_idx,
                                },
                            )
                        )
                    continue

                block_groups = []
                current_group = None
                for line in el["lines"]:
                    line_text = "".join(s["text"] for s in line["spans"]).strip()
                    if not line_text:
                        continue
                    max_line_size = max((s["size"] for s in line["spans"]), default=0.0)
                    if current_group and abs(current_group["max_size"] - max_line_size) < 0.3:
                        current_group["lines"].append(line_text)
                        current_group["max_size"] = max(
                            current_group["max_size"], max_line_size
                        )
                    else:
                        if current_group:
                            block_groups.append(current_group)
                        current_group = {"max_size": max_line_size, "lines": [line_text]}
                if current_group:
                    block_groups.append(current_group)

                for group in block_groups:
                    group_text = "\n".join(group["lines"]).strip()
                    rounded_size = round(group["max_size"], 1)
                    is_header = False
                    if rounded_size >= header_threshold and len(group_text) < 150:
                        is_header = True
                        if re.match(
                            r"^\s*(?:(?:\d+|[a-zA-Z])[\.\)\?]|[\u2022\u2023\u25E6\u2043\u2212\-\*])\s",
                            group_text,
                        ) and len(group_text) > 60:
                            is_header = False

                    if is_header:
                        flush_text()
                        while header_stack and header_stack[-1][1] <= rounded_size:
                            header_stack.pop()
                        header_stack.append((group_text, rounded_size, header_id_counter))
                        header_id_counter += 1
                    else:
                        append_text(group_text, page_num)

        flush_text()
        doc.close()
        return payloads


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chunk a PDF by section headers")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--generation", default=None)
    parser.add_argument("--doc-type", default=None)
    args = parser.parse_args()

    chunker = PDFSectionChunker()
    payloads = chunker.process_pdf(
        args.pdf_path,
        source_url=args.source_url,
        generation=args.generation,
        doc_type=args.doc_type,
    )
    print(f"Successfully processed {len(payloads)} chunks.")
    out_dir = Path(__file__).parent / "chunksJsonl"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{Path(args.pdf_path).stem}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for p in payloads:
            f.write(json.dumps(p.model_dump()) + "\n")
    print(f"Saved {out_path}")
    for i, p in enumerate(payloads[:3]):
        print(f"--- Chunk {i+1} ---")
        print(p.metadata)
        print(p.content[:240])
