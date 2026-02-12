#!/usr/bin/env python3
"""
Re-download all PMC PDFs using Europe PMC which provides direct PDF access.

Strategy: scan all .pdf files in year subfolders, check if they're real PDFs.
For invalid ones, extract the PMID from metadata CSV (matching by year + partial
title), look up the PMC_ID, and re-download from Europe PMC.
"""
import csv
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent.resolve()
ART_DIR = BASE / "Articles_Differential_Expression"
METADATA_CSV = ART_DIR / "articles_metadata.csv"

EUROPEPMC_PDF = "https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf"
NCBI_OA = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmcid}"
DELAY = 0.5


def urlopen_safe(url, retries=3, timeout=60):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ICDTRA-Demo/1.0",
                "Accept": "application/pdf,*/*",
            })
            return urllib.request.urlopen(req, timeout=timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            if attempt == retries - 1:
                raise
            time.sleep(3 * (attempt + 1))


def is_real_pdf(filepath):
    try:
        with open(filepath, 'rb') as f:
            return f.read(5) == b'%PDF-'
    except:
        return False


def download_pdf(pmc_id):
    """Try Europe PMC, then NCBI OA. Returns bytes or None."""
    # Method 1: Europe PMC
    url = EUROPEPMC_PDF.format(pmcid=pmc_id)
    try:
        resp = urlopen_safe(url)
        data = resp.read()
        if data[:5] == b'%PDF-':
            return data
    except:
        pass

    # Method 2: NCBI OA service (FTP link)
    try:
        import xml.etree.ElementTree as ET
        url2 = NCBI_OA.format(pmcid=pmc_id)
        resp2 = urlopen_safe(url2, timeout=30)
        tree = ET.parse(resp2)
        root = tree.getroot()
        for record in root.findall('.//record'):
            for link in record.findall('.//link'):
                if link.get('format', '') == 'pdf':
                    href = link.get('href', '')
                    if href:
                        resp3 = urlopen_safe(href)
                        data3 = resp3.read()
                        if data3[:5] == b'%PDF-':
                            return data3
    except:
        pass

    return None


def main():
    # Read metadata to build PMC_ID lookup
    with open(METADATA_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Build lookup: for each row with a PMC_ID, store year + title start for matching
    pmc_lookup = []
    for row in rows:
        pmc_id = row.get("PMC_ID", "").strip()
        if not pmc_id:
            continue
        pmc_lookup.append({
            "pmc_id": pmc_id,
            "pmid": row.get("PMID", "").strip(),
            "year": row.get("Year", "").strip(),
            "title_start": (row.get("Title", "")[:30]).lower().strip(),
        })

    print(f"Loaded {len(pmc_lookup)} PMC records from metadata")

    # Scan all PDF files in year subfolders
    all_pdfs = []
    for yr_dir in sorted(ART_DIR.iterdir()):
        if not yr_dir.is_dir() or not re.match(r'^\d{4}$', yr_dir.name):
            continue
        for pdf_path in sorted(yr_dir.glob("*.pdf")):
            all_pdfs.append(pdf_path)

    print(f"Found {len(all_pdfs)} PDF files in year subfolders")

    # Check which are invalid and need re-download
    invalid_pdfs = []
    valid_count = 0
    for pdf_path in all_pdfs:
        if is_real_pdf(pdf_path):
            valid_count += 1
        else:
            invalid_pdfs.append(pdf_path)

    print(f"  Valid PDFs: {valid_count}")
    print(f"  Invalid (HTML): {len(invalid_pdfs)}")

    if not invalid_pdfs:
        print("All PDFs are valid!")
        return

    # For each invalid PDF, find the matching PMC_ID
    success = 0
    failed = 0

    for idx, pdf_path in enumerate(invalid_pdfs):
        year = pdf_path.parent.name
        fname = pdf_path.name
        # Extract first ~25 chars of title from filename for matching
        fname_start = fname[:25].lower()

        # Find matching PMC record
        pmc_id = None
        for rec in pmc_lookup:
            if rec["year"] == year and rec["title_start"][:20] in fname_start[:25]:
                pmc_id = rec["pmc_id"]
                break

        if not pmc_id:
            # Try matching by just checking all records for this year
            for rec in pmc_lookup:
                if rec["year"] == year:
                    # Check if first few chars of title match filename start
                    t = rec["title_start"][:15]
                    if t and t in fname_start:
                        pmc_id = rec["pmc_id"]
                        break

        if not pmc_id:
            print(f"  [{idx+1}/{len(invalid_pdfs)}] NO PMC_ID found for: {fname[:60]}")
            failed += 1
            continue

        print(f"  [{idx+1}/{len(invalid_pdfs)}] {pmc_id} - {fname[:50]}...", end=" ", flush=True)

        data = download_pdf(pmc_id)
        if data:
            pdf_path.write_bytes(data)
            print(f"OK ({len(data)//1024} KB)")
            success += 1
        else:
            print("FAILED")
            failed += 1

        time.sleep(DELAY)

    print(f"\nResults:")
    print(f"  Already valid: {valid_count}")
    print(f"  Re-downloaded: {success}")
    print(f"  Failed: {failed}")


if __name__ == "__main__":
    main()
