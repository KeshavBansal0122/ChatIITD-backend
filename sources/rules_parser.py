#!/usr/bin/env python3
"""
Rules Parser - Converts PDF rules documents to JSONL format with header hierarchy
"""

import pymupdf4llm
import re
import json
from pathlib import Path
from typing import Dict, List, Tuple


def parse_pdf_rules_to_dict(text: str, header_text: str, start_line: int = 0) -> Dict:
    """
    Parse PDF text into a structured dictionary with sections and hierarchy.
    
    Args:
        text: Raw markdown text from PDF
        header_text: Header text to filter out
        start_line: Line number to start parsing from (to skip table of contents)
    
    Returns:
        Dictionary mapping section numbers to their data (title, content, subsections)
    """
    # Clean up document
    lines = [l.strip() for l in text.split('\n') if l.strip() != '' and l.strip() != header_text]
    lines = lines[start_line:]  # Skip the contents and intro part
    
    # Find and split at headers
    # Pattern matches: **1.2.3 Some Title** or ### **1.2.3 Some Title**
    header_regex = r"\#* ?\*\*((\.?\d+)+).*"
    
    sections = [(i, re.match(header_regex, l).group(1)) for i, l in enumerate(lines) if re.match(header_regex, l)]

    # Create a nested dict of sections
    parsed = {}
    for i, (idx, sec) in enumerate(sections):
        data = {'title': lines[idx], 'content': '', 'subsections': []}
        if i + 1 < len(sections):
            next_idx = sections[i + 1][0]
            data['content'] = '\n'.join(lines[(idx+1):next_idx])
        else:
            data['content'] = '\n'.join(lines[(idx+1):])
        
        # If this is a subsection, link to parent
        if '.' in sec:
            split = sec.split('.')
            for j in range(1, len(split)):
                parent_sec = '.'.join(split[:j])
                if parent_sec in parsed:
                    parsed[parent_sec]['subsections'].append(sec)
                    break
        
        parsed[sec] = data
    
    return parsed


def get_header_hierarchy(section: str) -> List[str]:
    """
    Extract the header hierarchy for a given section number.
    
    Args:
        section: Section number like "1.2.3"
    
    Returns:
        List of section numbers representing the hierarchy, e.g., ["1", "1.2", "1.2.3"]
    """
    parts = section.split('.')
    hierarchy = []
    for i in range(1, len(parts) + 1):
        hierarchy.append('.'.join(parts[:i]))
    return hierarchy


def convert_to_jsonl(processed_data: Dict, url: str, filename: str, output_path: Path) -> None:
    """
    Convert processed rules data to JSONL format with header hierarchy.
    
    Args:
        processed_data: Dictionary of parsed sections
        url: Source URL of the PDF
        filename: Name of the source file
        output_path: Path to write JSONL output
    """
    with open(output_path, 'w') as out_f:
        for section_num, section_data in processed_data.items():
            # Get header hierarchy
            hierarchy = get_header_hierarchy(section_num)
            hierarchy_titles = []
            
            for h in hierarchy:
                if h in processed_data:
                    # Extract clean title (remove markdown formatting)
                    title = processed_data[h]['title'].replace('*', '').replace('#', '').strip()
                    hierarchy_titles.append({
                        'section': h,
                        'title': title
                    })
            
            record = {
                'section': section_data['title'].replace('*', '').replace('#', '').strip(),
                'section_number': section_num,
                'content': section_data['content'],
                'hierarchy': hierarchy_titles,
                'subsections': section_data.get('subsections', []),
                'url': url,
                'file': filename
            }
            out_f.write(json.dumps(record) + '\n')


def process_rules_pdf(
    pdf_path: str,
    header_text: str,
    start_line: int,
    url: str,
    markdown_dir: Path,
    processed_dir: Path,
    jsonl_dir: Path
) -> None:
    """
    Process a rules PDF through all stages: PDF -> Markdown -> JSON -> JSONL
    
    Args:
        pdf_path: Path to the source PDF file
        header_text: Header text to filter out
        start_line: Line to start parsing from
        url: Source URL for the PDF
        markdown_dir: Directory to save markdown output
        processed_dir: Directory to save processed JSON
        jsonl_dir: Directory to save final JSONL
    """
    pdf_file = Path(pdf_path)
    base_name = pdf_file.stem
    
    print(f"Processing {pdf_file.name}...")
    
    # Step 1: Convert PDF to markdown
    print(f"  - Converting to markdown...")
    text = pymupdf4llm.to_markdown(str(pdf_path))
    lines = [l.strip() for l in text.split('\n') if l.strip() != '']
    
    markdown_path = markdown_dir / f"{base_name}.md"
    with open(markdown_path, 'w') as f:
        f.write('\n'.join(lines))
    
    # Step 2: Parse markdown to structured dict
    print(f"  - Parsing structure...")
    with open(markdown_path, 'r') as f:
        text = f.read()
    
    processed = parse_pdf_rules_to_dict(text, header_text, start_line)
    
    processed_path = processed_dir / f"{base_name}.json"
    with open(processed_path, 'w') as f:
        json.dump(processed, f, indent=4)
    
    # Step 3: Convert to JSONL with hierarchy
    print(f"  - Converting to JSONL with hierarchy...")
    jsonl_path = jsonl_dir / f"{base_name}.jsonl"
    convert_to_jsonl(processed, url, f"{base_name}.json", jsonl_path)
    
    print(f"  ✓ Completed: {jsonl_path}")


def main():
    """Main function to process all rules PDFs"""
    
    # Setup directories
    base_dir = Path(__file__).parent
    markdown_dir = base_dir / "markdown"
    processed_dir = base_dir / "processed"
    jsonl_dir = base_dir / "jsonl"
    
    # Create directories if they don't exist
    markdown_dir.mkdir(exist_ok=True)
    processed_dir.mkdir(exist_ok=True)
    jsonl_dir.mkdir(exist_ok=True)
    
    # Configuration for each PDF
    sources = [
        {
            'pdf': 'cos_24_rules.pdf',
            'header': 'Courses of Study 2024-2025 **common rules**',
            'start_line': 66,
            'url': 'https://home.iitd.ac.in/uploads/General%20Information/CoS%202024__General%20Rules%20(1).pdf'
        },
        {
            'pdf': 'ug_rules.pdf',
            'header': '**Undergraduate Programme Rules** Courses of Study 2024-2025',
            'start_line': 59,
            'url': 'https://home.iitd.ac.in/uploads/UG%20Programme%20Rules/CoS%202024__UG%20Programme%20Rules__changed.pdf'
        },
        {
            'pdf': 'pg_rules.pdf',
            'header': '**Postgraduate Programme Rules** Courses of Study 2024-2025',
            'start_line': 47,
            'url': 'https://home.iitd.ac.in/uploads/PG%20Programme%20Rules/CoS%202024__PG%20Programme%20Rules%20Changed.pdf'
        }
    ]
    
    # Process each PDF
    for source in sources:
        pdf_path = base_dir / source['pdf']
        if not pdf_path.exists():
            print(f"Warning: {pdf_path} not found, skipping...")
            continue
        
        process_rules_pdf(
            pdf_path=pdf_path,
            header_text=source['header'],
            start_line=source['start_line'],
            url=source['url'],
            markdown_dir=markdown_dir,
            processed_dir=processed_dir,
            jsonl_dir=jsonl_dir
        )
    
    print("\n✓ All rules PDFs processed successfully!")


if __name__ == "__main__":
    main()
