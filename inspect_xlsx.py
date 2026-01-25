from __future__ import annotations
import re
from pathlib import Path
import pandas as pd

SOURCES_DIR = Path("data_sources")

KEYWORDS_RESTR = re.compile(r"restricted", re.I)
KEYWORDS_CURR = re.compile(r"supported\s*currenc", re.I)
ALL_FIAT_RE = re.compile(r"all\s*fiat", re.I)

def col_letter(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s

def main():
    files = sorted([p for p in SOURCES_DIR.glob("*.xlsx") if p.is_file()])
    if not files:
        print("No .xlsx files found in data_sources/")
        return

    for fp in files:
        print("\n" + "=" * 90)
        print(f"FILE: {fp.name}")
        xl = pd.ExcelFile(fp)
        print("Sheets:", xl.sheet_names)

        restr_sheets = [s for s in xl.sheet_names if KEYWORDS_RESTR.search(s)]
        curr_sheets = [s for s in xl.sheet_names if KEYWORDS_CURR.search(s)]

        if restr_sheets:
            s = restr_sheets[0]
            df = pd.read_excel(fp, sheet_name=s, header=None, dtype=str)
            print(f"\n[Guess] Restrictions sheet: {s}")
            print("Preview:")
            print(df.iloc[:15, :4].fillna("").to_string(index=False, header=False))

            nonempty_cols = [
                i for i in range(df.shape[1])
                if (df.iloc[:, i].fillna("").astype(str).str.strip() != "").any()
            ]
            if nonempty_cols:
                c = nonempty_cols[0]
                print(f"Suggested restrictions_range: {col_letter(c)}2:{col_letter(c)}")

        if curr_sheets:
            s = curr_sheets[0]
            df = pd.read_excel(fp, sheet_name=s, header=None, dtype=str)
            print(f"\n[Guess] Currencies sheet: {s}")
            print("Preview:")
            print(df.iloc[:15, :6].fillna("").to_string(index=False, header=False))

            text_blob = " ".join(df.fillna("").astype(str).values.flatten().tolist())
            if ALL_FIAT_RE.search(text_blob):
                print("Detected: ALL_FIAT (found 'All Fiat')")

            nonempty_cols = [
                i for i in range(df.shape[1])
                if (df.iloc[:, i].fillna("").astype(str).str.strip() != "").any()
            ]
            if nonempty_cols:
                fiat_col = nonempty_cols[0]
                print(f"Suggested fiat_range: {col_letter(fiat_col)}2:{col_letter(fiat_col)}")
                if len(nonempty_cols) > 1:
                    crypto_col = nonempty_cols[1]
                    print(f"Suggested crypto_range: {col_letter(crypto_col)}2:{col_letter(crypto_col)}")

if __name__ == "__main__":
    main()
