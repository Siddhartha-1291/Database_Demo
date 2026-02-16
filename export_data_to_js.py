#!/usr/bin/env python3
"""
Export all data from the SQLite database into a JavaScript file (data.js)
that can be loaded directly in the browser via <script> tag.

This allows the website to work when opened by double-clicking index.html
(file:// protocol) without needing a backend server.

Run this script whenever the database changes, or run build_database.py first
to rebuild the database from CSV files, then run this.
"""
import json
import re
import sqlite3
from pathlib import Path

BASE = Path(__file__).parent.resolve()
DB_PATH = BASE / "Cancer_Genomics_Differential_Expression_Data.db"
OUTPUT = BASE / "data.js"


def export():
    conn = sqlite3.connect(str(DB_PATH))

    data = {}

    # --- 1. Signalling proteins tables ---
    for tbl in ("MTOR_signalling_proteins", "Wnt_signalling_proteins"):
        pragma = conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()
        cols = [r[1] for r in pragma]
        rows = conn.execute(f'SELECT * FROM "{tbl}"').fetchall()
        data[tbl] = {"columns": cols, "rows": [list(r) for r in rows]}

    # --- 2. URLs table ---
    pragma = conn.execute('PRAGMA table_info("URLs")').fetchall()
    cols = [r[1] for r in pragma]
    rows = conn.execute('SELECT * FROM "URLs"').fetchall()
    data["URLs"] = {"columns": cols, "rows": [list(r) for r in rows]}

    # --- 3. Differential expression tables ---
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_diffr_expr_cancer' ORDER BY name"
    )
    diff_tables = [r[0] for r in cur.fetchall()]
    diff_data = {}
    for tbl in diff_tables:
        pragma = conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()
        cols = [r[1] for r in pragma]
        rows = conn.execute(f'SELECT * FROM "{tbl}"').fetchall()
        diff_data[tbl] = {"columns": cols, "rows": [list(r) for r in rows]}
    data["diff_expr"] = diff_data

    # --- 4. Literature-sourced differential expression tables ---
    lit_table_names = [
        "Differential_Gene_Expression_From_Literature",
        "Differential_Gene_Expression_From_Literature_Direct_Quote",
        "Differential_Protein_Expression_From_Literature",
        "Differential_Protein_Expression_From_Literature_Direct_Quote",
    ]
    lit_data = {}
    for tbl in lit_table_names:
        try:
            pragma = conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()
            if not pragma:
                continue
            cols = [r[1] for r in pragma]
            rows = conn.execute(f'SELECT * FROM "{tbl}"').fetchall()
            lit_data[tbl] = {"columns": cols, "rows": [list(r) for r in rows]}
        except Exception:
            pass
    data["literature_expr"] = lit_data

    # --- 5. Biomarker prospective-studies tables ---
    biomarker_table_names = [
        "Biomarkers_in_Cancer_Prospective_Studies_Data_Table",
        "Gene_Biomarkers_in_Cancer_Prospective_Studies_Data_Table",
        "Protein_Biomarkers_in_Cancer_Prospective_Studies_Data_Table",
    ]
    bm_data = {}
    for tbl in biomarker_table_names:
        try:
            pragma = conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()
            if not pragma:
                continue
            cols = [r[1] for r in pragma]
            rows = conn.execute(f'SELECT * FROM "{tbl}"').fetchall()
            bm_data[tbl] = {"columns": cols, "rows": [list(r) for r in rows]}
        except Exception:
            pass
    data["biomarker_tables"] = bm_data

    # --- 6. NCG_TMC table ---
    try:
        pragma = conn.execute('PRAGMA table_info("NCG_TMC")').fetchall()
        if pragma:
            cols = [r[1] for r in pragma]
            rows = conn.execute('SELECT * FROM "NCG_TMC"').fetchall()
            data["ncg_tmc"] = {"columns": cols, "rows": [list(r) for r in rows]}
    except Exception:
        pass

    conn.close()

    # Write as a JS file that defines a global variable
    js_content = "// Auto-generated – do not edit manually.\n"
    js_content += "// Regenerate by running: python export_data_to_js.py\n"
    js_content += "var DB = " + json.dumps(data, separators=(",", ":")) + ";\n"

    OUTPUT.write_text(js_content, encoding="utf-8")
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"Exported data.js ({size_kb:.1f} KB)")


if __name__ == "__main__":
    export()
