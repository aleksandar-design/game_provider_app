import os
import io
import json
import re
import sqlite3
import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st
from openai import OpenAI

DB_PATH = Path("db") / "database.sqlite"

# =================================================
# Theme configuration
# =================================================
def get_theme():
    """Get current theme from session state or query params."""
    # First check session state (most reliable during interactions)
    if "theme" in st.session_state:
        return st.session_state["theme"]
    # Fall back to query params (for URL persistence)
    theme = st.query_params.get("theme", "dark")
    st.session_state["theme"] = theme
    return theme

def set_theme(theme: str):
    """Set theme in both session state and query params."""
    st.session_state["theme"] = theme
    st.query_params["theme"] = theme

# Theme color palettes - based on Figma design
THEMES = {
    "dark": {
        # Core colors from Figma theme.css
        "bg_primary": "#0F172A",
        "bg_secondary": "#16233B",
        "bg_card": "#111C2F",
        "bg_hover": "#1C3D66",
        "border": "#1E293B",
        "input_bg": "#1E293B",
        "text_primary": "#E5E7EB",
        "text_secondary": "#9CA3AF",
        "text_muted": "#9CA3AF",
        "primary": "#3B9CFF",
        "primary_foreground": "#FFFFFF",
        # Tags
        "tag_bg": "#16233B",
        "tag_blocked_bg": "#7F1D1D",
        "tag_blocked_text": "#FB7185",
        "tag_conditional_bg": "#78350F",
        "tag_conditional_text": "#FACC15",
        "tag_regulated_bg": "#1C3D66",
        "tag_regulated_text": "#67E8F9",
        "tag_fiat_bg": "#064E3B",
        "tag_fiat_text": "#4ADE80",
        "tag_crypto_bg": "#1C3D66",
        "tag_crypto_text": "#A78BFA",
        # Country tags
        "country_tag_bg": "#111C2F",
        "country_tag_border": "#4ADE80",
        # Currency buttons
        "currency_fiat_bg": "#064E3B",
        "currency_fiat_text": "#4ADE80",
        "currency_fiat_border": "#4ADE80",
        "currency_crypto_bg": "#1C3D66",
        "currency_crypto_text": "#A78BFA",
        "currency_crypto_border": "#A78BFA",
        # Stats
        "stat_icon_providers_bg": "#1C3D66",
        "stat_icon_currencies_bg": "#422006",
        "shadow": "rgba(0,0,0,0.4)",
        # Chart colors
        "chart_blue": "#3B9CFF",
        "chart_green": "#4ADE80",
        "chart_red": "#FB7185",
        "chart_yellow": "#FACC15",
    },
    "light": {
        # Core colors - cleaner light mode
        "bg_primary": "#FFFFFF",
        "bg_secondary": "#F3F4F6",
        "bg_card": "#F3F4F6",
        "bg_hover": "#EEF3FA",
        "border": "#E2E8F0",
        "input_bg": "#FFFFFF",
        "text_primary": "#1E293B",
        "text_secondary": "#64748B",
        "text_muted": "#64748B",
        "primary": "#2563EB",
        "primary_foreground": "#FFFFFF",
        # Tags - better contrast
        "tag_bg": "#F1F5F9",
        "tag_blocked_bg": "#FEE2E2",
        "tag_blocked_text": "#DC2626",
        "tag_conditional_bg": "#FEF3C7",
        "tag_conditional_text": "#B45309",
        "tag_regulated_bg": "#DBEAFE",
        "tag_regulated_text": "#1D4ED8",
        "tag_fiat_bg": "#D1FAE5",
        "tag_fiat_text": "#047857",
        "tag_crypto_bg": "#EDE9FE",
        "tag_crypto_text": "#6D28D9",
        # Country tags
        "country_tag_bg": "#FFFFFF",
        "country_tag_border": "#10B981",
        # Currency buttons
        "currency_fiat_bg": "#ECFDF5",
        "currency_fiat_text": "#047857",
        "currency_fiat_border": "#10B981",
        "currency_crypto_bg": "#F5F3FF",
        "currency_crypto_text": "#6D28D9",
        "currency_crypto_border": "#8B5CF6",
        # Stats
        "stat_icon_providers_bg": "#DBEAFE",
        "stat_icon_currencies_bg": "#FEF3C7",
        "shadow": "rgba(0,0,0,0.1)",
        # Chart colors
        "chart_blue": "#2563EB",
        "chart_green": "#10B981",
        "chart_red": "#DC2626",
        "chart_yellow": "#F59E0B",
    }
}

# =================================================
# Page config + styling
# =================================================
st.set_page_config(page_title="Game Providers", layout="wide", initial_sidebar_state="collapsed")

# Get current theme
current_theme = get_theme()
t = THEMES[current_theme]

st.markdown(
    f"""
    <style>
      /* Main app background */
      .stApp {{
        background: {t["bg_primary"]};
      }}

      /* Hide default header */
      header[data-testid="stHeader"] {{ display: none; }}
      .block-container {{ padding-top: 1rem; padding-bottom: 2rem; }}

      /* Custom header - Figma style */
      .logo-container {{
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.5rem 0;
      }}
      .logo-icon {{
        width: 44px;
        height: 44px;
        background: linear-gradient(135deg, {t["primary"]} 0%, #1E40AF 100%);
        border-radius: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-weight: 600;
        font-size: 1.1rem;
        box-shadow: 0 4px 12px {t["primary"]}40;
      }}
      .logo-text {{
        font-size: 1.25rem;
        font-weight: 600;
        color: {t["text_primary"]};
        letter-spacing: 0.02em;
      }}
      .logo-subtitle {{
        font-size: 0.7rem;
        color: {t["text_secondary"]};
        letter-spacing: 0.1em;
        text-transform: uppercase;
        margin-top: 0.1rem;
      }}
      .header-actions {{
        display: flex;
        gap: 0.5rem;
        align-items: center;
      }}

      /* Filter container - style bordered containers */
      [data-testid="stVerticalBlockBorderWrapper"] {{
        border-radius: 16px !important;
        margin-bottom: 1rem !important;
      }}
      /* Vertical gaps inside filter container */
      [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] {{
        gap: 0.75rem !important;
      }}
      [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] {{
        gap: 0.5rem !important;
      }}
      .filter-title {{
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 1rem;
        font-weight: 600;
        color: {t["text_primary"]};
        margin-bottom: 0.5rem;
      }}
      .filter-title svg {{
        color: {t["primary"]};
      }}

      /* Stats cards - Figma style with gradient backgrounds */
      .stats-container {{
        display: flex;
        gap: 1rem;
        margin-bottom: 1.5rem;
      }}
      .stat-card {{
        flex: 1;
        background: {t["bg_card"]};
        border: 1px solid {t["border"]};
        border-radius: 16px;
        padding: 1.25rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        transition: transform 0.2s, box-shadow 0.2s;
        box-shadow: 0 1px 3px {t["shadow"]};
      }}
      .stat-card:hover {{
        transform: translateY(-2px);
        box-shadow: 0 8px 24px {t["shadow"]};
      }}
      .stat-label {{
        font-size: 0.875rem;
        color: {t["text_secondary"]};
        margin-bottom: 0.25rem;
        font-weight: 500;
      }}
      .stat-value {{
        font-size: 2rem;
        font-weight: 700;
        color: {t["text_primary"]};
      }}
      .stat-icon {{
        width: 52px;
        height: 52px;
        border-radius: 14px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.5rem;
      }}
      .stat-icon.providers {{ background: {t["stat_icon_providers_bg"]}; color: {t["primary"]}; }}
      .stat-icon.currencies {{ background: {t["stat_icon_currencies_bg"]}; color: {t["chart_yellow"]}; }}

      /* Provider title */
      .providers-title {{
        font-size: 1.125rem;
        font-weight: 600;
        color: {t["text_primary"]};
        margin-bottom: 0.75rem;
      }}
      .tags-container {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
      }}
      .tag {{
        display: inline-block;
        padding: 0.35rem 0.85rem;
        background: {t["tag_bg"]};
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 500;
        color: {t["text_muted"]};
      }}
      .tag.blocked {{ background: {t["tag_blocked_bg"]}; color: {t["tag_blocked_text"]}; }}
      .tag.conditional {{ background: {t["tag_conditional_bg"]}; color: {t["tag_conditional_text"]}; }}
      .tag.regulated {{ background: {t["tag_regulated_bg"]}; color: {t["tag_regulated_text"]}; }}
      .tag.fiat {{ background: {t["tag_fiat_bg"]}; color: {t["tag_fiat_text"]}; }}
      .tag.crypto {{ background: {t["tag_crypto_bg"]}; color: {t["tag_crypto_text"]}; }}

      /* Country tags */
      .country-tags {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
        margin-bottom: 1rem;
      }}
      .country-tag {{
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.4rem 0.85rem;
        border: 1.5px solid {t["country_tag_border"]};
        border-radius: 20px;
        font-size: 0.8rem;
        color: {t["text_primary"]};
        background: {t["country_tag_bg"]};
        transition: all 0.2s;
      }}
      .country-tag:hover {{
        background: {t["bg_hover"]};
      }}
      .country-tag .iso {{
        background: {t["chart_green"]};
        color: white;
        padding: 0.15rem 0.4rem;
        border-radius: 4px;
        font-size: 0.7rem;
        font-weight: 600;
      }}

      /* Currency buttons grid - Figma style */
      .currency-grid {{
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 0.75rem;
        margin-bottom: 1rem;
      }}
      .currency-btn {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.5rem;
        padding: 0.75rem 1rem;
        border-radius: 25px;
        font-size: 0.85rem;
        font-weight: 500;
        text-align: center;
        transition: all 0.2s;
      }}
      .currency-btn:hover {{
        transform: translateY(-1px);
      }}
      .currency-btn.fiat {{
        background: {t["currency_fiat_bg"]};
        color: {t["currency_fiat_text"]};
        border: 1px solid {t["currency_fiat_border"]};
      }}
      .currency-btn.crypto {{
        background: {t["currency_crypto_bg"]};
        color: {t["currency_crypto_text"]};
        border: 1px solid {t["currency_crypto_border"]};
      }}
      .currency-btn .symbol {{
        font-weight: 600;
      }}

      /* Expander styling */
      [data-testid="stExpander"] {{
        border: none !important;
        background: transparent !important;
      }}
      [data-testid="stExpander"] details {{
        border: none !important;
        background: transparent !important;
      }}
      [data-testid="stExpander"] summary {{
        padding: 0.75rem 0 !important;
        border: none !important;
        background: transparent !important;
      }}
      [data-testid="stExpander"] summary:hover {{
        color: {t["primary"]} !important;
      }}
      [data-testid="stExpander"] summary p {{
        color: {t["primary"]} !important;
        font-weight: 500 !important;
        font-size: 0.875rem !important;
      }}
      [data-testid="stExpander"] summary svg {{
        color: {t["primary"]} !important;
      }}
      [data-testid="stExpander"] [data-testid="stExpanderDetails"] {{
        padding: 0.5rem 0 !important;
        background: transparent !important;
        border: none !important;
      }}

      /* Export button - Figma style */
      .export-btn {{
        background: {t["primary"]};
        color: {t["primary_foreground"]};
        padding: 0.5rem 1rem;
        border-radius: 10px;
        font-size: 0.875rem;
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        font-weight: 500;
      }}

      /* Streamlit overrides - Figma style */
      .stSelectbox label, .stTextInput label {{
        font-size: 0.875rem;
        color: {t["text_secondary"]};
        font-weight: 500;
      }}
      .stSelectbox > div > div, .stTextInput > div > div > input {{
        border-radius: 10px;
        border: 1px solid {t["border"]} !important;
        background: {t["input_bg"]} !important;
        color: {t["text_primary"]} !important;
      }}
      /* Fix dark corners and border on text input wrapper */
      .stTextInput, .stTextInput > div, .stTextInput > div > div {{
        background: transparent !important;
        border: none !important;
      }}
      .stTextInput [data-testid="stTextInputRootElement"] {{
        background: {t["input_bg"]} !important;
        border: 1px solid {t["border"]} !important;
        border-radius: 10px !important;
        overflow: hidden !important;
      }}
      .stTextInput [data-testid="stTextInputRootElement"] > div {{
        background: {t["input_bg"]} !important;
        border: none !important;
        border-radius: 10px !important;
      }}
      .stTextInput input {{
        background: {t["input_bg"]} !important;
        border: none !important;
      }}
      .stSelectbox > div > div:focus-within, .stTextInput > div > div > input:focus {{
        border-color: {t["primary"]} !important;
        box-shadow: 0 0 0 3px {t["primary"]}15 !important;
      }}
      /* Password toggle button (eye icon) - fix dark background */
      .stTextInput [data-testid="stTextInputRootElement"] > div {{
        background: {t["input_bg"]} !important;
      }}
      .stTextInput [data-testid="baseButton-secondary"],
      .stTextInput [data-testid="baseButton-secondaryFormSubmit"],
      .stTextInput button {{
        background: {t["input_bg"]} !important;
        border: none !important;
        color: {t["text_secondary"]} !important;
        border-radius: 0 10px 10px 0 !important;
      }}
      .stTextInput button:hover {{
        color: {t["text_primary"]} !important;
        background: {t["bg_hover"]} !important;
      }}
      .stTextInput button svg {{
        fill: {t["text_secondary"]} !important;
        stroke: {t["text_secondary"]} !important;
      }}
      .stTextInput button:hover svg {{
        fill: {t["text_primary"]} !important;
        stroke: {t["text_primary"]} !important;
      }}
      /* Dropdown menu styling */
      [data-testid="stSelectboxVirtualDropdown"] {{
        background: {t["bg_card"]} !important;
        border: 1px solid {t["border"]} !important;
        border-radius: 10px !important;
      }}

      /* Provider card styling - using details element */
      .provider-card {{
        background: {"#F3F4F6" if current_theme == "light" else t["bg_card"]};
        border: 1px solid {"#E5E7EB" if current_theme == "light" else t["border"]};
        border-radius: 12px;
        margin-bottom: 0.75rem;
        box-shadow: 0 1px 3px {t["shadow"]};
        transition: all 0.2s ease;
      }}
      .provider-card:hover {{
        box-shadow: 0 8px 24px {t["shadow"]};
        transform: translateY(-2px);
        border-color: {t["primary"]};
      }}
      .provider-card .card-header {{
        padding: 1rem;
        cursor: pointer;
        list-style: none;
        display: block;
      }}
      .provider-card .card-header::-webkit-details-marker {{
        display: none;
      }}
      .provider-card .expand-icon {{
        font-size: 0.625rem;
        color: {t["text_muted"]};
        transition: transform 0.2s;
      }}
      .provider-card[open] .expand-icon {{
        transform: rotate(180deg);
      }}
      .provider-card .card-details-content {{
        padding: 0 1rem 1rem 1rem;
        border-top: 1px solid {"#D1D5DB" if current_theme == "light" else t["border"]};
        margin: 0 1rem;
        padding-top: 0.75rem;
      }}

      /* Button styling - Figma style */
      .stButton > button {{
        border-radius: 10px !important;
        font-weight: 500 !important;
        transition: all 0.2s !important;
      }}
      .stButton > button:hover {{
        transform: translateY(-1px);
        box-shadow: 0 4px 12px {t["shadow"]};
      }}
      /* Primary button (active toggle) */
      .stButton > button[data-testid="stBaseButton-primary"] {{
        background: {t["primary"]} !important;
        color: {t["primary_foreground"]} !important;
        border: none !important;
      }}
      /* Secondary button (inactive toggle) */
      .stButton > button[data-testid="stBaseButton-secondary"] {{
        background: {t["bg_secondary"]} !important;
        color: {t["text_secondary"]} !important;
        border: 1px solid {t["border"]} !important;
      }}
      .stButton > button[data-testid="stBaseButton-secondary"]:hover {{
        background: {t["bg_hover"]} !important;
        color: {t["text_primary"]} !important;
      }}

      /* Download button - Figma style */
      .stDownloadButton > button {{
        border-radius: 10px !important;
        font-weight: 500 !important;
        background: {t["primary"]} !important;
        color: {t["primary_foreground"]} !important;
        border: none !important;
      }}
      .stDownloadButton > button:hover {{
        background: {t["primary"]}dd !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px {t["primary"]}40;
      }}

      /* Hide sidebar toggle */
      button[data-testid="baseButton-headerNoPadding"] {{ display: none; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# =================================================
# Auth
# =================================================
def get_admin_password():
    if "ADMIN_PASSWORD" in st.secrets:
        return str(st.secrets["ADMIN_PASSWORD"])
    return os.getenv("ADMIN_PASSWORD", "")


def is_admin():
    return bool(st.session_state.get("is_admin", False))


# Session token for persistent login
def get_session_secret():
    """Get or generate a secret for session tokens."""
    # Use admin password + a salt as the secret
    return hashlib.sha256(f"session_salt_{get_admin_password()}".encode()).hexdigest()[:32]


def generate_session_token():
    """Generate a session token for persistent login."""
    secret = get_session_secret()
    return hashlib.sha256(f"auth_{secret}".encode()).hexdigest()[:24]


def verify_session_token(token: str) -> bool:
    """Verify if a session token is valid."""
    if not token:
        return False
    expected = generate_session_token()
    return token == expected


# =================================================
# DB helpers
# =================================================
def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON;")
    return con


def qdf(sql, params=()):
    with db() as con:
        return pd.read_sql_query(sql, con, params=params)


@st.cache_data
def load_countries():
    try:
        df = qdf("SELECT iso3, iso2, name FROM countries ORDER BY name")
        if df.empty:
            return pd.DataFrame(columns=["iso3", "iso2", "name", "label"])
        df["label"] = df["name"] + " (" + df["iso3"] + ")"
        return df
    except Exception:
        return pd.DataFrame(columns=["iso3", "iso2", "name", "label"])


@st.cache_data
def load_fiat_currencies():
    try:
        # Try new table first
        return qdf(
            "SELECT DISTINCT currency_code FROM fiat_currencies ORDER BY currency_code"
        )["currency_code"].tolist()
    except Exception:
        try:
            # Fall back to legacy table
            return qdf(
                "SELECT DISTINCT currency_code FROM currencies WHERE currency_type='FIAT' ORDER BY currency_code"
            )["currency_code"].tolist()
        except Exception:
            return []


@st.cache_data
def load_crypto_currencies():
    try:
        # Try new table first
        return qdf(
            "SELECT DISTINCT currency_code FROM crypto_currencies ORDER BY currency_code"
        )["currency_code"].tolist()
    except Exception:
        try:
            # Fall back to legacy table
            return qdf(
                "SELECT DISTINCT currency_code FROM currencies WHERE currency_type='CRYPTO' ORDER BY currency_code"
            )["currency_code"].tolist()
        except Exception:
            return []


def get_provider_details(pid):
    prov = qdf(
        "SELECT provider_id, provider_name, currency_mode FROM providers WHERE provider_id=?",
        (pid,),
    )
    if prov.empty:
        return None

    restrictions = qdf(
        "SELECT country_code, restriction_type FROM restrictions WHERE provider_id=? ORDER BY restriction_type, country_code",
        (pid,),
    )
    blocked = restrictions[restrictions["restriction_type"] == "BLOCKED"]["country_code"].tolist()
    conditional = restrictions[restrictions["restriction_type"] == "CONDITIONAL"]["country_code"].tolist()
    regulated = restrictions[restrictions["restriction_type"] == "REGULATED"]["country_code"].tolist()

    # Try new tables first, fall back to legacy
    try:
        fiat_df = qdf(
            "SELECT currency_code, 'FIAT' as currency_type FROM fiat_currencies WHERE provider_id=? ORDER BY currency_code",
            (pid,),
        )
        crypto_df = qdf(
            "SELECT currency_code, 'CRYPTO' as currency_type FROM crypto_currencies WHERE provider_id=? ORDER BY currency_code",
            (pid,),
        )
        currencies = pd.concat([fiat_df, crypto_df], ignore_index=True)
    except Exception:
        # Fall back to legacy table
        currencies = qdf(
            "SELECT currency_code, currency_type FROM currencies WHERE provider_id=? ORDER BY currency_type, currency_code",
            (pid,),
        )

    return {
        "provider": prov.iloc[0],
        "blocked": blocked,
        "conditional": conditional,
        "regulated": regulated,
        "currencies": currencies,
    }


def get_provider_stats(pid):
    """Get restriction, currency, and game counts for a provider."""
    with db() as con:
        restrictions = con.execute(
            "SELECT COUNT(*) FROM restrictions WHERE provider_id=?", (pid,)
        ).fetchone()[0]
        try:
            # Try new tables first
            fiat_count = con.execute(
                "SELECT COUNT(*) FROM fiat_currencies WHERE provider_id=?", (pid,)
            ).fetchone()[0]
            crypto_count = con.execute(
                "SELECT COUNT(*) FROM crypto_currencies WHERE provider_id=?", (pid,)
            ).fetchone()[0]
            currencies = fiat_count + crypto_count
        except Exception:
            # Fall back to legacy table
            currencies = con.execute(
                "SELECT COUNT(*) FROM currencies WHERE provider_id=?", (pid,)
            ).fetchone()[0]
        # Get games count
        try:
            games = con.execute(
                "SELECT COUNT(*) FROM games WHERE provider_id=?", (pid,)
            ).fetchone()[0]
        except Exception:
            games = 0
    return {"restrictions": restrictions, "currencies": currencies, "games": games}


def get_supported_countries(restricted_codes: list[str], all_countries_df) -> list[dict]:
    """Get countries that are NOT restricted (supported)."""
    restricted_set = set(restricted_codes)
    supported = []
    for _, row in all_countries_df.iterrows():
        if row["iso3"] not in restricted_set:
            supported.append({
                "iso3": row["iso3"],
                "iso2": row.get("iso2", row["iso3"][:2]),
                "name": row["name"]
            })
    return supported[:20]  # Limit to 20 for display


def get_currency_symbol(code: str) -> str:
    """Get currency symbol for common currencies."""
    symbols = {
        "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥",
        "CAD": "C$", "AUD": "A$", "CHF": "Fr", "INR": "₹", "KRW": "₩",
        "BRL": "R$", "MXN": "$", "RUB": "₽", "SEK": "kr", "NOK": "kr",
        "DKK": "kr", "PLN": "zł", "THB": "฿", "SGD": "S$", "HKD": "HK$",
        "BTC": "₿", "ETH": "Ξ", "USDT": "₮", "USDC": "₵", "BNB": "◉",
        "XRP": "✕", "ADA": "₳", "DOGE": "Ð", "SOL": "◎", "DOT": "●",
        "LTC": "Ł", "TRX": "◈", "MATIC": "◇",
    }
    return symbols.get(code, "")


def upsert_provider_by_name(provider_name: str, currency_mode: str) -> int:
    with db() as con:
        cur = con.execute("SELECT provider_id FROM providers WHERE provider_name=?", (provider_name,))
        row = cur.fetchone()
        if row:
            pid = int(row[0])
            con.execute("UPDATE providers SET currency_mode=? WHERE provider_id=?", (currency_mode, pid))
            con.commit()
            return pid

        cur2 = con.execute(
            "INSERT INTO providers(provider_name, currency_mode, status) VALUES(?, ?, 'ACTIVE')",
            (provider_name, currency_mode),
        )
        con.commit()
        return int(cur2.lastrowid)


def replace_ai_restrictions(provider_id: int, iso3_list: list[str]):
    with db() as con:
        con.execute("DELETE FROM restrictions WHERE provider_id=? AND source='ai_import'", (provider_id,))
        con.executemany(
            "INSERT OR IGNORE INTO restrictions(provider_id, country_code, source) VALUES (?, ?, 'ai_import')",
            [(provider_id, code) for code in iso3_list],
        )
        con.commit()


def replace_ai_fiat_currencies(provider_id: int, fiat_codes: list[str]):
    with db() as con:
        # Try to write to new table if it exists
        try:
            con.execute(
                "DELETE FROM fiat_currencies WHERE provider_id=? AND source='ai_import'",
                (provider_id,),
            )
            con.executemany(
                """
                INSERT OR IGNORE INTO fiat_currencies(provider_id, currency_code, display, source)
                VALUES (?, ?, 1, 'ai_import')
                """,
                [(provider_id, c) for c in fiat_codes],
            )
        except Exception:
            pass  # New table doesn't exist yet

        # Always write to legacy table
        con.execute(
            "DELETE FROM currencies WHERE provider_id=? AND source='ai_import' AND currency_type='FIAT'",
            (provider_id,),
        )
        con.executemany(
            """
            INSERT OR IGNORE INTO currencies(provider_id, currency_code, currency_type, display, source)
            VALUES (?, ?, 'FIAT', 1, 'ai_import')
            """,
            [(provider_id, c) for c in fiat_codes],
        )
        con.commit()


# =================================================
# AI + Excel extraction helpers
# =================================================
ISO3_RE = re.compile(r"\b[A-Z]{3}\b")
CURRENCY_RE = re.compile(r"^\s*([A-Z0-9]{3,10})\s*(\(|$)")


def get_openai_client():
    if "OPENAI_API_KEY" in st.secrets:
        return OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    api_key = os.getenv("OPENAI_API_KEY", "")
    if api_key:
        return OpenAI(api_key=api_key)
    return None


def find_sheet_name(sheet_names: list[str], keyword: str) -> str:
    kw = keyword.lower()
    for s in sheet_names:
        if kw in s.lower():
            return s
    return ""


def safe_read_sheet(xls: pd.ExcelFile, sheet_name: str, max_rows: int = 200) -> pd.DataFrame:
    if not sheet_name:
        return pd.DataFrame()
    try:
        df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        return df.head(max_rows)
    except Exception:
        return pd.DataFrame()


def extract_iso3_from_df(df: pd.DataFrame, allowed_iso3: set[str]) -> list[str]:
    if df is None or df.empty:
        return []
    found = set()
    for v in df.astype(str).values.flatten().tolist():
        for m in ISO3_RE.findall(str(v).upper()):
            if m in allowed_iso3:
                found.add(m)
    return sorted(found)


def extract_currency_codes_from_df(df: pd.DataFrame) -> list[str]:
    if df is None or df.empty:
        return []
    found = []
    for v in df.astype(str).values.flatten().tolist():
        s = str(v).strip()
        if not s or s.lower().startswith("supported curr"):
            continue
        m = CURRENCY_RE.match(s.upper())
        if m:
            code = m.group(1).strip()
            if code.isalpha() or any(ch.isdigit() for ch in code):
                found.append(code)
    seen = set()
    ordered = []
    for c in found:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def read_excel_extract(file_bytes: bytes, allowed_iso3: list[str]) -> dict:
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    sheets = xls.sheet_names

    restrict_sheet = find_sheet_name(sheets, "restrict")
    currency_sheet = find_sheet_name(sheets, "currenc")

    df_restrict = safe_read_sheet(xls, restrict_sheet, max_rows=300)
    df_currency = safe_read_sheet(xls, currency_sheet, max_rows=400)

    allowed_set = set([c for c in allowed_iso3 if isinstance(c, str)])

    restricted_iso3 = extract_iso3_from_df(df_restrict, allowed_set)
    fiat_codes = extract_currency_codes_from_df(df_currency)

    currency_mode = "LIST" if fiat_codes else "ALL_FIAT"

    return {
        "sheet_names": sheets,
        "restrict_sheet": restrict_sheet,
        "currency_sheet": currency_sheet,
        "restricted_iso3": restricted_iso3,
        "fiat_codes": fiat_codes,
        "currency_mode_suggested": currency_mode,
    }


def ai_suggest_provider_name_and_notes(file_name: str, sheet_names: list[str], counts: dict) -> dict:
    client = get_openai_client()
    if not client:
        return {"provider_name": Path(file_name).stem, "notes": "AI disabled (missing API key)."}

    payload = {
        "file_name": file_name,
        "sheet_names": sheet_names,
        "counts": counts,
        "instruction": "Suggest a clean provider_name from the file name. Return JSON with provider_name and notes only.",
    }

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Return ONLY valid JSON. No extra text."},
            {"role": "user", "content": json.dumps(payload)},
        ],
        temperature=0.2,
    )

    text = (resp.choices[0].message.content or "").strip()
    try:
        data = json.loads(text)
        provider_name = str(data.get("provider_name", "")).strip() or Path(file_name).stem
        notes = str(data.get("notes", "")).strip()
        return {"provider_name": provider_name, "notes": notes}
    except Exception:
        return {"provider_name": Path(file_name).stem, "notes": "AI returned invalid JSON; using file name."}


# =================================================
# Login Page - Figma style with animated background
# =================================================
def show_login_page():
    """Display the login page with Figma-style design."""
    t = THEMES[get_theme()]
    st.markdown(f"""
    <style>
        .stApp {{
            background: {t["bg_primary"]};
        }}

        /* Animated background blobs - Figma style */
        .login-bg {{
            position: fixed;
            inset: 0;
            overflow: hidden;
            z-index: 0;
            pointer-events: none;
        }}
        .login-blob {{
            position: absolute;
            border-radius: 50%;
            filter: blur(80px);
            opacity: 0.4;
            animation: pulse 4s ease-in-out infinite;
        }}
        .login-blob-1 {{
            top: -10%;
            right: -10%;
            width: 400px;
            height: 400px;
            background: {t["primary"]};
        }}
        .login-blob-2 {{
            bottom: -15%;
            left: -10%;
            width: 350px;
            height: 350px;
            background: {t["primary"]};
            animation-delay: 1s;
        }}
        .login-blob-3 {{
            top: 40%;
            left: 40%;
            width: 300px;
            height: 300px;
            background: {t["bg_hover"]};
            animation-delay: 2s;
        }}
        @keyframes pulse {{
            0%, 100% {{ transform: scale(1); opacity: 0.3; }}
            50% {{ transform: scale(1.1); opacity: 0.5; }}
        }}

        /* Login card - Figma style */
        .login-card {{
            max-width: 420px;
            margin: 2rem auto;
            padding: 2.5rem;
            background: {t["bg_card"]};
            border: 1px solid {t["border"]};
            border-radius: 20px;
            box-shadow: 0 8px 32px {t["shadow"]};
            position: relative;
            z-index: 10;
        }}
        .login-header {{
            text-align: center;
            margin-bottom: 2rem;
        }}
        .login-logo {{
            width: 72px;
            height: 72px;
            background: linear-gradient(135deg, {t["primary"]} 0%, #1E40AF 100%);
            border-radius: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 1.75rem;
            margin: 0 auto 1.25rem auto;
            box-shadow: 0 8px 24px {t["primary"]}40;
        }}
        .login-title {{
            font-size: 1.75rem;
            font-weight: 600;
            color: {t["text_primary"]};
            margin-bottom: 0.5rem;
        }}
        .login-subtitle {{
            font-size: 0.9rem;
            color: {t["text_secondary"]};
        }}

        /* Form styling */
        .login-form-title {{
            font-size: 1.25rem;
            font-weight: 600;
            color: {t["text_primary"]};
            margin-bottom: 0.25rem;
        }}
        .login-form-desc {{
            font-size: 0.875rem;
            color: {t["text_secondary"]};
            margin-bottom: 1.5rem;
        }}

        /* Bottom gradient line - Figma style */
        .login-gradient-line {{
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: linear-gradient(90deg, {t["primary"]} 0%, {t["bg_hover"]} 50%, {t["primary"]} 100%);
            z-index: 100;
        }}

        /* Form inputs styling - comprehensive fix */
        .stTextInput label {{
            color: {t["text_primary"]} !important;
        }}
        .stTextInput [data-testid="stTextInputRootElement"],
        .stTextInput [data-testid="stTextInputRootElement"] *,
        .stTextInput > div,
        .stTextInput > div > div,
        .stTextInput > div > div > div {{
            background: {t["input_bg"]} !important;
            background-color: {t["input_bg"]} !important;
        }}
        .stTextInput [data-testid="stTextInputRootElement"] {{
            border: 2px solid #94A3B8 !important;
            border-radius: 10px !important;
            overflow: hidden !important;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1) !important;
            outline: 2px solid #94A3B8 !important;
            outline-offset: -2px !important;
        }}
        .stTextInput [data-testid="stTextInputRootElement"] > div {{
            border: none !important;
        }}
        .stTextInput input {{
            background: transparent !important;
            color: {t["text_primary"]} !important;
            border: none !important;
        }}
        .stTextInput input::placeholder {{
            color: {t["text_muted"]} !important;
        }}
        /* Password toggle button (eye icon) */
        .stTextInput button,
        .stTextInput [data-testid="stTextInputRootElement"] button {{
            background: {t["input_bg"]} !important;
            background-color: {t["input_bg"]} !important;
            border: none !important;
            border-radius: 0 !important;
        }}
        .stTextInput button svg {{
            fill: {t["text_secondary"]} !important;
            stroke: {t["text_secondary"]} !important;
        }}
        .stTextInput button:hover {{
            background: {t["bg_hover"]} !important;
            background-color: {t["bg_hover"]} !important;
        }}
        .stTextInput button:hover svg {{
            fill: {t["text_primary"]} !important;
            stroke: {t["text_primary"]} !important;
        }}

        /* Checkbox styling */
        .stCheckbox label {{
            color: {t["text_primary"]} !important;
        }}
        .stCheckbox label span {{
            color: {t["text_primary"]} !important;
        }}
        .stCheckbox label p {{
            color: {t["text_primary"]} !important;
        }}
        .stCheckbox [data-testid="stMarkdownContainer"] {{
            color: {t["text_primary"]} !important;
        }}
        .stCheckbox [data-testid="stMarkdownContainer"] p {{
            color: {t["text_primary"]} !important;
        }}

        /* Form submit button */
        .stFormSubmitButton button {{
            background: {t["primary"]} !important;
            color: {t["primary_foreground"]} !important;
            border: none !important;
            border-radius: 10px !important;
        }}

        /* Error message */
        [data-testid="stAlert"] {{
            background: {t["tag_blocked_bg"]} !important;
            border: 1px solid {t["tag_blocked_text"]}40 !important;
        }}
        [data-testid="stAlert"] * {{
            color: {t["tag_blocked_text"]} !important;
        }}
        [data-testid="stAlert"] p {{
            color: {t["tag_blocked_text"]} !important;
        }}
        [data-testid="stAlert"] [data-testid="stMarkdownContainer"] {{
            color: {t["tag_blocked_text"]} !important;
        }}
        [data-testid="stAlert"] [data-testid="stMarkdownContainer"] p {{
            color: {t["tag_blocked_text"]} !important;
        }}
    </style>

    <!-- Animated background -->
    <div class="login-bg">
        <div class="login-blob login-blob-1"></div>
        <div class="login-blob login-blob-2"></div>
        <div class="login-blob login-blob-3"></div>
    </div>

    <!-- Bottom gradient line -->
    <div class="login-gradient-line"></div>
    """, unsafe_allow_html=True)

    # Theme toggle in top right
    _, theme_col = st.columns([9, 1])
    with theme_col:
        current = get_theme()
        icon = "☀️" if current == "dark" else "🌙"

        def toggle_login_theme():
            new_theme = "light" if get_theme() == "dark" else "dark"
            set_theme(new_theme)

        st.button(icon, key="login_theme", help="Toggle light/dark theme", on_click=toggle_login_theme)

    # Center the login form
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.markdown("""
        <div class="login-header">
            <div class="login-logo">TT</div>
            <div class="login-title">Game Providers</div>
            <div class="login-subtitle">Browse providers by country and currency</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="login-form-title">Sign In</div>', unsafe_allow_html=True)
        st.markdown('<div class="login-form-desc">Enter your credentials to access the dashboard</div>', unsafe_allow_html=True)

        with st.form("login_form"):
            password = st.text_input("Password", type="password", placeholder="Enter password")
            remember_me = st.checkbox("Keep me signed in", value=True)
            submitted = st.form_submit_button("Sign In", use_container_width=True, type="primary")

            if submitted:
                if password == get_admin_password():
                    st.session_state["is_admin"] = True
                    st.session_state["remember_me"] = remember_me
                    # Set persistent session token if "Keep me signed in" is checked
                    if remember_me:
                        st.query_params["session"] = generate_session_token()
                    st.rerun()
                else:
                    st.error("Invalid password. Please try again.")


# =================================================
# App start
# =================================================
if not DB_PATH.exists():
    st.error("Database not found. Make sure db/database.sqlite exists.")
    st.stop()

# Check for persistent session token in query params
if not is_admin():
    session_token = st.query_params.get("session", "")
    if session_token and verify_session_token(session_token):
        st.session_state["is_admin"] = True
    else:
        show_login_page()
        st.stop()

# =================================================
# Dashboard (only shown after login)
# =================================================
countries_df = load_countries()
country_labels = countries_df["label"].tolist()
label_to_iso = dict(zip(countries_df["label"], countries_df["iso3"]))
allowed_iso3 = countries_df["iso3"].dropna().tolist()

fiat = load_fiat_currencies()
crypto = load_crypto_currencies()

# Sanitize stale session state
valid_currencies = ["All Currencies"] + fiat
if st.session_state.get("f_currency", "") and st.session_state["f_currency"] not in valid_currencies:
    st.session_state["f_currency"] = ""
if st.session_state.get("f_country", "") and st.session_state["f_country"] not in ["All Countries"] + country_labels:
    st.session_state["f_country"] = ""

# =================================================
# Header row - logo and buttons on same line
logo_col, spacer_col, theme_col, logout_col = st.columns([3, 4, 1, 2])

with logo_col:
    st.markdown("""
    <div class="logo-container">
        <div class="logo-icon">TT</div>
        <div>
            <div class="logo-text">TIMELESS TECH</div>
            <div class="logo-subtitle">iGaming Platform</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

with theme_col:
    current = get_theme()
    icon = "☀️" if current == "dark" else "🌙"

    def toggle_theme():
        new_theme = "light" if get_theme() == "dark" else "dark"
        set_theme(new_theme)

    st.button(icon, key="btn_theme", help="Toggle light/dark theme", on_click=toggle_theme)

with logout_col:
    if st.button("Logout", key="btn_logout"):
        st.session_state["is_admin"] = False
        # Clear persistent session token
        if "session" in st.query_params:
            del st.query_params["session"]
        st.rerun()

# Header divider
st.markdown(f'<div style="border-bottom: 1px solid {t["border"]}; margin-bottom: 1rem;"></div>', unsafe_allow_html=True)

# =================================================
# Filters
# =================================================
# Initialize filter mode in session state
if "f_mode" not in st.session_state:
    st.session_state["f_mode"] = "Supported"

filter_mode = st.session_state["f_mode"]

# Filter section with card styling
with st.container(border=True):
    # Filter title with funnel icon
    st.markdown(f'''
    <div class="filter-title">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="{t["primary"]}" stroke-width="2">
            <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon>
        </svg>
        Filters
    </div>
    ''', unsafe_allow_html=True)

    # Row 1: Search, Country, Currency
    f1, f2, f3 = st.columns([2, 2, 2])

    with f1:
        search = st.text_input("Search Provider", placeholder="Search by name...", key="f_search", label_visibility="visible")

    with f2:
        country_options = ["All Countries"] + country_labels
        country_idx = 0
        current_country = st.session_state.get("f_country", "All Countries")
        if current_country in country_options:
            country_idx = country_options.index(current_country)
        country_label = st.selectbox("🌐 Country", country_options, index=country_idx, key="f_country")

    with f3:
        currency_options = ["All Currencies"] + fiat
        currency_idx = 0
        current_currency = st.session_state.get("f_currency", "All Currencies")
        if current_currency in currency_options:
            currency_idx = currency_options.index(current_currency)
        currency = st.selectbox("💱 Currency", currency_options, index=currency_idx, key="f_currency")

    # Row 2: Toggle buttons under Country
    g1, g2, g3 = st.columns([2, 2, 2])
    with g2:
        btn1, btn2 = st.columns([1, 1])
        with btn1:
            supported_style = "primary" if filter_mode == "Supported" else "secondary"
            if st.button("Supported", key="btn_supported", type=supported_style, use_container_width=True):
                st.session_state["f_mode"] = "Supported"
                st.rerun()
        with btn2:
            restricted_style = "primary" if filter_mode == "Restricted" else "secondary"
            if st.button("Restricted", key="btn_restricted", type=restricted_style, use_container_width=True):
                st.session_state["f_mode"] = "Restricted"
                st.rerun()

    # Row 3: Crypto
    h1, h2, h3 = st.columns([2, 2, 2])
    with h1:
        crypto_options = ["All Crypto Currencies"] + crypto
        crypto_idx = 0
        current_crypto = st.session_state.get("f_crypto", "All Crypto Currencies")
        if current_crypto in crypto_options:
            crypto_idx = crypto_options.index(current_crypto)
        crypto_filter = st.selectbox("💎 Crypto Currency", crypto_options, index=crypto_idx, key="f_crypto")

# =================================================
# Query building
# =================================================
where = []
params = []

if search:
    where.append("LOWER(p.provider_name) LIKE ?")
    params.append(f"%{search.lower()}%")

country_iso = label_to_iso.get(country_label, "")
if country_iso:
    if filter_mode == "Supported":
        where.append("p.provider_id NOT IN (SELECT provider_id FROM restrictions WHERE country_code=?)")
        params.append(country_iso)
    else:  # Restricted
        where.append("p.provider_id IN (SELECT provider_id FROM restrictions WHERE country_code=?)")
        params.append(country_iso)

if currency and currency != "All Currencies":
    # Works with both new and legacy tables
    where.append(
        """
        (
            p.currency_mode='ALL_FIAT'
            OR EXISTS (
                SELECT 1 FROM currencies c
                WHERE c.provider_id=p.provider_id
                AND c.currency_type='FIAT'
                AND c.currency_code=?
            )
        )
        """
    )
    params.append(currency)

if crypto_filter and crypto_filter != "All Crypto Currencies":
    # Works with both new and legacy tables
    where.append(
        """
        EXISTS (
            SELECT 1 FROM currencies c
            WHERE c.provider_id=p.provider_id
            AND c.currency_type='CRYPTO'
            AND c.currency_code=?
        )
        """
    )
    params.append(crypto_filter)

where_sql = "WHERE " + " AND ".join(where) if where else ""

df = qdf(
    f"""
    SELECT provider_id AS ID, provider_name AS "Game Provider"
    FROM providers p
    {where_sql}
    ORDER BY provider_name
    """,
    tuple(params),
)

# =================================================
# Stats cards
# =================================================
total_providers = int(qdf("SELECT COUNT(*) c FROM providers")["c"][0])
try:
    total_games = int(qdf("SELECT COUNT(*) c FROM games")["c"][0])
except Exception:
    total_games = 0

st.markdown(f"""
<div class="stats-container">
    <div class="stat-card">
        <div>
            <div class="stat-label">Total Providers</div>
            <div class="stat-value">{len(df)}</div>
        </div>
        <div class="stat-icon providers">🎮</div>
    </div>
    <div class="stat-card">
        <div>
            <div class="stat-label">Total Games</div>
            <div class="stat-value">{total_games}</div>
        </div>
        <div class="stat-icon currencies">🎰</div>
    </div>
</div>
""", unsafe_allow_html=True)

# =================================================
# Provider list header with export
# =================================================
pcol1, pcol2, pcol3 = st.columns([1, 1.15, 0.22])
with pcol1:
    st.markdown(f'<div class="providers-title">Game Providers ({len(df)})</div>', unsafe_allow_html=True)
# pcol2 empty
with pcol3:
    # Export to Excel - aligned right under emoji
    excel_buffer = io.BytesIO()
    df.to_excel(excel_buffer, index=False, engine='openpyxl')
    excel_buffer.seek(0)
    st.download_button(
        "📥 Export to Excel",
        data=excel_buffer,
        file_name="providers.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="btn_export_excel",
    )

# =================================================
# Provider cards (2-column grid)
# =================================================
st.markdown('<div class="provider-cards">', unsafe_allow_html=True)
if df.empty:
    st.info("No providers match your filters.")
else:
    # Create two columns for the grid
    col1, col2 = st.columns(2)

    for idx, row in df.iterrows():
        pid = row["ID"]
        pname = row["Game Provider"]

        # Get provider stats
        stats = get_provider_stats(pid)
        details = get_provider_details(pid)

        # Alternate between columns
        target_col = col1 if idx % 2 == 0 else col2

        with target_col:
            # Build tags HTML
            tags_html = ""
            if details:
                blocked_count = len(details["blocked"])
                conditional_count = len(details["conditional"])
                regulated_count = len(details["regulated"])

                if blocked_count > 0:
                    tags_html += f'<span class="tag blocked">Blocked: {blocked_count}</span>'
                if conditional_count > 0:
                    tags_html += f'<span class="tag conditional">Restricted: {conditional_count}</span>'
                if regulated_count > 0:
                    tags_html += f'<span class="tag regulated">Regulated: {regulated_count}</span>'

                # Currency info
                if details["provider"].currency_mode == "ALL_FIAT":
                    tags_html += '<span class="tag fiat">All FIAT</span>'
                else:
                    fiat_list = details["currencies"][details["currencies"]["currency_type"] == "FIAT"]["currency_code"].tolist()
                    if fiat_list:
                        tags_html += f'<span class="tag fiat">FIAT: {len(fiat_list)}</span>'

                crypto_list = details["currencies"][details["currencies"]["currency_type"] == "CRYPTO"]["currency_code"].tolist()
                if crypto_list:
                    tags_html += f'<span class="tag crypto">Crypto: {len(crypto_list)}</span>'

            # Build details HTML content
            details_html = ""
            if details:
                p = details["provider"]

                # Helper to get country info from ISO3
                def get_country_info(iso3_list):
                    result = []
                    for iso3 in iso3_list:
                        match = countries_df[countries_df["iso3"] == iso3]
                        if not match.empty:
                            row = match.iloc[0]
                            result.append({
                                "iso3": iso3,
                                "iso2": row.get("iso2", iso3[:2]) or iso3[:2],
                                "name": row["name"]
                            })
                        else:
                            result.append({"iso3": iso3, "iso2": iso3[:2], "name": iso3})
                    return result

                # Blocked Countries
                if details["blocked"]:
                    details_html += f'<div style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; font-weight: 600; color: {t["text_primary"]}; margin: 0.75rem 0;"><span style="color: {t["chart_red"]};">✕</span> Blocked Countries ({len(details["blocked"])})</div>'
                    blocked_countries = get_country_info(details["blocked"][:20])
                    details_html += f'<div class="country-tags">'
                    for c in blocked_countries:
                        details_html += f'<span class="country-tag" style="border-color: {t["tag_blocked_text"]};"><span class="iso" style="background: {t["tag_blocked_text"]};">{c["iso2"]}</span>{c["name"]}</span>'
                    if len(details["blocked"]) > 20:
                        details_html += f'<span class="country-tag">+{len(details["blocked"]) - 20} more</span>'
                    details_html += '</div>'

                # Restricted Countries
                if details["conditional"]:
                    details_html += f'<div style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; font-weight: 600; color: {t["text_primary"]}; margin: 0.75rem 0;"><span style="color: {t["chart_yellow"]};">⚠</span> Restricted Countries ({len(details["conditional"])})</div>'
                    conditional_countries = get_country_info(details["conditional"][:20])
                    details_html += '<div class="country-tags">'
                    for c in conditional_countries:
                        details_html += f'<span class="country-tag" style="border-color: {t["tag_conditional_text"]};"><span class="iso" style="background: {t["tag_conditional_text"]};">{c["iso2"]}</span>{c["name"]}</span>'
                    if len(details["conditional"]) > 20:
                        details_html += f'<span class="country-tag">+{len(details["conditional"]) - 20} more</span>'
                    details_html += '</div>'

                # Regulated Countries
                if details["regulated"]:
                    details_html += f'<div style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; font-weight: 600; color: {t["text_primary"]}; margin: 0.75rem 0;"><span style="color: {t["primary"]};">⚖</span> Regulated Countries ({len(details["regulated"])})</div>'
                    regulated_countries = get_country_info(details["regulated"][:20])
                    details_html += '<div class="country-tags">'
                    for c in regulated_countries:
                        details_html += f'<span class="country-tag" style="border-color: {t["tag_regulated_text"]};"><span class="iso" style="background: {t["tag_regulated_text"]};">{c["iso2"]}</span>{c["name"]}</span>'
                    if len(details["regulated"]) > 20:
                        details_html += f'<span class="country-tag">+{len(details["regulated"]) - 20} more</span>'
                    details_html += '</div>'

                # Supported Currencies
                fiat_list = details["currencies"][details["currencies"]["currency_type"] == "FIAT"]["currency_code"].tolist() if not details["currencies"].empty else []
                if p.currency_mode == "ALL_FIAT" or fiat_list:
                    details_html += f'<div style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; font-weight: 600; color: {t["text_primary"]}; margin: 0.75rem 0;"><span style="color: {t["chart_green"]};">✓</span> Supported Currencies</div>'
                    if p.currency_mode == "ALL_FIAT":
                        details_html += '<div class="currency-grid"><div class="currency-btn fiat"><span class="symbol">*</span>All FIAT</div></div>'
                    else:
                        details_html += '<div class="currency-grid">'
                        for curr in fiat_list[:9]:
                            symbol = get_currency_symbol(curr)
                            details_html += f'<div class="currency-btn fiat"><span class="symbol">{symbol}</span>{curr}</div>'
                        details_html += '</div>'
                        if len(fiat_list) > 9:
                            details_html += f'<div style="font-size: 0.75rem; color: {t["text_muted"]}; margin-top: 0.25rem;">+{len(fiat_list) - 9} more</div>'

                # Supported Crypto
                crypto_list = details["currencies"][details["currencies"]["currency_type"] == "CRYPTO"]["currency_code"].tolist() if not details["currencies"].empty else []
                if crypto_list:
                    details_html += f'<div style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; font-weight: 600; color: {t["text_primary"]}; margin: 0.75rem 0;"><span style="color: {t["chart_green"]};">✓</span> Crypto Currencies</div>'
                    details_html += '<div class="currency-grid">'
                    for curr in crypto_list[:9]:
                        symbol = get_currency_symbol(curr)
                        details_html += f'<div class="currency-btn crypto"><span class="symbol">{symbol}</span>{curr}</div>'
                    details_html += '</div>'
                    if len(crypto_list) > 9:
                        details_html += f'<div style="font-size: 0.75rem; color: {t["text_muted"]}; margin-top: 0.25rem;">+{len(crypto_list) - 9} more</div>'

            # Render complete card with details inside - using details/summary as the card wrapper
            st.markdown(f"""
            <details class="provider-card">
                <summary class="card-header">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem;">
                        <div style="display: flex; gap: 0.75rem; align-items: center;">
                            <div style="width: 48px; height: 48px; background: linear-gradient(135deg, {t["bg_hover"]} 0%, {t["bg_secondary"]} 100%); border-radius: 12px; display: flex; align-items: center; justify-content: center; color: {t["primary"]}; font-size: 1.25rem;">🎮</div>
                            <div>
                                <div style="font-size: 1rem; font-weight: 600; color: {t["text_primary"]};">{pname}</div>
                                <div style="font-size: 0.8rem; color: {t["text_secondary"]};">{stats['games']} games</div>
                            </div>
                        </div>
                        <span class="expand-icon">▼</span>
                    </div>
                    <div style="margin-top: 0.75rem;">
                        <div style="font-size: 0.75rem; color: {t["text_secondary"]}; margin-bottom: 0.5rem; font-weight: 500;">Restrictions & Currencies</div>
                        <div class="tags-container">
                            {tags_html if tags_html else '<span class="tag">No data</span>'}
                        </div>
                    </div>
                </summary>
                <div class="card-details-content">
                    {details_html if details_html else '<p style="color: ' + t["text_muted"] + ';">No details available</p>'}
                </div>
            </details>
            """, unsafe_allow_html=True)

# =================================================
# Admin: AI Agent — Import provider from Excel
# =================================================
if is_admin():
    st.markdown("---")
    with st.expander("🔧 Admin: Import Provider from Excel", expanded=False):
        st.caption(
            "Upload an Excel file to extract provider data. "
            "AI suggests the provider name, codes are extracted deterministically."
        )

        up = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"], key="ai_import_uploader")

        if up is not None:
            extracted = read_excel_extract(up.getvalue(), allowed_iso3)

            st.write("Detected sheets:", extracted["sheet_names"])
            st.write("Detected restriction sheet:", extracted["restrict_sheet"] or "Not found")
            st.write("Detected currency sheet:", extracted["currency_sheet"] or "Not found")

            if st.button("Run extraction", key="btn_run_ai"):
                ai_meta = ai_suggest_provider_name_and_notes(
                    up.name,
                    extracted["sheet_names"],
                    counts={
                        "restricted_iso3_count": len(extracted["restricted_iso3"]),
                        "fiat_codes_count": len(extracted["fiat_codes"]),
                    },
                )
                st.session_state["ai_import_plan"] = {
                    "provider_name": ai_meta["provider_name"],
                    "notes": ai_meta["notes"],
                    "currency_mode": extracted["currency_mode_suggested"],
                    "restricted_iso3": extracted["restricted_iso3"],
                    "fiat_codes": extracted["fiat_codes"],
                }

            plan = st.session_state.get("ai_import_plan", None)
            if plan:
                st.success("Plan ready. Review and apply if correct.")
                st.json(
                    {
                        "provider_name": plan["provider_name"],
                        "currency_mode": plan["currency_mode"],
                        "restricted_iso3_count": len(plan["restricted_iso3"]),
                        "fiat_codes_count": len(plan["fiat_codes"]),
                        "notes": plan["notes"],
                    }
                )

                provider_name = st.text_input(
                    "Provider name (edit if needed)",
                    value=plan["provider_name"],
                    key="ai_provider_name",
                )

                currency_mode = st.selectbox(
                    "Currency mode",
                    ["ALL_FIAT", "LIST"],
                    index=0 if plan["currency_mode"] == "ALL_FIAT" else 1,
                    key="ai_currency_mode",
                )

                st.markdown("**Restricted countries (extracted)**")
                st.write(", ".join(plan["restricted_iso3"]) if plan["restricted_iso3"] else "None")

                st.markdown("**Supported FIAT currencies (extracted)**")
                st.write(", ".join(plan["fiat_codes"][:50]) if plan["fiat_codes"] else "None")
                if len(plan["fiat_codes"]) > 50:
                    st.caption(f"Showing first 50 of {len(plan['fiat_codes'])} currency codes.")

                if st.button("Apply import to database", type="primary", key="btn_apply_ai"):
                    pid = upsert_provider_by_name(provider_name, currency_mode)
                    replace_ai_restrictions(pid, plan["restricted_iso3"])
                    if currency_mode == "LIST":
                        replace_ai_fiat_currencies(pid, plan["fiat_codes"])
                    st.success(f"Imported {provider_name} (ID: {pid})")
                    st.cache_data.clear()
