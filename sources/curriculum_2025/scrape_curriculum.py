"""
Scrape https://curriculum.iitd.ac.in/ into sources/curriculum_2025/{programmes,courses}/.

Usage (from backend/):
  python sources/curriculum_2025/scrape_curriculum.py
"""

from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, parse_qs

BASE = "https://curriculum.iitd.ac.in/"
HERE = Path(__file__).resolve().parent
PROG_DIR = HERE / "programmes"
COURSE_DIR = HERE / "courses"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ChatIITDCurriculumBot/1.0"})
    contexts = [ssl.create_default_context(), ssl._create_unverified_context()]
    last_err: Exception | None = None
    for ctx in contexts:
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001 — retry with unverified SSL
            last_err = e
            continue
    raise RuntimeError(f"Failed to fetch {url}: {last_err}")


class _OptionCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_select = False
        self.select_name = ""
        self.current_value = ""
        self.current_text: list[str] = []
        self.options: dict[str, list[tuple[str, str]]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = dict(attrs)
        if tag == "select":
            self.in_select = True
            self.select_name = ad.get("name") or ad.get("id") or "unknown"
            self.options.setdefault(self.select_name, [])
        elif tag == "option" and self.in_select:
            self.current_value = ad.get("value") or ""
            self.current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self.in_select = False
        elif tag == "option" and self.in_select and self.current_value:
            text = re.sub(r"\s+", " ", "".join(self.current_text)).strip()
            self.options[self.select_name].append((self.current_value, text))

    def handle_data(self, data: str) -> None:
        if self.in_select:
            self.current_text.append(data)


def discover_codes(index_html: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    parser = _OptionCollector()
    parser.feed(index_html)
    aus = parser.options.get("au", [])
    # programme_code appears in multiple forms; merge unique
    seen: dict[str, str] = {}
    for name, opts in parser.options.items():
        if name == "program_code" or "program" in name:
            for code, label in opts:
                seen[code] = label
    return aus, list(seen.items())


def _strip_tags(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", "", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", "", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:p|div|tr|h[1-6]|li)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def parse_course_page(html: str, au: str) -> list[dict[str, Any]]:
    courses: list[dict[str, Any]] = []
    # Blocks: <h4 id="CODE" class="ct">CODE: Title</h4><div class="csub">...</div><div class="cct">...</div><div class="cclo">...</div>
    pattern = re.compile(
        r'<h4[^>]*id="(?P<code>[A-Z0-9]+)"[^>]*class="ct"[^>]*>'
        r"(?P<header>.*?)</h4>\s*"
        r'(?:<div class="csub">(?P<sub>.*?)</div>)?\s*'
        r'(?:<div class="cct">(?P<desc>.*?)</div>)?\s*'
        r"(?:<p>\s*)?"
        r'(?:<div class="cclo">(?P<clo>.*?)</div>)?',
        re.I | re.S,
    )
    for m in pattern.finditer(html):
        code = m.group("code").upper()
        header = _strip_tags(m.group("header") or "")
        title = header.split(":", 1)[-1].strip() if ":" in header else header
        sub = _strip_tags(m.group("sub") or "")
        credits = None
        hours = {"lecture": None, "tutorial": None, "practical": None}
        cm = re.search(
            r"([\d.]+)\s*credits\s*\(([\d.]+)-([\d.]+)-([\d.]+)\)",
            sub,
            re.I,
        )
        if cm:
            credits = float(cm.group(1))
            hours = {
                "lecture": float(cm.group(2)),
                "tutorial": float(cm.group(3)),
                "practical": float(cm.group(4)),
            }
        desc = _strip_tags(m.group("desc") or "")
        clo_html = m.group("clo") or ""
        outcomes = [
            _strip_tags(li)
            for li in re.findall(r"<li[^>]*>(.*?)</li>", clo_html, flags=re.I | re.S)
        ]
        outcomes = [o for o in outcomes if o]
        courses.append(
            {
                "code": code,
                "name": title,
                "description": desc,
                "credits": credits,
                "hours": hours,
                "learning_outcomes": outcomes,
                "academic_unit": au,
                "generation": "2025",
                "source": "curriculum_web",
                "source_url": f"{BASE}coursesbyau.php?au={au}#{code}",
            }
        )
    return courses


def _parse_credit_tables(text_lines: list[str]) -> list[dict[str, Any]]:
    reqs: list[dict[str, Any]] = []
    # Look for Category / Credits pairs in overall structure region
    cats = {
        "BS": "Basic Sciences",
        "GE": "General Engineering",
        "HS": "Humanities and Social Sciences",
        "EAS": "Engineering Arts and Sciences",
        "HuSS": "Humanities and Social Sciences",
        "PL": "Programme-Linked",
        "DC": "Departmental Core",
        "DE": "Departmental Electives",
        "OC": "Open Category",
        "PC": "Programme Core",
    }
    joined = "\n".join(text_lines)
    for code, label in cats.items():
        m = re.search(
            rf"{re.escape(code)}\s*(?:\([^)]+\))?\s*\n?\s*(\d+(?:\.\d+)?)",
            joined,
            re.I,
        )
        if m:
            reqs.append(
                {
                    "category": code,
                    "label": label,
                    "credits_or_units": float(m.group(1)),
                    "kind": "graded",
                }
            )
    # NGU lines
    for label, key in [
        ("Life skills", "NGU_LIFE"),
        ("English language learning", "NGU_ENGLISH"),
        ("Departmental project, internship experience", "NGU_PROJECT"),
        ("NCC / NSO / NSS", "NGU_NCC"),
    ]:
        m = re.search(rf"{re.escape(label)}\s*\n?\s*(\d+(?:\.\d+)?)", joined, re.I)
        if m:
            reqs.append(
                {
                    "category": key,
                    "label": label,
                    "credits_or_units": float(m.group(1)),
                    "kind": "ngu",
                }
            )
    return reqs


def _parse_plos(text_lines: list[str]) -> list[dict[str, str]]:
    plos = []
    for i, line in enumerate(text_lines):
        m = re.match(r"^(PLO\s*\d+)\s*$", line.strip(), re.I)
        if m and i + 1 < len(text_lines):
            plos.append({"outcome_id": m.group(1).upper().replace(" ", ""), "text": text_lines[i + 1].strip()})
    return plos


COURSE_ROW = re.compile(
    r"^([A-Z]{2,4}\d{3,4})\s+(.+?)\s+([\d.\-–]+)\s+([\d.\-–]+)\s+([\d.\-–]+)\s+([\d.\-–]+)\s*$"
)
COURSE_INLINE = re.compile(
    r"([A-Z]{2,4}\d{3,4})\s+(.+?)\s+\(([\d.]+)-([\d.]+)-([\d.]+)\)\s+([\d.]+)"
)


def parse_program_page(html: str, code: str, name: str) -> dict[str, Any]:
    plain = _strip_tags(html)
    lines = [re.sub(r"\s+", " ", l).strip() for l in plain.splitlines()]
    lines = [l for l in lines if l]

    credit_reqs = _parse_credit_tables(lines)
    outcomes = _parse_plos(lines)

    # Category course lists: capture tables under known headings
    category_courses: dict[str, list[dict[str, Any]]] = {}
    current_cat = None
    cat_headers = {
        "General Engineering Core": "GE",
        "Basic Science Core": "BS",
        "Departmental Core": "DC",
        "Programme Core": "PC",
        "General Engineering Electives": "GE_ELEC",
        "Humanities and Social Sciences Electives": "HS",
        "Basic Science Electives": "BS_ELEC",
        "Departmental Electives": "DE",
    }
    for line in lines:
        if line in cat_headers:
            current_cat = cat_headers[line]
            category_courses.setdefault(current_cat, [])
            continue
        if line.startswith("Semester-wise"):
            current_cat = None
            continue
        if current_cat:
            m = COURSE_ROW.match(line.replace("–", "-"))
            if m:
                category_courses[current_cat].append(
                    {
                        "course_code": m.group(1),
                        "title": m.group(2).strip(),
                        "hours": {
                            "lecture": m.group(3),
                            "tutorial": m.group(4),
                            "practical": m.group(5),
                        },
                        "credits": m.group(6),
                    }
                )

    # Semester schedule via inline course patterns under "Sem N"
    semesters: dict[int, list[dict[str, Any]]] = {}
    current_sem = None
    for line in lines:
        sm = re.match(r"^(\d{1,2})\s*$", line)
        # Heuristic: semester numbers appear as lone digits in schedule table — weak.
        # Prefer lines that contain course codes with L-T-P
        for m in COURSE_INLINE.finditer(line):
            entry = {
                "course_code": m.group(1),
                "title": m.group(2).strip(),
                "hours": {
                    "lecture": float(m.group(3)),
                    "tutorial": float(m.group(4)),
                    "practical": float(m.group(5)),
                },
                "credits": float(m.group(6)),
            }
            # If we haven't detected semester, dump into 0 and fix later from HTML tables
            semesters.setdefault(current_sem or 0, []).append(entry)
        if re.match(r"^Sem(?:ester)?\s*(\d+)$", line, re.I):
            current_sem = int(re.match(r"^Sem(?:ester)?\s*(\d+)$", line, re.I).group(1))

    # Better semester parse from HTML tables: first column digit
    semesters_html: dict[int, list[dict[str, Any]]] = {}
    for table in re.findall(r"<table[^>]*>(.*?)</table>", html, flags=re.I | re.S):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, flags=re.I | re.S)
        if not rows:
            continue
        header = _strip_tags(rows[0]).lower()
        if "sem" not in header and "courses" not in header:
            continue
        for row in rows[1:]:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.I | re.S)
            if len(cells) < 2:
                continue
            sem_txt = _strip_tags(cells[0])
            if not re.match(r"^\d+$", sem_txt):
                continue
            sem = int(sem_txt)
            body = cells[1]
            entries = []
            for m in COURSE_INLINE.finditer(_strip_tags(body).replace("\n", " ")):
                entries.append(
                    {
                        "course_code": m.group(1),
                        "title": m.group(2).strip(),
                        "hours": {
                            "lecture": float(m.group(3)),
                            "tutorial": float(m.group(4)),
                            "practical": float(m.group(5)),
                        },
                        "credits": float(m.group(6)),
                    }
                )
            # Basket placeholders (no course code)
            for basket in re.findall(
                r"([A-Za-z][^<\n]{3,60}?)\s*\(([\d.]+)-([\d.]+)-([\d.]+)\)\s*([\d.]+)\s*(?:NGU)?",
                _strip_tags(body),
            ):
                if re.match(r"^[A-Z]{2,4}\d", basket[0].strip()):
                    continue
                entries.append(
                    {
                        "basket": basket[0].strip(),
                        "hours": {
                            "lecture": float(basket[1]),
                            "tutorial": float(basket[2]),
                            "practical": float(basket[3]),
                        },
                        "credits": float(basket[4]),
                    }
                )
            if entries:
                semesters_html[sem] = entries

    if semesters_html:
        semesters = semesters_html

    dual = "and M.Tech" in name or "Dual" in name
    degree_type = "unknown"
    lower = name.lower()
    if "b.tech" in lower and "m.tech" in lower:
        degree_type = "dual"
    elif "b.tech" in lower:
        degree_type = "btech"
    elif "bachelor of design" in lower or "b.des" in lower:
        degree_type = "bdes"
    elif "bs in" in lower or lower.startswith("bs "):
        degree_type = "bs"
    elif "m.tech" in lower:
        degree_type = "mtech"
    elif "m.sc" in lower:
        degree_type = "msc"
    elif "m.a" in lower or "master of arts" in lower:
        degree_type = "ma"
    elif "public policy" in lower:
        degree_type = "mpp"
    elif "master of design" in lower:
        degree_type = "mdes"

    return {
        "code": code,
        "name": name,
        "generation": "2025",
        "degree_type": degree_type,
        "dual": dual,
        "source_url": f"{BASE}view_program.php?program_code={code}",
        "credit_requirements": credit_reqs,
        "outcomes": outcomes,
        "courses_by_category": category_courses,
        "semesters": {str(k): v for k, v in sorted(semesters.items())},
        "raw_text_preview": "\n".join(lines[:80]),
    }


def main() -> None:
    PROG_DIR.mkdir(parents=True, exist_ok=True)
    COURSE_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching index…")
    index = fetch(BASE)
    aus, programmes = discover_codes(index)
    print(f"Found {len(aus)} academic units, {len(programmes)} programmes")

    # Courses by AU
    all_courses: dict[str, dict] = {}
    for au, au_name in aus:
        url = urljoin(BASE, f"coursesbyau.php?au={au}")
        print(f"  courses au={au} ({au_name})")
        try:
            html = fetch(url)
        except urllib.error.HTTPError as e:
            print(f"    skip: {e}")
            continue
        for c in parse_course_page(html, au):
            all_courses[c["code"]] = c
        time.sleep(0.15)

    for code, c in all_courses.items():
        (COURSE_DIR / f"{code}.json").write_text(json.dumps(c, indent=2), encoding="utf-8")
    (HERE / "courses_index.json").write_text(
        json.dumps(sorted(all_courses.keys()), indent=2), encoding="utf-8"
    )
    print(f"Wrote {len(all_courses)} courses")

    # Programmes
    for code, name in programmes:
        url = urljoin(BASE, f"view_program.php?program_code={code}")
        print(f"  programme {code}: {name}")
        try:
            html = fetch(url)
        except urllib.error.HTTPError as e:
            print(f"    skip: {e}")
            continue
        data = parse_program_page(html, code, name)
        (PROG_DIR / f"{code}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        time.sleep(0.15)

    meta = {
        "source": BASE,
        "academic_units": [{"code": a, "name": n} for a, n in aus],
        "programmes": [{"code": c, "name": n} for c, n in programmes],
        "course_count": len(all_courses),
    }
    (HERE / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("Done.")


if __name__ == "__main__":
    main()
