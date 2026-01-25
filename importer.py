from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

DB_PATH = Path("db") / "database.sqlite"
SOURCES_DIR = Path("data_sources")
CONFIG_PATH = Path("config.csv")


def _clean_token(s: str) -> str:
    s = str(s).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _extract_code(value: str) -> str:
    """
    Handles formats like:
      - 'BRL'
      - 'BRL (Brazilian Real)'
      - 'BRL - Brazilian real'
      - 'GRC (Greece)'
    Returns the leading token if it looks like a code.
    """
    v = _clean_token(value)
    if not v:
        return ""

    # Split on common separators
    v = v.split("(")[0].strip()
    v = v.split("-")[0].strip()
    v = v.split(" ")[0].strip()

    code = v.upper()

    # Basic validation: keep 2-4 letters only (covers ISO4217=3; also some providers use 2/4)
    if re.fullmatch(r"[A-Z]{2,4}", code):
        return code
    return ""


def _read_range_excel(file_path: Path, sheet_name: str, a1_range: str) -> list[str]:
    """
    Very simple range reader:
    - supports "A2:A" or "C2:C" (single column)
    - reads the column and drops blanks
    """
    m = re.fullmatch(r"([A-Z]+)(\d+):\1?", a1_range.strip().upper())
    if not m:
        # allow A2:A9999 style too
        m2 = re.fullmatch(r"([A-Z]+)(\d+):\1(\d+)", a1_range.strip().upper())
        if not m2:
            raise ValueError(f"Unsupported range format: {a1_range} (use like A2:A or C2:C)")
        col, start, end = m2.group(1), int(m2.group(2)), int(m2.group(3))
    else:
        col, start = m.group(1), int(m.group(2))
        end = None

    # read whole sheet, then slice
    df = pd.read_excel(file_path, sheet_name=sheet_name, header=None, dtype=str)
    col_idx = _col_to_index(col)
    # If the sheet doesn't have that many columns, return empty instead of crashing
    if col_idx >= df.shape[1]:
        return []

    series = df.iloc[:, col_idx]
    series = series.iloc[start - 1 :]  # 1-based row to 0-based index
    if end is not None:
        series = series.iloc[: (end - start + 1)]
    series = series.dropna().astype(str).map(_clean_token)
    series = series[series != ""]
    return series.tolist()


def _col_to_index(col_letters: str) -> int:
    # A -> 0, B -> 1, Z -> 25, AA -> 26 ...
    idx = 0
    for ch in col_letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


@dataclass
class ProviderConfig:
    provider_id: int
    provider_name: str
    file_name: str
    status: str
    currency_mode: str  # LIST / ALL_FIAT
    restrictions_sheet: str
    restrictions_range: str
    currencies_sheet: str
    fiat_range: str
    crypto_range: str
    all_fiat_hint_sheet: str
    all_fiat_hint_cell: str
    all_fiat_hint_regex: str
    notes: str


def load_config() -> list[ProviderConfig]:
    df = pd.read_csv(CONFIG_PATH, dtype=str).fillna("")
    out: list[ProviderConfig] = []
    for _, r in df.iterrows():
        out.append(
            ProviderConfig(
                provider_id=int(r["provider_id"]),
                provider_name=r["provider_name"].strip(),
                file_name=r["file_name"].strip(),
                status=(r["status"].strip() or "DRAFT").upper(),
                currency_mode=(r["currency_mode"].strip() or "LIST").upper(),
                restrictions_sheet=r["restrictions_sheet"].strip(),
                restrictions_range=r["restrictions_range"].strip(),
                currencies_sheet=r["currencies_sheet"].strip(),
                fiat_range=r["fiat_range"].strip(),
                crypto_range=r["crypto_range"].strip(),
                all_fiat_hint_sheet=r["all_fiat_hint_sheet"].strip(),
                all_fiat_hint_cell=r["all_fiat_hint_cell"].strip(),
                all_fiat_hint_regex=r["all_fiat_hint_regex"].strip(),
                notes=r.get("notes", "").strip(),
            )
        )
    return out


def init_db_if_needed() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"DB not found at {DB_PATH}. Run: py db_init.py"
        )


def upsert_provider(con: sqlite3.Connection, pc: ProviderConfig) -> None:
    con.execute(
        """
        INSERT INTO providers(provider_id, provider_name, status, currency_mode, notes)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(provider_id) DO UPDATE SET
          provider_name=excluded.provider_name,
          status=excluded.status,
          currency_mode=excluded.currency_mode,
          notes=excluded.notes
        """,
        (pc.provider_id, pc.provider_name, pc.status, pc.currency_mode, pc.notes),
    )


def replace_provider_restrictions(con: sqlite3.Connection, provider_id: int, rows: list[str], source: str) -> None:
    con.execute("DELETE FROM restrictions WHERE provider_id=?", (provider_id,))
    payload = []
    for v in rows:
        code = _extract_code(v)
        if code:
            payload.append((provider_id, code, source))
    if payload:
        con.executemany(
            "INSERT OR IGNORE INTO restrictions(provider_id, country_code, source) VALUES (?, ?, ?)",
            payload,
        )


def replace_provider_currencies(con: sqlite3.Connection, provider_id: int, fiat: list[str], crypto: list[str], source: str) -> None:
    # Remove old currencies for this provider
    con.execute("DELETE FROM currencies WHERE provider_id=?", (provider_id,))

    payload = []

    # FIAT currencies (ISO 4217 only)
    for v in fiat:
        code = _extract_code(v)
        if code and len(code) == 3:
            payload.append((provider_id, code, "FIAT", 1, source))

    # CRYPTO currencies (hidden by default)
    for v in crypto:
        code = _extract_code(v)
        if code:
            payload.append((provider_id, code, "CRYPTO", 0, source))

    if payload:
        con.executemany(
            """
            INSERT OR IGNORE INTO currencies
            (provider_id, currency_code, currency_type, display, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            payload,
        )

def main() -> None:
    init_db_if_needed()
    cfg = load_config()
    if not cfg:
        print("⚠️ config.csv is empty.")
        return

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON;")

    imported = 0
    for pc in cfg:
        file_path = SOURCES_DIR / pc.file_name
        if not file_path.exists():
            print(f"⚠️ Missing file for provider_id={pc.provider_id}: {file_path}")
            continue

        upsert_provider(con, pc)

        # Restrictions
        restr_values = []
        if pc.restrictions_sheet and pc.restrictions_range:
            restr_values = _read_range_excel(file_path, pc.restrictions_sheet, pc.restrictions_range)
        replace_provider_restrictions(con, pc.provider_id, restr_values, source=pc.file_name)

        # Currencies
        if pc.currency_mode == "ALL_FIAT":
            # only store crypto if provided (optional)
            crypto_values = []
            if pc.crypto_range:
                crypto_values = _read_range_excel(file_path, pc.currencies_sheet, pc.crypto_range)
            replace_provider_currencies(con, pc.provider_id, fiat=[], crypto=crypto_values, source=pc.file_name)
        else:
            fiat_values = []
            crypto_values = []
            if pc.fiat_range:
                fiat_values = _read_range_excel(file_path, pc.currencies_sheet, pc.fiat_range)
            if pc.crypto_range:
                crypto_values = _read_range_excel(file_path, pc.currencies_sheet, pc.crypto_range)
            replace_provider_currencies(con, pc.provider_id, fiat=fiat_values, crypto=crypto_values, source=pc.file_name)

        imported += 1
        print(f"✅ Imported provider {pc.provider_id}: {pc.provider_name}")

    con.commit()
    con.close()
    print(f"\nDone. Imported {imported} provider(s) into {DB_PATH.resolve()}")

if __name__ == "__main__":
    main()
