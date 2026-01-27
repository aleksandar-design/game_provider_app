"""
Google Sheets Sync Script

Scans a Google Drive folder for provider sheets and imports data to SQLite.
Handles two-tier restriction system: BLOCKED vs CONDITIONAL.

Features:
- Automatic backup before each sync
- Duplicate detection and handling
- Restore from backup capability
- Change tracking (only updates if data changed)

Setup:
1. Create service account in Google Cloud Console
2. Enable Google Drive API and Google Sheets API
3. Download JSON key as 'service_account.json'
4. Share the Drive folder with the service account email
5. Set GOOGLE_DRIVE_FOLDER_ID in .env or secrets.toml

Usage:
    python google_sync.py              # Sync to STAGING database (safe)
    python google_sync.py --preview    # Preview staging data before promoting
    python google_sync.py --promote    # Promote staging to main database
    python google_sync.py --restore    # Restore main DB from backup
    python google_sync.py --list       # List available backups
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Fix Windows console encoding for emoji support
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Rate limiting: Google Sheets API allows 60 read requests per minute per user
# Adding delays between API calls to avoid hitting the quota
API_DELAY = 1.5  # seconds between API calls (safe margin for 60/min limit)

import io
import pandas as pd

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

DB_PATH = Path("db") / "database.sqlite"
STAGING_DB_PATH = Path("db") / "staging.sqlite"
BACKUP_DIR = Path("db") / "backups"
SERVICE_ACCOUNT_FILE = Path("service_account.json")

# Scopes needed for reading Drive and Sheets
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


def get_folder_id() -> str:
    """Get Google Drive folder ID from environment or secrets."""
    # Try Streamlit secrets first
    try:
        import streamlit as st
        if "GOOGLE_DRIVE_FOLDER_ID" in st.secrets:
            return str(st.secrets["GOOGLE_DRIVE_FOLDER_ID"])
    except Exception:
        pass

    # Fall back to environment variable
    folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
    if not folder_id:
        raise ValueError(
            "GOOGLE_DRIVE_FOLDER_ID not set. Add it to .env or .streamlit/secrets.toml"
        )
    return folder_id


def get_credentials():
    """Load service account credentials."""
    if not SERVICE_ACCOUNT_FILE.exists():
        raise FileNotFoundError(
            f"Service account file not found: {SERVICE_ACCOUNT_FILE}\n"
            "Download it from Google Cloud Console and save as 'service_account.json'"
        )

    return service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_FILE), scopes=SCOPES
    )


def backup_database() -> Optional[str]:
    """Create a backup of the database before sync."""
    if not DB_PATH.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"database_backup_{timestamp}.sqlite"

    shutil.copy2(DB_PATH, backup_file)

    # Record backup in database (ensure table exists first)
    size = backup_file.stat().st_size
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT (datetime('now')),
                filename TEXT NOT NULL,
                size_bytes INTEGER
            )
        """)
        con.execute(
            "INSERT INTO backups (filename, size_bytes) VALUES (?, ?)",
            (backup_file.name, size)
        )
        con.commit()

    print(f"✅ Backup created: {backup_file.name} ({size / 1024:.1f} KB)")
    return str(backup_file)


def cleanup_old_backups(keep_count: int = 10):
    """Keep only the most recent backups."""
    if not BACKUP_DIR.exists():
        return

    backups = sorted(BACKUP_DIR.glob("database_backup_*.sqlite"), reverse=True)
    for old_backup in backups[keep_count:]:
        old_backup.unlink()
        print(f"🗑️ Removed old backup: {old_backup.name}")


def list_backups() -> list[Path]:
    """List all available backups."""
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("database_backup_*.sqlite"), reverse=True)


def restore_from_backup(backup_path: Optional[Path] = None) -> bool:
    """Restore database from a backup file."""
    if backup_path is None:
        # Get the most recent backup
        backups = list_backups()
        if not backups:
            print("❌ No backups available to restore from.")
            return False
        backup_path = backups[0]

    if not backup_path.exists():
        print(f"❌ Backup file not found: {backup_path}")
        return False

    # Create a safety backup of current DB before restoring
    if DB_PATH.exists():
        safety_backup = BACKUP_DIR / f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite"
        shutil.copy2(DB_PATH, safety_backup)
        print(f"📦 Safety backup created: {safety_backup.name}")

    # Restore
    shutil.copy2(backup_path, DB_PATH)
    print(f"✅ Database restored from: {backup_path.name}")
    return True


def compute_data_hash(restrictions: dict, currencies: dict, games: list = None) -> str:
    """Compute a hash of the provider data to detect changes."""
    data = {
        "restrictions": {k: sorted(v) for k, v in restrictions.items()},
        "currencies": {k: sorted(v) for k, v in currencies.items()}
    }
    if games:
        # Include games in hash (sorted by title for consistency)
        data["games"] = sorted([g.get("game_title", "") for g in games])
    data_str = json.dumps(data, sort_keys=True)
    return hashlib.md5(data_str.encode()).hexdigest()


def get_existing_data_hash(con: sqlite3.Connection, provider_id: int) -> Optional[str]:
    """Get hash of existing provider data from database."""
    # Get restrictions
    cur = con.execute(
        "SELECT country_code, restriction_type FROM restrictions WHERE provider_id = ? ORDER BY country_code",
        (provider_id,)
    )
    restrictions = {"BLOCKED": [], "CONDITIONAL": [], "REGULATED": []}
    for row in cur.fetchall():
        if row[1] in restrictions:
            restrictions[row[1]].append(row[0])

    # Get currencies from new separate tables
    currencies = {"FIAT": [], "CRYPTO": []}

    # Get FIAT currencies
    cur = con.execute(
        "SELECT currency_code FROM fiat_currencies WHERE provider_id = ? ORDER BY currency_code",
        (provider_id,)
    )
    currencies["FIAT"] = [row[0] for row in cur.fetchall()]

    # Get CRYPTO currencies
    cur = con.execute(
        "SELECT currency_code FROM crypto_currencies WHERE provider_id = ? ORDER BY currency_code",
        (provider_id,)
    )
    currencies["CRYPTO"] = [row[0] for row in cur.fetchall()]

    # Get games
    games = []
    try:
        cur = con.execute(
            "SELECT game_title FROM games WHERE provider_id = ? ORDER BY game_title",
            (provider_id,)
        )
        games = [{"game_title": row[0]} for row in cur.fetchall()]
    except sqlite3.OperationalError:
        pass  # games table may not exist yet

    return compute_data_hash(restrictions, currencies, games)


def deduplicate_codes(codes: list[str]) -> list[str]:
    """Remove duplicate codes while preserving order."""
    seen = set()
    result = []
    for code in codes:
        code_upper = code.upper().strip()
        if code_upper and code_upper not in seen:
            seen.add(code_upper)
            result.append(code_upper)
    return result


def init_staging_db():
    """Initialize staging database with same schema as main."""
    from db_init import SCHEMA
    STAGING_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Remove old staging if exists
    if STAGING_DB_PATH.exists():
        STAGING_DB_PATH.unlink()

    con = sqlite3.connect(STAGING_DB_PATH)
    con.executescript(SCHEMA)
    con.commit()
    con.close()
    print(f"📦 Staging database initialized: {STAGING_DB_PATH}")


def preview_staging():
    """Show summary of data in staging database."""
    if not STAGING_DB_PATH.exists():
        print("❌ No staging database found. Run sync first.")
        return

    con = sqlite3.connect(STAGING_DB_PATH)

    # Count providers
    providers = con.execute("SELECT provider_id, provider_name, currency_mode FROM providers ORDER BY provider_name").fetchall()

    if not providers:
        print("📭 Staging database is empty.")
        con.close()
        return

    print(f"\n📊 STAGING DATABASE PREVIEW")
    print(f"{'='*60}\n")
    print(f"Total providers: {len(providers)}\n")

    for pid, name, mode in providers:
        # Get restrictions
        blocked = con.execute(
            "SELECT COUNT(*) FROM restrictions WHERE provider_id = ? AND restriction_type = 'BLOCKED'",
            (pid,)
        ).fetchone()[0]
        conditional = con.execute(
            "SELECT COUNT(*) FROM restrictions WHERE provider_id = ? AND restriction_type = 'CONDITIONAL'",
            (pid,)
        ).fetchone()[0]
        regulated = con.execute(
            "SELECT COUNT(*) FROM restrictions WHERE provider_id = ? AND restriction_type = 'REGULATED'",
            (pid,)
        ).fetchone()[0]

        # Get currencies from new separate tables
        fiat = con.execute(
            "SELECT COUNT(*) FROM fiat_currencies WHERE provider_id = ?",
            (pid,)
        ).fetchone()[0]
        crypto = con.execute(
            "SELECT COUNT(*) FROM crypto_currencies WHERE provider_id = ?",
            (pid,)
        ).fetchone()[0]

        # Get games count
        try:
            games_count = con.execute(
                "SELECT COUNT(*) FROM games WHERE provider_id = ?",
                (pid,)
            ).fetchone()[0]
            game_types_count = con.execute(
                "SELECT COUNT(DISTINCT game_type) FROM games WHERE provider_id = ?",
                (pid,)
            ).fetchone()[0]
        except sqlite3.OperationalError:
            games_count = 0
            game_types_count = 0

        fiat_display = "ALL (*)" if mode == "ALL_FIAT" else str(fiat)
        print(f"📂 {name}")
        print(f"   Blocked: {blocked} | Conditional: {conditional} | Regulated: {regulated} | FIAT: {fiat_display} | Crypto: {crypto}")
        if games_count > 0:
            print(f"   🎮 Games: {games_count} games, {game_types_count} types")

    con.close()

    print(f"\n{'='*60}")
    print("✅ To apply this data to main database, run:")
    print("   python google_sync.py --promote")


def promote_staging():
    """Copy staging database to main database, preserving the countries table."""
    if not STAGING_DB_PATH.exists():
        print("❌ No staging database found. Run sync first.")
        return False

    # Backup main DB first
    countries_data = []
    if DB_PATH.exists():
        backup_database()
        # Preserve countries table (not synced from Google)
        try:
            with sqlite3.connect(DB_PATH) as main_con:
                countries_data = main_con.execute(
                    "SELECT iso3, iso2, name FROM countries"
                ).fetchall()
                if countries_data:
                    print(f"   📋 Preserving {len(countries_data)} countries from main DB")
        except sqlite3.OperationalError:
            pass  # countries table doesn't exist

    # Copy staging to main
    shutil.copy2(STAGING_DB_PATH, DB_PATH)
    print(f"✅ Staging promoted to main database: {DB_PATH}")

    # Restore countries table
    if countries_data:
        with sqlite3.connect(DB_PATH) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS countries (
                    iso3 TEXT PRIMARY KEY,
                    iso2 TEXT,
                    name TEXT
                )
            """)
            con.executemany(
                "INSERT OR REPLACE INTO countries (iso3, iso2, name) VALUES (?, ?, ?)",
                countries_data
            )
            con.commit()
        print(f"   ✅ Restored {len(countries_data)} countries")

    # Keep staging for reference (or remove it)
    # STAGING_DB_PATH.unlink()  # Uncomment to delete staging after promote

    return True


def compare_staging_to_main():
    """Compare staging with main DB and show differences."""
    if not STAGING_DB_PATH.exists():
        print("❌ No staging database found.")
        return

    if not DB_PATH.exists():
        print("ℹ️ Main database doesn't exist yet. All staging data is new.")
        return

    staging_con = sqlite3.connect(STAGING_DB_PATH)
    main_con = sqlite3.connect(DB_PATH)

    # Get providers from both
    staging_providers = set(r[0] for r in staging_con.execute("SELECT provider_name FROM providers").fetchall())
    main_providers = set(r[0] for r in main_con.execute("SELECT provider_name FROM providers").fetchall())

    new_providers = staging_providers - main_providers
    removed_providers = main_providers - staging_providers
    existing_providers = staging_providers & main_providers

    print(f"\n📊 COMPARISON: Staging vs Main")
    print(f"{'='*60}")
    print(f"🆕 New providers: {len(new_providers)}")
    if new_providers:
        for p in sorted(new_providers):
            print(f"   + {p}")

    print(f"🗑️ Removed providers: {len(removed_providers)}")
    if removed_providers:
        for p in sorted(removed_providers):
            print(f"   - {p}")

    print(f"📝 Existing providers: {len(existing_providers)}")

    staging_con.close()
    main_con.close()


def list_provider_folders(drive_service, folder_id: str) -> list[dict]:
    """List all subfolders (provider folders) in the main folder with pagination."""
    query = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"

    all_files = []
    page_token = None

    while True:
        results = drive_service.files().list(
            q=query,
            fields="nextPageToken, files(id, name)",
            pageSize=100,
            pageToken=page_token
        ).execute()
        time.sleep(API_DELAY)  # Rate limiting

        all_files.extend(results.get("files", []))
        page_token = results.get("nextPageToken")

        if not page_token:
            break

    return all_files


def list_spreadsheets_in_folder(drive_service, folder_id: str) -> list[dict]:
    """List all spreadsheets directly in a folder (for flat structure) with pagination."""
    query = (
        f"'{folder_id}' in parents "
        f"and (mimeType = 'application/vnd.google-apps.spreadsheet' "
        f"or mimeType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet') "
        f"and trashed = false"
    )

    all_files = []
    page_token = None

    while True:
        results = drive_service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType)",
            pageSize=100,
            pageToken=page_token
        ).execute()
        time.sleep(API_DELAY)  # Rate limiting

        all_files.extend(results.get("files", []))
        page_token = results.get("nextPageToken")

        if not page_token:
            break

    return all_files


def find_main_data_sheet(drive_service, folder_id: str) -> Optional[dict]:
    """Find the 'Main DATA' sheet in a provider folder.

    Searches for both native Google Sheets and uploaded Excel files.
    """
    # Search for Google Sheets AND Excel files
    query = (
        f"'{folder_id}' in parents "
        f"and (mimeType = 'application/vnd.google-apps.spreadsheet' "
        f"or mimeType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet') "
        f"and trashed = false"
    )

    results = drive_service.files().list(
        q=query,
        fields="files(id, name, mimeType)",
        pageSize=10
    ).execute()
    time.sleep(API_DELAY)  # Rate limiting

    files = results.get("files", [])

    # Debug: show what files were found
    if not files:
        # Try listing ALL files in folder to debug
        all_query = f"'{folder_id}' in parents and trashed = false"
        all_results = drive_service.files().list(
            q=all_query,
            fields="files(id, name, mimeType)",
            pageSize=10
        ).execute()
        time.sleep(API_DELAY)
        all_files = all_results.get("files", [])
        if all_files:
            print(f"   📁 Found {len(all_files)} files in folder:")
            for f in all_files[:5]:
                print(f"      - {f['name']} ({f['mimeType']})")

    # Look for file containing "Main DATA" (case insensitive)
    for f in files:
        if "main data" in f["name"].lower():
            return f

    # If no "Main DATA", return the first spreadsheet
    return files[0] if files else None


def download_excel_file(drive_service, file_id: str) -> bytes:
    """Download an Excel file from Google Drive.

    Raises HttpError 403 if the file is a native Google Sheet (not binary).
    """
    request = drive_service.files().get_media(fileId=file_id)
    file_buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(file_buffer, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()

    time.sleep(API_DELAY)  # Rate limiting
    file_buffer.seek(0)
    return file_buffer.read()


def process_spreadsheet_data(drive_service, sheets_service, sheet_id: str, sheet_name: str, is_excel: bool) -> tuple[dict, dict, str, list]:
    """
    Process a spreadsheet (Excel or native Google Sheet) and extract data.

    If Excel download fails (file is actually a native Sheet), automatically falls back to Sheets API.

    Returns: (restrictions, currencies, currency_mode, games)
    """
    if is_excel:
        try:
            print(f"   📥 Downloading Excel file...")
            file_bytes = download_excel_file(drive_service, sheet_id)
            parsed = parse_excel_file(file_bytes)

            restrictions = parsed["restrictions"]
            currencies = parsed["currencies"]
            all_fiat_flag = parsed["all_fiat"]

            print(f"   🚫 Restrictions: {len(restrictions['BLOCKED'])} blocked, {len(restrictions['CONDITIONAL'])} conditional, {len(restrictions['REGULATED'])} regulated")

            if all_fiat_flag:
                currency_mode = "ALL_FIAT"
                print(f"   💰 Currencies: ALL FIAT (*), {len(currencies['CRYPTO'])} crypto")
            elif currencies["FIAT"]:
                currency_mode = "LIST"
                print(f"   💰 Currencies: {len(currencies['FIAT'])} FIAT, {len(currencies['CRYPTO'])} crypto")
            else:
                currency_mode = "ALL_FIAT"
                print(f"   💰 Currencies: ALL FIAT (default), {len(currencies['CRYPTO'])} crypto")

            # Parse games from Excel (first sheet)
            games = parsed.get("games", [])
            first_sheet = parsed.get("sheet_names", [""])[0] if parsed.get("sheet_names") else ""
            if games:
                game_types = get_unique_game_types(games)
                print(f"   🎮 First tab '{first_sheet}': {len(games)} games, {len(game_types)} types")
            else:
                print(f"   🎮 First tab '{first_sheet}': no game headers found")

            return restrictions, currencies, currency_mode, games

        except Exception as e:
            if "Only files with binary content" in str(e):
                print(f"   ⚠️ File is a native Google Sheet (despite .xlsx name), switching to Sheets API...")
                # Fall through to Sheets API handling below
            else:
                raise  # Re-raise other errors

    # Native Google Sheet - use Sheets API
    tab_names = get_sheet_names(sheets_service, sheet_id)

    # Find and read restrictions (multi-column: A=Restricted, C=Regulated)
    restrictions_tab = find_restrictions_sheet(tab_names)
    restrictions = {"BLOCKED": [], "CONDITIONAL": [], "REGULATED": []}
    if restrictions_tab:
        rows = read_sheet_range(sheets_service, sheet_id, restrictions_tab, "A1:Z200")
        if rows:
            restrictions = parse_restrictions_from_range(rows)
        print(f"   🚫 Restrictions: {len(restrictions['BLOCKED'])} blocked, {len(restrictions['CONDITIONAL'])} conditional, {len(restrictions['REGULATED'])} regulated")

    # Find and read currencies
    currencies_tab = find_currencies_sheet(tab_names)
    currencies = {"FIAT": [], "CRYPTO": []}
    currency_mode = "ALL_FIAT"
    if currencies_tab:
        rows = read_sheet_range(sheets_service, sheet_id, currencies_tab, "A1:Z200")
        if rows:
            currencies, all_fiat_flag = parse_currencies_from_range(rows)
            if all_fiat_flag:
                currency_mode = "ALL_FIAT"
                print(f"   💰 Currencies: ALL FIAT (*), {len(currencies['CRYPTO'])} crypto", flush=True)
            elif currencies["FIAT"]:
                currency_mode = "LIST"
                print(f"   💰 Currencies: {len(currencies['FIAT'])} FIAT, {len(currencies['CRYPTO'])} crypto", flush=True)
            else:
                print(f"   💰 Currencies: ALL FIAT (default), {len(currencies['CRYPTO'])} crypto", flush=True)
        else:
            print(f"   💰 Currencies: ALL FIAT (no data found)", flush=True)

    # Games are always in the first sheet - check if it has game headers
    games = []
    if tab_names:
        first_tab = tab_names[0]
        print(f"   🎮 Checking first tab: {first_tab}", flush=True)
        try:
            rows = read_sheet_range(sheets_service, sheet_id, first_tab, "A1:Z5000")
            if rows and has_game_headers(rows):
                games = parse_games_from_range(rows)
                if games:
                    game_types = get_unique_game_types(games)
                    print(f"   🎮 Found {len(games)} games, {len(game_types)} types")
            else:
                print(f"   🎮 First tab has no game headers, skipping")
        except Exception as e:
            print(f"   ❌ Error reading first tab: {e}")

    return restrictions, currencies, currency_mode, games


def parse_excel_file(file_bytes: bytes) -> dict:
    """
    Parse an Excel file and extract sheet names, restrictions, currencies, and games.

    Returns dict with:
    - sheet_names: list of sheet names
    - restrictions: {"BLOCKED": [...], "CONDITIONAL": [...], "REGULATED": [...]}
    - currencies: {"FIAT": [...], "CRYPTO": [...]}
    - all_fiat: bool
    - games: list of game dicts
    """
    excel_buffer = io.BytesIO(file_bytes)
    xlsx = pd.ExcelFile(excel_buffer)

    sheet_names = xlsx.sheet_names

    # Find restrictions sheet
    restrictions = {"BLOCKED": [], "CONDITIONAL": [], "REGULATED": []}
    restrictions_sheet = None
    for name in sheet_names:
        if "restrict" in name.lower():
            restrictions_sheet = name
            break

    if restrictions_sheet:
        df = pd.read_excel(xlsx, sheet_name=restrictions_sheet, header=None)
        # Convert entire dataframe to 2D list for multi-column parsing
        if not df.empty:
            rows = []
            for _, row in df.iterrows():
                row_data = [str(cell) if pd.notna(cell) else "" for cell in row]
                rows.append(row_data)
            restrictions = parse_restrictions_from_range(rows)

    # Find currencies sheet
    currencies = {"FIAT": [], "CRYPTO": []}
    all_fiat = False
    currencies_sheet = None
    for name in sheet_names:
        if "currenc" in name.lower():
            currencies_sheet = name
            break

    if currencies_sheet:
        df = pd.read_excel(xlsx, sheet_name=currencies_sheet, header=None)
        if not df.empty:
            # Convert entire dataframe to list of lists (like read_sheet_range)
            rows = []
            for _, row in df.iterrows():
                row_data = [str(cell) if pd.notna(cell) else "" for cell in row]
                rows.append(row_data)
            currencies, all_fiat = parse_currencies_from_range(rows)

    # Games are always in the first sheet - check if it has game headers
    games = []
    if sheet_names:
        first_sheet = sheet_names[0]
        df = pd.read_excel(xlsx, sheet_name=first_sheet, header=None)
        if not df.empty:
            rows = []
            for _, row in df.iterrows():
                row_data = [str(cell) if pd.notna(cell) else "" for cell in row]
                rows.append(row_data)
            if has_game_headers(rows):
                games = parse_games_from_range(rows)

    return {
        "sheet_names": sheet_names,
        "restrictions": restrictions,
        "currencies": currencies,
        "all_fiat": all_fiat,
        "games": games
    }


def get_sheet_names(sheets_service, spreadsheet_id: str) -> list[str]:
    """Get all sheet/tab names in a spreadsheet."""
    result = sheets_service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets.properties.title"
    ).execute()
    time.sleep(API_DELAY)  # Rate limiting

    return [sheet["properties"]["title"] for sheet in result.get("sheets", [])]


def read_sheet_column(sheets_service, spreadsheet_id: str, sheet_name: str, column: str = "A") -> list[str]:
    """Read a single column from a sheet."""
    range_name = f"'{sheet_name}'!{column}:{column}"

    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        time.sleep(API_DELAY)  # Rate limiting

        values = result.get("values", [])
        return [row[0] if row else "" for row in values]
    except Exception as e:
        time.sleep(API_DELAY)  # Rate limiting even on error
        print(f"  ⚠️ Error reading {sheet_name}: {e}")
        return []


def read_sheet_columns(sheets_service, spreadsheet_id: str, sheet_name: str, columns: list[str]) -> dict[str, list[str]]:
    """Read multiple columns from a sheet."""
    result = {}
    for col in columns:
        result[col] = read_sheet_column(sheets_service, spreadsheet_id, sheet_name, col)
    return result


def read_sheet_range(sheets_service, spreadsheet_id: str, sheet_name: str, range_str: str = "A1:Z100") -> list[list[str]]:
    """Read a range from a sheet, returns 2D list of values."""
    full_range = f"'{sheet_name}'!{range_str}"

    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=full_range
        ).execute()
        time.sleep(API_DELAY)  # Rate limiting

        return result.get("values", [])
    except Exception as e:
        time.sleep(API_DELAY)  # Rate limiting even on error
        print(f"  ⚠️ Error reading range {sheet_name}: {e}")
        return []


def find_crypto_column(rows: list[list[str]]) -> int:
    """
    Find which column contains crypto currencies by looking for 'crypto' in headers.
    Returns column index (0-based) or -1 if not found.
    """
    if not rows:
        return -1

    # Check first few rows for "crypto" header
    for row_idx, row in enumerate(rows[:5]):
        for col_idx, cell in enumerate(row):
            if cell and "crypto" in str(cell).lower():
                return col_idx

    return -1


def find_fiat_columns(rows: list[list[str]]) -> list[int]:
    """
    Find all columns that contain FIAT currencies by looking for headers like:
    - "Supported currencies"
    - "Upon request also supporting"
    - Any column header containing "currenc" or "support" (but not "crypto")

    Returns list of column indices (0-based).
    """
    fiat_cols = []

    if not rows:
        return [0]  # Default to column A

    # Check first few rows for FIAT headers
    for row_idx, row in enumerate(rows[:5]):
        for col_idx, cell in enumerate(row):
            if cell:
                cell_lower = str(cell).lower()
                # Look for FIAT-related headers (but not crypto)
                if ("crypto" not in cell_lower and "digital" not in cell_lower and
                    ("support" in cell_lower or "currenc" in cell_lower or "request" in cell_lower or "fiat" in cell_lower)):
                    if col_idx not in fiat_cols:
                        fiat_cols.append(col_idx)

    # Default to column A if no headers found
    return fiat_cols if fiat_cols else [0]


def parse_currencies_from_range(rows: list[list[str]]) -> tuple[dict[str, list[str]], bool]:
    """
    Parse currency data from a 2D range, auto-detecting FIAT columns and Crypto columns.

    Handles multi-column layouts like:
    - Column A: "Supported currencies"
    - Column C: "Upon request also supporting:"

    Returns:
        (currencies_dict, all_fiat_flag)
    """
    fiat = []
    crypto = []
    all_fiat = False

    code_pattern = re.compile(r"^([A-Z0-9]{2,10})\b")

    # Find crypto column
    crypto_col = find_crypto_column(rows)

    # Find all FIAT columns (could be multiple: main + upon request)
    fiat_cols = find_fiat_columns(rows)

    for row in rows:
        # Process all FIAT columns
        for fiat_col in fiat_cols:
            if len(row) > fiat_col:
                cell = str(row[fiat_col]).strip()
                if cell:
                    cell_lower = cell.lower()

                    # Detect "All currencies" patterns
                    if "all" in cell_lower and ("iso" in cell_lower or "4217" in cell_lower or "currencies" in cell_lower or "fiat" in cell_lower):
                        all_fiat = True
                        continue

                    # Skip header rows
                    if "supported" in cell_lower or "request" in cell_lower or cell_lower == "currency" or "upon" in cell_lower:
                        continue

                    # Extract FIAT code
                    match = code_pattern.match(cell)
                    if match:
                        code = match.group(1)
                        if len(code) == 3 and code.isalpha():
                            fiat.append(code)

        # Crypto column (dynamic position)
        if crypto_col > 0 and crypto_col not in fiat_cols and len(row) > crypto_col:
            cell = str(row[crypto_col]).strip()
            if cell:
                cell_lower = cell.lower()

                # Skip header rows
                if "crypto" in cell_lower or "digital" in cell_lower:
                    continue

                # Extract crypto code
                match = code_pattern.match(cell)
                if match:
                    code = match.group(1)
                    crypto.append(code)

    return {
        "FIAT": deduplicate_codes(fiat),
        "CRYPTO": deduplicate_codes(crypto)
    }, all_fiat


def parse_restrictions(rows: list[str]) -> dict[str, list[str]]:
    """
    Parse restriction rows into BLOCKED, CONDITIONAL, and REGULATED lists.
    (Legacy: single column parsing)

    Looks for section headers like:
    - "Blocked Countries (blocked for all operators...)"
    - "Restricted Countries (blocked by default, can open...)"
    - "Regulated Countries (requires license/documentation)"
    """
    blocked = []
    conditional = []
    regulated = []

    current_section = None
    iso3_pattern = re.compile(r"^([A-Z]{3})\b")

    for row in rows:
        row = row.strip()
        if not row:
            continue

        row_lower = row.lower()

        # Detect section headers - order matters!
        # Check for "regulated" first (most specific)
        if "regulated" in row_lower and ("countries" in row_lower or "areas" in row_lower or "markets" in row_lower):
            current_section = "REGULATED"
            continue

        # Check for "restricted" (conditional)
        if "restricted" in row_lower and ("countries" in row_lower or "areas" in row_lower):
            current_section = "CONDITIONAL"
            continue

        # Check for "blocked"
        if "blocked" in row_lower and ("countries" in row_lower or "areas" in row_lower):
            # "blocked by default, can open" means conditional
            if "by default" in row_lower or "can open" in row_lower:
                current_section = "CONDITIONAL"
            else:
                current_section = "BLOCKED"
            continue

        # Extract ISO3 code from rows like "USA (United States)" or "USA United States"
        match = iso3_pattern.match(row)
        if match and current_section:
            code = match.group(1)
            if current_section == "BLOCKED":
                blocked.append(code)
            elif current_section == "CONDITIONAL":
                conditional.append(code)
            else:  # REGULATED
                regulated.append(code)

    # Deduplicate codes
    return {
        "BLOCKED": deduplicate_codes(blocked),
        "CONDITIONAL": deduplicate_codes(conditional),
        "REGULATED": deduplicate_codes(regulated)
    }


def parse_restrictions_from_range(rows: list[list[str]]) -> dict[str, list[str]]:
    """
    Parse restriction data from a 2D range, auto-detecting columns by header.

    Handles multi-column layouts like:
    - Column A: "Restricted countries" → CONDITIONAL (or BLOCKED if header says so)
    - Column C: "Regulated markets (unless locally licenced)" → REGULATED

    Returns: {"BLOCKED": [...], "CONDITIONAL": [...], "REGULATED": [...]}
    """
    blocked = []
    conditional = []
    regulated = []

    iso3_pattern = re.compile(r"^([A-Z]{3})\b")

    # Detect column types from headers (first few rows)
    # col_type[col_idx] = "BLOCKED" | "CONDITIONAL" | "REGULATED" | None
    col_types = {}

    for row_idx, row in enumerate(rows[:3]):  # Check first 3 rows for headers
        for col_idx, cell in enumerate(row):
            if not cell:
                continue
            cell_lower = str(cell).lower()

            # Detect "Regulated" column
            if "regulated" in cell_lower and ("market" in cell_lower or "countr" in cell_lower or "area" in cell_lower):
                col_types[col_idx] = "REGULATED"

            # Detect "Blocked" column
            elif "blocked" in cell_lower and ("countr" in cell_lower or "area" in cell_lower):
                # "blocked by default, can open" means conditional
                if "by default" in cell_lower or "can open" in cell_lower:
                    col_types[col_idx] = "CONDITIONAL"
                else:
                    col_types[col_idx] = "BLOCKED"

            # Detect "Restricted" column (default to CONDITIONAL)
            elif "restricted" in cell_lower and ("countr" in cell_lower or "area" in cell_lower):
                col_types[col_idx] = "CONDITIONAL"

    # Default: if no headers detected, treat column 0 as CONDITIONAL
    if not col_types:
        col_types[0] = "CONDITIONAL"

    # Parse data from each detected column
    for row in rows:
        for col_idx, restriction_type in col_types.items():
            if col_idx >= len(row):
                continue
            cell = str(row[col_idx]).strip()
            if not cell:
                continue

            # Skip header rows
            cell_lower = cell.lower()
            if any(kw in cell_lower for kw in ["restricted", "regulated", "blocked", "countries", "markets", "areas"]):
                continue

            # Extract ISO3 code
            match = iso3_pattern.match(cell)
            if match:
                code = match.group(1)
                if restriction_type == "BLOCKED":
                    blocked.append(code)
                elif restriction_type == "CONDITIONAL":
                    conditional.append(code)
                elif restriction_type == "REGULATED":
                    regulated.append(code)

    return {
        "BLOCKED": deduplicate_codes(blocked),
        "CONDITIONAL": deduplicate_codes(conditional),
        "REGULATED": deduplicate_codes(regulated)
    }


def parse_currencies_from_columns(fiat_rows: list[str], crypto_rows: list[str]) -> tuple[dict[str, list[str]], bool]:
    """
    Parse currency data from separate FIAT and CRYPTO columns.

    Returns:
        (currencies_dict, all_fiat_flag)
        - currencies_dict: {"FIAT": [...], "CRYPTO": [...]}
        - all_fiat_flag: True if "All ISO-4217" or similar detected
    """
    fiat = []
    crypto = []
    all_fiat = False

    code_pattern = re.compile(r"^([A-Z0-9]{2,10})\b")

    # Parse FIAT column
    for row in fiat_rows:
        row = row.strip()
        if not row:
            continue

        row_lower = row.lower()

        # Detect "All currencies" patterns
        if ("all" in row_lower and ("iso" in row_lower or "4217" in row_lower or "currencies" in row_lower or "fiat" in row_lower)):
            all_fiat = True
            continue

        # Skip header rows
        if "supported" in row_lower or ("currency" in row_lower and "currencies" not in row_lower):
            continue

        # Extract currency code (e.g., "USD (United States Dollar)" -> "USD")
        match = code_pattern.match(row)
        if match:
            code = match.group(1)
            if len(code) == 3 and code.isalpha():  # ISO 4217 FIAT codes are 3 letters
                fiat.append(code)

    # Parse CRYPTO column
    for row in crypto_rows:
        row = row.strip()
        if not row:
            continue

        row_lower = row.lower()

        # Skip header rows
        if "crypto" in row_lower or "digital" in row_lower:
            continue

        # Extract currency code (e.g., "BTC (Bitcoin)" -> "BTC")
        match = code_pattern.match(row)
        if match:
            code = match.group(1)
            crypto.append(code)

    # Deduplicate codes
    return {
        "FIAT": deduplicate_codes(fiat),
        "CRYPTO": deduplicate_codes(crypto)
    }, all_fiat


def parse_currencies(rows: list[str]) -> tuple[dict[str, list[str]], bool]:
    """
    Parse currency rows into FIAT and CRYPTO lists (single column format).

    Returns:
        (currencies_dict, all_fiat_flag)
        - currencies_dict: {"FIAT": [...], "CRYPTO": [...]}
        - all_fiat_flag: True if "All ISO-4217" or similar detected

    Extracts codes from formats like:
    - "USD (United States Dollar)"
    - "BTC Bitcoin"
    - "EUR"
    - "All ISO-4217 currencies" -> sets all_fiat flag
    """
    fiat = []
    crypto = []
    all_fiat = False

    current_section = "FIAT"  # Default to FIAT
    code_pattern = re.compile(r"^([A-Z0-9]{2,10})\b")

    # Known crypto symbols (comprehensive list)
    crypto_symbols = {
        # Major cryptocurrencies
        "BTC", "ETH", "USDT", "USDC", "BNB", "XRP", "ADA", "DOGE", "SOL", "DOT",
        "MATIC", "LTC", "BCH", "LINK", "XLM", "ATOM", "UNI", "AVAX", "TRX", "ETC",
        "NEAR", "ALGO", "FTM", "SAND", "MANA", "AXS", "AAVE", "MKR", "COMP", "SNX",
        # Stablecoins
        "DAI", "BUSD", "TUSD", "USDP", "FRAX", "LUSD", "GUSD", "PAX", "EURS",
        # Other popular tokens
        "SHIB", "APE", "CRO", "LEO", "OKB", "QNT", "VET", "HBAR", "FIL", "ICP",
        "THETA", "XTZ", "EOS", "ZEC", "XMR", "DASH", "NEO", "WAVES", "KSM", "CAKE",
        "RUNE", "ZIL", "ENJ", "BAT", "GRT", "1INCH", "CRV", "SUSHI", "YFI", "LRC",
    }

    for row in rows:
        row = row.strip()
        if not row:
            continue

        row_lower = row.lower()

        # Detect "All currencies" patterns
        if ("all" in row_lower and ("iso" in row_lower or "4217" in row_lower or "currencies" in row_lower or "fiat" in row_lower)):
            all_fiat = True
            continue

        # Detect section headers
        if "crypto" in row_lower or "digital" in row_lower or "token" in row_lower:
            current_section = "CRYPTO"
            continue
        if "fiat" in row_lower or "traditional" in row_lower:
            current_section = "FIAT"
            continue

        # Skip header rows
        if "supported" in row_lower or "currency" in row_lower and not code_pattern.match(row):
            continue

        # Extract currency code
        match = code_pattern.match(row)
        if match:
            code = match.group(1)

            # Determine if crypto or fiat based on multiple signals
            is_crypto = (
                code in crypto_symbols or
                current_section == "CRYPTO" or
                (len(code) > 3 and code not in {"USD", "EUR", "GBP"})  # Most FIAT codes are 3 chars
            )

            if is_crypto:
                crypto.append(code)
            elif len(code) == 3 and code.isalpha():  # ISO 4217 FIAT codes are 3 letters
                fiat.append(code)

    # Deduplicate codes
    return {
        "FIAT": deduplicate_codes(fiat),
        "CRYPTO": deduplicate_codes(crypto)
    }, all_fiat


def find_restrictions_sheet(sheet_names: list[str]) -> Optional[str]:
    """Find sheet with restrictions data."""
    for name in sheet_names:
        if "restrict" in name.lower():
            return name
    return None


def find_currencies_sheet(sheet_names: list[str]) -> Optional[str]:
    """Find sheet with currencies data."""
    for name in sheet_names:
        if "currenc" in name.lower():
            return name
    return None


def has_game_headers(rows: list[list[str]]) -> bool:
    """Check if sheet has game-related headers (game title, wallet game id, etc.)."""
    if not rows:
        return False

    # Check first 3 rows for game headers
    for row in rows[:3]:
        row_text = " ".join(str(cell).lower() for cell in row)
        if "game title" in row_text or "game_title" in row_text:
            return True
        if "wallet" in row_text and "id" in row_text:
            return True
    return False


def parse_games_from_range(rows: list[list[str]]) -> list[dict]:
    """
    Parse games from a 2D range (Game List tab).

    Expected columns (from screenshot):
    - A: Wallet game ID
    - B: Game title
    - C: Game provider
    - D: Vendor
    - E: Game type

    Returns: list of game dicts with wallet_game_id, game_title, game_provider, vendor, game_type
    """
    games = []

    if not rows:
        return []

    # Find column indices by looking at headers
    col_map = {
        "wallet_game_id": -1,
        "game_title": -1,
        "game_provider": -1,
        "vendor": -1,
        "game_type": -1
    }
    header_row_idx = 0

    for row_idx, row in enumerate(rows[:3]):  # Check first 3 rows for headers
        for col_idx, cell in enumerate(row):
            if not cell:
                continue
            cell_lower = str(cell).lower()
            if "wallet" in cell_lower and "id" in cell_lower:
                col_map["wallet_game_id"] = col_idx
            elif "game title" in cell_lower or cell_lower == "game title":
                col_map["game_title"] = col_idx
            elif "game provider" in cell_lower or cell_lower == "game provider":
                col_map["game_provider"] = col_idx
            elif "vendor" in cell_lower:
                col_map["vendor"] = col_idx
            elif "game type" in cell_lower:
                col_map["game_type"] = col_idx

        # If we found at least game_title, use this row as header
        if col_map["game_title"] >= 0 or col_map["game_type"] >= 0:
            header_row_idx = row_idx
            break

    # Default column positions if headers not found (based on screenshot)
    if col_map["wallet_game_id"] < 0:
        col_map["wallet_game_id"] = 0
    if col_map["game_title"] < 0:
        col_map["game_title"] = 1
    if col_map["game_provider"] < 0:
        col_map["game_provider"] = 2
    if col_map["vendor"] < 0:
        col_map["vendor"] = 3
    if col_map["game_type"] < 0:
        col_map["game_type"] = 4

    # Parse data rows (skip header)
    for row in rows[header_row_idx + 1:]:
        def get_cell(col_idx):
            if col_idx >= 0 and col_idx < len(row):
                val = str(row[col_idx]).strip()
                if val.lower() in ["", "nan", "none"]:
                    return ""
                return val
            return ""

        game_title = get_cell(col_map["game_title"])
        if not game_title:
            continue  # Skip rows without a title

        games.append({
            "wallet_game_id": get_cell(col_map["wallet_game_id"]),
            "game_title": game_title,
            "game_provider": get_cell(col_map["game_provider"]),
            "vendor": get_cell(col_map["vendor"]),
            "game_type": get_cell(col_map["game_type"])
        })

    return games


def get_unique_game_types(games: list[dict]) -> list[str]:
    """Extract unique game types from a list of games."""
    types = set()
    for game in games:
        if game.get("game_type"):
            types.add(game["game_type"])
    return sorted(list(types))


def upsert_provider(con: sqlite3.Connection, name: str, sheet_id: str, currency_mode: str = "LIST") -> tuple[int, bool]:
    """Insert or update a provider and return (ID, is_new)."""
    cur = con.execute("SELECT provider_id FROM providers WHERE provider_name = ?", (name,))
    row = cur.fetchone()

    now = datetime.now().isoformat()

    if row:
        provider_id = row[0]
        con.execute(
            "UPDATE providers SET google_sheet_id = ?, last_synced = ?, currency_mode = ? WHERE provider_id = ?",
            (sheet_id, now, currency_mode, provider_id)
        )
        return provider_id, False
    else:
        cur = con.execute(
            "INSERT INTO providers (provider_name, status, currency_mode, google_sheet_id, last_synced) VALUES (?, 'ACTIVE', ?, ?, ?)",
            (name, currency_mode, sheet_id, now)
        )
        provider_id = cur.lastrowid
        return provider_id, True


def replace_restrictions(con: sqlite3.Connection, provider_id: int, restrictions: dict[str, list[str]], source: str):
    """Replace all restrictions for a provider."""
    con.execute("DELETE FROM restrictions WHERE provider_id = ?", (provider_id,))

    for restriction_type, codes in restrictions.items():
        for code in codes:
            con.execute(
                "INSERT OR IGNORE INTO restrictions (provider_id, country_code, restriction_type, source) VALUES (?, ?, ?, ?)",
                (provider_id, code, restriction_type, source)
            )


def get_provider_id_by_name(con: sqlite3.Connection, provider_name: str) -> Optional[int]:
    """Look up provider_id by name (case-insensitive partial match)."""
    if not provider_name:
        return None

    # Try exact match first
    cur = con.execute(
        "SELECT provider_id FROM providers WHERE LOWER(provider_name) = LOWER(?)",
        (provider_name,)
    )
    row = cur.fetchone()
    if row:
        return row[0]

    # Try partial match (provider_name contains the search term)
    cur = con.execute(
        "SELECT provider_id FROM providers WHERE LOWER(provider_name) LIKE LOWER(?)",
        (f"%{provider_name}%",)
    )
    row = cur.fetchone()
    if row:
        return row[0]

    return None


def replace_games(con: sqlite3.Connection, games: list[dict], source: str, default_provider_id: int = None):
    """Replace all games, matching each game to its provider by game_provider column."""
    # Don't delete existing games if no new games were found
    if not games:
        return 0

    # Group games by game_provider
    games_by_provider = {}
    for game in games:
        game_provider = game.get("game_provider", "")
        if game_provider not in games_by_provider:
            games_by_provider[game_provider] = []
        games_by_provider[game_provider].append(game)

    total_inserted = 0

    for game_provider, provider_games in games_by_provider.items():
        # Look up provider_id by game_provider name
        provider_id = get_provider_id_by_name(con, game_provider)

        # Fall back to default provider if no match found
        if provider_id is None:
            provider_id = default_provider_id

        if provider_id is None:
            print(f"      ⚠️ No provider found for '{game_provider}', skipping {len(provider_games)} games")
            continue

        # Delete existing games for this provider before inserting
        con.execute("DELETE FROM games WHERE provider_id = ?", (provider_id,))

        for game in provider_games:
            con.execute(
                """INSERT INTO games (provider_id, wallet_game_id, game_title, game_provider, vendor, game_type, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (provider_id, game.get("wallet_game_id"), game.get("game_title"),
                 game.get("game_provider"), game.get("vendor"), game.get("game_type"), source)
            )
            total_inserted += 1

    return total_inserted


def replace_currencies(con: sqlite3.Connection, provider_id: int, currencies: dict[str, list[str]], source: str):
    """Replace all currencies for a provider (writes to new separate tables)."""
    # Clear old data from new tables
    con.execute("DELETE FROM fiat_currencies WHERE provider_id = ?", (provider_id,))
    con.execute("DELETE FROM crypto_currencies WHERE provider_id = ?", (provider_id,))

    # Also clear legacy table for backwards compatibility
    con.execute("DELETE FROM currencies WHERE provider_id = ?", (provider_id,))

    # Write FIAT currencies to fiat_currencies table
    for code in currencies.get("FIAT", []):
        con.execute(
            "INSERT OR IGNORE INTO fiat_currencies (provider_id, currency_code, display, source) VALUES (?, ?, 1, ?)",
            (provider_id, code, source)
        )
        # Also write to legacy table for backwards compatibility
        con.execute(
            "INSERT OR IGNORE INTO currencies (provider_id, currency_code, currency_type, display, source) VALUES (?, ?, 'FIAT', 1, ?)",
            (provider_id, code, source)
        )

    # Write CRYPTO currencies to crypto_currencies table
    for code in currencies.get("CRYPTO", []):
        con.execute(
            "INSERT OR IGNORE INTO crypto_currencies (provider_id, currency_code, display, source) VALUES (?, ?, 1, ?)",
            (provider_id, code, source)
        )
        # Also write to legacy table for backwards compatibility
        con.execute(
            "INSERT OR IGNORE INTO currencies (provider_id, currency_code, currency_type, display, source) VALUES (?, ?, 'CRYPTO', 0, ?)",
            (provider_id, code, source)
        )


def log_sync(con: sqlite3.Connection, provider_name: str, sheet_id: str, status: str, message: str, restrictions_count: int = 0, currencies_count: int = 0):
    """Log sync result."""
    con.execute(
        "INSERT INTO sync_log (provider_name, sheet_id, status, message, restrictions_count, currencies_count) VALUES (?, ?, ?, ?, ?, ?)",
        (provider_name, sheet_id, status, message, restrictions_count, currencies_count)
    )


def sync_all():
    """Main sync function - scans Drive folder and imports to STAGING database."""
    print("🔄 Starting Google Sheets sync to STAGING database...\n")
    print("⚠️  This will NOT modify your main database.")
    print("   After sync, use --preview to review and --promote to apply.\n")

    folder_id = get_folder_id()
    creds = get_credentials()

    # Build API clients
    drive_service = build("drive", "v3", credentials=creds)
    sheets_service = build("sheets", "v4", credentials=creds)

    # Initialize fresh staging database
    init_staging_db()

    # Get provider folders (subfolders)
    print(f"\n📁 Scanning folder: {folder_id}")
    provider_folders = list_provider_folders(drive_service, folder_id)
    print(f"   Found {len(provider_folders)} provider subfolders")

    # Also check for spreadsheets directly in the root folder (flat structure)
    root_spreadsheets = list_spreadsheets_in_folder(drive_service, folder_id)
    print(f"   Found {len(root_spreadsheets)} spreadsheets in root folder\n")

    if not provider_folders and not root_spreadsheets:
        print("⚠️ No provider folders or spreadsheets found. Check folder sharing permissions.")
        return

    # Process each provider - write to STAGING database
    con = sqlite3.connect(STAGING_DB_PATH)
    con.execute("PRAGMA foreign_keys = ON;")

    stats = {
        "new": 0,
        "updated": 0,
        "unchanged": 0,
        "failed": 0
    }

    for folder in provider_folders:
        folder_name = folder["name"]
        folder_id_inner = folder["id"]

        print(f"📂 {folder_name}")

        # Find main data sheet
        sheet_file = find_main_data_sheet(drive_service, folder_id_inner)
        if not sheet_file:
            print(f"   ⚠️ No spreadsheet found")
            log_sync(con, folder_name, "", "FAILED", "No spreadsheet found")
            stats["failed"] += 1
            continue

        sheet_id = sheet_file["id"]
        sheet_name = sheet_file["name"]
        file_mime = sheet_file.get("mimeType", "")
        # Explicit check: native Google Sheets have this exact mimeType
        is_native_sheet = file_mime == "application/vnd.google-apps.spreadsheet"
        is_excel = not is_native_sheet and ("openxmlformats" in file_mime or sheet_name.endswith(".xlsx"))
        print(f"   📊 Found: {sheet_name} ({'Excel' if is_excel else 'Google Sheet'}) [mime: {file_mime}]")

        try:
            # Process spreadsheet (with automatic fallback if Excel download fails)
            restrictions, currencies, currency_mode, games = process_spreadsheet_data(
                drive_service, sheets_service, sheet_id, sheet_name, is_excel
            )

            # Check if provider exists and get ID
            provider_id, is_new = upsert_provider(con, folder_name, sheet_id, currency_mode)

            # Compute hash of new data
            new_hash = compute_data_hash(restrictions, currencies, games)

            # Check if data actually changed (skip update if identical)
            if not is_new:
                existing_hash = get_existing_data_hash(con, provider_id)
                if existing_hash == new_hash:
                    print(f"   ⏭️ No changes detected (ID: {provider_id})")
                    log_sync(con, folder_name, sheet_id, "SUCCESS", "No changes", 0, 0)
                    stats["unchanged"] += 1
                    continue

            # Data changed or new provider - update database
            replace_restrictions(con, provider_id, restrictions, f"google:{sheet_id}")
            replace_currencies(con, provider_id, currencies, f"google:{sheet_id}")
            games_inserted = replace_games(con, games, f"google:{sheet_id}", default_provider_id=provider_id)

            total_restrictions = len(restrictions["BLOCKED"]) + len(restrictions["CONDITIONAL"]) + len(restrictions["REGULATED"])
            total_currencies = len(currencies["FIAT"]) + len(currencies["CRYPTO"])

            if is_new:
                log_sync(con, folder_name, sheet_id, "SUCCESS", "New provider added", total_restrictions, total_currencies)
                print(f"   ✅ NEW provider added (ID: {provider_id}), {games_inserted} games")
                stats["new"] += 1
            else:
                log_sync(con, folder_name, sheet_id, "SUCCESS", "Data updated", total_restrictions, total_currencies)
                print(f"   ✅ Updated (ID: {provider_id}), {games_inserted} games")
                stats["updated"] += 1

        except Exception as e:
            print(f"   ❌ Error: {e}")
            log_sync(con, folder_name, sheet_id, "FAILED", str(e))
            stats["failed"] += 1

    # Also process spreadsheets directly in root folder (flat structure)
    # Extract provider name from spreadsheet name (e.g., "Provider Name Main DATA" -> "Provider Name")
    for sheet_file in root_spreadsheets:
        sheet_name = sheet_file["name"]
        sheet_id = sheet_file["id"]
        file_mime = sheet_file.get("mimeType", "")
        # Explicit check: native Google Sheets have this exact mimeType
        is_native_sheet = file_mime == "application/vnd.google-apps.spreadsheet"
        is_excel = not is_native_sheet and ("openxmlformats" in file_mime or sheet_name.endswith(".xlsx"))

        # Extract provider name from filename (remove "Main DATA" suffix and .xlsx extension)
        provider_name = sheet_name
        if provider_name.lower().endswith(".xlsx"):
            provider_name = provider_name[:-5]  # Remove .xlsx
        for suffix in ["main data", "main", "data"]:
            if provider_name.lower().endswith(suffix):
                provider_name = provider_name[:-(len(suffix))].strip()
                break

        print(f"📊 {provider_name} (from: {sheet_name}, {'Excel' if is_excel else 'Google Sheet'}) [mime: {file_mime}]")

        try:
            # Process spreadsheet (with automatic fallback if Excel download fails)
            restrictions, currencies, currency_mode, games = process_spreadsheet_data(
                drive_service, sheets_service, sheet_id, sheet_name, is_excel
            )

            # Upsert provider
            provider_id, is_new = upsert_provider(con, provider_name, sheet_id, currency_mode)
            new_hash = compute_data_hash(restrictions, currencies, games)

            if not is_new:
                existing_hash = get_existing_data_hash(con, provider_id)
                if existing_hash == new_hash:
                    print(f"   ⏭️ No changes detected (ID: {provider_id})")
                    log_sync(con, provider_name, sheet_id, "SUCCESS", "No changes", 0, 0)
                    stats["unchanged"] += 1
                    continue

            replace_restrictions(con, provider_id, restrictions, f"google:{sheet_id}")
            replace_currencies(con, provider_id, currencies, f"google:{sheet_id}")
            games_inserted = replace_games(con, games, f"google:{sheet_id}", default_provider_id=provider_id)

            total_restrictions = len(restrictions["BLOCKED"]) + len(restrictions["CONDITIONAL"]) + len(restrictions["REGULATED"])
            total_currencies = len(currencies["FIAT"]) + len(currencies["CRYPTO"])

            if is_new:
                log_sync(con, provider_name, sheet_id, "SUCCESS", "New provider added", total_restrictions, total_currencies)
                print(f"   ✅ NEW provider added (ID: {provider_id}), {games_inserted} games")
                stats["new"] += 1
            else:
                log_sync(con, provider_name, sheet_id, "SUCCESS", "Data updated", total_restrictions, total_currencies)
                print(f"   ✅ Updated (ID: {provider_id}), {games_inserted} games")
                stats["updated"] += 1

        except Exception as e:
            print(f"   ❌ Error: {e}")
            log_sync(con, provider_name, sheet_id, "FAILED", str(e))
            stats["failed"] += 1

    con.commit()
    con.close()

    print(f"\n{'='*50}")
    print(f"📊 Sync Summary (STAGING):")
    print(f"   🆕 New providers: {stats['new']}")
    print(f"   🔄 Updated: {stats['updated']}")
    print(f"   ⏭️ Unchanged: {stats['unchanged']}")
    print(f"   ❌ Failed: {stats['failed']}")
    print(f"\n📍 Data saved to: {STAGING_DB_PATH}")
    print(f"\n👉 Next steps:")
    print(f"   1. Preview:  python google_sync.py --preview")
    print(f"   2. Compare:  python google_sync.py --compare")
    print(f"   3. Promote:  python google_sync.py --promote")


def main():
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(
        description="Sync game providers from Google Sheets (SAFE - uses staging DB)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
  1. python google_sync.py           # Sync to STAGING (doesn't touch main DB)
  2. python google_sync.py --preview # Review what's in staging
  3. python google_sync.py --compare # Compare staging vs main
  4. python google_sync.py --promote # Apply staging to main DB (creates backup first)

Other commands:
  python google_sync.py --list       # List available backups
  python google_sync.py --restore    # Restore main DB from backup
        """
    )

    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available backups"
    )

    parser.add_argument(
        "--preview", "-p",
        action="store_true",
        help="Preview data in staging database"
    )

    parser.add_argument(
        "--compare", "-c",
        action="store_true",
        help="Compare staging database with main database"
    )

    parser.add_argument(
        "--promote",
        action="store_true",
        help="Promote staging database to main (creates backup first)"
    )

    parser.add_argument(
        "--restore", "-r",
        nargs="?",
        const="latest",
        metavar="BACKUP_FILE",
        help="Restore main DB from backup (latest if no file specified)"
    )

    args = parser.parse_args()

    if args.list:
        backups = list_backups()
        if not backups:
            print("📭 No backups found.")
        else:
            print(f"📦 Available backups ({len(backups)}):\n")
            for i, b in enumerate(backups):
                size = b.stat().st_size / 1024
                mtime = datetime.fromtimestamp(b.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                marker = " (latest)" if i == 0 else ""
                print(f"  {i+1}. {b.name} - {size:.1f} KB - {mtime}{marker}")
        return

    if args.preview:
        preview_staging()
        return

    if args.compare:
        compare_staging_to_main()
        return

    if args.promote:
        print("🚀 Promoting staging to main database...")
        if promote_staging():
            print("\n✅ Done! Main database updated.")
            print("   Old data backed up in db/backups/")
        return

    if args.restore:
        if args.restore == "latest":
            restore_from_backup()
        else:
            backup_path = BACKUP_DIR / args.restore
            if not backup_path.exists():
                backup_path = Path(args.restore)
            restore_from_backup(backup_path)
        return

    # Default: run sync to staging
    sync_all()


if __name__ == "__main__":
    main()
