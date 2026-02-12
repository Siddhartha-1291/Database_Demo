#!/usr/bin/env python3
"""
Convert TSV files to CSV with Protein column inserted between Gene and Species.
Input: ProteinName_diffr_expr_cancer.tsv
Output: ProteinName_diffr_expr_cancer.csv
"""

import csv
import re
from pathlib import Path

BASE = Path(__file__).parent
FOLDERS = [
    "MTOR_signalling_proteins_differential_expression_in_cancer",
    "Wnt_signalling_proteins_differential_expression_in_cancer",
]

# Match filename: ProteinName_diffr_expr_cancer.tsv
PATTERN = re.compile(r"^(.+)_diffr_expr_cancer\.tsv$")


def process_file(tsv_path):
    match = PATTERN.match(tsv_path.name)
    if not match:
        return
    protein_name = match.group(1)
    csv_path = tsv_path.with_suffix(".csv")

    rows = []
    with open(tsv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        for i, row in enumerate(reader):
            if i == 0:
                # Header: Gene, Species, ... -> Gene, Protein, Species, ...
                if row[0] == "Gene" and row[1] == "Species":
                    new_header = ["Gene", "Protein"] + row[1:]
                    rows.append(new_header)
                else:
                    rows.append(["Gene", "Protein"] + row[1:])
            else:
                rows.append([row[0], protein_name] + row[1:])

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    print(f"Created {csv_path.relative_to(BASE)}")


def main():
    for folder_name in FOLDERS:
        folder = BASE / folder_name
        if not folder.is_dir():
            print(f"Skipping {folder_name}: not found")
            continue
        for tsv_path in sorted(folder.glob("*_diffr_expr_cancer.tsv")):
            process_file(tsv_path)


if __name__ == "__main__":
    main()
