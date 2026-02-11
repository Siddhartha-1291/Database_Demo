#!/usr/bin/env python3
"""
Rename downloaded PDFs to Title_Authors_Journal_Year.pdf format,
create year subfolders, and move PDFs into them.
Also generates literature_data.js for the website.
"""
import csv
import json
import os
import re
import shutil
from pathlib import Path

BASE = Path(__file__).parent.resolve()
ART_DIR = BASE / "Articles_Differential_Expression"
METADATA_CSV = ART_DIR / "articles_metadata.csv"


def sanitize_filename(s, max_len=80):
    """Remove or replace characters not valid in Windows filenames."""
    # Replace problematic characters
    s = s.replace("/", "-").replace("\\", "-")
    s = s.replace(":", " -").replace("*", "").replace("?", "")
    s = s.replace('"', "'").replace("<", "(").replace(">", ")")
    s = s.replace("|", "-").replace("&", "and")
    s = s.replace("\n", " ").replace("\r", " ")
    # Remove any remaining characters illegal on Windows
    s = re.sub(r'[<>:"/\\|?*]', '', s)
    # Collapse multiple spaces
    s = re.sub(r"\s+", " ", s).strip()
    # Truncate to max_len
    if len(s) > max_len:
        s = s[:max_len].rstrip()
    # Remove trailing dots/spaces (Windows restriction)
    s = s.rstrip(". ")
    return s


def format_authors(authors_str):
    """
    Convert "Abdul NS; Shenoy M; Shivakumar GC" 
    to     "Abdul NS_Shenoy M_Shivakumar GC"
    """
    # Split by semicolon followed by optional spaces
    parts = re.split(r";\s*", authors_str.strip())
    # Strip each name and filter blanks
    parts = [p.strip() for p in parts if p.strip()]
    return "_".join(parts)


def main():
    if not METADATA_CSV.exists():
        print(f"ERROR: {METADATA_CSV} not found.")
        return

    # Read metadata
    with open(METADATA_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Read {len(rows)} article records from metadata CSV.")

    # Step 1: Rename PDFs
    rename_map = {}  # old filename -> new filename
    pdf_records = []  # records with PDFs (for year organisation)

    for row in rows:
        old_fname = row.get("PDF_Filename", "").strip()
        if not old_fname:
            continue
        old_path = ART_DIR / old_fname
        if not old_path.exists():
            print(f"  WARNING: {old_fname} not found, skipping.")
            continue

        title = sanitize_filename(row.get("Title", "Untitled"), max_len=60)
        authors = format_authors(row.get("Authors", "Unknown"))
        authors = sanitize_filename(authors, max_len=60)
        journal = sanitize_filename(row.get("Journal", "Unknown"), max_len=40)
        year = row.get("Year", "Unknown").strip()

        new_fname = f"{title}_{authors}_{journal}_{year}.pdf"
        # Windows total path limit safety (260 chars minus directory path ~170)
        max_fname = 85
        if len(new_fname) > max_fname:
            # Shorten title and authors proportionally
            suffix = f"_{journal}_{year}.pdf"
            available = max_fname - len(suffix) - 1  # -1 for underscore
            if available < 20:
                available = 20
            t_len = min(len(title), available // 2)
            a_len = available - t_len
            title = sanitize_filename(row.get("Title", "Untitled"), max_len=t_len)
            authors = sanitize_filename(format_authors(row.get("Authors", "Unknown")), max_len=a_len)
            new_fname = f"{title}_{authors}_{journal}_{year}.pdf"

        new_path = ART_DIR / new_fname

        # Handle filename collision
        if new_path.exists() and new_path != old_path:
            base, ext = os.path.splitext(new_fname)
            counter = 2
            while (ART_DIR / f"{base}_{counter}{ext}").exists():
                counter += 1
            new_fname = f"{base}_{counter}{ext}"
            new_path = ART_DIR / new_fname

        if old_path != new_path:
            old_path.rename(new_path)
            rename_map[old_fname] = new_fname

        pdf_records.append({
            "filename": new_fname,
            "year": year,
            "title": row.get("Title", ""),
            "authors": row.get("Authors", ""),
            "journal": row.get("Journal", ""),
            "pmid": row.get("PMID", ""),
        })

    print(f"Renamed {len(rename_map)} PDF files.")

    # Update the CSV with new filenames
    for row in rows:
        old = row.get("PDF_Filename", "").strip()
        if old in rename_map:
            row["PDF_Filename"] = rename_map[old]

    with open(METADATA_CSV, "w", encoding="utf-8", newline="") as f:
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print("Updated articles_metadata.csv with new filenames.")

    # Step 2: Create year subfolders and move PDFs
    years_with_pdfs = {}
    for rec in pdf_records:
        yr = rec["year"]
        if yr not in years_with_pdfs:
            years_with_pdfs[yr] = []
        years_with_pdfs[yr].append(rec)

    for yr in sorted(years_with_pdfs.keys()):
        yr_dir = ART_DIR / yr
        yr_dir.mkdir(exist_ok=True)
        for rec in years_with_pdfs[yr]:
            src = ART_DIR / rec["filename"]
            dst = yr_dir / rec["filename"]
            if src.exists():
                shutil.move(str(src), str(dst))
            elif dst.exists():
                pass  # already moved
            else:
                print(f"  WARNING: {rec['filename']} not found for move.")

    print(f"Created {len(years_with_pdfs)} year folders: {', '.join(sorted(years_with_pdfs.keys()))}")

    # Step 3: Generate literature_data.js for the website
    lit_data = {}
    for yr in sorted(years_with_pdfs.keys(), reverse=True):
        lit_data[yr] = []
        for rec in sorted(years_with_pdfs[yr], key=lambda r: r["filename"]):
            lit_data[yr].append(rec["filename"])

    js_path = BASE / "literature_data.js"
    js_content = "// Auto-generated – lists PDF files per publication year.\n"
    js_content += "var LITERATURE = " + json.dumps(lit_data, indent=2) + ";\n"
    js_path.write_text(js_content, encoding="utf-8")
    print(f"Generated literature_data.js ({js_path.stat().st_size / 1024:.1f} KB)")

    total_pdfs = sum(len(v) for v in years_with_pdfs.values())
    print(f"\nDone! {total_pdfs} PDFs organised into {len(years_with_pdfs)} year folders.")


if __name__ == "__main__":
    main()
