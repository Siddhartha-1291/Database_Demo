#!/usr/bin/env python3
"""
Build the Cancer_Genomics_Differential_Expression_Data SQLite database from CSV files.
Called on server startup to keep the database in sync with CSV files on disk.
"""
import csv
import os
import re
import sqlite3
from pathlib import Path

BASE = Path(__file__).parent.resolve()
DB_PATH = BASE / "Cancer_Genomics_Differential_Expression_Data.db"

DIFF_EXPR_FOLDERS = [
    "MTOR_signalling_proteins_differential_expression_in_cancer",
    "Wnt_signalling_proteins_differential_expression_in_cancer",
]
URL_FILES = [
    "ebi_expression_atlas_MTOR_signalling_pathway_proteins_URLs.csv",
    "ebi_expression_atlas_Wnt_signalling_pathway_proteins_URLs.csv",
]
SIGNALLING_FILES = [
    "MTOR_signalling_proteins.csv",
    "Wnt_signalling_proteins.csv",
]

DIFF_EXPR_PATTERN = re.compile(r"^(.+)_diffr_expr_cancer\.csv$")

# Literature-sourced differential expression CSV files
LITERATURE_EXPR_DIR = BASE / "Differential_Expression_Data_From_Literature"
LITERATURE_CSV_FILES = [
    ("Differential_Gene_Expression_Data", "Differential_Gene_Expression_From_Literature.csv"),
    ("Differential_Gene_Expression_Data", "Differential_Gene_Expression_From_Literature_Direct_Quote.csv"),
    ("Differential_Protein_Expression_Data", "Differential_Protein_Expression_From_Literature.csv"),
    ("Differential_Protein_Expression_Data", "Differential_Protein_Expression_From_Literature_Direct_Quote.csv"),
]


def sanitize_table_name(name):
    """Make a safe SQLite table name, preserving the base name."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def read_csv_rows(filepath):
    rows = []
    # Try UTF-8 first, fall back to cp1252 for Windows-encoded files
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            with open(filepath, "r", encoding=enc) as f:
                reader = csv.reader(f)
                for row in reader:
                    # Strip trailing empty columns
                    while row and row[-1].strip() == "":
                        row.pop()
                    rows.append(row)
            return rows
        except UnicodeDecodeError:
            rows = []
            continue
    return rows


def create_table_from_csv(conn, table_name, rows):
    """Create a table from CSV rows (first row = header)."""
    if not rows:
        return
    safe_name = sanitize_table_name(table_name)
    header = rows[0]
    col_defs = ", ".join(f'"{sanitize_table_name(h)}" TEXT' for h in header)
    conn.execute(f'DROP TABLE IF EXISTS "{safe_name}"')
    conn.execute(f'CREATE TABLE "{safe_name}" ({col_defs})')
    placeholders = ", ".join(["?"] * len(header))
    for row in rows[1:]:
        # Pad or trim to match header length
        padded = (row + [""] * len(header))[:len(header)]
        conn.execute(f'INSERT INTO "{safe_name}" VALUES ({placeholders})', padded)


def build_database():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # --- 1. Differential expression CSV files from subfolders ---
    seen_content_hashes = {}
    for folder_name in DIFF_EXPR_FOLDERS:
        folder = BASE / folder_name
        if not folder.is_dir():
            continue
        for csv_file in sorted(folder.glob("*_diffr_expr_cancer.csv")):
            m = DIFF_EXPR_PATTERN.match(csv_file.name)
            if not m:
                continue
            table_name = m.group(1) + "_diffr_expr_cancer"
            rows = read_csv_rows(csv_file)
            # Deduplication: hash content to detect identical tables
            content_hash = hash(str(rows))
            if content_hash in seen_content_hashes:
                continue  # Skip duplicate
            seen_content_hashes[content_hash] = table_name
            create_table_from_csv(conn, table_name, rows)

    # --- 2. URLs table (combined, deduplicated) ---
    url_rows_all = []
    url_header = None
    for url_file_name in URL_FILES:
        url_path = BASE / url_file_name
        if not url_path.exists():
            continue
        rows = read_csv_rows(url_path)
        if not rows:
            continue
        if url_header is None:
            url_header = rows[0]
        for row in rows[1:]:
            url_rows_all.append(tuple(row))
    # Deduplicate
    unique_urls = list(dict.fromkeys(url_rows_all))
    if url_header:
        combined = [url_header] + [list(r) for r in unique_urls]
        create_table_from_csv(conn, "URLs", combined)

    # --- 3. Signalling proteins tables ---
    for sp_file_name in SIGNALLING_FILES:
        sp_path = BASE / sp_file_name
        if not sp_path.exists():
            continue
        rows = read_csv_rows(sp_path)
        table_name = sp_path.stem  # e.g. MTOR_signalling_proteins
        create_table_from_csv(conn, table_name, rows)

    # --- 4. Literature-sourced differential expression tables ---
    for subfolder, csv_name in LITERATURE_CSV_FILES:
        csv_path = LITERATURE_EXPR_DIR / subfolder / csv_name
        if not csv_path.exists():
            continue
        table_name = csv_path.stem  # e.g. Differential_Gene_Expression_From_Literature
        rows = read_csv_rows(csv_path)
        create_table_from_csv(conn, table_name, rows)

    # --- 5. Remove tables for which the CSV no longer exists ---
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = [r[0] for r in cur.fetchall()]
    # Build set of expected diff_expr table names from CSV files on disk
    expected_diff = set()
    for folder_name in DIFF_EXPR_FOLDERS:
        folder = BASE / folder_name
        if not folder.is_dir():
            continue
        for csv_file in folder.glob("*_diffr_expr_cancer.csv"):
            m = DIFF_EXPR_PATTERN.match(csv_file.name)
            if m:
                expected_diff.add(sanitize_table_name(m.group(1) + "_diffr_expr_cancer"))
    # Protected tables that should not be removed
    protected = {"URLs"}
    for sp in SIGNALLING_FILES:
        protected.add(sanitize_table_name(Path(sp).stem))
    for tbl in existing_tables:
        if tbl in protected:
            continue
        if tbl.endswith("_diffr_expr_cancer") and tbl not in expected_diff:
            conn.execute(f'DROP TABLE IF EXISTS "{tbl}"')

    conn.commit()
    conn.close()
    print(f"Database built: {DB_PATH}")
    return DB_PATH


if __name__ == "__main__":
    build_database()
    # Also export data.js for client-side use
    from export_data_to_js import export
    export()
