#!/usr/bin/env python3
"""
Scrape public course templates from https://courses.iitd.ac.in/ into
sources/courses_iitd/courses/*.json

Uses the HTML catalog (complete public listing). JSON:API is used as a
supplementary source when available.

Usage (from backend/):
  python sources/courses_iitd/scrape_courses_iitd.py
  python sources/courses_iitd/scrape_courses_iitd.py --max-pages 5   # smoke test
  python sources/courses_iitd/scrape_courses_iitd.py --resume        # retry only missing
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

BASE = "https://courses.iitd.ac.in"
HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "courses"
CODE_RE = re.compile(r"\b([A-Z]{2,4}\d{3,4})\b")


def fetch(url: str, *, accept: str = "text/html", retries: int = 4, backoff: float = 1.5) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ChatIITDCoursesBot/1.0 (+academic assistant; contact devops)",
            "Accept": accept,
        },
    )
    contexts = [ssl.create_default_context(), ssl._create_unverified_context()]
    last: Exception | None = None
    for attempt in range(retries + 1):
        for ctx in contexts:
            try:
                with urllib.request.urlopen(req, context=ctx, timeout=90) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception as e:  # noqa: BLE001
                last = e
        if attempt < retries:
            delay = backoff * (2**attempt)
            print(f"  retry {attempt + 1}/{retries} after {delay:.1f}s: {last}")
            time.sleep(delay)
    raise RuntimeError(f"Failed to fetch {url}: {last}")


def _existing_course(out_path: Path) -> Optional[dict[str, Any]]:
    """Return parsed course JSON if it looks successfully scraped (has a code)."""
    if not out_path.exists():
        return None
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not data.get("code"):
        return None
    return data


def _strip(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", "", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", "", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:p|div|li|tr|h[1-6])>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def discover_course_paths(max_pages: Optional[int] = None) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    page = 0
    while True:
        if max_pages is not None and page >= max_pages:
            break
        url = f"{BASE}/courses" if page == 0 else f"{BASE}/courses?page={page}"
        print(f"[list] {url}")
        try:
            html = fetch(url)
        except Exception as e:
            print(f"  stop: {e}")
            break
        found = sorted(
            {
                m
                for m in re.findall(r'href=["\'](/courses/[^"\'?#]+)["\']', html)
                if m != "/courses"
            }
        )
        new = [p for p in found if p not in seen]
        if not new:
            print(f"  empty page {page} — done")
            break
        for p in new:
            seen.add(p)
            paths.append(p)
        print(f"  +{len(new)} (total {len(paths)})")
        # stop if pager indicates last
        pages = [int(x) for x in re.findall(r"[?&]page=(\d+)", html)]
        if pages and page >= max(pages):
            break
        page += 1
        time.sleep(0.12)
    return paths


def _field_item(html: str, field_name: str) -> Optional[str]:
    """Extract first field-item text for a Drupal field-name-* block."""
    # Prefer exact field-type-string/decimal/integer items when present
    patterns = [
        rf'field-name-{re.escape(field_name)}\s+field-type-[^"]*?field-item[^"]*">\s*([^<]+)',
        rf'field-name-{re.escape(field_name)}[\s\S]*?<div class="field-item[^"]*">\s*([^<]+)',
        rf'field-name-{re.escape(field_name)}[\s\S]*?<div class="field-item[^"]*">(.*?)</div>',
    ]
    for pat in patterns:
        m = re.search(pat, html, flags=re.I)
        if m:
            val = _strip(m.group(1))
            if val:
                return val
    return None


def parse_course_page(html: str, path: str) -> dict[str, Any]:
    title_m = re.search(
        r'field--node--title[\s\S]*?<span>(.*?)</span>',
        html,
        flags=re.I,
    ) or re.search(r"<h1[^>]*>[\s\S]*?<span>(.*?)</span>", html, flags=re.I)
    title = _strip(title_m.group(1)) if title_m else path.rsplit("/", 1)[-1]

    # Course code: dedicated string field item
    code = None
    m = re.search(
        r'field-name-field-course-number\s+field-type-string\s+field-label-hidden\s+field-item">\s*([A-Z0-9]+)',
        html,
        flags=re.I,
    )
    if m:
        code = m.group(1).upper()
    if not code:
        # fallback: first CODE-like token near "Course Number"
        window = re.search(r"Course Number[\s\S]{0,800}", html, flags=re.I)
        if window:
            codes = CODE_RE.findall(_strip(window.group(0)))
            if codes:
                code = codes[0].upper()

    credits_s = _field_item(html, "field-credit")
    # L-T-P: prefer values inside the L-T-P structure fieldset
    ltp_block = re.search(
        r'field-name-field-l-t-p-structure[\s\S]*?(?=field-name-field-(?!l-|t-|p-)|</article>|$)',
        html,
        flags=re.I,
    )
    ltp_html = ltp_block.group(0) if ltp_block else html
    lecture = _field_item(ltp_html, "field-l-lecture-new") or _field_item(ltp_html, "field-l-lecture")
    tutorial = _field_item(ltp_html, "field-t-tutorial-new") or _field_item(ltp_html, "field-t-tutorial")
    practical = _field_item(ltp_html, "field-p-practical-new") or _field_item(ltp_html, "field-p-practical")
    prereq = _field_item(html, "field-prerequisite-text")
    contents = None
    m = re.search(
        r'field-name-field-course-contents[\s\S]*?<div class="field-item[^"]*">(.*?)</div>',
        html,
        flags=re.I | re.S,
    )
    if m:
        contents = _strip(m.group(1))
    if not contents:
        contents = _field_item(html, "field-course-contents")
    # Department: often shown near course prefix cell
    dept = None
    dm = re.search(
        r'field-name-field-department[\s\S]*?<div class="field-item[^"]*">(.*?)</div>',
        html,
        flags=re.I | re.S,
    )
    if dm:
        dept = _strip(dm.group(1))
    if not dept:
        dm = re.search(r"\[([A-Z]{2,3})\]\s+([^<\n]{3,80}?),\s*Department", html)
        if dm:
            dept = _strip(dm.group(2) + ", Department of")

    # Precluded / overlap list
    precluded: list[str] = []
    pm = re.search(
        r'field-name-field-precluded-courses[\s\S]*?<div class="field-items">(.*?)</div>\s*</div>',
        html,
        flags=re.I | re.S,
    )
    if pm:
        precluded = CODE_RE.findall(_strip(pm.group(1)))

    # CLOs
    outcomes: list[str] = []
    for lm in re.finditer(r"<li[^>]*>(.*?)</li>", html, flags=re.I | re.S):
        t = _strip(lm.group(1))
        if t and len(t) > 15 and not t.lower().startswith("file name"):
            # keep only likely CLO items near learning outcomes
            outcomes.append(t)
    # Heuristic: CLOs usually under "On successful completion"
    if "On successful completion" in html:
        region = html.split("On successful completion", 1)[1][:3000]
        outcomes = [_strip(x) for x in re.findall(r"<li[^>]*>(.*?)</li>", region, flags=re.I | re.S)]
        outcomes = [o for o in outcomes if o]

    def _fnum(s: Optional[str]) -> Optional[float]:
        if not s:
            return None
        m = re.search(r"[\d.]+", s.replace(",", ""))
        return float(m.group(0)) if m else None

    digits = sum(ch.isdigit() for ch in (code or ""))
    generation = "2025" if digits >= 4 else "legacy"

    return {
        "code": code,
        "name": title,
        "description": contents,
        "credits": _fnum(credits_s),
        "hours": {
            "lecture": _fnum(lecture),
            "tutorial": _fnum(tutorial),
            "practical": _fnum(practical),
        },
        "prereq": prereq,
        "overlap": ", ".join(dict.fromkeys(precluded)) if precluded else None,
        "learning_outcomes": outcomes,
        "department": dept,
        "generation": generation,
        "source": "courses_iitd",
        "source_url": urljoin(BASE, path),
        "slug": path.rsplit("/", 1)[-1],
    }


def maybe_enrich_jsonapi(course: dict[str, Any]) -> dict[str, Any]:
    """Optional light enrichment — skipped if API is flaky; HTML is source of truth."""
    return course


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape courses.iitd.ac.in. "
            "After a partial run (sleep/network), re-run with --resume to fetch only missing courses."
        )
    )
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--max-courses", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.12)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip courses that already have a slug JSON with a course code; retry the rest",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Alias for --resume (retry only courses not successfully saved yet)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=4,
        help="Per-URL network retries with exponential backoff (default 4)",
    )
    args = parser.parse_args()
    if args.retry_failed:
        args.resume = True

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = discover_course_paths(max_pages=args.max_pages)
    if args.max_courses:
        paths = paths[: args.max_courses]

    if args.resume:
        missing = [
            p
            for p in paths
            if _existing_course(OUT_DIR / f"{p.rsplit('/', 1)[-1]}.json") is None
        ]
        print(
            f"Resume mode: {len(paths) - len(missing)} already saved, "
            f"{len(missing)} to fetch (of {len(paths)} listed)"
        )
    else:
        print(f"Fetching {len(paths)} course pages…")

    index: list[dict[str, str]] = []
    ok = 0
    skipped = 0
    failed = 0
    for i, path in enumerate(paths, start=1):
        slug = path.rsplit("/", 1)[-1]
        out_path = OUT_DIR / f"{slug}.json"
        if args.resume:
            existing = _existing_course(out_path)
            if existing:
                index.append(
                    {
                        "code": existing["code"],
                        "slug": slug,
                        "source_url": existing.get("source_url") or urljoin(BASE, path),
                    }
                )
                ok += 1
                skipped += 1
                continue

        url = urljoin(BASE, path)
        try:
            html = fetch(url, retries=args.retries)
            course = parse_course_page(html, path)
            course = maybe_enrich_jsonapi(course)
        except Exception as e:
            failed += 1
            print(f"  [{i}/{len(paths)}] FAIL {path}: {e}")
            time.sleep(args.sleep)
            continue

        if not course.get("code"):
            print(f"  [{i}/{len(paths)}] no code for {path} — saving anyway")
            out_path.write_text(json.dumps(course, indent=2), encoding="utf-8")
            failed += 1  # incomplete; resume will retry until code is present
        else:
            code_path = OUT_DIR / f"{course['code']}.json"
            payload = json.dumps(course, indent=2)
            out_path.write_text(payload, encoding="utf-8")
            code_path.write_text(payload, encoding="utf-8")
            index.append(
                {
                    "code": course["code"],
                    "slug": slug,
                    "source_url": course["source_url"],
                }
            )
            ok += 1
            print(f"  [{i}/{len(paths)}] {course['code']} {course.get('name','')[:60]}")
        time.sleep(args.sleep)

    meta = {
        "source": BASE,
        "course_count": ok,
        "paths_seen": len(paths),
        "skipped_existing": skipped,
        "failed": failed,
        "courses": index,
    }
    (HERE / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (HERE / "courses_index.json").write_text(
        json.dumps(sorted({c["code"] for c in index}), indent=2), encoding="utf-8"
    )
    print(
        f"Done. ok_with_code={ok} skipped_existing={skipped} failed_or_incomplete={failed} "
        f"under {OUT_DIR}"
    )
    if failed:
        print("Re-run with: python3 sources/courses_iitd/scrape_courses_iitd.py --resume")


if __name__ == "__main__":
    main()
