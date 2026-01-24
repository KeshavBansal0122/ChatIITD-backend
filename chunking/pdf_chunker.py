import fitz 
import argparse
from typing import List, Dict, Optional, Any, Tuple
from pydantic import BaseModel, Field
from collections import Counter
from langchain_text_splitters import RecursiveCharacterTextSplitter
import re

class Payload(BaseModel):
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class PDFSectionChunker:
    def __init__(self, chunk_size: int = 300, chunk_overlap: int = 30):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ".", " ", ""],
            keep_separator=False
        )

    def get_font_statistics(self, doc) -> Dict[str, Any]:
        """
        Analyzes the document to determine the most common font size (body text)
        and potential header sizes.
        """
        font_sizes = []
        for page in doc:
            blocks = page.get_text("dict")["blocks"]
            for b in blocks:
                if b['type'] == 0:  # text block
                    for l in b["lines"]:
                        for s in l["spans"]:
                            font_sizes.append(s["size"])
        
        if not font_sizes:
            return {"body_size": 11.0} # Default fallback

        # Round sizes to avoid floating point noise
        rounded_sizes = [round(s, 1) for s in font_sizes]
        size_counts = Counter(rounded_sizes)
        
        # Most common size is likely body text
        body_size = size_counts.most_common(1)[0][0]
        
        return {"body_size": body_size}

    def _create_payloads_from_section(self, content: str, headers: List[str], base_metadata: Dict) -> List[Payload]:
        if not content:
            return []
        
        # 1. Pre-process to identify list items (numbered or bulleted)
        SPLIT_MARKER = "<<<SPLIT_HERE>>>"
        
        # Regex for supported list items:
        # - Numbered: 1., 1), 1?, 1.1, etc.
        # - Alpha: a), b), a., b.
        # - Bullets: -, *, ?, etc. (PyMuPDF sometimes outputs unusual chars for bullets)
        pattern = r'(?:\n|^)\s*(?:(?:(?:\d+|[a-zA-Z])[\.\)\?]+)|[\u2022\u2023\u25E6\u2043\u2212\-\*])\s+'
        
        # Substitution to inject split marker
        content = re.sub(f'({pattern})', f'{SPLIT_MARKER}\\1', content)

        # Split by marker
        raw_chunks = content.split(SPLIT_MARKER)
        
        payloads = []
        
        # Track overall index if needed, or just per-section index
        global_chunk_index = 0
        
        for raw_chunk in raw_chunks:
            if not raw_chunk.strip():
                continue
                
            # Now apply size-based splitting to this logical chunk (in case it's huge)
            sub_chunks = self.text_splitter.split_text(raw_chunk)
            
            for chunk in sub_chunks:
                metadata = base_metadata.copy()
                metadata["headers"] = headers # List of headers from root to leaf
                metadata["type"] = "text" 
                if len(sub_chunks) > 1:
                    metadata["chunk_index"] = global_chunk_index
                else: 
                     metadata["chunk_index"] = global_chunk_index
                
                payloads.append(Payload(
                    content=chunk,
                    metadata=metadata
                ))
                global_chunk_index += 1
                
        return payloads

    def process_pdf(self, file_path: str) -> List[Payload]:
        """
        Parses PDF using PyMuPDF and groups content by Headers based on font size.
        Maintains a hierarchy of headers.
        Extracts tables separately.
        """
        try:
            doc = fitz.open(file_path)
        except Exception as e:
            print(f"Error opening PDF: {e}")
            raise

        stats = self.get_font_statistics(doc)
        body_size = stats["body_size"]
        header_threshold = body_size + 0.5 

        payloads = []
        
        # Stack of (header_title, font_size)
        header_stack: List[Tuple[str, float]] = []
        
        current_content_buffer = []
        current_page_num = 1
        
        for page_num, page in enumerate(doc):
            current_page_num = page_num + 1
            
            # 1. Detect Tables
            tabs = page.find_tables()
            tables = tabs.tables
            
            # 2. Get Text Blocks
            text_blocks = page.get_text("dict")["blocks"]

            # 3. Merge and Sort
            elements = []
            
            # Add tables
            for table in tables:
                elements.append(("table", table.bbox[1], table))
                
            # Add text blocks (filtering those that overlap with tables)
            for b in text_blocks:
                if b['type'] != 0: # Skip non-text
                    continue
                
                # Check overlap
                b_rect = fitz.Rect(b["bbox"])
                is_overlap = False
                for table in tables:
                    if b_rect.intersects(fitz.Rect(table.bbox)):
                         is_overlap = True
                         break
                
                if not is_overlap:
                    elements.append(("text", b["bbox"][1], b))
            
            # Sort by vertical position (y0)
            elements.sort(key=lambda x: x[1])

            # 4. Process Elements
            for el_type, _, el in elements:
                if el_type == "table":
                    # Flush pending text content
                    full_content = "\n".join(current_content_buffer).strip()
                    if full_content:
                        current_headers = [h[0] for h in header_stack]
                        if not current_headers:
                            current_headers = ["Introduction"]
                        payloads.extend(
                            self._create_payloads_from_section(
                                full_content, 
                                current_headers, 
                                {"page": current_page_num, "source_file": file_path}
                            )
                        )
                    current_content_buffer = []
                    
                    # Extract Table Content Row-by-Row
                    table_data = el.extract()
                    
                    if not table_data:
                        continue
                        
                    # Generate a unique ID for this table to link rows
                    import hashlib
                    table_str = str(table_data)
                    table_id = hashlib.md5(table_str.encode()).hexdigest()[:8]
                    
                    if len(table_data) < 1:
                        continue

                    current_headers = [h[0] for h in header_stack]
                    if not current_headers:
                        current_headers = ["Introduction"]

                    # Process ALL rows (including potential header row)
                    for row_idx, row in enumerate(table_data):
                         # Clean and collect non-empty cells
                         clean_cells = [str(cell).replace('\n', ' ').strip() for cell in row if str(cell).strip()]
                         
                         if not clean_cells:
                             continue
                             
                         # Format: "Val1 | Val2 | Val3"
                         row_content = " | ".join(clean_cells)
                         
                         payloads.append(Payload(
                            content=row_content,
                            metadata={
                                "page": current_page_num,
                                "headers": current_headers,
                                "type": "table_row",
                                "table_id": table_id,
                                "row_index": row_idx,
                                "source_file": file_path
                            }
                        ))
                    
                elif el_type == "text":
                    b = el
                    # Group lines within the block by font size
                    block_groups = []
                    current_group = None 

                    for l in b["lines"]:
                        line_text = []
                        max_line_size = 0.0
                        for s in l["spans"]:
                            line_text.append(s["text"])
                            if s["size"] > max_line_size:
                                max_line_size = s["size"]
                        
                        text_str = "".join(line_text).strip()
                        if not text_str:
                            continue
                            
                        # Group by size
                        if current_group and abs(current_group['max_size'] - max_line_size) < 0.3:
                            current_group['lines'].append(text_str)
                            current_group['max_size'] = max(current_group['max_size'], max_line_size)
                        else:
                            if current_group:
                                block_groups.append(current_group)
                            current_group = {'max_size': max_line_size, 'lines': [text_str]}
                    
                    if current_group:
                        block_groups.append(current_group)

                    # Process groups
                    for group in block_groups:
                        group_text = "\n".join(group['lines']).strip()
                        rounded_size = round(group['max_size'], 1)
                        
                        is_header = False
                        
                        # Refined Header Heuristic
                        if rounded_size >= header_threshold:
                            # Basic length check
                            if len(group_text) < 150: 
                                is_header = True
                                
                                # Strict check: If it looks like a list item, it must be VERY short to be a header
                                # E.g. "1. Introduction" is fine. "1. Some long sentence..." is content.
                                if re.match(r'^\s*(?:(?:\d+|[a-zA-Z])[\.\)\?]|[\u2022\u2023\u25E6\u2043\u2212\-\*])\s', group_text):
                                    if len(group_text) > 60:
                                        is_header = False
                            else:
                                is_header = False

                        if is_header:
                            # 1. Flush Content Context
                            full_content = "\n".join(current_content_buffer).strip()
                            if full_content:
                                current_headers = [h[0] for h in header_stack]
                                if not current_headers:
                                    current_headers = ["Introduction"]

                                payloads.extend(
                                    self._create_payloads_from_section(
                                        full_content, 
                                        current_headers, 
                                        {"page": current_page_num, "source_file": file_path} 
                                    )
                                )
                            
                            # 2. Update Stack
                            if header_stack:
                                while header_stack and header_stack[-1][1] <= rounded_size:
                                    header_stack.pop()
                            
                            header_stack.append((group_text, rounded_size))
                            current_content_buffer = []

                        else:
                            current_content_buffer.append(group_text)

        # Flush remaining content
        if current_content_buffer:
            full_content = "\n".join(current_content_buffer).strip()
            current_headers = [h[0] for h in header_stack]
            if not current_headers:
                current_headers = ["Introduction"]

            payloads.extend(
                self._create_payloads_from_section(
                    full_content, 
                    current_headers, 
                    {"page": current_page_num, "source_file": file_path}
                )
            )

        doc.close()
        return payloads

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest PDF and split by sections using PyMuPDF")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    
    args = parser.parse_args()
    
    chunker = PDFSectionChunker() 
    try:
        payloads = chunker.process_pdf(args.pdf_path)
        print(f"Successfully processed {len(payloads)} chunks.")
        for i, p in enumerate(payloads):
                 print(f"--- Chunk {i+1} ---")
                 print(f"Metadata: {p.metadata}")
                 content_preview = p.content.encode('ascii', 'replace').decode('ascii')
                 print(f"Content Preview: {content_preview}")
                 print()
    except Exception as e:
        print(f"Error processing PDF: {e}")
