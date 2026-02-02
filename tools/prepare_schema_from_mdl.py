import os
import json
import re
from pathlib import Path
import argparse


ENTITY_REGEX = re.compile(
    r"entity\s+(\w+)\s*\{(.*?)\}",
    re.DOTALL | re.IGNORECASE
)

COLUMN_REGEX = re.compile(
    r"column\s+(\w+)\s*:\s*([a-zA-Z0-9_\(\)\'\,]+)\s*(\[.*?\])?",
    re.IGNORECASE
)

FOREIGN_KEY_REGEX = re.compile(
    r"foreign_key\s+(\w+)\s+references\s+(\w+)\((\w+)\)",
    re.IGNORECASE
)

UNIQUE_KEY_REGEX = re.compile(
    r"unique_key\s+(\w+)\s*\((.*?)\)",
    re.IGNORECASE
)


def parse_mdl(text, schema_name):
    entities = {}

    for em in ENTITY_REGEX.finditer(text):
        entity_name = em.group(1)
        body = em.group(2)

        columns = []
        foreign_keys = []
        unique_keys = []

        # Parse columns
        for cm in COLUMN_REGEX.finditer(body):
            col_name = cm.group(1)
            col_type = cm.group(2)
            annotation = cm.group(3) or ""
            annotation = annotation.strip("[]") if annotation else ""

            columns.append({
                "name": col_name,
                "type": col_type,
                "annotation": annotation
            })

        # Parse foreign keys
        for fk in FOREIGN_KEY_REGEX.finditer(body):
            local_col = fk.group(1)
            ref_table = fk.group(2)
            ref_col = fk.group(3)
            foreign_keys.append({
                "column": local_col,
                "references": f"{ref_table}.{ref_col}"
            })

        # Parse unique keys
        for uk in UNIQUE_KEY_REGEX.finditer(body):
            uk_name = uk.group(1)
            cols = [c.strip() for c in uk.group(2).split(",")]
            unique_keys.append({
                "name": uk_name,
                "columns": cols
            })

        fq_name = f"{schema_name}.{entity_name}"

        entities[fq_name] = {
            "schema": schema_name,
            "table": entity_name,
            "columns": columns,
            "foreign_keys": foreign_keys,
            "unique_keys": unique_keys
        }

    return entities


def main(mdl_dir, out_file):
    mdl_dir = Path(mdl_dir)
    combined = {}

    for mdl_file in mdl_dir.glob("*.mdl"):
        print(f"[+] Reading {mdl_file}")

        # Convert filename: ems_account_service -> ems-account
        # ems_account_service -> ems-account-service
        schema_name = mdl_file.stem.replace("_", "-")


        text = mdl_file.read_text(errors="ignore")
        parsed = parse_mdl(text, schema_name)
        combined.update(parsed)

    out_file = Path(out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    with out_file.open("w") as f:
        json.dump({"entities": combined}, f, indent=2)

    print(f"[✔] Parsed {len(combined)} fully qualified entities")
    print(f"[✔] Wrote: {out_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mdl", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    main(args.mdl, args.out)
