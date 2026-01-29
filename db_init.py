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
  google_sheet_id TEXT,
  last_synced     TEXT,
  notes           TEXT
);

CREATE TABLE IF NOT EXISTS restrictions (
  provider_id       INTEGER NOT NULL,
  country_code      TEXT NOT NULL, -- ISO3 code
  restriction_type  TEXT NOT NULL DEFAULT 'RESTRICTED' CHECK(restriction_type IN ('RESTRICTED','REGULATED')),
  source            TEXT,
  PRIMARY KEY (provider_id, country_code),
  FOREIGN KEY (provider_id) REFERENCES providers(provider_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fiat_currencies (
  provider_id    INTEGER NOT NULL,
  currency_code  TEXT NOT NULL, -- ISO4217 code (USD, EUR, etc.)
  display        INTEGER NOT NULL DEFAULT 1 CHECK(display IN (0,1)),
  source         TEXT,
  PRIMARY KEY (provider_id, currency_code),
  FOREIGN KEY (provider_id) REFERENCES providers(provider_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS crypto_currencies (
  provider_id    INTEGER NOT NULL,
  currency_code  TEXT NOT NULL, -- Crypto symbol (BTC, ETH, USDT, etc.)
  display        INTEGER NOT NULL DEFAULT 1 CHECK(display IN (0,1)),
  source         TEXT,
  PRIMARY KEY (provider_id, currency_code),
  FOREIGN KEY (provider_id) REFERENCES providers(provider_id) ON DELETE CASCADE
);

-- Legacy table for backwards compatibility (will be migrated)
CREATE TABLE IF NOT EXISTS currencies (
  provider_id    INTEGER NOT NULL,
  currency_code  TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS sync_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  ts              TEXT NOT NULL DEFAULT (datetime('now')),
  provider_name   TEXT,
  sheet_id        TEXT,
  status          TEXT NOT NULL CHECK(status IN ('SUCCESS','FAILED')),
  message         TEXT,
  restrictions_count INTEGER,
  currencies_count   INTEGER
);

CREATE TABLE IF NOT EXISTS backups (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          TEXT NOT NULL DEFAULT (datetime('now')),
  filename    TEXT NOT NULL,
  size_bytes  INTEGER
);

CREATE TABLE IF NOT EXISTS games (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  provider_id     INTEGER NOT NULL,
  game_id         INTEGER,           -- API id
  title           TEXT NOT NULL,
  platform        TEXT,              -- desktop-and-mobile, etc.
  game_type       TEXT,              -- slots, live, etc.
  subtype         TEXT,              -- casino, etc.
  enabled         INTEGER DEFAULT 1,
  fun_mode        INTEGER DEFAULT 0,
  rtp             REAL,              -- e.g. 94.59
  volatility      TEXT,              -- e.g. "5"
  features        TEXT,              -- JSON array
  themes          TEXT,              -- JSON array
  tags            TEXT,              -- JSON array
  thumbnail       TEXT,              -- main thumbnail URL
  api_provider    TEXT,              -- original API provider name
  source          TEXT,
  FOREIGN KEY (provider_id) REFERENCES providers(provider_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_games_provider ON games(provider_id);
CREATE INDEX IF NOT EXISTS idx_games_type ON games(game_type);
CREATE INDEX IF NOT EXISTS idx_games_game_id ON games(game_id);
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
