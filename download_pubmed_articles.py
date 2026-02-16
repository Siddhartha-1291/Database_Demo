#!/usr/bin/env python3
"""
PubMed Article Downloader & Metadata Collector  (v4 – lean & parallel)
======================================================================
Lean download strategies + 8 parallel workers for maximum throughput.
- Europe PMC for PMC articles (single attempt, fastest source)
- Unpaywall for OA articles without PMC or when Europe PMC fails
- NCBI PMC as final fallback for PMC articles
"""

import requests, xml.etree.ElementTree as ET
import csv, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ── Config ───────────────────────────────────────────────────────────────────
OUTPUT_DIR  = "Biomarker_Prospective_Study_Cancer"
CSV_FILE    = "articles_metadata.csv"
PROG_FILE   = "download_progress.json"
EUTILS      = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_DELAY  = 0.35
BATCH       = 200
MAX_WORKERS = 8

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HDR = {"User-Agent": UA}

SEARCH_QUERY = (
    '((biomarker[Title/Abstract]) AND (prospective study[Title/Abstract])) AND '
    '((cancer[Title/Abstract]) OR (leukemia[Title/Abstract]) OR '
    '(astrocytoma[Title/Abstract]) OR (blastoma[Title/Abstract]) OR '
    '(carcinoma[Title/Abstract]) OR (cholangiocarcinoma[Title/Abstract]) OR '
    '(chordoma[Title/Abstract]) OR (craniopharyngioma[Title/Abstract]) OR '
    '(ependymoma[Title/Abstract]) OR (esthesioneuroblastoma[Title/Abstract]) OR '
    '(glioma[Title/Abstract]) OR (histiocytoma[Title/Abstract]) OR '
    '(lymphoma[Title/Abstract]) OR (medulloblastoma[Title/Abstract]) OR '
    '(melanoma[Title/Abstract]) OR (mesothelioma[Title/Abstract]) OR '
    '(myeloma[Title/Abstract]) OR (neuroblastoma[Title/Abstract]) OR '
    '(osteosarcoma[Title/Abstract]) OR (papillomatosis[Title/Abstract]) OR '
    '(paraganglioma[Title/Abstract]) OR (pheochromocytoma[Title/Abstract]) OR '
    '(retinoblastoma[Title/Abstract]) OR (rhabdomyosarcoma[Title/Abstract]) OR '
    '(sarcoma[Title/Abstract]) OR (thymoma[Title/Abstract]))'
)

FIELDNAMES = ["PMID","Title","Authors","Journal","Year",
              "DOI","PMC_ID","Free_PMC","PDF_Downloaded","PDF_Filename"]

# Thread-safe helpers
_plock = Lock()
_clock = Lock()
stats = {"ok":0, "fail":0, "skip":0, "done":0}

def tprint(msg):
    with _plock: print(msg, flush=True)

# ── Utilities ────────────────────────────────────────────────────────────────
def _eget(url, params, timeout=(15,120)):
    for i in range(3):
        try:
            time.sleep(NCBI_DELAY)
            r = requests.get(url, params=params, headers=HDR, timeout=timeout)
            if r.status_code == 429: time.sleep(5*(i+1)); continue
            r.raise_for_status(); return r
        except: time.sleep(2)
    return None

def _text(el):
    return "".join(el.itertext()).strip() if el is not None else ""

def verify_pdf(path):
    try:
        sz = os.path.getsize(path)
        if sz < 5000: return False
        with open(path,"rb") as f: h=f.read(512)
        if b"%PDF" not in h: return False
        if h.lstrip()[:15].lower().startswith((b"<!doctype",b"<html")): return False
        return True
    except: return False

def _rm(p):
    try: os.remove(p)
    except: pass

def load_prog():
    try:
        with open(PROG_FILE,"r") as f: return json.load(f)
    except: return {}

def save_prog(p):
    with open(PROG_FILE,"w") as f: json.dump(p,f)

def write_csv(arts):
    with open(CSV_FILE,"w",newline="",encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES); w.writeheader(); w.writerows(arts)

# ── PubMed metadata ─────────────────────────────────────────────────────────
def search_pubmed(q, retmax=1500):
    tprint("Step 1/4 - Searching PubMed ...")
    r = _eget(f"{EUTILS}/esearch.fcgi",
              {"db":"pubmed","term":q,"retmax":retmax,"retmode":"json","sort":"relevance"})
    if not r: tprint("ERROR: search failed"); return []
    d = r.json().get("esearchresult",{})
    ids = d.get("idlist",[])
    tprint(f"  {d.get('count',0)} hits, retrieved {len(ids)} PMIDs")
    return ids

def fetch_meta(pmids):
    tprint("Step 2/4 - Fetching metadata ...")
    arts=[]; nb=(len(pmids)+BATCH-1)//BATCH
    for i in range(0,len(pmids),BATCH):
        b=pmids[i:i+BATCH]; bn=i//BATCH+1
        tprint(f"  Batch {bn}/{nb} ({len(b)} PMIDs) ...")
        r = _eget(f"{EUTILS}/efetch.fcgi",
                  {"db":"pubmed","id":",".join(b),"rettype":"xml","retmode":"xml"})
        if not r:
            for p in b: arts.append(_blank(p))
            continue
        try:
            root = ET.fromstring(r.content)
            for el in root.findall(".//PubmedArticle"): arts.append(_parse(el))
        except ET.ParseError:
            for p in b: arts.append(_blank(p))
    tprint(f"  {len(arts)} articles parsed")
    return arts

def _blank(pmid):
    return {k:"" for k in FIELDNAMES}|{"PMID":pmid,"Free_PMC":"No","PDF_Downloaded":"No"}

def _parse(el):
    a=_blank("")
    a["PMID"]=_text(el.find(".//MedlineCitation/PMID"))
    a["Title"]=_text(el.find(".//Article/ArticleTitle"))
    aus=[]
    for au in el.findall(".//Article/AuthorList/Author"):
        ln=(au.findtext("LastName") or "").strip()
        fn=(au.findtext("ForeName") or "").strip()
        if ln: aus.append(f"{ln} {fn}".strip() if fn else ln)
        else:
            c=(au.findtext("CollectiveName") or "").strip()
            if c: aus.append(c)
    a["Authors"]="; ".join(aus)
    a["Journal"]=_text(el.find(".//Article/Journal/Title"))
    pd=el.find(".//Article/Journal/JournalIssue/PubDate")
    if pd is not None:
        ye=pd.findtext("Year")
        if ye: a["Year"]=ye.strip()
        else:
            md=pd.findtext("MedlineDate") or ""
            m=re.search(r"(\d{4})",md)
            if m: a["Year"]=m.group(1)
    for aid in el.findall(".//PubmedData/ArticleIdList/ArticleId"):
        t=aid.get("IdType",""); v=(aid.text or "").strip()
        if t=="doi" and v: a["DOI"]=v
        elif t=="pmc" and v:
            a["PMC_ID"]=v if v.upper().startswith("PMC") else f"PMC{v}"
            a["Free_PMC"]="Yes"
    if not a["DOI"]:
        for loc in el.findall(".//Article/ELocationID"):
            if loc.get("EIdType")=="doi" and loc.text:
                a["DOI"]=loc.text.strip(); break
    return a

# ── PDF download worker ─────────────────────────────────────────────────────
def _mk_session():
    s=requests.Session(); s.headers.update(HDR)
    retry = Retry(total=1, backoff_factor=0.3, status_forcelist=[429,500,502,503])
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=2)
    s.mount("https://", adapter); s.mount("http://", adapter)
    return s

def _dl(sess, url, path, timeout=(6,20)):
    """Download url→path. True if result is a valid PDF."""
    try:
        r = sess.get(url, timeout=timeout, stream=True)
        if r.status_code != 200: return False
        ct = r.headers.get("Content-Type","").lower()
        if "html" in ct and "pdf" not in ct: return False
        with open(path,"wb") as f:
            for ch in r.iter_content(65536): f.write(ch)
        if verify_pdf(path): return True
        _rm(path); return False
    except:
        _rm(path); return False

def download_one(article, odir):
    """Download PDF for one article. Returns (pmid, success, was_cached)."""
    pmid=article["PMID"]; pmc=article["PMC_ID"]; doi=article["DOI"]
    fp=os.path.join(odir, f"PMID_{pmid}.pdf")

    if os.path.exists(fp) and verify_pdf(fp):
        return (pmid, True, True)

    s = _mk_session()

    # 1. Europe PMC  (fast, reliable for PMC content)
    if pmc:
        url=f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmc}&blobtype=pdf"
        if _dl(s, url, fp, timeout=(6,25)): return (pmid, True, False)

    # 2. NCBI PMC
    if pmc:
        url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc}/pdf/"
        if _dl(s, url, fp, timeout=(6,25)): return (pmid, True, False)

    # 3. Unpaywall (OA PDFs from publisher sites)
    if doi:
        try:
            r=s.get(f"https://api.unpaywall.org/v2/{doi}",
                    params={"email":"pubmed_dl@research.org"}, timeout=(6,12))
            if r.status_code==200:
                d=r.json(); urls=[]
                best=d.get("best_oa_location")
                if best and best.get("url_for_pdf"): urls.append(best["url_for_pdf"])
                for loc in d.get("oa_locations",[]):
                    u=loc.get("url_for_pdf")
                    if u and u not in urls: urls.append(u)
                for u in urls[:2]:
                    if _dl(s, u, fp, timeout=(6,30)): return (pmid, True, False)
        except: pass

    return (pmid, False, False)

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    prog = load_prog()

    pmids = search_pubmed(SEARCH_QUERY)
    if not pmids: return
    articles = fetch_meta(pmids)
    art_map = {a["PMID"]:a for a in articles}
    pmc_n = sum(1 for a in articles if a["PMC_ID"])
    tprint(f"\n  {pmc_n}/{len(articles)} have PMC IDs\n")

    tprint(f"Step 3/4 - Downloading PDFs ({MAX_WORKERS} workers) ...")
    t0 = time.time()

    # Process PMC articles first (higher success rate), then the rest
    pmc_arts  = [a for a in articles if a["PMC_ID"]]
    rest_arts = [a for a in articles if not a["PMC_ID"]]
    ordered   = pmc_arts + rest_arts

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = {pool.submit(download_one, a, OUTPUT_DIR): a["PMID"] for a in ordered}
        for fut in as_completed(futs):
            pmid = futs[fut]
            try: _pmid, ok, cached = fut.result()
            except: ok, cached = False, False

            a = art_map[pmid]
            with _clock:
                stats["done"] += 1
                if ok:
                    a["PDF_Downloaded"]="Yes"; a["PDF_Filename"]=f"PMID_{pmid}.pdf"
                    stats["ok"] += 1
                    if cached: stats["skip"] += 1
                    prog[pmid]="ok"
                else:
                    a["PDF_Downloaded"]="No"; a["PDF_Filename"]=""
                    stats["fail"] += 1
                    prog[pmid]="fail"

                done = stats["done"]
                if done % 10 == 0 or done == len(articles):
                    el = time.time()-t0
                    rate = done/el if el else 1
                    eta = (len(articles)-done)/rate/60 if rate else 0
                    tprint(f"  [{done:>4}/{len(articles)}]  ok={stats['ok']}  "
                           f"fail={stats['fail']}  skip={stats['skip']}  "
                           f"elapsed={el/60:.1f}min  ETA~{eta:.1f}min")
                    save_prog(prog)
                    write_csv(articles)

    save_prog(prog)

    # Final CSV
    tprint("\nStep 4/4 - Writing final CSV ...")
    write_csv(articles)

    y = sum(1 for a in articles if a["PDF_Downloaded"]=="Yes")
    n = sum(1 for a in articles if a["PDF_Downloaded"]=="No")
    p = sum(1 for a in articles if a["Free_PMC"]=="Yes")
    tprint(f"\n{'='*60}")
    tprint(f"  Total articles :  {len(articles)}")
    tprint(f"  Free PMC       :  {p}")
    tprint(f"  PDFs downloaded:  {y}")
    tprint(f"  PDFs failed    :  {n}")
    tprint(f"  CSV file       :  {CSV_FILE}")
    tprint(f"  PDF folder     :  {OUTPUT_DIR}/")
    tprint(f"{'='*60}")
    tprint("Done.")

if __name__=="__main__":
    main()
