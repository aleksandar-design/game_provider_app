from __future__ import annotations
import re
from pathlib import Path
import pandas as pd

SOURCES_DIR = Path("data_sources")
OUT_PATH = Path("config_generated.csv")

KEY_RESTR = re.compile(r"restricted", re.I)
KEY_CURR = re.compile(r"supported\s*currenc", re.I)
ALL_FIAT_RE = re.compile(r"all\s*fiat", re.I)

def guess_first_data_col(df: pd.DataFrame) -> str:
    # find first non-empty column index
    for i in range(df.shape[1]):
        col = df.iloc[:, i].fillna("").astype(str).str.strip()
        if (col != "").any():
            return chr(ord("A") + i)  # works for A-Z only; good enough for your sheets
    return "A"

def main():
    files = sorted([p for p in SOURCES_DIR.glob("*.xlsx") if p.is_file()])
    if not files:
        print("No .xlsx files found in data_sources/")
        return

    rows = []
    for fp in files:
        xl = pd.ExcelFile(fp)
        sheets = xl.sheet_names

        restr_sheet = next((s for s in sheets if KEY_RESTR.search(s)), "")
        curr_sheet = next((s for s in sheets if KEY_CURR.search(s)), "")

        restr_range = ""
        if restr_sheet:
            df = pd.read_excel(fp, sheet_name=restr_sheet, header=None, dtype=str)
            col = guess_first_data_col(df)
            restr_range = f"{col}2:{col}"

        fiat_range = ""
        crypto_range = ""
        currency_mode = "LIST"

        if curr_sheet:
            dfc = pd.read_excel(fp, sheet_name=curr_sheet, header=None, dtype=str)
            blob = " ".join(dfc.fillna("").astype(str).values.flatten().tolist())
            if ALL_FIAT_RE.search(blob):
                currency_mode = "ALL_FIAT"

            col = guess_first_data_col(dfc)
            fiat_range = f"{col}2:{col}"
            # we don't assume crypto; leave blank

        rows.append({
            "provider_id": "",
            "provider_name": "",
            "file_name": fp.name,
            "status": "DRAFT",
            "currency_mode": currency_mode,
            "restrictions_sheet": restr_sheet,
            "restrictions_range": restr_range,
            "currencies_sheet": curr_sheet,
            "fiat_range": fiat_range,
            "crypto_range": "",
            "all_fiat_hint_sheet": "",
            "all_fiat_hint_cell": "",
            "all_fiat_hint_regex": "",
            "notes": "",
        })

    df_out = pd.DataFrame(rows, columns=[
        "provider_id","provider_name","file_name","status","currency_mode",
        "restrictions_sheet","restrictions_range",
        "currencies_sheet","fiat_range","crypto_range",
        "all_fiat_hint_sheet","all_fiat_hint_cell","all_fiat_hint_regex","notes"
    ])
    df_out.to_csv(OUT_PATH, index=False)
    print(f"✅ Wrote {OUT_PATH} with {len(df_out)} row(s). Fill provider_id and provider_name, then copy into config.csv.")

if __name__ == "__main__":
    main()
