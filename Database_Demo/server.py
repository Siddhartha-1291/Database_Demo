#!/usr/bin/env python3
"""
Flask server for ICDTRA – Cancer Genomics Differential Expression Data.

On startup the SQLite database is rebuilt from CSV files so that
any new CSV files added (or removed) are reflected automatically.
"""
import json
import os
import re
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from build_database import build_database, DB_PATH, BASE

app = Flask(__name__, static_folder=str(BASE), static_url_path="")


# ---------------------------------------------------------------------------
# Database rebuild on startup
# ---------------------------------------------------------------------------
def get_db():
    """Return a fresh connection for the current request."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(str(BASE), "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(str(BASE), filename)


# ---------------------------------------------------------------------------
# API: Search for a protein / gene name
# ---------------------------------------------------------------------------
@app.route("/api/search-protein")
def search_protein():
    """
    Search for an exact match of the provided name against:
    1. Protein_Name columns in MTOR_signalling_proteins and Wnt_signalling_proteins
    2. Gene_Name columns (space-separated gene names within each entry)
    Returns: { found: bool, proteins: [{name, source_table}], error: str|null }
    """
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify(found=False, proteins=[], error="No name provided.")

    conn = get_db()
    found_proteins = []

    # Tables to search (table_name, protein_col, gene_col)
    tables = [
        ("MTOR_signalling_proteins", "Protein_Name", "Gene_Name"),
        ("Wnt_signalling_proteins", "Protein_Name", "Gene_Name"),
    ]

    for tbl, pcol, gcol in tables:
        try:
            # 1) Exact protein-name match
            rows = conn.execute(
                f'SELECT "{pcol}" FROM "{tbl}" WHERE "{pcol}" = ?', (name,)
            ).fetchall()
            for r in rows:
                found_proteins.append({"name": r[0], "source_table": tbl})

            # 2) Exact gene-name match (space-separated entries)
            if not rows:
                gene_rows = conn.execute(
                    f'SELECT "{pcol}", "{gcol}" FROM "{tbl}"'
                ).fetchall()
                for gr in gene_rows:
                    gene_names = gr[1].split() if gr[1] else []
                    if name in gene_names:
                        found_proteins.append({"name": gr[0], "source_table": tbl})
        except Exception as e:
            print(f"Error searching {tbl}: {e}")

    conn.close()

    # Deduplicate by protein name
    seen = set()
    unique = []
    for p in found_proteins:
        if p["name"] not in seen:
            seen.add(p["name"])
            unique.append(p)

    if unique:
        return jsonify(found=True, proteins=unique, error=None)
    else:
        return jsonify(
            found=False,
            proteins=[],
            error=(
                "The Protein/gene name provided is either not in the database, "
                "at present, or is misspelt. Please re-check the spelling and "
                "try again, if you altered it."
            ),
        )


# ---------------------------------------------------------------------------
# API: Get proteins for one or more pathways, with optional subset filtering
# ---------------------------------------------------------------------------
@app.route("/api/pathway-proteins")
def pathway_proteins():
    """
    Query params:
      pathways  – comma-separated list of pathway keys, e.g. "wnt,mtor"
      subset    – one of "entire", "common", "notcommon" (optional)

    Returns { proteins: [str], error: str|null }
    """
    pathways_raw = request.args.get("pathways", "")
    subset = request.args.get("subset", "").strip()
    pathway_keys = [p.strip().lower() for p in pathways_raw.split(",") if p.strip()]

    if not pathway_keys:
        return jsonify(proteins=[], error="No pathway selected.")

    # Map pathway key -> table name
    key_to_table = {
        "wnt": "Wnt_signalling_proteins",
        "mtor": "MTOR_signalling_proteins",
    }

    conn = get_db()
    pathway_sets = {}  # key -> set of protein names
    for key in pathway_keys:
        tbl = key_to_table.get(key)
        if not tbl:
            continue
        try:
            rows = conn.execute(f'SELECT "Protein_Name" FROM "{tbl}"').fetchall()
            pathway_sets[key] = set(r[0] for r in rows if r[0])
        except Exception as e:
            print(f"Error reading {tbl}: {e}")
            pathway_sets[key] = set()
    conn.close()

    if not pathway_sets:
        return jsonify(proteins=[], error="No matching pathway tables found.")

    sets_list = list(pathway_sets.values())

    if len(pathway_keys) == 1 or not subset:
        # Single pathway or no subset: union (non-redundant)
        result = set()
        for s in sets_list:
            result |= s
        return jsonify(proteins=sorted(result), error=None)

    if subset == "entire":
        result = set()
        for s in sets_list:
            result |= s
        return jsonify(proteins=sorted(result), error=None)

    elif subset == "common":
        result = sets_list[0]
        for s in sets_list[1:]:
            result = result & s
        if not result:
            return jsonify(
                proteins=[],
                error="There are no proteins that are common to all of the selected signalling pathways.",
            )
        return jsonify(proteins=sorted(result), error=None)

    elif subset == "notcommon":
        # Proteins NOT in common across any pair
        # = proteins appearing in exactly one pathway set
        from collections import Counter
        counter = Counter()
        for s in sets_list:
            for p in s:
                counter[p] += 1
        result = {p for p, c in counter.items() if c == 1}
        if not result:
            return jsonify(proteins=[], error="All proteins are shared across the selected pathways.")
        return jsonify(proteins=sorted(result), error=None)

    return jsonify(proteins=[], error="Invalid subset parameter.")


# ---------------------------------------------------------------------------
# API: Get differential expression data for a given protein
# ---------------------------------------------------------------------------
@app.route("/api/protein-data")
def protein_data():
    """
    Query params: name – Protein name (table = <name>_diffr_expr_cancer)
    Returns { columns: [str], rows: [[str]], error: str|null }
    """
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify(columns=[], rows=[], error="No protein name provided.")

    table_name = re.sub(r"[^a-zA-Z0-9_]", "_", name) + "_diffr_expr_cancer"
    conn = get_db()

    try:
        # Check table exists
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        if not cur.fetchone():
            conn.close()
            return jsonify(columns=[], rows=[], error=f"No data table found for {name}.")

        pragma = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        columns = [r[1] for r in pragma]
        data_rows = conn.execute(f'SELECT * FROM "{table_name}"').fetchall()
        rows = [list(r) for r in data_rows]
        conn.close()
        return jsonify(columns=columns, rows=rows, error=None)
    except Exception as e:
        conn.close()
        return jsonify(columns=[], rows=[], error=str(e))


# ---------------------------------------------------------------------------
# API: Get the URL for a given protein name
# ---------------------------------------------------------------------------
@app.route("/api/protein-url")
def protein_url():
    """
    Query params: name – Protein name
    Returns { url: str|null, error: str|null }
    """
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify(url=None, error="No protein name provided.")

    conn = get_db()
    try:
        row = conn.execute(
            'SELECT "URL" FROM "URLs" WHERE "Protein_Name" = ?', (name,)
        ).fetchone()
        conn.close()
        if row:
            return jsonify(url=row[0], error=None)
        return jsonify(url=None, error=f"No URL found for {name}.")
    except Exception as e:
        conn.close()
        return jsonify(url=None, error=str(e))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Rebuilding database from CSV files …")
    build_database()
    print("Starting ICDTRA server on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
