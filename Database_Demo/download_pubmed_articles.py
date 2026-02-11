#!/usr/bin/env python3
"""
Download PubMed articles matching the search:
  "cancer" AND "differential expression" AND "India"

Steps:
  1. Use NCBI E-utilities (ESearch) to retrieve all PMIDs.
  2. Use EFetch to get full metadata in XML for each batch.
  3. Identify articles available via PubMed Central (PMC) as open-access.
  4. Download PDFs from PMC for free articles.
  5. Save a metadata CSV listing every article and its download status.

Rate-limit: 3 requests/sec without API key (NCBI guideline).
"""
import csv
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path(__file__).parent.resolve()
OUT_DIR = BASE / "Articles_Differential_Expression"
OUT_DIR.mkdir(exist_ok=True)

# NCBI E-utilities base URLs
ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ELINK   = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"

SEARCH_TERM = '"cancer" AND "differential expression" AND "India"'
BATCH = 100          # IDs per EFetch call
DELAY = 0.4          # seconds between API calls (< 3/sec)

PMC_OA_PDF = "https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"


def urlopen_safe(url, retries=3, timeout=30):
    """Open URL with retries."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ICDTRA-Demo/1.0"})
            return urllib.request.urlopen(req, timeout=timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def esearch_all():
    """Return list of all PMIDs for the search."""
    params = urllib.parse.urlencode({
        "db": "pubmed",
        "term": SEARCH_TERM,
        "retmax": 10000,
        "retmode": "xml",
    })
    url = f"{ESEARCH}?{params}"
    resp = urlopen_safe(url)
    tree = ET.parse(resp)
    root = tree.getroot()
    count = int(root.findtext("Count", "0"))
    ids = [id_el.text for id_el in root.findall(".//IdList/Id")]
    print(f"ESearch: {count} results, retrieved {len(ids)} PMIDs")
    return ids


def efetch_batch(pmids):
    """Fetch article metadata for a batch of PMIDs. Returns XML root."""
    params = urllib.parse.urlencode({
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "rettype": "xml",
    })
    url = f"{EFETCH}?{params}"
    resp = urlopen_safe(url)
    tree = ET.parse(resp)
    return tree.getroot()


def parse_article(article_el):
    """Extract metadata from a PubmedArticle XML element."""
    mc = article_el.find("MedlineCitation")
    if mc is None:
        return None
    pmid = mc.findtext("PMID", "")

    art = mc.find("Article")
    title = ""
    if art is not None:
        title = art.findtext("ArticleTitle", "")
        # journal
        journal_el = art.find("Journal")
        journal = journal_el.findtext("Title", "") if journal_el else ""
        # year
        pd = art.find("Journal/JournalIssue/PubDate")
        year = pd.findtext("Year", "") if pd is not None else ""
        if not year and pd is not None:
            med_date = pd.findtext("MedlineDate", "")
            m = re.match(r"(\d{4})", med_date)
            if m:
                year = m.group(1)
        # authors
        authors_el = art.findall("AuthorList/Author")
        author_strs = []
        for a in authors_el:
            ln = a.findtext("LastName", "")
            ini = a.findtext("Initials", "")
            if ln:
                author_strs.append(f"{ln} {ini}".strip())
        authors = "; ".join(author_strs)
    else:
        journal = year = authors = ""

    # DOI
    doi = ""
    aid_list = art.findall("ELocationID") if art is not None else []
    for aid in aid_list:
        if aid.get("EIdType") == "doi":
            doi = aid.text or ""
            break

    # PMC ID from PubmedData/ArticleIdList
    pmc_id = ""
    pd_el = article_el.find("PubmedData")
    if pd_el is not None:
        for aid in pd_el.findall("ArticleIdList/ArticleId"):
            if aid.get("IdType") == "pmc":
                pmc_id = aid.text or ""
                break

    return {
        "PMID": pmid,
        "Title": title,
        "Authors": authors,
        "Journal": journal,
        "Year": year,
        "DOI": doi,
        "PMC_ID": pmc_id,
        "Free_PMC": "Yes" if pmc_id else "No",
        "PDF_Downloaded": "No",
        "PDF_Filename": "",
    }


def download_pmc_pdf(pmc_id, pmid):
    """Attempt to download a PDF from PMC. Returns filename or None."""
    url = PMC_OA_PDF.format(pmcid=pmc_id)
    try:
        resp = urlopen_safe(url, timeout=60)
        content_type = resp.headers.get("Content-Type", "")
        data = resp.read()
        if len(data) < 1000:
            return None  # too small, probably an error page
        fname = f"PMID_{pmid}_{pmc_id}.pdf"
        fpath = OUT_DIR / fname
        fpath.write_bytes(data)
        return fname
    except Exception as e:
        print(f"  Could not download PDF for {pmc_id}: {e}")
        return None


def main():
    print("=" * 60)
    print("PubMed Article Downloader")
    print("=" * 60)

    # Step 1: Get all PMIDs
    print("\n[1/4] Searching PubMed...")
    pmids = esearch_all()
    if not pmids:
        print("No results found. Exiting.")
        return
    time.sleep(DELAY)

    # Step 2: Fetch metadata in batches
    print(f"\n[2/4] Fetching metadata for {len(pmids)} articles...")
    articles = []
    for i in range(0, len(pmids), BATCH):
        batch = pmids[i:i + BATCH]
        print(f"  Batch {i // BATCH + 1}: PMIDs {i + 1}–{min(i + BATCH, len(pmids))}")
        root = efetch_batch(batch)
        for art_el in root.findall("PubmedArticle"):
            info = parse_article(art_el)
            if info:
                articles.append(info)
        time.sleep(DELAY)

    print(f"  Parsed {len(articles)} articles")
    pmc_articles = [a for a in articles if a["PMC_ID"]]
    print(f"  {len(pmc_articles)} have PMC IDs (potentially free)")

    # Step 3: Download PDFs for PMC articles
    print(f"\n[3/4] Downloading PDFs for {len(pmc_articles)} PMC articles...")
    downloaded = 0
    for idx, art in enumerate(pmc_articles):
        pmc_id = art["PMC_ID"]
        pmid = art["PMID"]
        print(f"  [{idx + 1}/{len(pmc_articles)}] {pmc_id} (PMID {pmid})...", end=" ")
        fname = download_pmc_pdf(pmc_id, pmid)
        if fname:
            art["PDF_Downloaded"] = "Yes"
            art["PDF_Filename"] = fname
            downloaded += 1
            print("OK")
        else:
            print("skipped")
        time.sleep(DELAY)

    print(f"\n  Downloaded {downloaded} / {len(pmc_articles)} PMC PDFs")

    # Step 4: Save metadata CSV
    csv_path = OUT_DIR / "articles_metadata.csv"
    print(f"\n[4/4] Saving metadata CSV: {csv_path}")
    fieldnames = [
        "PMID", "Title", "Authors", "Journal", "Year",
        "DOI", "PMC_ID", "Free_PMC", "PDF_Downloaded", "PDF_Filename",
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(articles)

    print(f"\nDone!")
    print(f"  Total articles: {len(articles)}")
    print(f"  PDFs downloaded: {downloaded}")
    print(f"  Metadata CSV: {csv_path}")
    print(f"  PDFs saved to: {OUT_DIR}")


if __name__ == "__main__":
    main()
