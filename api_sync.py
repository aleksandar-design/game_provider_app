"""
API Sync Module
Fetches providers and games from external API, maps to existing DB providers.
"""
from __future__ import annotations
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import requests

# Only import streamlit if available (not needed for CLI)
try:
    import streamlit as st
except ImportError:
    st = None

DB_PATH = Path("db") / "database.sqlite"
SECRETS_PATH = Path(".streamlit") / "secrets.toml"
LOG_DIR = Path("logs")

# ============================================
# Logging Setup
# ============================================
def setup_logging() -> logging.Logger:
    """Configure logging for API sync."""
    LOG_DIR.mkdir(exist_ok=True)

    # Create logger
    logger = logging.getLogger("api_sync")
    logger.setLevel(logging.DEBUG)

    # Clear existing handlers
    logger.handlers.clear()

    # File handler - detailed logs with timestamp in filename
    log_file = LOG_DIR / f"sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_format)

    # Console handler - info and above
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S")
    console_handler.setFormatter(console_format)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

# Initialize logger
log = setup_logging()

# ============================================
# Configuration
# ============================================
def load_secrets_toml():
    """Load secrets from .streamlit/secrets.toml file."""
    if not SECRETS_PATH.exists():
        return {}
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    with open(SECRETS_PATH, "rb") as f:
        return tomllib.load(f)


def get_api_config():
    """Get API configuration from secrets.toml or Streamlit secrets."""
    # Try Streamlit secrets first (when running in Streamlit app)
    try:
        if st is not None and hasattr(st, 'secrets') and "API_BASE_URL" in st.secrets:
            return {
                "base_url": st.secrets["API_BASE_URL"],
                "operator_id": st.secrets.get("X_OPERATOR_ID", ""),
                "auth_key": st.secrets.get("X_AUTHORIZATION", ""),
            }
    except Exception:
        pass

    # Fall back to reading secrets.toml directly (for CLI usage)
    secrets = load_secrets_toml()
    return {
        "base_url": secrets.get("API_BASE_URL", ""),
        "operator_id": secrets.get("X_OPERATOR_ID", ""),
        "auth_key": secrets.get("X_AUTHORIZATION", ""),
    }

# ============================================
# Provider Name Mapping
# Maps API provider names to DB provider names
# ============================================
PROVIDER_MAPPING = {
    # Pragmatic Play variants
    "Pragmatic Play Slots": "Pragmatic Play",
    "Pragmatic Play Live": "Pragmatic Play",
    "Pragmatic Play Virtual": "Pragmatic Play",
    "Pragmatic Play Scratch": "Pragmatic Play",

    # Platipus variants
    "Platipus": "Platipus",
    "Platipus Live": "Platipus",

    # Skywind variants
    "Skywind": "Skywind",
    "Skywind-live": "Skywind",

    # PopOK variants
    "PopOK": "PopOK",
    "PopOK Live": "PopOK",

    # MicroGaming variants
    "MicroGaming": "Microgaming",
    "MicroGaming Live": "Microgaming",

    # Amusnet variants
    "Amusnet": "Amusnet",
    "Amusnet Live": "Amusnet",

    # PatePlay variants
    "PatePlay": "PatePlay",
    "PatePlay Live": "PatePlay",

    # Iconic21 variants
    "Iconic21": "Iconic21",
    "Iconic21 Live": "Iconic21",

    # Jacktop variants
    "Jacktop": "Jacktop",
    "Jacktop Live": "Jacktop",

    # 7Mojos variants (multiple spellings)
    "7Mojos Live": "7 mojos",
    "7Mojos Slots": "7 mojos",
    "7-Mojos Live": "7 mojos",
    "7-Mojos": "7 mojos",

    # TVBet
    "TVBet Live": "TVBet",

    # Yeebet
    "Yeebet Live": "YeeBet Live",

    # Name normalization (API name -> DB name)
    "Vivo": "VIVO",
    "GlobalBet": "GoldenRace",  # Update if different
    "Spribe": "Spribe",
    "Netgame": "Netgame",
    "Macaw": "Macaw",
    "BitVille": "Bitville",
    "Evoplay": "Evoplay",
    "Ezugi": "Ezugi",
    "Booming": "Booming",
    "Caleta Gaming": "Caleta Gaming",
    "KAGaming": "KA GAMING",
    "Habanero": "Habanero",
    "Mancala Gaming": "Mancala Gaming",
    "Golden Race": "GoldenRace",
    "BetOnGames": "Bet On Games",
    "7777 Gaming": "7777 Gaming",
    "Absolute Live Gaming": "Absolute",
    "Religa": "Religa",
    "Altente": "Altente",
    "Endorphina": "Endorphina",
    "OneTouch": "One Touch",
    "BFGames": "BFGames",
    "Spinomenal": "Spinomenal",
    "Adlunam": "AdLunam",
    "ArmadilloStudios": "Armadillo Studios",
    "FlipLuck": "FlipLuck",
    "Irondog": "Iron Dog Studios",
    "JVL": "JVL",
    "ProspectGaming": "Prospect Gaming",
    "Spearhead": "Spearhead",
    "1x2Gaming": "1x2 Gaming",
    "Fils": "Fils",
    "LiWGames": "LIWGames",
    "Smartsoft": "Smartsoft",
    "PGSoft": "PG SOFT",
    "PlatinGaming": "PlatinGaming",
    "Galaxsys": "Galaxsys",
    "EAGaming": "EAGaming",
    "3Oaks": "3Oaks",
    "Play-son": "Playson",
    "TurboGames": "Turbo Games",
    "Novomatic": "Novomatic",
    "CTInteractive": "CT Interactive",
    "Gamzix": "Gamzix",
    "RedRake": "Red Rake",
    "Aviatrix": "Aviatrix",
    "AmigoGaming": "Amigo Gaming",
    "BigPot": "Bigpot",
    "EvolutionLive": "Evolution Live",
    "RedTiger": "Red Tiger",
    "Netent": "Net Ent",
    "NoLimitCity": "NoLimit City",
    "Big Time Gaming": "Big Time Gaming",
    "Pascal Gaming": "Pascal Gaming",
    "Creedroomz": "Creedz",
    "Hacksaw": "Hacksaw Gaming",
    "Backseat Gaming": "Backseat Gaming",
    "BullShark Games": "BullShark Games",
    "Hacksaw-OpenRGS": "Hacksaw Gaming",
    "EGT Digital": "EGT Digital",
    "RubyPlay": "RubyPlay",
    "LiveGames": "LiveGames",
    "Fazi": "Fazi",
    "SAGaming": "SA Gaming",
    "OneGame": "OneGame",
    "AirDice": "AirDice",
    "BitBlox": "BitBlox",
    "BetSoft": "Betsoft",
    "Wazdan": "Wazdan",
    "Yggdrasil": "Yggdrasil",
    "TaDa Gaming": "TaDa Gaming",
    "Apparat Gaming": "Apparat",
    "BallyWulff": "BW Gaming",
    "BarbaraBang": "Barbarabang",
    "100HP Gaming": "100HP Gaming",
    "OnlyPlay": "OnlyPlay",
    "Bgaming": "BGaming",
    "EezeCasino": "Eeze Casino",
    "Dreamplay": "DreamPlay",
    "PopiPlay": "PopiPlay",
    "YOriginal Games": "YOriginal Games",
    "SimplePlay": "Simple Play",
    "Beon": "Beon",
    "ShadyLady": "Shady Lady",
    "WickedGames": "Wicked Games",
    "Formula Spin": "Formula Spin",
    "Gamebeat": "GameBeat",
    "Phoenix7": "Phoenix7",
    "PixmoveGames": "Pixmove Games",
    "Clawbuster": "Clawbuster",
    "Winfinity": "Winfinity",
    "Pigaboom": "Pig A Boom",
    "InOut": "InOut",
    "AbraCadabra": "AbraCadabra",
    "AvatarUX": "AvatarUX",
    "Mascot Gaming": "Mascot Gaming",
    "SpinLogic": "SpinLogic (RTG Slots)",
    "MaracashGames": "Maracash Games",
    "Hot Dog": "HotDog Gaming",
    "Ela Games": "Ela Games",
    "Iconix Interactive": "Iconix",
    "ImagineLive": "ImagineLive",
    "Live88": "Live88",
    "Winspinity": "Winspinity",
}

def normalize_provider_name(api_name: str) -> str:
    """Map API provider name to DB provider name."""
    return PROVIDER_MAPPING.get(api_name, api_name)


# ============================================
# Database
# ============================================
def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON;")
    return con


def get_provider_id_by_name(provider_name: str) -> int | None:
    """Get provider_id from DB by name. Returns None if not found."""
    with db() as con:
        cur = con.execute(
            "SELECT provider_id FROM providers WHERE provider_name = ?",
            (provider_name,)
        )
        row = cur.fetchone()
        return row[0] if row else None


def upsert_provider(provider_name: str) -> int:
    """
    Insert provider if not exists, return provider_id.
    Does NOT touch restrictions or currencies.
    """
    with db() as con:
        cur = con.execute(
            "SELECT provider_id FROM providers WHERE provider_name = ?",
            (provider_name,)
        )
        row = cur.fetchone()

        if row:
            return row[0]
        else:
            cur = con.execute(
                """INSERT INTO providers (provider_name, currency_mode, status)
                   VALUES (?, 'ALL_FIAT', 'ACTIVE')""",
                (provider_name,)
            )
            con.commit()
            return cur.lastrowid


def replace_games_for_provider(provider_id: int, games: list[dict], source: str = "api_sync") -> dict:
    """
    Replace all games for a provider with new data from API.
    Returns dict with old_count and new_count.
    """
    import json

    with db() as con:
        # Count existing games before deleting
        cur = con.execute(
            "SELECT COUNT(*) FROM games WHERE provider_id = ? AND source = ?",
            (provider_id, source)
        )
        old_count = cur.fetchone()[0]

        # Delete existing games from this source
        con.execute(
            "DELETE FROM games WHERE provider_id = ? AND source = ?",
            (provider_id, source)
        )

        # Insert new games
        for g in games:
            details = g.get("details", {})
            thumbnails = details.get("thumbnails", {})
            # Pick a main thumbnail (prefer JPG version, then 440x590)
            thumbnail = thumbnails.get("440x590-jpg") or thumbnails.get("440x590") or thumbnails.get("300x300") or next(iter(thumbnails.values()), None) if thumbnails else None

            title = g.get("title") or "Unknown"
            con.execute(
                """INSERT INTO games
                   (provider_id, game_id, game_title, title, platform, game_type, subtype,
                    enabled, fun_mode, rtp, volatility, features, themes, tags,
                    thumbnail, api_provider, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    provider_id,
                    g.get("id"),
                    title,  # game_title (old schema, NOT NULL)
                    title,  # title (new schema)
                    g.get("platform"),
                    g.get("type"),
                    g.get("subtype"),
                    g.get("enabled", 1),
                    g.get("fun_mode", 0),
                    details.get("rtp"),
                    details.get("volatility"),
                    json.dumps(details.get("features", [])),
                    json.dumps(details.get("themes", [])),
                    json.dumps(details.get("tags", [])),
                    thumbnail,
                    g.get("provider"),
                    source
                )
            )
        con.commit()

        return {"old_count": old_count, "new_count": len(games)}


# ============================================
# API Calls
# ============================================
def get_headers() -> dict:
    """Build request headers with API credentials."""
    config = get_api_config()
    return {
        "X-Operator-Id": config["operator_id"],
        "X-Authorization": config["auth_key"],
        "Content-Type": "application/json"
    }


def fetch_providers() -> list[str]:
    """
    Fetch all providers from API.
    Returns list of provider names.
    """
    config = get_api_config()
    url = f"{config['base_url']}/api/generic/games/v2/providers"

    log.debug(f"GET {url}")
    response = requests.get(url, headers=get_headers())
    log.debug(f"Response: {response.status_code}")
    response.raise_for_status()

    data = response.json()
    # Response format: {"status": "OK", "data": ["Provider1", ...]}
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return data


def fetch_games_for_provider(provider_name: str) -> list[dict]:
    """
    Fetch games for a specific provider.
    Returns list of game dicts.
    """
    config = get_api_config()
    url = f"{config['base_url']}/api/generic/games/v2/list"
    params = {"providers": provider_name}

    log.debug(f"GET {url}?providers={provider_name}")
    response = requests.get(url, headers=get_headers(), params=params)
    log.debug(f"Response: {response.status_code}")
    response.raise_for_status()

    data = response.json()
    # Response format: {"status": "OK", "data": [...]}
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return data


# ============================================
# Main Sync Logic
# ============================================
def sync_all() -> dict:
    """
    Main sync function:
    1. Fetch all providers from API
    2. Map API provider names to DB provider names
    3. For each unique DB provider, fetch games from all API variants
    4. Upsert provider and replace games

    Returns dict with sync stats.
    """
    start_time = datetime.now()
    log.info("=" * 60)
    log.info("API SYNC STARTED")
    log.info("=" * 60)

    # Check config
    config = get_api_config()
    if not config["base_url"]:
        log.error("API_BASE_URL not configured in secrets.toml!")
        raise ValueError("API_BASE_URL not configured")
    log.info(f"API Base URL: {config['base_url']}")
    log.debug(f"Operator ID: {config['operator_id'][:4]}***" if config['operator_id'] else "Operator ID: NOT SET")

    # Fetch all API providers
    log.info("Fetching providers from API...")
    try:
        all_api_providers = fetch_providers()
        log.info(f"Found {len(all_api_providers)} API providers")
        log.debug(f"Providers: {', '.join(all_api_providers[:10])}{'...' if len(all_api_providers) > 10 else ''}")
    except requests.RequestException as e:
        log.error(f"Failed to fetch providers: {e}")
        raise

    # Group API providers by their DB mapping
    db_provider_groups: dict[str, list[str]] = {}
    for api_name in all_api_providers:
        db_name = normalize_provider_name(api_name)
        if db_name not in db_provider_groups:
            db_provider_groups[db_name] = []
        db_provider_groups[db_name].append(api_name)

    log.info(f"Mapped to {len(db_provider_groups)} unique DB providers")

    # Log provider mappings with multiple variants
    multi_variant = {k: v for k, v in db_provider_groups.items() if len(v) > 1}
    if multi_variant:
        log.info(f"Providers with multiple API variants: {len(multi_variant)}")
        for db_name, variants in multi_variant.items():
            log.debug(f"  {db_name} <- {variants}")

    # Process each DB provider
    total_providers = 0
    total_games = 0
    new_providers = []
    failed_providers = []
    provider_stats = []

    for idx, (db_name, api_variants) in enumerate(db_provider_groups.items(), 1):
        progress = f"[{idx}/{len(db_provider_groups)}]"
        log.info(f"{progress} Processing: {db_name}")

        # Upsert provider (preserves restrictions/currencies)
        existing_id = get_provider_id_by_name(db_name)
        provider_id = upsert_provider(db_name)
        if existing_id is None:
            new_providers.append(db_name)
            log.info(f"  NEW provider created (ID: {provider_id})")
        else:
            log.debug(f"  Existing provider (ID: {provider_id})")

        # Fetch games from all API variants
        all_games = []
        variant_errors = []
        for api_name in api_variants:
            try:
                games = fetch_games_for_provider(api_name)
                log.info(f"    {api_name}: {len(games)} games")
                all_games.extend(games)
            except requests.RequestException as e:
                log.warning(f"    {api_name}: FAILED - {e}")
                variant_errors.append((api_name, str(e)))

        # Replace games for this provider
        if all_games:
            result = replace_games_for_provider(provider_id, all_games)
            if result["old_count"] > 0:
                log.info(f"  -> Replaced {result['old_count']} games with {result['new_count']} games")
            else:
                log.info(f"  -> Added {result['new_count']} games (new)")
            total_games += len(all_games)
            provider_stats.append((db_name, len(all_games), result["old_count"]))
        elif variant_errors:
            failed_providers.append((db_name, variant_errors))
            log.warning(f"  -> No games synced (all variants failed)")
        else:
            log.info(f"  -> No games found")
            provider_stats.append((db_name, 0, 0))

        total_providers += 1

    # Identify providers with 0 games
    zero_game_providers = [name for name, new_count, old_count in provider_stats if new_count == 0]

    # Calculate totals
    total_replaced = sum(old for _, _, old in provider_stats if old > 0)
    providers_updated = sum(1 for _, new, old in provider_stats if old > 0 and new > 0)

    # Summary
    elapsed = datetime.now() - start_time
    log.info("")
    log.info("=" * 60)
    log.info("SYNC COMPLETE")
    log.info("=" * 60)
    log.info(f"Duration: {elapsed.total_seconds():.1f} seconds")
    log.info(f"Providers processed: {total_providers}")
    log.info(f"Total games synced: {total_games}")
    log.info(f"Games replaced: {total_replaced}")

    if new_providers:
        log.info("")
        log.info(f"NEW PROVIDERS INSERTED ({len(new_providers)}):")
        for p in new_providers:
            # Find game count for this provider
            games_count = next((c for n, c, _ in provider_stats if n == p), 0)
            log.info(f"  + {p} ({games_count} games)")

    if providers_updated:
        log.info("")
        log.info(f"PROVIDERS UPDATED ({providers_updated}):")
        for name, new_count, old_count in provider_stats:
            if old_count > 0 and new_count > 0:
                diff = new_count - old_count
                diff_str = f"+{diff}" if diff > 0 else str(diff) if diff < 0 else "="
                log.info(f"  ~ {name}: {old_count} -> {new_count} ({diff_str})")

    if zero_game_providers:
        log.info("")
        log.info(f"PROVIDERS WITH NO GAMES ({len(zero_game_providers)}):")
        for p in zero_game_providers:
            log.info(f"  - {p}")

    if failed_providers:
        log.info("")
        log.warning(f"PROVIDERS WITH ERRORS ({len(failed_providers)}):")
        for p, errors in failed_providers:
            log.warning(f"  ! {p}")
            for api_name, err in errors:
                log.warning(f"      {api_name}: {err}")

    # All providers by game count
    log.info("")
    log.info("GAMES PER PROVIDER:")
    log.info("-" * 50)
    log.info(f"  {'NEW':>5} | {'OLD':>5} | PROVIDER")
    log.info("-" * 50)
    for name, new_count, old_count in sorted(provider_stats, key=lambda x: -x[1]):
        if new_count > 0 or old_count > 0:
            log.info(f"  {new_count:5d} | {old_count:5d} | {name}")
    log.info("-" * 50)
    log.info(f"  {total_games:5d} | {total_replaced:5d} | TOTAL")

    log.info("")
    log.info("=" * 60)

    return {
        "providers": total_providers,
        "games": total_games,
        "new_providers": len(new_providers),
        "updated_providers": providers_updated,
        "failed": len(failed_providers),
        "zero_games": len(zero_game_providers),
        "games_replaced": total_replaced,
        "duration_seconds": elapsed.total_seconds()
    }


# ============================================
# CLI
# ============================================
if __name__ == "__main__":
    sync_all()
