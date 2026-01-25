from __future__ import annotations
import sqlite3
from pathlib import Path

DB_PATH = Path("db") / "database.sqlite"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS providers (
  provider_id     INTEGER PRIMARY KEY,
  provider_name   TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'DRAFT',
  currency_mode   TEXT NOT NULL CHECK(currency_mode IN ('LIST','ALL_FIAT')),
  notes           TEXT
);

CREATE TABLE IF NOT EXISTS restrictions (
  provider_id   INTEGER NOT NULL,
  country_code  TEXT NOT NULL, -- ISO2 preferred
  source        TEXT,
  PRIMARY KEY (provider_id, country_code),
  FOREIGN KEY (provider_id) REFERENCES providers(provider_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS currencies (
  provider_id    INTEGER NOT NULL,
  currency_code  TEXT NOT NULL, -- ISO4217 (FIAT) or token symbol (CRYPTO)
  currency_type  TEXT NOT NULL CHECK(currency_type IN ('FIAT','CRYPTO')),
  display        INTEGER NOT NULL DEFAULT 1 CHECK(display IN (0,1)),
  source         TEXT,
  PRIMARY KEY (provider_id, currency_code, currency_type),
  FOREIGN KEY (provider_id) REFERENCES providers(provider_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS overrides_log (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  ts            TEXT NOT NULL DEFAULT (datetime('now')),
  action        TEXT NOT NULL,
  details_json  TEXT
);
"""

def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    con.commit()
    con.close()
    print(f"✅ DB initialized at: {DB_PATH.resolve()}")

if __name__ == "__main__":
    main()
