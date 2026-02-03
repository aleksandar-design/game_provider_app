import os
import io
import json
import re
import sqlite3
import hashlib
import base64
import secrets
import time
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from openai import OpenAI

DB_PATH = Path("db") / "database.sqlite"

# =================================================
# Games data loader (early for components.html injection)
# =================================================
@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_all_games_json():
    """Load all games data as JSON for client-side lazy loading."""
    if not DB_PATH.exists():
        return "[]"
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT provider_id, game_id, title, rtp, volatility, themes, features, thumbnail
            FROM games
            ORDER BY provider_id, title
        """)
        rows = cursor.fetchall()
        games_records = []
        for row in rows:
            games_records.append({
                "provider_id": row[0],
                "game_id": row[1],
                "title": row[2] or "",
                "rtp": row[3],
                "volatility": row[4] or "",
                "themes": row[5] or "[]",
                "features": row[6] or "[]",
                "thumbnail": row[7] or "",
            })
        return json.dumps(games_records)
    finally:
        conn.close()

# =================================================
# Auth helpers (defined early for session restoration)
# =================================================
def get_admin_password():
    if "ADMIN_PASSWORD" in st.secrets:
        return str(st.secrets["ADMIN_PASSWORD"])
    return os.getenv("ADMIN_PASSWORD", "")

def get_session_secret():
    """Get or generate a secret for session tokens."""
    return hashlib.sha256(f"session_salt_{get_admin_password()}".encode()).hexdigest()[:32]

def generate_session_token():
    """Generate a session token with expiry (7 days) and randomness."""
    secret = get_session_secret()
    expiry = int(time.time()) + (7 * 24 * 60 * 60)  # 7 days from now
    random_part = secrets.token_hex(8)
    # Format: {expiry_timestamp}.{random}.{signature}
    data = f"{expiry}.{random_part}"
    signature = hashlib.sha256(f"{data}.{secret}".encode()).hexdigest()[:16]
    return f"{data}.{signature}"

def verify_session_token(token: str) -> bool:
    """Verify if a session token is valid and not expired."""
    if not token:
        return False
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return False
        expiry_str, random_part, signature = parts
        expiry = int(expiry_str)

        # Check expiry
        if time.time() > expiry:
            return False

        # Verify signature
        secret = get_session_secret()
        data = f"{expiry_str}.{random_part}"
        expected_sig = hashlib.sha256(f"{data}.{secret}".encode()).hexdigest()[:16]
        return signature == expected_sig
    except (ValueError, AttributeError):
        return False

def is_admin():
    return bool(st.session_state.get("is_admin", False))

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
    # Preserve session token when changing theme
    session = st.query_params.get("session", "")
    st.query_params["theme"] = theme
    if session:
        st.query_params["session"] = session

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
        "tag_restricted_bg": "#78350F",
        "tag_restricted_text": "#FACC15",
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
        "tag_restricted_bg": "#FEF3C7",
        "tag_restricted_text": "#B45309",
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
# SVG Icons (inline, theme-aware)
# =================================================
def svg_icon(name: str, color: str = "currentColor", size: int = 16) -> str:
    """Return inline SVG icon by name."""
    icons = {
        "wallet": f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><line x1="1" y1="10" x2="23" y2="10"/></svg>',
        "globe": f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
        "gamepad": f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="12" x2="10" y2="12"/><line x1="8" y1="10" x2="8" y2="14"/><line x1="15" y1="13" x2="15.01" y2="13"/><line x1="18" y1="11" x2="18.01" y2="11"/><rect x="2" y="6" width="20" height="12" rx="2"/></svg>',
        "folder": f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
        "card": f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><line x1="1" y1="10" x2="23" y2="10"/></svg>',
        "crypto": f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="15" r="6"/><circle cx="16" cy="9" r="6"/></svg>',
        "dice": f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5" fill="{color}"/><circle cx="15.5" cy="8.5" r="1.5" fill="{color}"/><circle cx="8.5" cy="15.5" r="1.5" fill="{color}"/><circle cx="15.5" cy="15.5" r="1.5" fill="{color}"/></svg>',
        "x-circle": f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
        "check-circle": f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9 12l2 2 4-4"/></svg>',
        "alert-triangle": f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
        "info": f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
        "filter": f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>',
        "chevron-down": f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>',
    }
    return icons.get(name, "")

# =================================================
# Page config + styling
# =================================================
st.set_page_config(page_title="Game Providers", layout="wide", initial_sidebar_state="collapsed")

# =================================================
# Early session restoration (before any rendering)
# =================================================
# Check for session token in URL and restore session BEFORE any rendering
if not is_admin():
    _session_token = st.query_params.get("session", "")
    if _session_token and verify_session_token(_session_token):
        st.session_state["is_admin"] = True

# Get current theme
current_theme = get_theme()
t = THEMES[current_theme]

st.markdown(
    f"""
    <style>
      /* CSS Variables for theming - only these change on theme switch */
      :root {{
        --bg-primary: {t["bg_primary"]};
        --bg-secondary: {t["bg_secondary"]};
        --bg-card: {t["bg_card"]};
        --bg-hover: {t["bg_hover"]};
        --border: {t["border"]};
        --input-bg: {t["input_bg"]};
        --text-primary: {t["text_primary"]};
        --text-secondary: {t["text_secondary"]};
        --text-muted: {t["text_muted"]};
        --primary: {t["primary"]};
        --chart-green: {t["chart_green"]};
        --chart-yellow: {t["chart_yellow"]};
        --chart-red: {t["chart_red"]};
        --tag-restricted-text: {t["tag_restricted_text"]};
        --tag-regulated-text: {t["tag_regulated_text"]};
        --shadow: {t["shadow"]};
      }}

      /* Prevent white flash - set background immediately on all containers */
      html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"], .main {{
        background: var(--bg-primary) !important;
      }}

      /* Smooth theme transitions */
      .stApp, .stApp *, .stApp *::before, .stApp *::after {{
        transition: background-color 0.15s ease-out, color 0.1s ease-out, border-color 0.15s ease-out, fill 0.1s ease-out, stroke 0.1s ease-out;
      }}

      /* Main app background */
      .stApp {{
        background: var(--bg-primary);
      }}

      /* Hide default header */
      header[data-testid="stHeader"] {{ display: none; }}
      .block-container {{ padding-top: 3.5rem; padding-bottom: 2rem; margin-top: -0.5rem; }}
      .block-container > [data-testid="stVerticalBlock"] {{ gap: 0.5rem !important; }}
      .block-container > [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlock"]:first-child {{ padding-top: 0 !important; margin-top: 0 !important; }}

      /* Sticky header */
      .st-key-sticky_header {{
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        right: 0 !important;
        z-index: 999 !important;
        background: {t["bg_primary"]} !important;
        padding: 0.5rem 1rem !important;
        border-bottom: 1px solid {t["border"]} !important;
        overflow: visible !important;
      }}
      .st-key-sticky_header [data-testid="stVerticalBlock"] {{
        gap: 0 !important;
        overflow: visible !important;
      }}
      .st-key-sticky_header [data-testid="stHorizontalBlock"] {{
        overflow: visible !important;
      }}
      .st-key-sticky_header [data-testid="stHorizontalBlock"] > div {{
        overflow: visible !important;
      }}
      /* Override Streamlit's max-width on header logo */
      .st-key-sticky_header img {{
        max-width: none !important;
      }}

      /* Custom header - Figma style */
      .logo-container {{
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.5rem 0;
      }}
      .logo-icon {{
        width: 40px;
        height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
      }}
      .logo-icon img {{
        width: auto;
        height: 44px;
        max-width: none !important;
        object-fit: contain;
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
      /* Tighter gap for header buttons */
      [data-testid="stHorizontalBlock"]:has(.st-key-btn_theme) {{
        gap: 0.25rem !important;
      }}
      /* Header buttons - override Streamlit's direction="column" */
      div.stVerticalBlock.st-key-header_buttons[direction="column"] {{
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        gap: 0.5rem !important;
        justify-content: flex-end !important;
        align-items: center !important;
      }}

      /* Filter container - style bordered containers */
      [data-testid="stVerticalBlockBorderWrapper"] {{
        border-radius: 16px !important;
        border: 1.5px solid {t["border"]} !important;
        background: {t["bg_card"]} !important;
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
        font-weight: 700;
        color: {t["text_primary"]};
        margin-bottom: 0.5rem;
      }}
      .filter-title svg {{
        color: {t["primary"]};
      }}

      /* More Filters toggle - full width text link */
      .st-key-btn_toggle_filters {{
        width: 100% !important;
      }}
      .st-key-btn_toggle_filters button {{
        background: transparent !important;
        border: none !important;
        border-top: 1px solid {t["border"]} !important;
        box-shadow: none !important;
        color: {t["text_secondary"]} !important;
        font-size: 0.8rem !important;
        font-weight: 500 !important;
        padding: 0.5rem 0 !important;
        min-height: unset !important;
        width: 100% !important;
        text-align: left !important;
        justify-content: flex-start !important;
        border-radius: 0 !important;
      }}
      .st-key-btn_toggle_filters button:hover {{
        color: {t["text_primary"]} !important;
        background: {t["bg_hover"]} !important;
        box-shadow: none !important;
        border: 1px solid {t["border"]} !important;
        text-decoration: none !important;
      }}
      .st-key-btn_toggle_filters button:focus,
      .st-key-btn_toggle_filters button:active {{
        outline: none !important;
        box-shadow: none !important;
      }}

      /* Apply Filters button */
      .st-key-btn_apply_filters {{
        width: 100px !important;
      }}
      .st-key-btn_apply_filters button {{
        background: {t["primary"]} !important;
        color: {t["primary_foreground"]} !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-size: 0.8rem !important;
        letter-spacing: 0.05em !important;
        text-transform: uppercase !important;
        padding: 0.4rem 1rem !important;
        width: 100px !important;
        min-width: 100px !important;
        max-width: 100px !important;
        transition: all 0.2s ease !important;
      }}
      .st-key-btn_apply_filters button:hover {{
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 12px {t["primary"]}40 !important;
      }}

      /* APPLY button column - always push to far right */
      div[data-testid="stHorizontalBlock"]:has(.st-key-btn_apply_filters) {{
        align-items: center !important;
      }}
      div[data-testid="stHorizontalBlock"]:has(.st-key-btn_apply_filters) > div:last-child {{
        margin-left: auto !important;
        flex: 0 0 100px !important;
        width: 100px !important;
        min-width: 100px !important;
        max-width: 100px !important;
      }}

      /* Hide "Press Enter to apply" hint on text inputs */
      [data-testid="InputInstructions"] {{
        display: none !important;
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
      .games-container {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
      }}
      .game-chip {{
        display: inline-flex;
        align-items: center;
        padding: 0.25rem 0.6rem;
        background: {t["tag_bg"]};
        border: 1px solid {t["border"]};
        border-radius: 999px;
        font-size: 0.7rem;
        font-weight: 600;
        color: {t["text_primary"]};
        line-height: 1.4;
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
      .tag.restricted {{ background: {t["tag_restricted_bg"]}; color: {t["tag_restricted_text"]}; }}
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

      /* Active filter badges */
      .active-filters-container {{
        display: flex;
        align-items: center;
        gap: 0.5rem;
        flex-wrap: wrap;
        padding: 0.5rem 0;
      }}
      .active-filters-row {{
        display: inline-flex !important;
        align-items: center !important;
        gap: 0.5rem !important;
        flex-wrap: wrap !important;
        margin: 0 !important;
        padding: 0 !important;
        width: fit-content !important;
      }}
      /* Make the active-filters columns shrink-to-fit */
      div[data-testid="stHorizontalBlock"]:has(.active-filters-row) {{
        align-items: center !important;
        gap: 0.5rem !important;
      }}
      div[data-testid="stHorizontalBlock"]:has(.active-filters-row) > div[data-testid="column"],
      div[data-testid="stHorizontalBlock"]:has(.active-filters-row) > div.stColumn {{
        flex: 0 0 auto !important;
        width: fit-content !important;
        min-width: 0 !important;
        max-width: 100% !important;
      }}
      /* Tighten the badges column specifically */
      div[data-testid="stHorizontalBlock"]:has(.active-filters-row) > div.stColumn:has(.filter-badges-container),
      div[data-testid="stHorizontalBlock"]:has(.active-filters-row) > div[data-testid="column"]:has(.filter-badges-container) {{
        flex: 0 0 auto !important;
        width: fit-content !important;
        max-width: 100% !important;
      }}
      /* Tighten the clear-all column specifically */
      div[data-testid="stHorizontalBlock"]:has(.active-filters-row) > div.stColumn:has(.stButton button[key="btn_clear_all"]),
      div[data-testid="stHorizontalBlock"]:has(.active-filters-row) > div[data-testid="column"]:has(.stButton button[key="btn_clear_all"]) {{
        flex: 0 0 auto !important;
        width: fit-content !important;
        max-width: 100% !important;
      }}
      .filter-badge {{
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.35rem 0.75rem;
        background: {"#E0F2FE" if current_theme == "light" else "#1E3A8A"};
        border: none !important;
        outline: none !important;
        border-radius: 16px;
        font-size: 0.8rem;
        color: {"#0369A1" if current_theme == "light" else "#93C5FD"};
        font-weight: 500;
      }}
      .filter-badge-label {{
        color: {"#0369A1" if current_theme == "light" else "#93C5FD"};
        font-weight: 500;
      }}
      .filter-badge-value {{
        color: {"#0284C7" if current_theme == "light" else "#BFDBFE"};
        font-weight: 600;
      }}
      /* Filter badges container - match React flexbox */
      .filter-badges-container {{
        display: inline-flex !important;
        align-items: center !important;
        gap: 0.5rem !important;
        flex-wrap: wrap !important;
        margin: 0 !important;
        vertical-align: middle !important;
      }}

      /* Inline row for badges + clear button */
      div:has(> .filter-badges-container) {{
        display: inline-flex !important;
        align-items: center !important;
        flex-wrap: wrap !important;
        gap: 0.5rem !important;
        margin: 0 !important;
        padding: 0 !important;
        vertical-align: middle !important;
      }}
      div:has(.stButton button[key="btn_clear_all"]) {{
        display: inline-flex !important;
        align-items: center !important;
        margin: 0 !important;
        padding: 0 !important;
        vertical-align: middle !important;
      }}

      /* Clear all button styling - inline text style next to badges */
      button[key="btn_clear_all"] {{
        background: transparent !important;
        border: none !important;
        outline: none !important;
        box-shadow: none !important;
        color: {t["text_secondary"]} !important;
        padding: 0 !important;
        margin: 0 !important;
        font-size: 0.75rem !important;
        font-weight: 400 !important;
        min-height: 1.5rem !important;
        height: 1.5rem !important;
        line-height: 1.5 !important;
        text-decoration: none !important;
        cursor: pointer !important;
      }}

      button[key="btn_clear_all"]:hover {{
        color: {t["text_primary"]} !important;
        background: transparent !important;
        box-shadow: none !important;
        border: none !important;
        text-decoration: underline !important;
        transform: none !important;
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

      /* Currency tabs styling */
      .currency-tabs {{
        margin-bottom: 1rem;
      }}
      .currency-tabs input[type="radio"] {{
        display: none;
      }}
      .currency-tab-buttons {{
        display: flex;
        gap: 0.5rem;
        margin-bottom: 1rem;
      }}
      .currency-tabs label.subtab {{
        flex: 1;
        text-align: center;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem;
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        color: rgba(255, 255, 255, 0.6);
        font-size: 0.875rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s ease;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.375rem;
      }}
      .currency-tabs label.subtab svg {{
        flex-shrink: 0;
      }}
      .currency-tabs label.subtab:hover {{
        background: rgba(255, 255, 255, 0.08);
        border-color: rgba(59, 130, 246, 0.5);
      }}
      .currency-tabs .fiat-panel,
      .currency-tabs .crypto-panel {{
        display: none;
      }}
      /* When fiat radio is checked */
      .currency-tabs input[id$="-fiat"]:checked ~ .currency-tab-buttons label[for$="-fiat"] {{
        background: rgb(59, 130, 246);
        border-color: rgb(59, 130, 246);
        color: white;
      }}
      .currency-tabs input[id$="-fiat"]:checked ~ .fiat-panel {{
        display: block;
      }}
      /* When crypto radio is checked */
      .currency-tabs input[id$="-crypto"]:checked ~ .currency-tab-buttons label[for$="-crypto"] {{
        background: rgb(59, 130, 246);
        border-color: rgb(59, 130, 246);
        color: white;
      }}
      .currency-tabs input[id$="-crypto"]:checked ~ .crypto-panel {{
        display: block;
      }}

      /* Provider main tabs styling - pure CSS radio pattern */
      .provider-main-tabs {{
        margin-bottom: 1rem;
      }}
      .provider-main-tabs > input[type="radio"] {{
        display: none;
      }}
      .main-tab-buttons {{
        display: flex;
        gap: 0.5rem;
        margin-bottom: 1.5rem;
        flex-wrap: nowrap;
      }}
      .provider-main-tabs .main-tab {{
        flex: 1;
        text-align: center;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem;
        background: {t["bg_secondary"]};
        border: 1px solid {t["border"]};
        color: {t["text_secondary"]};
        font-size: 0.875rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s ease;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.375rem;
        box-shadow: 0 1px 2px {t["shadow"]};
      }}
      .provider-main-tabs .main-tab svg {{
        flex-shrink: 0;
      }}
      .provider-main-tabs .main-tab:hover {{
        background: {t["bg_hover"]};
        border-color: {t["primary"]};
        color: {t["text_primary"]};
        box-shadow: 0 2px 6px {t["shadow"]};
      }}
      .provider-main-tabs .main-panel {{
        display: none;
      }}
      /* Main tabs active states - CSS sibling selectors */
      .provider-main-tabs input[id$="-currencies"]:checked ~ .main-tab-buttons label[for$="-currencies"],
      .provider-main-tabs input[id$="-countries"]:checked ~ .main-tab-buttons label[for$="-countries"],
      .provider-main-tabs input[id$="-gamelist"]:checked ~ .main-tab-buttons label[for$="-gamelist"],
      .provider-main-tabs input[id$="-assets"]:checked ~ .main-tab-buttons label[for$="-assets"] {{
        background: rgb(59, 130, 246);
        border-color: rgb(59, 130, 246);
        color: white;
      }}
      .provider-main-tabs input[id$="-currencies"]:checked ~ .currencies-panel {{
        display: block;
      }}
      .provider-main-tabs input[id$="-countries"]:checked ~ .countries-panel {{
        display: block;
      }}
      .provider-main-tabs input[id$="-gamelist"]:checked ~ .gamelist-panel {{
        display: block;
      }}
      .provider-main-tabs input[id$="-assets"]:checked ~ .assets-panel {{
        display: block;
      }}

      /* Country type sub-tabs - match main tab styling */
      .country-type-tabs {{
        margin-top: 0.5rem;
      }}
      .country-type-tabs > input[type="radio"] {{
        display: none;
      }}
      .country-tab-buttons {{
        display: flex;
        gap: 0.5rem;
        margin-bottom: 1rem;
      }}
      .country-type-tabs .subtab {{
        flex: 1;
        text-align: center;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem;
        background: {t["bg_card"]};
        border: 1px solid {t["border"]};
        color: {t["text_secondary"]};
        font-size: 0.875rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s ease;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.375rem;
      }}
      .country-type-tabs .subtab:hover {{
        background: {t["bg_hover"]};
        border-color: rgba(59, 130, 246, 0.5);
      }}
      .country-type-tabs .restricted-panel,
      .country-type-tabs .regulated-panel {{
        display: none;
      }}
      .country-type-tabs input[id$="-restricted"]:checked ~ .country-tab-buttons label[for$="-restricted"],
      .country-type-tabs input[id$="-regulated"]:checked ~ .country-tab-buttons label[for$="-regulated"] {{
        background: rgb(59, 130, 246);
        border-color: rgb(59, 130, 246);
        color: white;
      }}
      .country-type-tabs input[id$="-restricted"]:checked ~ .restricted-panel {{
        display: block;
      }}
      .country-type-tabs input[id$="-regulated"]:checked ~ .regulated-panel {{
        display: block;
      }}

      /* Country section layout */
      .country-section {{
        margin-bottom: 1.5rem;
      }}
      .country-section:last-child {{
        margin-bottom: 0;
      }}

      /* Section header with counter */
      .country-section-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 0.75rem;
      }}
      .country-section-title {{
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.9rem;
        font-weight: 600;
        color: var(--text-primary);
      }}
      .country-count {{
        font-size: 0.8rem;
        color: var(--text-secondary);
        font-weight: 500;
      }}

      /* Disclaimer styling */
      .country-disclaimer {{
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-top: 0.75rem;
        padding: 0.5rem 0.75rem;
        border-radius: 8px;
        font-size: 0.8rem;
      }}
      .country-disclaimer.restricted {{
        background: rgba(239, 68, 68, 0.1);
        color: #EF4444;
        border: 1px solid rgba(239, 68, 68, 0.2);
      }}
      .country-disclaimer.regulated {{
        background: rgba(59, 130, 246, 0.1);
        color: {t["primary"]};
        border: 1px solid rgba(59, 130, 246, 0.2);
      }}
      .country-disclaimer svg {{
        flex-shrink: 0;
      }}

      /* Export button - small inline download link */
      .export-btn {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.35rem;
        padding: 0.4rem 0.75rem;
        font-size: 0.8rem;
        font-weight: 600;
        line-height: 1;
        background: #3B82F6;
        border: 1px solid #3B82F6;
        border-radius: 6px;
        color: #FFFFFF !important;
        cursor: pointer;
        text-decoration: none !important;
        transition: all 0.2s ease;
      }}
      .export-btn:hover {{
        transform: translateY(-1px);
        box-shadow: 0 4px 12px #3B82F640;
      }}
      .export-btn::before {{
        content: "↓";
        font-weight: bold;
        display: flex;
        align-items: center;
        justify-content: center;
      }}
      /* Panel header with title and export button */
      .panel-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 0.75rem;
      }}
      .panel-header .section-header {{
        margin-bottom: 0;
      }}

      /* Modal overlay */
      .modal-overlay {{
        display: none;
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.7);
        z-index: 10000;
        justify-content: center;
        align-items: center;
      }}
      .modal-overlay.open {{
        display: flex;
      }}

      /* Modal content */
      .modal-content {{
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 16px;
        width: 95%;
        max-width: 1500px;
        max-height: 80vh;
        overflow: hidden;
        display: flex;
        flex-direction: column;
      }}

      /* Modal header */
      .modal-header {{
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 1rem 1.5rem;
        border-bottom: 1px solid var(--border);
      }}
      .modal-header h3 {{
        margin: 0;
        color: var(--text-primary);
        font-size: 1.1rem;
        flex: 1;
      }}
      /* Hide auto-generated anchor link on modal headings */
      .modal-header h3 a {{
        display: none !important;
      }}
      .modal-header .modal-count {{
        font-size: 0.85rem;
        color: var(--text-secondary);
      }}
      .modal-header .export-btn {{
        margin-left: 0;
      }}
      .modal-close {{
        background: none;
        border: none;
        font-size: 1.5rem;
        color: var(--text-secondary);
        cursor: pointer;
        padding: 0;
        line-height: 1;
        margin-left: 0.5rem;
      }}
      .modal-close:hover {{
        color: var(--text-primary);
      }}

      /* Modal search input */
      .modal-search {{
        padding: 1rem 1.5rem;
      }}
      .modal-search input {{
        width: 100%;
        padding: 0.75rem 1rem;
        border: 1px solid var(--border);
        border-radius: 8px;
        background: var(--input-bg);
        color: var(--text-primary);
        font-size: 0.9rem;
        box-sizing: border-box;
      }}
      .modal-search input::placeholder {{
        color: var(--text-muted);
      }}
      .modal-search input:focus {{
        outline: none;
        border-color: var(--primary);
      }}

      /* Modal tabs */
      .modal-tabs {{
        padding: 0 1.5rem 1.5rem;
        overflow-y: auto;
        flex: 1;
      }}
      .modal-tabs > input[type="radio"] {{
        display: none;
      }}
      .modal-tab-buttons {{
        display: flex;
        gap: 0.5rem;
        margin-bottom: 1rem;
      }}
      .modal-tab-buttons label.subtab {{
        flex: 1;
        text-align: center;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem;
        background: var(--bg-card);
        border: 1px solid var(--border);
        color: var(--text-secondary);
        font-size: 0.875rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s ease;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.375rem;
      }}
      .modal-tab-buttons label.subtab:hover {{
        background: var(--bg-hover);
        border-color: rgba(59, 130, 246, 0.5);
      }}
      .modal-tab-buttons label.subtab svg {{
        flex-shrink: 0;
      }}

      /* Modal tab panels */
      .modal-restricted-panel,
      .modal-regulated-panel {{
        display: none;
        flex-wrap: wrap;
        gap: 0.5rem;
      }}
      .modal-tabs input[id$="-restricted"]:checked ~ .modal-tab-buttons label[for$="-restricted"],
      .modal-tabs input[id$="-regulated"]:checked ~ .modal-tab-buttons label[for$="-regulated"] {{
        background: rgb(59, 130, 246);
        border-color: rgb(59, 130, 246);
        color: white;
      }}
      .modal-tabs input[id$="-restricted"]:checked ~ .modal-restricted-panel {{
        display: flex;
      }}
      .modal-tabs input[id$="-regulated"]:checked ~ .modal-regulated-panel {{
        display: flex;
      }}

      /* View All button */
      .view-all-btn {{
        background: var(--bg-hover);
        border: 1px dashed var(--border);
        border-radius: 20px;
        padding: 0.5rem 1rem;
        color: var(--text-secondary);
        cursor: pointer;
        font-size: 0.85rem;
        margin-top: 0.75rem;
        transition: all 0.2s ease;
      }}
      .view-all-btn:hover {{
        background: var(--primary);
        color: white;
        border-color: var(--primary);
        border-style: solid;
      }}

      /* In-panel export button - match view-all-btn style */
      div:has(> .view-all-btn) > .export-btn {{
        background: var(--bg-hover) !important;
        border: 1px dashed var(--border) !important;
        border-radius: 20px !important;
        padding: 0.5rem 1rem !important;
        color: var(--text-secondary) !important;
        font-size: 0.85rem !important;
        font-weight: 500 !important;
        transition: all 0.2s ease !important;
        text-decoration: none !important;
        box-shadow: none !important;
        transform: none !important;
      }}
      div:has(> .view-all-btn) > .export-btn:hover {{
        background: var(--primary) !important;
        color: white !important;
        border-color: var(--primary) !important;
        border-style: solid !important;
        box-shadow: none !important;
        transform: none !important;
      }}

      /* Hidden by search */
      .country-tag.hidden {{
        display: none !important;
      }}
      .currency-btn.hidden {{
        display: none !important;
      }}

      /* Currency modal grid - more columns since modal is wider */
      .modal-currency-grid {{
        grid-template-columns: repeat(4, 1fr) !important;
      }}

      @media (max-width: 640px) {{
        .modal-currency-grid {{
          grid-template-columns: repeat(2, 1fr) !important;
        }}
      }}

      /* Currency more toggle styled as currency button */
      .currency-btn.more-toggle {{
        background: var(--bg-hover) !important;
        border-style: dashed !important;
        cursor: pointer;
      }}
      .currency-btn.more-toggle:hover {{
        background: var(--primary) !important;
        color: white !important;
        border-color: var(--primary) !important;
        border-style: solid !important;
      }}

      /* Modal body scrollable area */
      .modal-body {{
        padding: 0 1.5rem 1.5rem;
        overflow-y: auto;
        flex: 1;
      }}

      /* Currency modal tabs - reuse modal-tabs pattern */
      .currency-modal-tabs > input[type="radio"] {{
        display: none;
      }}
      .currency-modal-tabs .fiat-panel,
      .currency-modal-tabs .crypto-panel {{
        display: none;
      }}
      .currency-modal-tabs input[id$="-fiat"]:checked ~ .fiat-panel {{
        display: block;
      }}
      .currency-modal-tabs input[id$="-crypto"]:checked ~ .crypto-panel {{
        display: block;
      }}
      .currency-modal-tabs input[id$="-fiat"]:checked ~ .modal-tab-buttons label[for$="-fiat"],
      .currency-modal-tabs input[id$="-crypto"]:checked ~ .modal-tab-buttons label[for$="-crypto"] {{
        background: rgb(59, 130, 246);
        border-color: rgb(59, 130, 246);
        color: white;
      }}

      /* Modal header with count */
      .modal-header .modal-count {{
        font-size: 0.85rem;
        color: var(--text-secondary);
        margin-left: auto;
        margin-right: 1rem;
      }}

      /* Game List Modal - larger size */
      .modal-content.modal-lg {{
        max-width: 1500px;
        max-height: 85vh;
      }}

      /* Games filter bar */
      .games-filter-bar {{
        padding: 1rem 1.5rem;
        border-bottom: 1px solid var(--border);
        background: var(--bg-secondary);
      }}
      .filter-row {{
        display: flex;
        gap: 1rem;
        flex-wrap: wrap;
      }}
      .filter-group {{
        flex: 1;
        min-width: 150px;
      }}
      .filter-group label {{
        display: block;
        font-size: 0.75rem;
        color: var(--text-secondary);
        margin-bottom: 0.25rem;
        font-weight: 600;
      }}
      .filter-group input,
      .filter-group select {{
        width: 100%;
        padding: 0.5rem 0.75rem;
        border: 1px solid var(--border);
        border-radius: 8px;
        background: var(--input-bg);
        color: var(--text-primary);
        font-size: 0.85rem;
        box-sizing: border-box;
      }}
      .filter-group input:focus,
      .filter-group select:focus {{
        outline: none;
        border-color: var(--primary);
      }}

      /* Collapsible filter wrapper - desktop: always show content */
      .games-filter-collapse {{
        display: block;
      }}
      .games-filter-collapse > summary {{
        display: none;
      }}
      .games-filter-collapse > summary::-webkit-details-marker {{
        display: none;
      }}
      /* Force content visible on desktop regardless of open state */
      .games-filter-collapse > .games-filter-bar {{
        display: block !important;
      }}
      .filter-toggle {{
        display: flex;
        align-items: center;
        gap: 0.5rem;
      }}
      .filter-chevron {{
        transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        margin-left: auto;
      }}
      .games-filter-collapse[open] .filter-chevron {{
        transform: rotate(180deg);
      }}

      /* Animation keyframes for filter bar */
      @keyframes filterSlideDown {{
        from {{
          opacity: 0;
          transform: translateY(-10px);
        }}
        to {{
          opacity: 1;
          transform: translateY(0);
        }}
      }}
      @keyframes filterSlideUp {{
        from {{
          opacity: 1;
          transform: translateY(0);
        }}
        to {{
          opacity: 0;
          transform: translateY(-10px);
        }}
      }}

      /* Apply button - hidden on desktop */
      .filter-apply-btn {{
        display: none;
      }}

      /* Games list */
      .games-list {{
        padding: 1rem 1.5rem;
        overflow-y: auto;
        max-height: calc(85vh - 200px);
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
      }}

      /* Game card */
      .game-card {{
        display: flex;
        gap: 1rem;
        padding: 1rem;
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 12px;
        transition: all 0.2s;
      }}
      .game-card:hover {{
        border-color: var(--primary);
        box-shadow: 0 4px 12px var(--shadow);
      }}
      .game-card.hidden {{
        display: none !important;
      }}

      /* Thumbnail - portrait ratio to match 440x590 images */
      .game-thumbnail {{
        width: 64px;
        height: 86px;
        border-radius: 8px;
        background: var(--bg-secondary);
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        overflow: hidden;
      }}
      .game-thumbnail img {{
        width: 100%;
        height: 100%;
        object-fit: cover;
      }}
      .game-thumbnail .placeholder-icon {{
        color: var(--text-muted);
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--bg-secondary);
      }}

      /* Game info */
      .game-info {{
        flex: 1;
        min-width: 0;
      }}
      .game-title {{
        font-size: 1rem;
        font-weight: 600;
        color: var(--text-primary);
        margin-bottom: 0.5rem;
      }}

      /* Game meta row */
      .game-meta {{
        display: flex;
        gap: 1.5rem;
        margin-bottom: 0.5rem;
        flex-wrap: wrap;
      }}
      .game-meta-item {{
        display: flex;
        flex-direction: column;
        gap: 0.125rem;
      }}
      .meta-label {{
        font-size: 0.7rem;
        color: var(--text-muted);
        text-transform: uppercase;
      }}
      .meta-value {{
        font-size: 0.85rem;
        color: var(--text-primary);
        font-weight: 500;
      }}

      /* Volatility badges */
      .volatility-badge {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 0.2rem 0.5rem;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
        line-height: 1;
      }}
      .volatility-badge.low {{
        background: rgba(34, 197, 94, 0.2);
        color: #22C55E;
      }}
      .volatility-badge.medium-low {{
        background: rgba(132, 204, 22, 0.2);
        color: #84CC16;
      }}
      .volatility-badge.medium {{
        background: rgba(245, 158, 11, 0.2);
        color: #F59E0B;
      }}
      .volatility-badge.medium-high {{
        background: rgba(249, 115, 22, 0.2);
        color: #F97316;
      }}
      .volatility-badge.high {{
        background: rgba(239, 68, 68, 0.2);
        color: #EF4444;
      }}

      /* Feature tags */
      .game-features {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.375rem;
      }}
      .feature-tag {{
        padding: 0.25rem 0.5rem;
        background: var(--bg-secondary);
        border: 1px solid var(--border);
        border-radius: 6px;
        font-size: 0.7rem;
        color: var(--text-secondary);
      }}

      /* Game list empty state */
      .games-empty {{
        text-align: center;
        padding: 3rem 1.5rem;
        color: var(--text-muted);
      }}
      .games-empty svg {{
        margin-bottom: 1rem;
        opacity: 0.5;
      }}

      /* Game list loading state */
      .games-loading {{
        text-align: center;
        padding: 3rem 1.5rem;
        color: var(--text-muted);
        font-size: 0.9rem;
      }}

      /* Mobile responsive for modals */
      @media (max-width: 640px) {{
        .modal-content,
        .modal-content.modal-lg {{
          max-width: 100%;
          width: calc(100% - 1rem);
          margin: 0.5rem;
          max-height: 90vh;
        }}
        .filter-row {{
          flex-direction: column;
        }}
        .filter-group {{
          min-width: 100%;
        }}
        /* Keep horizontal layout on mobile */
        .game-card {{
          flex-direction: row;
          gap: 0.75rem;
          padding: 0.75rem;
        }}
        /* Smaller thumbnail on mobile */
        .game-thumbnail {{
          width: 50px;
          height: 67px;
          flex-shrink: 0;
        }}
        .game-title {{
          font-size: 0.9rem;
        }}
        .game-meta {{
          gap: 0.5rem;
        }}
        .game-meta-item {{
          min-width: 0;
        }}
        .meta-label {{
          font-size: 0.65rem;
        }}
        .meta-value {{
          font-size: 0.75rem;
        }}
        .volatility-badge {{
          font-size: 0.65rem;
          padding: 0.15rem 0.35rem;
        }}
        /* Show features on mobile (compact) */
        .game-features {{
          display: flex;
          flex-wrap: wrap;
          gap: 0.25rem;
          margin-top: 0.5rem;
        }}
        .feature-tag {{
          font-size: 0.65rem;
          padding: 0.2rem 0.4rem;
        }}
        /* Collapsible filter on mobile */
        .games-filter-collapse {{
          display: block;
          border-bottom: 1px solid var(--border);
        }}
        .games-filter-collapse > summary {{
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 0.75rem 1rem;
          cursor: pointer;
          font-weight: 600;
          font-size: 0.9rem;
          color: var(--text-primary);
          list-style: none;
          background: var(--bg-secondary);
          transition: background 0.2s;
        }}
        .games-filter-collapse > summary:active {{
          background: var(--bg-hover);
        }}
        .games-filter-collapse[open] > summary {{
          border-bottom: 1px solid var(--border);
        }}
        /* Override desktop forced visibility - hide when closed on mobile */
        .games-filter-collapse > .games-filter-bar {{
          display: none !important;
        }}
        .games-filter-collapse[open] > .games-filter-bar {{
          display: block !important;
          padding: 0.75rem 1rem 1rem;
          background: var(--bg-secondary);
        }}
        .filter-apply-btn {{
          display: block !important;
          width: 100%;
          margin-top: 1rem;
          padding: 0.75rem 1rem;
          background: var(--primary);
          color: white;
          border: none;
          border-radius: 8px;
          font-size: 0.9rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s;
        }}
        .filter-apply-btn:active {{
          transform: scale(0.98);
          opacity: 0.9;
        }}

        /* Export buttons - compact with text on mobile */
        .modal-header .export-btn {{
          font-size: 0.7rem !important;
          padding: 0.3rem 0.6rem !important;
          white-space: nowrap;
        }}
        .panel-header .export-btn {{
          font-size: 0.7rem !important;
          padding: 0.3rem 0.6rem !important;
          white-space: nowrap;
        }}

        /* Hide icon in Streamlit download button on mobile */
        [data-testid="stDownloadButton"] button svg,
        [data-testid="stDownloadButton"] button span[data-testid="stIconMaterial"] {{
          display: none !important;
        }}
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
        color: {t["text_secondary"]} !important;
        font-weight: 700 !important;
      }}
      [data-testid="stWidgetLabel"] {{
        color: {t["text_secondary"]} !important;
      }}
      [data-testid="stWidgetLabel"] > label,
      [data-testid="stWidgetLabel"] label,
      [data-testid="stWidgetLabel"] p {{
        font-weight: 700 !important;
        color: {t["text_secondary"]} !important;
      }}
      .stSelectbox > div > div, .stTextInput > div > div > input {{
        border-radius: 10px;
        border: 1px solid {t["border"]} !important;
        background: {t["input_bg"]} !important;
        color: {t["text_primary"]} !important;
        font-weight: 600 !important;
      }}
      .stSelectbox [data-testid="stSelectbox"] div {{
        color: {t["text_primary"]} !important;
      }}
      .stSelectbox [data-testid="stSelectbox"] span {{
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
        color: {t["text_primary"]} !important;
      }}
      .stTextInput input::placeholder {{
        color: {t["text_secondary"]} !important;
        opacity: 1 !important;
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
      [data-testid="stSelectboxVirtualDropdown"] * {{
        color: {t["text_primary"]} !important;
      }}
      [data-testid="stSelectboxVirtualDropdown"] [role="option"] {{
        background: transparent !important;
      }}
      [data-testid="stSelectboxVirtualDropdown"] [role="option"][aria-selected="true"] {{
        background: {t["bg_hover"]} !important;
      }}

      /* Provider cards grid container */
      .provider-cards {{
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 0.75rem;
      }}

      /* Provider card styling - using details element */
      .provider-card {{
        background: {"#F3F4F6" if current_theme == "light" else t["bg_card"]};
        border: 1px solid {"#E5E7EB" if current_theme == "light" else t["border"]};
        border-radius: 12px;
        box-shadow: 0 1px 3px {t["shadow"]};
        transition: all 0.2s ease;
      }}
      /* Full width when card is expanded */
      .provider-card[open] {{
        grid-column: 1 / -1;
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
        border-top: 1px solid var(--border);
        margin: 0 1rem;
        padding-top: 0.75rem;
      }}

      /* Card header layout classes */
      .card-header-top {{
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 0.5rem;
      }}
      .card-header-left {{
        display: flex;
        gap: 0.75rem;
        align-items: center;
      }}
      .provider-icon {{
        width: 48px;
        height: 48px;
        background: linear-gradient(135deg, var(--bg-hover) 0%, var(--bg-secondary) 100%);
        border-radius: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
      }}
      .provider-name {{
        font-size: 1rem;
        font-weight: 600;
        color: var(--text-primary);
      }}
      .provider-games {{
        font-size: 0.8rem;
        color: var(--text-secondary);
      }}
      .card-games-section {{
        margin-top: 0.75rem;
      }}
      .games-label {{
        font-size: 0.75rem;
        color: var(--text-secondary);
        margin-bottom: 0.5rem;
        font-weight: 600;
      }}

      /* Section headers and icons */
      .section-header {{
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.9rem;
        font-weight: 600;
        color: var(--text-primary);
        margin: 0.75rem 0;
      }}
      .icon-warning {{ color: var(--chart-yellow); }}
      .icon-regulated {{ color: var(--primary); }}
      .icon-success {{ color: var(--chart-green); }}

      /* Country tag variants */
      /* Restricted - red (danger - cannot offer) */
      .country-tag.restricted {{
        border-color: #EF4444;
        background: rgba(239, 68, 68, 0.1);
      }}
      .country-tag.restricted .iso {{
        background: #EF4444;
        color: white;
      }}
      /* Regulated - blue (info - can offer with compliance) */
      .country-tag.regulated {{
        border-color: #3B82F6;
        background: rgba(59, 130, 246, 0.1);
      }}
      .country-tag.regulated .iso {{
        background: #3B82F6;
        color: white;
      }}

      /* Utility classes */
      .more-text {{
        font-size: 0.75rem;
        color: var(--text-muted);
        margin-top: 0.25rem;
      }}
      .muted-text {{
        color: var(--text-muted);
      }}

      /* Button styling - Figma style */
      .stButton > button,
      .stButton button,
      button[data-testid="stBaseButton-secondary"],
      button[data-testid="stBaseButton-minimal"],
      button[kind="secondary"] {{
        border-radius: 6px !important;
        font-weight: 500 !important;
        font-size: 0.8rem !important;
        transition: all 0.2s !important;
        background: {t["bg_card"]} !important;
        color: {t["text_primary"]} !important;
        border: 1px solid {t["border"]} !important;
        padding: 0.35rem 0.75rem !important;
        min-height: unset !important;
        line-height: 1.4 !important;
      }}
      .stButton > button:hover,
      .stButton button:hover,
      button[data-testid="stBaseButton-secondary"]:hover,
      button[data-testid="stBaseButton-minimal"]:hover,
      button[kind="secondary"]:hover {{
        box-shadow: 0 2px 8px {t["shadow"]};
        background: {t["bg_hover"]} !important;
        border-color: {t["primary"]} !important;
        color: {t["text_primary"]} !important;
      }}
      /* Primary button (active toggle) */
      .stButton > button[data-testid="stBaseButton-primary"],
      button[data-testid="stBaseButton-primary"],
      button[kind="primary"] {{
        background: {t["primary"]} !important;
        color: {t["primary_foreground"]} !important;
        border: none !important;
      }}
      /* Mode toggle buttons: unselected state = no border, hover shows border */
      button[key="btn_supported"]:not([data-testid="stBaseButton-primary"]),
      button[key="btn_restricted"]:not([data-testid="stBaseButton-primary"]) {{
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
        color: {t["text_secondary"]} !important;
      }}
      button[key="btn_supported"]:not([data-testid="stBaseButton-primary"]):hover,
      button[key="btn_restricted"]:not([data-testid="stBaseButton-primary"]):hover {{
        background: {t["bg_hover"]} !important;
        border: 1px solid {t["border"]} !important;
        color: {t["text_primary"]} !important;
      }}
      .stButton:has(button[key="btn_supported"]),
      .stButton:has(button[key="btn_restricted"]) {{
        box-shadow: none !important;
      }}
      button[key="btn_supported"][data-testid="stBaseButton-secondary"]:hover,
      button[key="btn_restricted"][data-testid="stBaseButton-secondary"]:hover {{
        background: {t["bg_hover"]} !important;
        border-color: {t["border"]} !important;
        color: {t["text_primary"]} !important;
      }}

      /* Download button - Figma style */
      .stDownloadButton > button {{
        border-radius: 10px !important;
        font-weight: 500 !important;
        background: {t["primary"]} !important;
        color: {t["primary_foreground"]} !important;
        border: none !important;
        transition: all 0.2s ease !important;
      }}
      .stDownloadButton > button:hover {{
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 12px {t["primary"]}40 !important;
      }}

      /* Clear all button overrides (beat generic button styling) */
      .stButton > button[key="btn_clear_all"] {{
        background: transparent !important;
        border: 0 !important;
        border-color: transparent !important;
        outline: none !important;
        box-shadow: none !important;
        color: {t["text_secondary"]} !important;
        padding: 0 !important;
        margin: 0 !important;
        font-size: 0.75rem !important;
        font-weight: 500 !important;
        min-height: unset !important;
        height: auto !important;
        line-height: 1.4 !important;
        border-radius: 0 !important;
        text-decoration: none !important;
        cursor: pointer !important;
      }}
      .stButton > button[key="btn_clear_all"] * {{
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
        outline: none !important;
      }}
      .stButton > button[key="btn_clear_all"]:hover {{
        color: {t["text_primary"]} !important;
        background: transparent !important;
        box-shadow: none !important;
        border: none !important;
        text-decoration: underline !important;
        transform: none !important;
      }}
      .stButton > button[key="btn_clear_all"]:focus,
      .stButton > button[key="btn_clear_all"]:active {{
        background: transparent !important;
        box-shadow: none !important;
        border: none !important;
        outline: none !important;
      }}
      /* Streamlit wraps buttons in stElementContainer with the key */
      div[data-testid="stElementContainer"][key="btn_clear_all"] {{
        width: fit-content !important;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
      }}
      div[data-testid="stElementContainer"][key="btn_clear_all"] .stButton {{
        margin: 0 !important;
        padding: 0 !important;
        display: inline-flex !important;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
      }}
      div[data-testid="stElementContainer"][key="btn_clear_all"] button,
      div[data-testid="stElementContainer"][key="btn_clear_all"] button[data-testid="stBaseButton-secondary"] {{
        background: transparent !important;
        border: none !important;
        outline: none !important;
        box-shadow: none !important;
        color: {t["text_secondary"]} !important;
        padding: 0 !important;
        margin: 0 !important;
        min-height: unset !important;
        height: auto !important;
        line-height: 1.4 !important;
        border-radius: 0 !important;
      }}
      div[data-testid="stElementContainer"][key="btn_clear_all"] * {{
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
        color: inherit !important;
      }}
      div[data-testid="stElementContainer"][key="btn_clear_all"] button * {{
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
        outline: none !important;
      }}
      div[data-testid="stElementContainer"][key="btn_clear_all"] button:hover,
      div[data-testid="stElementContainer"][key="btn_clear_all"] button[data-testid="stBaseButton-secondary"]:hover {{
        color: {t["text_primary"]} !important;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        text-decoration: underline !important;
      }}

      /* Clear all (Active filters row) - plain text style */
      div[data-testid="stHorizontalBlock"]:has(.filter-badges-container) > div:nth-child(2) {{
        flex: 0 0 auto !important;
        width: fit-content !important;
        max-width: fit-content !important;
      }}
      div[data-testid="stHorizontalBlock"]:has(.filter-badges-container) > div:nth-child(2) .stButton > button,
      div[data-testid="stHorizontalBlock"]:has(.filter-badges-container) > div:nth-child(2) button {{
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
        padding: 0.125rem 0.5rem !important;
        margin: 0 !important;
        min-height: 0 !important;
        height: auto !important;
        color: {t["text_secondary"]} !important;
        font-size: 0.8rem !important;
        font-weight: 500 !important;
        line-height: 1.2 !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: flex-start !important;
        border: 1px solid transparent !important;
        border-radius: 0.5rem !important;
      }}
      div[data-testid="stHorizontalBlock"]:has(.filter-badges-container) > div:nth-child(2) .stButton > button:hover,
      div[data-testid="stHorizontalBlock"]:has(.filter-badges-container) > div:nth-child(2) button:hover {{
        color: {t["text_primary"]} !important;
        text-decoration: none !important;
        background: {t["bg_hover"]} !important;
        border-color: {t["border"]} !important;
        font-weight: 600 !important;
      }}
      div[data-testid="stHorizontalBlock"]:has(.filter-badges-container) > div:nth-child(2) .stButton > button:focus,
      div[data-testid="stHorizontalBlock"]:has(.filter-badges-container) > div:nth-child(2) .stButton > button:focus-visible,
      div[data-testid="stHorizontalBlock"]:has(.filter-badges-container) > div:nth-child(2) button:focus,
      div[data-testid="stHorizontalBlock"]:has(.filter-badges-container) > div:nth-child(2) button:focus-visible {{
        outline: none !important;
        box-shadow: none !important;
      }}

      /* Hide sidebar toggle */
      button[data-testid="baseButton-headerNoPadding"] {{ display: none; }}

      /* ===========================================
         BUTTON TEXT WRAPPING FIXES (all screen sizes)
         =========================================== */
      /* Logout button - always prevent wrapping */
      .st-key-btn_logout button {{
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
      }}
      /* Export button - always prevent wrapping */
      .st-key-btn_export_excel button {{
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        min-width: max-content !important;
      }}

      /* ===========================================
         TABLET RESPONSIVE (1100px and below)
         =========================================== */
      @media (max-width: 1100px) {{
        /* Logout button - show just arrow */
        .st-key-btn_logout button {{
          font-size: 0 !important;
          padding: 0.4rem 0.6rem !important;
        }}
        .st-key-btn_logout button::after {{
          content: "→" !important;
          font-size: 1rem !important;
        }}
        /* Export button more compact */
        .st-key-btn_export_excel button {{
          font-size: 0.75rem !important;
          padding: 0.4rem 0.6rem !important;
        }}
        /* Provider cards - single column on tablets */
        .provider-cards {{
          grid-template-columns: 1fr !important;
        }}
      }}

      /* ===========================================
         MOBILE RESPONSIVE STYLES
         =========================================== */
      @media (max-width: 768px) {{
        /* Filter container - full width */
        .block-container {{
          padding-left: 0.75rem !important;
          padding-right: 0.75rem !important;
        }}

        /* Filter columns stack on mobile */
        [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] {{
          flex-direction: column !important;
          gap: 0.5rem !important;
        }}
        [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > div {{
          width: 100% !important;
          flex: 1 1 100% !important;
        }}

        /* Stats cards - stack vertically */
        .stats-container {{
          flex-direction: column !important;
          gap: 0.75rem !important;
        }}

        /* Provider cards - single column grid */
        .provider-cards {{
          grid-template-columns: 1fr !important;
        }}

        /* Provider card details - smaller text */
        .provider-card .tag {{
          font-size: 0.65rem !important;
          padding: 0.2rem 0.4rem !important;
        }}
        .currency-grid {{
          grid-template-columns: repeat(3, 1fr) !important;
        }}
        .country-grid {{
          grid-template-columns: repeat(2, 1fr) !important;
        }}

        /* Main tabs wrap to 2 rows */
        .main-tab-buttons {{
          flex-wrap: wrap !important;
          gap: 0.5rem !important;
        }}
        .provider-main-tabs .main-tab {{
          flex: 0 0 calc(50% - 0.25rem) !important;
          min-width: calc(50% - 0.25rem) !important;
          font-size: 0.7rem !important;
          padding: 0.4rem 0.5rem !important;
        }}

        /* Currency sub-tabs also wrap if needed */
        .currency-tab-buttons {{
          flex-wrap: wrap !important;
          gap: 0.5rem !important;
        }}
        .currency-tabs label.subtab {{
          flex: 0 0 calc(50% - 0.25rem) !important;
          min-width: calc(50% - 0.25rem) !important;
          font-size: 0.75rem !important;
        }}
      }}

      /* ===========================================
         MOBILE HEADER FIX - 2 rows: centered logo, then buttons
         =========================================== */
      @media (max-width: 640px) {{
        .st-key-sticky_header {{
          padding: 0.5rem !important;
        }}

        /* Fix header-to-content spacing for taller mobile header */
        .block-container {{
          padding-top: 7rem !important;
          margin-top: -1rem !important;
        }}

        /* Stack main header columns into rows */
        .st-key-sticky_header > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] {{
          flex-wrap: wrap !important;
          gap: 0.5rem !important;
          justify-content: center !important;
        }}
        /* Logo column - full width, centered */
        .st-key-sticky_header > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] > div:first-child {{
          width: 100% !important;
          flex: 0 0 100% !important;
          display: flex !important;
          justify-content: center !important;
        }}
        /* Spacer column - hide it */
        .st-key-sticky_header > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] > div:nth-child(2) {{
          display: none !important;
        }}
        /* Buttons column - full width, centered */
        .st-key-sticky_header > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] > div:last-child {{
          width: 100% !important;
          flex: 0 0 100% !important;
          display: flex !important;
          justify-content: center !important;
        }}

        /* Center the logo container and its content */
        .st-key-sticky_header .logo-container {{
          justify-content: center !important;
          width: 100% !important;
        }}
        .st-key-sticky_header [data-testid="stHorizontalBlock"] > div:first-child [data-testid="stMarkdownContainer"],
        .st-key-sticky_header [data-testid="stHorizontalBlock"] > div:first-child {{
          display: flex !important;
          justify-content: center !important;
          width: 100% !important;
          text-align: center !important;
        }}

        /* Header buttons - center on mobile with spacing */
        div.stVerticalBlock.st-key-header_buttons[direction="column"] {{
          justify-content: center !important;
          margin-top: 0.5rem !important;
        }}
        /* Button styling */
        .st-key-btn_theme button {{
          padding: 0.4rem 0.75rem !important;
          min-width: auto !important;
          white-space: nowrap !important;
        }}
        /* Reset logout button - show original text, remove tablet ::after */
        .st-key-btn_logout button {{
          font-size: 0.8rem !important;
          padding: 0.4rem 0.75rem !important;
          min-width: auto !important;
          white-space: nowrap !important;
        }}
        .st-key-btn_logout button::after {{
          content: none !important;
        }}

        /* Export button - compact on mobile */
        .st-key-btn_export_excel button {{
          font-size: 0 !important;
          padding: 0.4rem 0.6rem !important;
          min-width: auto !important;
        }}


        /* Constrain expanded card content on mobile */
        .provider-card {{
          max-width: 100% !important;
          overflow-x: hidden !important;
        }}
        .provider-card .card-details-content {{
          max-width: 100% !important;
          overflow-x: hidden !important;
          box-sizing: border-box !important;
        }}
        .provider-card .currency-grid {{
          max-width: 100% !important;
          box-sizing: border-box !important;
        }}
        .provider-card .currency-btn {{
          min-width: 0 !important;
          overflow: hidden !important;
          text-overflow: ellipsis !important;
          padding: 0.5rem 0.75rem !important;
          font-size: 0.75rem !important;
        }}
      }}

      /* Extra small screens */
      @media (max-width: 420px) {{
        .currency-grid {{
          grid-template-columns: repeat(2, 1fr) !important;
        }}
        .country-grid {{
          grid-template-columns: 1fr !important;
        }}
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

# Tab toggle handler (client-side)
# Load games data for injection into JavaScript
_games_json_data = load_all_games_json()
components.html(
    """
    <script>
    (function () {
      try {
      // Attach to the Streamlit page (parent), not the iframe
      const doc = window.parent.document;

      // Remove old listeners before re-attaching (prevents duplicates AND stale refs)
      if (doc.__ttCleanup) {
        try { doc.__ttCleanup(); } catch(e) {}
      }

      // Reset init flag on each run so listeners re-attach after rerun
      doc.__ttStopPropInit = false;

      if (doc.__ttStopPropInit) return;
      doc.__ttStopPropInit = true;

      // Store all listeners for cleanup
      var listeners = [];
      function addListener(target, event, handler, capture) {
        try {
          target.addEventListener(event, handler, capture || false);
          listeners.push({ target: target, event: event, handler: handler, capture: capture || false });
        } catch(e) { console.warn('addListener error:', e); }
      }

      doc.__ttCleanup = function() {
        listeners.forEach(function(l) {
          try { l.target.removeEventListener(l.event, l.handler, l.capture); } catch(e) {}
        });
        listeners = [];
        doc.__ttStopPropInit = false;
      };

      function stopIfTabClick(e) {
        try {
        // Currency sub-tabs - explicitly check radio since stopPropagation prevents default
        const currencySubtab = e.target.closest('.currency-tabs label.subtab');
        if (currencySubtab) {
          if (e.type === 'click') {
            const radioId = currencySubtab.getAttribute('for');
            if (radioId) {
              const radio = doc.getElementById(radioId);
              if (radio) radio.checked = true;
            }
          }
          e.stopPropagation();
          return;
        }

        // Country sub-tabs
        const countrySubtab = e.target.closest('.country-type-tabs label.subtab');
        if (countrySubtab) {
          if (e.type === 'click') {
            const radioId = countrySubtab.getAttribute('for');
            if (radioId) {
              const radio = doc.getElementById(radioId);
              if (radio) radio.checked = true;
            }
          }
          e.stopPropagation();
          return;
        }

        // Main tabs
        const mainTab = e.target.closest('.provider-main-tabs label.main-tab');
        if (mainTab) {
          if (e.type === 'click') {
            const radioId = mainTab.getAttribute('for');
            if (radioId) {
              const radio = doc.getElementById(radioId);
              if (radio) radio.checked = true;

              // Open games modal when clicking Game List tab
              if (radioId.includes('-gamelist')) {
                const pid = radioId.replace('main_', '').replace('-gamelist', '');
                const modal = doc.getElementById('games-modal-' + pid);
                if (modal) {
                  populateGamesModal(modal, pid);
                  modal.classList.add('open');
                  // On mobile, collapse filter by default
                  const filterDetails = modal.querySelector('.games-filter-collapse');
                  if (filterDetails) {
                    if (window.innerWidth <= 640) {
                      filterDetails.removeAttribute('open');
                    } else {
                      filterDetails.setAttribute('open', '');
                    }
                  }
                  const searchInput = modal.querySelector('.game-search');
                  if (searchInput) {
                    setTimeout(function() { searchInput.focus(); }, 100);
                  }
                }
              }
            }
          }
          e.stopPropagation();
          return;
        }
        } catch(err) { console.warn('stopIfTabClick error:', err); }
      }

      // Use capture phase so we intercept before <summary> handles it
      addListener(doc, 'pointerdown', stopIfTabClick, true);
      addListener(doc, 'click', stopIfTabClick, true);

      // Accordion: close other cards when one opens
      addListener(doc, 'click', function(e) {
        try {
        const summary = e.target.closest('details.provider-card > summary');
        if (summary) {
          const card = summary.parentElement;
          if (!card.open) {
            // Card is about to open - close all others
            doc.querySelectorAll('details.provider-card[open]').forEach(function(d) {
              if (d !== card) d.open = false;
            });
          }
        }
        } catch(err) { console.warn('Accordion error:', err); }
      }, true);

      // Modal open (View All button)
      addListener(doc, 'click', function(e) {
        try {
        const openBtn = e.target.closest('[data-modal]');
        if (openBtn) {
          const modalId = openBtn.getAttribute('data-modal');
          const modal = doc.getElementById(modalId);
          if (modal) {
            modal.classList.add('open');
            // Focus search input when modal opens
            const searchInput = modal.querySelector('.country-search');
            if (searchInput) {
              setTimeout(function() { searchInput.focus(); }, 100);
            }
          }
          e.stopPropagation();
          e.preventDefault();
        }
        } catch(err) { console.warn('Modal open error:', err); }
      });

      // Helper: switch back to currencies tab when closing games modal
      function switchToCurrenciesTab(modalId) {
        try {
        if (modalId && modalId.startsWith('games-modal-')) {
          const pid = modalId.replace('games-modal-', '');
          const currenciesRadio = doc.getElementById('main_' + pid + '-currencies');
          if (currenciesRadio) currenciesRadio.checked = true;
        }
        } catch(err) {}
      }

      // Modal close (X button)
      addListener(doc, 'click', function(e) {
        try {
        const closeBtn = e.target.closest('[data-close-modal]');
        if (closeBtn) {
          const modalId = closeBtn.getAttribute('data-close-modal');
          const modal = doc.getElementById(modalId);
          if (modal) {
            modal.classList.remove('open');
            switchToCurrenciesTab(modalId);
          }
          e.stopPropagation();
        }
        } catch(err) { console.warn('Modal close error:', err); }
      });

      // Modal close (backdrop click)
      addListener(doc, 'click', function(e) {
        try {
        if (e.target.classList.contains('modal-overlay')) {
          e.target.classList.remove('open');
          switchToCurrenciesTab(e.target.id);
        }
        } catch(err) { console.warn('Backdrop click error:', err); }
      });

      // Modal close (ESC key)
      addListener(doc, 'keydown', function(e) {
        try {
        if (e.key === 'Escape') {
          doc.querySelectorAll('.modal-overlay.open').forEach(function(m) {
            m.classList.remove('open');
            switchToCurrenciesTab(m.id);
          });
        }
        } catch(err) { console.warn('ESC key error:', err); }
      });

      // Modal tab click handler
      addListener(doc, 'click', function(e) {
        try {
        const modalSubtab = e.target.closest('.modal-tabs label.subtab');
        if (modalSubtab) {
          const radioId = modalSubtab.getAttribute('for');
          if (radioId) {
            const radio = doc.getElementById(radioId);
            if (radio) radio.checked = true;
          }
          e.stopPropagation();
        }
        } catch(err) { console.warn('Modal tab error:', err); }
      }, true);

      // Country search filter
      addListener(doc, 'input', function(e) {
        try {
        if (e.target.classList.contains('country-search')) {
          const query = e.target.value.toLowerCase();
          const modalId = e.target.getAttribute('data-target');
          const modal = doc.getElementById(modalId);
          if (modal) {
            modal.querySelectorAll('.country-tag').forEach(function(tag) {
              const name = tag.getAttribute('data-name') || tag.textContent.toLowerCase();
              tag.classList.toggle('hidden', !name.includes(query));
            });
          }
        }
        } catch(err) { console.warn('Country search error:', err); }
      });

      // Currency search filter
      addListener(doc, 'input', function(e) {
        try {
        if (e.target.classList.contains('currency-search-input')) {
          const query = e.target.value.toLowerCase();
          const modalId = e.target.getAttribute('data-modal-id');
          const modal = doc.getElementById(modalId);
          if (modal) {
            modal.querySelectorAll('.currency-btn:not(.more-toggle)').forEach(function(btn) {
              const code = btn.getAttribute('data-code') || '';
              const name = btn.getAttribute('data-name') || '';
              const text = btn.textContent.toLowerCase();
              const match = code.includes(query) || name.includes(query) || text.includes(query);
              btn.classList.toggle('hidden', !match);
            });
          }
        }
        } catch(err) { console.warn('Currency search error:', err); }
      });

      // Currency modal tab click handler
      addListener(doc, 'click', function(e) {
        try {
        const currencySubtab = e.target.closest('.currency-modal-tabs label.subtab');
        if (currencySubtab) {
          const radioId = currencySubtab.getAttribute('for');
          if (radioId) {
            const radio = doc.getElementById(radioId);
            if (radio) radio.checked = true;
          }
          e.stopPropagation();
        }
        } catch(err) { console.warn('Currency modal tab error:', err); }
      }, true);

      // Placeholder SVG for missing thumbnails
      var placeholderSvg = '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="12" x2="10" y2="12"/><line x1="8" y1="10" x2="8" y2="14"/><line x1="15" y1="13" x2="15.01" y2="13"/><line x1="18" y1="11" x2="18.01" y2="11"/><rect x="2" y="6" width="20" height="12" rx="2"/></svg>';

      // Games data injected directly from Python
      var gamesDataCache = __GAMES_JSON_PLACEHOLDER__;
      function getGamesData() {
        return gamesDataCache || [];
      }

      // Convert volatility value to display label
      function getVolatilityLabel(vol) {
        if (!vol && vol !== 0) return '';
        var vs = String(vol).trim();
        // Handle numeric values 1-5
        var labelMap = {'1': 'Low', '2': 'Medium Low', '3': 'Medium', '4': 'Medium High', '5': 'High'};
        if (labelMap[vs]) return labelMap[vs];
        // Handle string values
        var vl = vs.toLowerCase();
        if (vl.includes('medium') && vl.includes('low')) return 'Medium Low';
        if (vl.includes('medium') && vl.includes('high')) return 'Medium High';
        if (vl === 'low' || vl === 'l') return 'Low';
        if (vl === 'medium' || vl === 'med' || vl === 'm') return 'Medium';
        if (vl === 'high' || vl === 'h') return 'High';
        return vs;
      }

      // Normalize volatility for CSS class
      function normalizeVolatilityClass(vol) {
        if (!vol) return '';
        var vs = String(vol).trim();
        // Handle numeric values 1-5
        var classMap = {'1': 'low', '2': 'medium-low', '3': 'medium', '4': 'medium-high', '5': 'high'};
        if (classMap[vs]) return classMap[vs];
        // Handle string values
        var vl = vs.toLowerCase();
        if (vl.includes('medium') && vl.includes('low')) return 'medium-low';
        if (vl.includes('medium') && vl.includes('high')) return 'medium-high';
        if (vl === 'low' || vl === 'l') return 'low';
        if (vl === 'medium' || vl === 'med' || vl === 'm') return 'medium';
        if (vl === 'high' || vl === 'h') return 'high';
        return '';
      }

      // Parse JSON field (themes/features)
      function parseJsonField(val) {
        if (!val) return [];
        if (Array.isArray(val)) return val;
        try {
          var parsed = JSON.parse(val);
          return Array.isArray(parsed) ? parsed : [];
        } catch(e) {
          return [];
        }
      }

      // Build a single game card HTML
      function buildGameCard(game) {
        var title = game.title || '';
        var rtp = game.rtp;
        var rtpDisplay = rtp ? rtp.toFixed(2) : 'N/A';
        var volatility = getVolatilityLabel(game.volatility);
        var volClass = normalizeVolatilityClass(game.volatility);
        var themes = parseJsonField(game.themes);
        var theme = themes[0] || '';
        var features = parseJsonField(game.features);
        var thumbnail = game.thumbnail || '';

        var thumbHtml = thumbnail
          ? '<img src="' + thumbnail + '" alt="' + title + '" class="game-thumb-img"><div class="placeholder-icon" style="display:none;">' + placeholderSvg + '</div>'
          : '<div class="placeholder-icon">' + placeholderSvg + '</div>';

        var featureTags = features.slice(0, 5).map(function(f) {
          return '<span class="feature-tag">' + f + '</span>';
        }).join('');
        if (features.length > 5) {
          featureTags += '<span class="feature-tag">+' + (features.length - 5) + ' more</span>';
        }

        return '<div class="game-card" data-title="' + title.toLowerCase() + '" data-rtp="' + (rtp || 0) + '" data-volatility="' + volClass + '" data-theme="' + theme.toLowerCase() + '">' +
          '<div class="game-thumbnail">' + thumbHtml + '</div>' +
          '<div class="game-info">' +
            '<div class="game-title">' + title + '</div>' +
            '<div class="game-meta">' +
              '<div class="game-meta-item"><span class="meta-label">RTP</span><span class="meta-value">' + rtpDisplay + '%</span></div>' +
              '<div class="game-meta-item"><span class="meta-label">Volatility</span><span class="volatility-badge ' + volClass + '">' + (volatility || 'N/A') + '</span></div>' +
              '<div class="game-meta-item"><span class="meta-label">Theme</span><span class="meta-value">' + (theme || 'N/A') + '</span></div>' +
              '<div class="game-meta-item"><span class="meta-label">Features</span><span class="meta-value">' + features.length + ' features</span></div>' +
            '</div>' +
            '<div class="game-features">' + featureTags + '</div>' +
          '</div>' +
        '</div>';
      }

      // Populate games modal content on open
      function populateGamesModal(modal, pid) {
        var gamesList = modal.querySelector('.games-list');
        if (!gamesList) return;

        // Skip if already populated
        if (gamesList.getAttribute('data-loaded') === 'true') return;

        var allGames = getGamesData();
        var pidNum = parseInt(pid, 10);
        var providerGames = allGames.filter(function(g) {
          return g.provider_id === pidNum || g.provider_id === pid || String(g.provider_id) === String(pid);
        });
        console.log('Provider', pid, '- found', providerGames.length, 'games out of', allGames.length, 'total');

        if (providerGames.length === 0) {
          gamesList.innerHTML = '<div class="games-empty">' + placeholderSvg + '<p>No games available</p></div>';
          gamesList.setAttribute('data-loaded', 'true');
          return;
        }

        // Build game cards
        var cardsHtml = providerGames.map(buildGameCard).join('');
        gamesList.innerHTML = cardsHtml;
        gamesList.setAttribute('data-loaded', 'true');

        // Update count
        var countEl = modal.querySelector('.modal-count');
        if (countEl) countEl.textContent = providerGames.length + ' games';

        // Populate theme dropdown with unique themes
        var themes = {};
        providerGames.forEach(function(g) {
          var t = parseJsonField(g.themes);
          if (t[0]) themes[t[0]] = true;
        });
        var sortedThemes = Object.keys(themes).sort();
        var themeSelect = modal.querySelector('.game-filter-theme');
        if (themeSelect) {
          themeSelect.innerHTML = '<option value="">All Themes</option>' +
            sortedThemes.map(function(t) {
              return '<option value="' + t.toLowerCase() + '">' + t + '</option>';
            }).join('');
        }
      }

      // Game filters function
      function filterGames(modalId) {
        const modal = doc.getElementById('games-modal-' + modalId);
        if (!modal) return;

        const searchVal = (modal.querySelector('.game-search')?.value || '').toLowerCase();
        const rtpVal = modal.querySelector('.game-filter-rtp')?.value || '';
        const volVal = modal.querySelector('.game-filter-volatility')?.value || '';
        const themeVal = (modal.querySelector('.game-filter-theme')?.value || '').toLowerCase();

        modal.querySelectorAll('.game-card').forEach(function(card) {
          const title = card.getAttribute('data-title') || '';
          const rtp = parseFloat(card.getAttribute('data-rtp')) || 0;
          const volatility = card.getAttribute('data-volatility') || '';
          const theme = card.getAttribute('data-theme') || '';

          var show = true;

          // Search filter
          if (searchVal && !title.includes(searchVal)) show = false;

          // RTP filter
          if (rtpVal) {
            if (rtpVal === '95-96' && (rtp < 95 || rtp >= 96)) show = false;
            if (rtpVal === '96-97' && (rtp < 96 || rtp >= 97)) show = false;
            if (rtpVal === '97+' && rtp < 97) show = false;
          }

          // Volatility filter
          if (volVal && volatility !== volVal) show = false;

          // Theme filter
          if (themeVal && theme !== themeVal) show = false;

          card.classList.toggle('hidden', !show);
        });

        // Update visible count
        const visibleCount = modal.querySelectorAll('.game-card:not(.hidden)').length;
        const countEl = modal.querySelector('.modal-count');
        if (countEl) countEl.textContent = visibleCount + ' games';
      }

      // Game search filter
      addListener(doc, 'input', function(e) {
        try {
        if (e.target.classList.contains('game-search')) {
          const modalId = e.target.getAttribute('data-modal');
          filterGames(modalId);
        }
        } catch(err) { console.warn('Game search error:', err); }
      });

      // Game dropdown filters
      addListener(doc, 'change', function(e) {
        try {
        if (e.target.classList.contains('game-filter-rtp') ||
            e.target.classList.contains('game-filter-volatility') ||
            e.target.classList.contains('game-filter-theme')) {
          const modalId = e.target.getAttribute('data-modal');
          filterGames(modalId);
        }
        } catch(err) { console.warn('Game filter error:', err); }
      });

      // Apply filter button (mobile) - closes filter panel
      addListener(doc, 'click', function(e) {
        try {
        if (e.target.classList.contains('filter-apply-btn')) {
          const modalId = e.target.getAttribute('data-modal');
          filterGames(modalId);
          const details = e.target.closest('details.games-filter-collapse');
          if (details) details.removeAttribute('open');
        }
        } catch(err) { console.warn('Filter apply error:', err); }
      });

      // Handle broken images - show placeholder (capture phase for img errors)
      addListener(doc, 'error', function(e) {
        try {
        if (e.target.classList && e.target.classList.contains('game-thumb-img')) {
          e.target.style.display = 'none';
          const placeholder = e.target.nextElementSibling;
          if (placeholder && placeholder.classList.contains('placeholder-icon')) {
            placeholder.style.display = 'flex';
          }
        }
        } catch(err) {}
      }, true);

      } catch(e) { console.warn('TT init error:', e); }
    })();
    </script>
    """.replace("__GAMES_JSON_PLACEHOLDER__", _games_json_data),
    height=0,
)


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

        # label like: "us United States (USA)"
        iso2 = df["iso2"].fillna(df["iso3"].str[:2]).str.lower()
        df["label"] = iso2 + " " + df["name"] + " (" + df["iso3"] + ")"
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


@st.cache_data(ttl=60)
def load_provider_card_data(provider_ids_tuple):
    """Bulk load all data needed for provider cards. Cached to speed up theme switches."""
    if not provider_ids_tuple:
        return {
            "currency_mode": {},
            "restricted": {},
            "regulated": {},
            "restrictions_count": {},
            "fiat": {},
            "crypto": {},
            "currency_count": {},
            "games": {},
            "game_types": {},
        }

    provider_ids = list(provider_ids_tuple)
    placeholders = ",".join(["?"] * len(provider_ids))

    # Provider metadata
    provider_meta_df = qdf(
        f"SELECT provider_id, currency_mode FROM providers WHERE provider_id IN ({placeholders})",
        tuple(provider_ids),
    )
    currency_mode = dict(zip(provider_meta_df["provider_id"], provider_meta_df["currency_mode"]))

    # Restrictions
    restrictions_df = qdf(
        f"SELECT provider_id, country_code, restriction_type FROM restrictions WHERE provider_id IN ({placeholders})",
        tuple(provider_ids),
    )
    restricted = {}
    regulated = {}
    restrictions_count = {}
    if not restrictions_df.empty:
        for row in restrictions_df.itertuples(index=False):
            restrictions_count[row.provider_id] = restrictions_count.get(row.provider_id, 0) + 1
            if row.restriction_type == "REGULATED":
                regulated.setdefault(row.provider_id, []).append(row.country_code)
            else:
                restricted.setdefault(row.provider_id, []).append(row.country_code)

    # Currencies
    fiat_map = {}
    crypto_map = {}
    currency_count = {}
    try:
        fiat_df = qdf(
            f"SELECT provider_id, currency_code FROM fiat_currencies WHERE provider_id IN ({placeholders})",
            tuple(provider_ids),
        )
        crypto_df = qdf(
            f"SELECT provider_id, currency_code FROM crypto_currencies WHERE provider_id IN ({placeholders})",
            tuple(provider_ids),
        )
        for row in fiat_df.itertuples(index=False):
            fiat_map.setdefault(row.provider_id, []).append(row.currency_code)
        for row in crypto_df.itertuples(index=False):
            crypto_map.setdefault(row.provider_id, []).append(row.currency_code)
        # Currency count
        for pid in provider_ids:
            currency_count[pid] = len(fiat_map.get(pid, [])) + len(crypto_map.get(pid, []))
    except Exception:
        pass

    # Games
    games_map = {}
    try:
        games_df = qdf(
            f"SELECT provider_id, COUNT(*) as games FROM games WHERE provider_id IN ({placeholders}) GROUP BY provider_id",
            tuple(provider_ids),
        )
        games_map = dict(zip(games_df["provider_id"], games_df["games"]))
    except Exception:
        pass

    # Game types
    game_types_map = {}
    try:
        game_types_df = qdf(
            f"SELECT provider_id, LOWER(game_type) as game_type FROM games WHERE provider_id IN ({placeholders}) GROUP BY provider_id, LOWER(game_type)",
            tuple(provider_ids),
        )
        if not game_types_df.empty:
            for row in game_types_df.itertuples(index=False):
                game_types_map.setdefault(row.provider_id, []).append(row.game_type or "")
    except Exception:
        pass

    # Note: Full game details are now loaded globally via JSON for lazy-loading in JS

    return {
        "currency_mode": currency_mode,
        "restricted": restricted,
        "regulated": regulated,
        "restrictions_count": restrictions_count,
        "fiat": fiat_map,
        "crypto": crypto_map,
        "currency_count": currency_count,
        "games": games_map,
        "game_types": game_types_map,
    }


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
    restricted = restrictions[restrictions["restriction_type"] == "RESTRICTED"]["country_code"].tolist()
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
        "restricted": restricted,
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


def get_currency_name(code: str) -> str:
    try:
        import pycountry
        cur = pycountry.currencies.get(alpha_3=code)
        return cur.name if cur else ""
    except Exception:
        return ""


def create_csv_data_url(headers: list[str], rows: list[list[str]], filename: str) -> tuple[str, str]:
    """Generate a base64-encoded CSV data URL for Excel download.
    Uses semicolon separator which Excel recognizes universally.
    Returns tuple of (data_url, filename) for use in <a> href and download attributes.
    """
    import base64

    def escape_cell(cell):
        # Escape quotes and wrap in quotes if contains separator or quotes
        val = str(cell).replace('"', '""')
        if ';' in val or '"' in val or '\n' in val:
            return f'"{val}"'
        return val

    # Build CSV with semicolon separator (works universally)
    lines = []
    lines.append(';'.join(escape_cell(h) for h in headers))
    for row in rows:
        lines.append(';'.join(escape_cell(c) for c in row))
    content = '\r\n'.join(lines)

    # UTF-8 with BOM for Excel
    file_bytes = ('\ufeff' + content).encode('utf-8')
    b64 = base64.b64encode(file_bytes).decode('ascii')

    safe_filename = filename.replace(' ', '_').replace('"', '').replace("'", '')
    return f"data:text/csv;base64,{b64}", f"{safe_filename}.csv"


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


def replace_ai_restrictions(provider_id: int, iso3_list: list[str], restriction_type: str = "RESTRICTED"):
    with db() as con:
        con.execute(
            "DELETE FROM restrictions WHERE provider_id=? AND source='ai_import' AND restriction_type=?",
            (provider_id, restriction_type),
        )
        con.executemany(
            """
            INSERT OR IGNORE INTO restrictions(provider_id, country_code, restriction_type, source)
            VALUES (?, ?, ?, 'ai_import')
            """,
            [(provider_id, code, restriction_type) for code in iso3_list],
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
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 1.25rem auto;
        }}
        .login-title {{
            font-size: 1.75rem;
            font-weight: 600;
            color: {t["text_primary"]};
            margin-bottom: 0.5rem;
        }}
        .login-subtitle {{
            font-size: 0.75rem;
            color: {t["text_secondary"]};
            letter-spacing: 0.1em;
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

        /* Theme toggle button on login page */
        .stButton > button,
        .stButton button {{
            background: {t["bg_card"]} !important;
            color: {t["text_primary"]} !important;
            border: 1px solid {t["border"]} !important;
            border-radius: 10px !important;
        }}
        .stButton > button:hover,
        .stButton button:hover {{
            background: {t["bg_hover"]} !important;
        }}

        /* Error message */
        [data-testid="stAlert"] {{
            background: #7F1D1D !important;
            border: 1px solid {t["chart_red"]}40 !important;
        }}
        [data-testid="stAlert"] * {{
            color: {t["chart_red"]} !important;
        }}
        [data-testid="stAlert"] p {{
            color: {t["chart_red"]} !important;
        }}
        [data-testid="stAlert"] [data-testid="stMarkdownContainer"] {{
            color: {t["chart_red"]} !important;
        }}
        [data-testid="stAlert"] [data-testid="stMarkdownContainer"] p {{
            color: {t["chart_red"]} !important;
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
    _, theme_col = st.columns([12, 1])
    with theme_col:
        def toggle_login_theme():
            new_theme = "light" if get_theme() == "dark" else "dark"
            set_theme(new_theme)
        login_current = get_theme()
        login_icon = "☀" if login_current == "dark" else "☾"
        st.button(login_icon, key="login_theme", help="Toggle theme", on_click=toggle_login_theme)

    # Center the login form
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        # Load logo for login page (dark logo for light mode, light logo for dark mode)
        login_theme = get_theme()
        login_logo_filename = "ttLogoDark.png" if login_theme == "light" else "ttLogo.png"
        login_logo_path = Path("assets") / login_logo_filename
        if login_logo_path.exists():
            with open(login_logo_path, "rb") as f:
                login_logo_b64 = base64.b64encode(f.read()).decode()
            st.markdown(f"""
            <div class="login-header">
                <img src="data:image/png;base64,{login_logo_b64}" alt="Timeless Tech" style="height: 80px; margin-bottom: 1.5rem;">
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="login-header">
                <div class="login-title">TIMELESS TECH™</div>
                <div class="login-subtitle">iGAMING PLATFORM</div>
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
                        token = generate_session_token()
                        st.query_params["session"] = token
                        # Also preserve theme
                        st.query_params["theme"] = get_theme()
                    st.rerun()
                else:
                    st.error("Invalid password. Please try again.")


# =================================================
# App start
# =================================================
if not DB_PATH.exists():
    st.error("Database not found. Make sure db/database.sqlite exists.")
    st.stop()

# Show login page if not authenticated (session already restored early if token was valid)
if not is_admin():
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

# =================================================
# Header row - logo on left, buttons floated right
# =================================================

# Load logo image based on theme (dark logo for light mode, light logo for dark mode)
logo_filename = "ttLogoDark.png" if current_theme == "light" else "ttLogo.png"
logo_path = Path("assets") / logo_filename
if logo_path.exists():
    with open(logo_path, "rb") as f:
        logo_b64 = base64.b64encode(f.read()).decode()
    logo_html = f'<img src="data:image/png;base64,{logo_b64}" alt="Timeless Tech" style="height: 44px;">'
else:
    logo_html = f'''<div style="display:flex;flex-direction:column;">
        <div style="font-size:1.25rem;font-weight:600;color:{t["text_primary"]};">TIMELESS TECH™</div>
        <div style="font-size:0.7rem;color:{t["text_secondary"]};letter-spacing:0.1em;">iGAMING PLATFORM</div>
    </div>'''

# Note: Header buttons use column ratios [2, 12, 0.5, 1] to push buttons right
# Header with columns - logo left, spacer grows to push buttons right
with st.container(key="sticky_header"):
    logo_col, spacer, buttons_col = st.columns([2, 8, 2])

    with logo_col:
        st.markdown(logo_html, unsafe_allow_html=True)

    # spacer is empty - just pushes buttons right

    with buttons_col:
        # Use container with key for CSS targeting - buttons inside will be inline via CSS
        with st.container(key="header_buttons"):
            def toggle_theme():
                new_theme = "light" if get_theme() == "dark" else "dark"
                set_theme(new_theme)
            # Moon icon for current dark mode, sun for light mode
            theme_icon = "☀" if current_theme == "dark" else "☾"
            st.button(theme_icon, key="btn_theme", help="Toggle theme", on_click=toggle_theme)
            if st.button("→ Logout", key="btn_logout"):
                st.session_state["is_admin"] = False
                if "session" in st.query_params:
                    del st.query_params["session"]
                st.rerun()

# =================================================
# Filters (collapsible accordion)
# =================================================

# Defaults
st.session_state.setdefault("f_mode", "Supported")
st.session_state.setdefault("f_search", "")
st.session_state.setdefault("f_country", "All Countries")
st.session_state.setdefault("f_currency", "All Fiat Currencies")
st.session_state.setdefault("f_crypto", "All Crypto Currencies")
st.session_state.setdefault("filters_expanded", False)

filter_mode = st.session_state["f_mode"]

# Clear all handler (runs before widgets via on_click)
def clear_all_filters():
    st.session_state["f_mode"] = "Supported"
    st.session_state["f_search"] = ""
    st.session_state["f_country"] = "All Countries"
    st.session_state["f_currency"] = "All Fiat Currencies"
    st.session_state["f_crypto"] = "All Crypto Currencies"

# Build option lists
country_options = ["All Countries"] + country_labels

fiat_codes = fiat
fiat_options = ["All Fiat Currencies"]
fiat_label_to_code = {}
for c in fiat_codes:
    sym = get_currency_symbol(c)
    nm = get_currency_name(c)
    if nm:
        # Has name: "$ USD - US Dollar"
        label = f"{sym} {c} - {nm}".strip() if sym else f"{c} - {nm}"
    else:
        # No name: just "USD" or "$ USD"
        label = f"{sym} {c}".strip() if sym else c
    fiat_options.append(label)
    fiat_label_to_code[label] = c

# Crypto options with symbols
crypto_codes = crypto
crypto_options = ["All Crypto Currencies"]
crypto_label_to_code = {}
for c in crypto_codes:
    sym = get_currency_symbol(c)
    label = f"{sym} {c}".strip() if sym else c
    crypto_options.append(label)
    crypto_label_to_code[label] = c

# Sanitize stale state - rerun if any changes needed
_needs_rerun = False
if st.session_state["f_country"] not in country_options:
    st.session_state["f_country"] = "All Countries"
    _needs_rerun = True
if st.session_state["f_currency"] not in fiat_options:
    st.session_state["f_currency"] = "All Fiat Currencies"
    _needs_rerun = True
if st.session_state["f_crypto"] not in crypto_options:
    st.session_state["f_crypto"] = "All Crypto Currencies"
    _needs_rerun = True
if _needs_rerun:
    st.rerun()

# Count active secondary filters (excluding search which is always visible)
_secondary_filter_count = sum([
    st.session_state["f_country"] != "All Countries",
    st.session_state["f_currency"] != "All Fiat Currencies",
    st.session_state["f_crypto"] != "All Crypto Currencies",
    st.session_state["f_mode"] != "Supported"
])

with st.container(border=True):
    st.markdown(f'''
    <div class="filter-title">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="{t["primary"]}" stroke-width="2">
            <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon>
        </svg>
        Filters
    </div>
    ''', unsafe_allow_html=True)

    # Search (always visible)
    search = st.text_input(
        "Search Provider:",
        placeholder="Search by name...",
        key="f_search",
        label_visibility="visible",
    )

    # Toggle button for secondary filters
    _chevron = "▲" if st.session_state.get("filters_expanded", False) else "▼"
    _count_label = f" ({_secondary_filter_count})" if _secondary_filter_count > 0 else ""
    _toggle_label = f"{_chevron} More Filters{_count_label}"

    def toggle_filters():
        st.session_state["filters_expanded"] = not st.session_state.get("filters_expanded", False)

    st.button(_toggle_label, key="btn_toggle_filters", on_click=toggle_filters)

    # Secondary filters - only render when expanded (prevents flicker)
    if st.session_state.get("filters_expanded", False):
        # Row 1: Country (full width)
        country_label = st.selectbox(
            "Country:",
            country_options,
            key="f_country",
        )

        # Row 2: Fiat | Crypto
        fc1, fc2 = st.columns(2)
        with fc1:
            fiat_label = st.selectbox(
                "Fiat Currency:",
                fiat_options,
                key="f_currency",
            )
        with fc2:
            crypto_label = st.selectbox(
                "Crypto Currency:",
                crypto_options,
                key="f_crypto",
            )

        # Row 3: Supported | Restricted
        m1, m2 = st.columns(2)
        with m1:
            def set_supported():
                st.session_state["f_mode"] = "Supported"
            supported_style = "primary" if filter_mode == "Supported" else "secondary"
            st.button("Supported", key="btn_supported", type=supported_style, use_container_width=True, on_click=set_supported)
        with m2:
            def set_restricted():
                st.session_state["f_mode"] = "Restricted"
            restricted_style = "primary" if filter_mode == "Restricted" else "secondary"
            st.button("Restricted", key="btn_restricted", type=restricted_style, use_container_width=True, on_click=set_restricted)
    else:
        # When collapsed, read from session state directly (no widgets rendered = no flicker)
        country_label = st.session_state.get("f_country", "All Countries")
        fiat_label = st.session_state.get("f_currency", "All Fiat Currencies")
        crypto_label = st.session_state.get("f_crypto", "All Crypto Currencies")

    # Active filter badges + Clear all (always visible)
    active_filters = []

    if search:
        active_filters.append(("Search", search))

    if country_label != "All Countries":
        # show just country name in badge (like mock)
        # country_label format: "us United States (USA)"
        badge_country = country_label.split(" ", 1)[1] if " " in country_label else country_label
        active_filters.append(("Country", badge_country))

    fiat_code = fiat_label_to_code.get(fiat_label, "") if fiat_label != "All Fiat Currencies" else ""
    if fiat_code:
        active_filters.append(("Currency", fiat_code))

    selected_crypto_code = (
        crypto_label_to_code.get(crypto_label, "")
        if crypto_label != "All Crypto Currencies"
        else ""
    )
    if selected_crypto_code:
        active_filters.append(("Crypto", selected_crypto_code))

    if filter_mode != "Supported":
        active_filters.append(("Mode", filter_mode))

    if active_filters:
        badges_html = '<div class="active-filters-row filter-badges-container" style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;padding:0.5rem 0;margin:0;">'
        badges_html += f'<span style="color:{t["text_secondary"]};font-size:0.85rem;font-weight:500;">Active filters:</span>'
        for label, value in active_filters:
            display_value = value if len(str(value)) <= 30 else str(value)[:27] + "..."
            bg_color = "rgba(14, 165, 233, 0.15)" if current_theme == "light" else "rgba(30, 58, 138, 1)"
            text_color = "#0369A1" if current_theme == "light" else "#93C5FD"
            badges_html += (
                f'<span style="display:inline-flex;align-items:center;gap:0.35rem;'
                f'background:{bg_color};color:{text_color};border:1px solid transparent;'
                f'padding:0.125rem 0.5rem;border-radius:0.5rem;font-size:0.75rem;font-weight:500;line-height:1.6;">'
                f'<span style="font-weight:500;">{label}:</span>'
                f'<span style="font-weight:600;">{display_value}</span>'
                f'</span>'
            )
        badges_html += "</div>"

    # Active filters row: badges + clear all + APPLY (always rendered)
    af1, af2, af3 = st.columns([7, 0.8, 1.2], gap="small")
    if active_filters:
        with af1:
            st.markdown(badges_html, unsafe_allow_html=True)
        with af2:
            st.button("Clear all", key="btn_clear_all", type="secondary", on_click=clear_all_filters)
    with af3:
        st.button("Apply", key="btn_apply_filters", type="primary", use_container_width=True)

# =================================================
# Query building
# =================================================
# Variables search, country_label, fiat_label, crypto_filter are already defined
# from the widgets above and are accessible here due to Python scoping

# Convert selected fiat label -> code for SQL
selected_fiat_code = ""
if fiat_label != "All Fiat Currencies":
    selected_fiat_code = fiat_label_to_code.get(fiat_label, "")

where = []
params = []

if search:
    where.append("LOWER(p.provider_name) LIKE ?")
    params.append(f"%{search.lower()}%")

country_iso = label_to_iso.get(country_label, "")
if country_iso:
    if filter_mode == "Supported":
        where.append("""
            p.provider_id NOT IN (
                SELECT provider_id
                FROM restrictions
                WHERE country_code=?
                  AND (restriction_type='RESTRICTED' OR restriction_type IS NULL)
            )
        """)
        params.append(country_iso)
    else:  # Restricted
        where.append("""
            p.provider_id IN (
                SELECT provider_id
                FROM restrictions
                WHERE country_code=?
                  AND (restriction_type='RESTRICTED' OR restriction_type IS NULL)
            )
        """)
        params.append(country_iso)

if selected_fiat_code:
    where.append(
        """
        (
            p.currency_mode='ALL_FIAT'
            OR EXISTS (
                SELECT 1 FROM fiat_currencies fc
                WHERE fc.provider_id=p.provider_id AND fc.currency_code=?
            )
            OR EXISTS (
                SELECT 1 FROM currencies c
                WHERE c.provider_id=p.provider_id
                  AND c.currency_type='FIAT'
                  AND c.currency_code=?
            )
        )
        """
    )
    params.extend([selected_fiat_code, selected_fiat_code])

if selected_crypto_code:
    # Check both new and legacy tables
    where.append(
        """
        (
            EXISTS (
                SELECT 1 FROM crypto_currencies cc
                WHERE cc.provider_id=p.provider_id AND cc.currency_code=?
            )
            OR EXISTS (
                SELECT 1 FROM currencies c
                WHERE c.provider_id=p.provider_id
                  AND c.currency_type='CRYPTO'
                  AND c.currency_code=?
            )
        )
        """
    )
    params.extend([selected_crypto_code, selected_crypto_code])

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
total_providers = len(df)
try:
    provider_ids = df["ID"].tolist()
    if provider_ids:
        placeholders = ",".join(["?"] * len(provider_ids))
        total_games = int(
            qdf(
                f"SELECT COUNT(*) c FROM games WHERE provider_id IN ({placeholders})",
                tuple(provider_ids),
            )["c"][0]
        )
    else:
        total_games = 0
except Exception:
    total_games = 0

st.markdown(f"""
<div class="stats-container">
    <div class="stat-card">
        <div>
            <div class="stat-label">Total Providers</div>
            <div class="stat-value">{len(df)}</div>
        </div>
        <div class="stat-icon providers">{svg_icon("gamepad", t["primary"], 20)}</div>
    </div>
    <div class="stat-card">
        <div>
            <div class="stat-label">Total Games</div>
            <div class="stat-value">{total_games}</div>
        </div>
        <div class="stat-icon currencies">{svg_icon("dice", t["chart_yellow"], 20)}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# =================================================
# Provider list header with export
# =================================================
pcol1, pcol2, pcol3 = st.columns([7, 0.8, 1.2], gap="small")
with pcol1:
    st.markdown(f'<div class="providers-title">Game Providers ({len(df)})</div>', unsafe_allow_html=True)
# pcol2 empty
with pcol3:
    # Export to Excel - aligned right under emoji
    excel_buffer = io.BytesIO()
    df.to_excel(excel_buffer, index=False, engine='openpyxl')
    excel_buffer.seek(0)
    st.download_button(
        "Export to Excel",
        data=excel_buffer,
        file_name="providers.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="btn_export_excel",
        use_container_width=True,
    )

# =================================================
# Provider cards (CSS Grid - expands to full width when open)
# =================================================
if df.empty:
    st.info("No providers match your filters.")
else:
    provider_ids = df["ID"].tolist()

    # Load all provider card data (cached for fast theme switches)
    card_data = load_provider_card_data(tuple(provider_ids))
    provider_currency_mode = card_data["currency_mode"]
    restricted_map = card_data["restricted"]
    regulated_map = card_data["regulated"]
    restrictions_count_map = card_data["restrictions_count"]
    fiat_map = card_data["fiat"]
    crypto_map = card_data["crypto"]
    currency_count_map = card_data["currency_count"]
    games_map = card_data["games"]
    game_types_map = card_data["game_types"]

    def format_game_type(gt: str) -> str:
        if not gt:
            return ""
        normalized = gt.strip().lower()
        mapping = {
            "slots": "Slots",
            "tablegames": "Table Games",
            "instantgame": "Instant Games",
            "crashgame": "Crash Games",
            "scratchcards": "Scratch Cards",
            "shooting": "Shooting",
            "roulette": "Roulette",
            "blackjack": "Blackjack",
            "baccarat": "Baccarat",
        }
        if normalized in mapping:
            return mapping[normalized]
        return normalized.replace("_", " ").title()

    # Pre-build dict lookup for O(1) country info access (instead of O(n) pandas filter)
    countries_lookup = {
        row.iso3: {"iso2": row.iso2 if pd.notna(row.iso2) else row.iso3[:2], "name": row.name}
        for row in countries_df.itertuples(index=False)
    }

    def get_country_info(iso3_list):
        result = []
        for iso3 in iso3_list:
            if iso3 in countries_lookup:
                info = countries_lookup[iso3]
                result.append({"iso3": iso3, "iso2": info["iso2"], "name": info["name"]})
            else:
                result.append({"iso3": iso3, "iso2": iso3[:2], "name": iso3})
        return result

    # Pagination
    CARDS_PER_PAGE = 24
    total_providers = len(df)
    total_pages = max(1, (total_providers + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE)

    if "cards_page" not in st.session_state:
        st.session_state.cards_page = 0
    # Reset to page 0 if filters changed and current page is out of bounds
    if st.session_state.cards_page >= total_pages:
        st.session_state.cards_page = 0

    current_page = st.session_state.cards_page
    start_idx = current_page * CARDS_PER_PAGE
    end_idx = min(start_idx + CARDS_PER_PAGE, total_providers)
    df_page = df.iloc[start_idx:end_idx]

    # Build all cards HTML for CSS Grid
    all_cards_html = []

    for idx, row in df_page.iterrows():
        pid = row["ID"]
        pname = row["Game Provider"]

        stats = {
            "restrictions": restrictions_count_map.get(pid, 0),
            "currencies": currency_count_map.get(pid, 0),
            "games": int(games_map.get(pid, 0)),
        }
        details = {
            "restricted": restricted_map.get(pid, []),
            "regulated": regulated_map.get(pid, []),
            "currency_mode": provider_currency_mode.get(pid, "ALL_FIAT"),
        }
        supported_games = sorted(
            {format_game_type(gt) for gt in game_types_map.get(pid, []) if gt}
        )

        # Build Countries section HTML with sub-tabs if needed
        has_restricted = bool(details["restricted"])
        has_regulated = bool(details["regulated"])

        # Build restricted HTML
        restricted_html = ""
        if has_restricted:
            restricted_countries = get_country_info(details["restricted"][:20])
            restricted_tags = ''.join([
                f'<span class="country-tag restricted"><span class="iso">{c["iso2"]}</span>{c["name"]}</span>'
                for c in restricted_countries
            ])
            restricted_count = len(details["restricted"])
            restricted_html = f'''<div class="country-section">
  <div class="country-section-header">
    <div class="country-section-title">{svg_icon("x-circle", t["chart_red"], 16)} Restricted Countries</div>
    <div class="country-count">{restricted_count} {"country" if restricted_count == 1 else "countries"}</div>
  </div>
  <div class="country-tags">{restricted_tags}</div>
  <div class="country-disclaimer restricted">{svg_icon("alert-triangle", t["chart_yellow"], 14)} Games cannot be offered in these countries</div>
</div>'''

        # Build regulated HTML
        regulated_html = ""
        if has_regulated:
            regulated_countries = get_country_info(details["regulated"][:20])
            regulated_tags = ''.join([
                f'<span class="country-tag regulated"><span class="iso">{c["iso2"]}</span>{c["name"]}</span>'
                for c in regulated_countries
            ])
            regulated_count = len(details["regulated"])
            regulated_html = f'''<div class="country-section">
  <div class="country-section-header">
    <div class="country-section-title">{svg_icon("check-circle", t["primary"], 16)} Regulated Countries</div>
    <div class="country-count">{regulated_count} {"country" if regulated_count == 1 else "countries"}</div>
  </div>
  <div class="country-tags">{regulated_tags}</div>
  <div class="country-disclaimer regulated">{svg_icon("info", t["primary"], 14)} Games can be offered but must comply with local regulations</div>
</div>'''

        # Build countries section with sub-tabs if both types exist
        countries_html = ""
        countries_modal_html = ""
        countries_export_btn = ""
        total_countries = len(details["restricted"]) + len(details["regulated"])

        # Generate countries export CSV data
        if has_restricted or has_regulated:
            country_rows = []
            all_restricted_info = get_country_info(details["restricted"])
            all_regulated_info = get_country_info(details["regulated"])
            for c in all_restricted_info:
                country_rows.append([c["iso3"], c["name"], "Restricted"])
            for c in all_regulated_info:
                country_rows.append([c["iso3"], c["name"], "Regulated"])

            if country_rows:
                csv_url, csv_filename = create_csv_data_url(
                    ["Country Code (ISO3)", "Country Name", "Restriction Type"],
                    country_rows,
                    f"{pname}_countries"
                )
                countries_export_btn = f'<a href="{csv_url}" download="{csv_filename}" class="export-btn">Export to Excel</a>'

        if has_restricted and has_regulated:
            country_tab_id = f"country_{pid}"
            countries_html = (
                f'<div class="country-type-tabs">'
                f'<input type="radio" id="{country_tab_id}-restricted" name="{country_tab_id}" checked>'
                f'<input type="radio" id="{country_tab_id}-regulated" name="{country_tab_id}">'
                f'<div class="country-tab-buttons">'
                f'<label for="{country_tab_id}-restricted" class="subtab">{svg_icon("x-circle", "currentColor", 14)} Restricted ({len(details["restricted"])})</label>'
                f'<label for="{country_tab_id}-regulated" class="subtab">{svg_icon("check-circle", "currentColor", 14)} Regulated ({len(details["regulated"])})</label>'
                f'</div>'
                f'<div class="restricted-panel">{restricted_html}</div>'
                f'<div class="regulated-panel">{regulated_html}</div>'
                f'</div>'
            )
        elif has_restricted:
            countries_html = f'{restricted_html}'
        elif has_regulated:
            countries_html = f'{regulated_html}'
        else:
            countries_html = '<p class="muted-text">No country restrictions</p>'

        # Add "View All" button and build modal if there are countries
        if has_restricted or has_regulated:
            # Build modal with ALL countries
            all_restricted_countries = get_country_info(details["restricted"])
            all_regulated_countries = get_country_info(details["regulated"])

            # Build restricted section for modal (all countries)
            modal_restricted_tags = ''.join([
                f'<span class="country-tag restricted" data-name="{c["name"].lower()}"><span class="iso">{c["iso2"]}</span>{c["name"]}</span>'
                for c in all_restricted_countries
            ])
            restricted_count = len(details["restricted"])
            modal_restricted_section = f'''<div class="country-section">
  <div class="country-section-header">
    <div class="country-section-title">{svg_icon("x-circle", t["chart_red"], 16)} Restricted Countries</div>
    <div class="country-count">{restricted_count} {"country" if restricted_count == 1 else "countries"}</div>
  </div>
  <div class="country-tags" style="display: flex; flex-wrap: wrap; gap: 0.5rem;">{modal_restricted_tags}</div>
  <div class="country-disclaimer restricted">{svg_icon("alert-triangle", t["chart_yellow"], 14)} Games cannot be offered in these countries</div>
</div>'''

            # Build regulated section for modal (all countries)
            modal_regulated_tags = ''.join([
                f'<span class="country-tag regulated" data-name="{c["name"].lower()}"><span class="iso">{c["iso2"]}</span>{c["name"]}</span>'
                for c in all_regulated_countries
            ])
            regulated_count = len(details["regulated"])
            modal_regulated_section = f'''<div class="country-section">
  <div class="country-section-header">
    <div class="country-section-title">{svg_icon("check-circle", t["primary"], 16)} Regulated Countries</div>
    <div class="country-count">{regulated_count} {"country" if regulated_count == 1 else "countries"}</div>
  </div>
  <div class="country-tags" style="display: flex; flex-wrap: wrap; gap: 0.5rem;">{modal_regulated_tags}</div>
  <div class="country-disclaimer regulated">{svg_icon("info", t["primary"], 14)} Games can be offered but must comply with local regulations</div>
</div>'''

            # Build modal tabs HTML (only show tabs that have data)
            modal_tab_id = f"modal_{pid}"
            if has_restricted and has_regulated:
                # Default to restricted tab
                modal_tabs_html = (
                    f'<input type="radio" id="{modal_tab_id}-restricted" name="{modal_tab_id}" checked>'
                    f'<input type="radio" id="{modal_tab_id}-regulated" name="{modal_tab_id}">'
                    f'<div class="modal-tab-buttons">'
                    f'<label for="{modal_tab_id}-restricted" class="subtab">{svg_icon("x-circle", "currentColor", 14)} Restricted ({len(details["restricted"])})</label>'
                    f'<label for="{modal_tab_id}-regulated" class="subtab">{svg_icon("check-circle", "currentColor", 14)} Regulated ({len(details["regulated"])})</label>'
                    f'</div>'
                    f'<div class="modal-restricted-panel">{modal_restricted_section}</div>'
                    f'<div class="modal-regulated-panel">{modal_regulated_section}</div>'
                )
            elif has_restricted:
                modal_tabs_html = (
                    f'<input type="radio" id="{modal_tab_id}-restricted" name="{modal_tab_id}" checked>'
                    f'<div class="modal-restricted-panel" style="display: block;">{modal_restricted_section}</div>'
                )
            else:  # has_regulated only
                modal_tabs_html = (
                    f'<input type="radio" id="{modal_tab_id}-regulated" name="{modal_tab_id}" checked>'
                    f'<div class="modal-regulated-panel" style="display: block;">{modal_regulated_section}</div>'
                )

            # Build the complete modal HTML
            countries_modal_html = f'''<div class="modal-overlay" id="countries-modal-{pid}">
  <div class="modal-content">
    <div class="modal-header">
      <h3>Countries - {pname}</h3>
      <span class="modal-count">{total_countries} countries</span>
      {countries_export_btn}
      <button class="modal-close" data-close-modal="countries-modal-{pid}">&times;</button>
    </div>
    <div class="modal-search">
      <input type="text" placeholder="Search countries..." class="country-search" data-target="countries-modal-{pid}">
    </div>
    <div class="modal-tabs">
      {modal_tabs_html}
    </div>
  </div>
</div>'''

            # Add "View All" + Export row to countries_html
            countries_html += (
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:0.75rem;">'
                f'<button class="view-all-btn" data-modal="countries-modal-{pid}" style="margin-top:0;">View All ({total_countries} countries)</button>'
                f'{countries_export_btn}'
                f'</div>'
            )

        # Supported Currencies - build fiat and crypto HTML
        fiat_html = ""
        crypto_html = ""
        currencies_modal_html = ""

        # Build fiat HTML
        fiat_list = fiat_map.get(pid, [])
        has_fiat = details["currency_mode"] == "ALL_FIAT" or bool(fiat_list)
        if has_fiat:
            fiat_html = '<div class="section-header"><span class="icon-success">✓</span> Supported Fiat Currencies</div>'
            if details["currency_mode"] == "ALL_FIAT":
                fiat_html += '<div class="currency-grid"><div class="currency-btn fiat"><span class="symbol">*</span>All FIAT</div></div>'
            else:
                fiat_html += '<div class="currency-grid">'
                for curr in fiat_list[:9]:
                    symbol = get_currency_symbol(curr)
                    fiat_html += f'<div class="currency-btn fiat"><span class="symbol">{symbol}</span>{curr}</div>'
                fiat_html += '</div>'

        # Build crypto HTML
        crypto_list = crypto_map.get(pid, [])
        has_crypto = bool(crypto_list)
        if has_crypto:
            crypto_html = '<div class="section-header"><span class="icon-success">✓</span> Supported Crypto Currencies</div>'
            crypto_html += '<div class="currency-grid">'
            for curr in crypto_list[:9]:
                symbol = get_currency_symbol(curr)
                crypto_html += f'<div class="currency-btn crypto"><span class="symbol">{symbol}</span>{curr}</div>'
            crypto_html += '</div>'

        # Generate currencies export CSV data (used for both modal and panel)
        currencies_export_btn = ""
        if has_fiat or has_crypto:
            currency_rows = []
            for curr in fiat_list:
                symbol = get_currency_symbol(curr)
                currency_rows.append([curr, "Fiat", symbol])
            for curr in crypto_list:
                symbol = get_currency_symbol(curr)
                currency_rows.append([curr, "Crypto", symbol])

            if currency_rows:
                csv_url, csv_filename = create_csv_data_url(
                    ["Currency Code", "Type", "Symbol"],
                    currency_rows,
                    f"{pname}_currencies"
                )
                currencies_export_btn = f'<a href="{csv_url}" download="{csv_filename}" class="export-btn">Export to Excel</a>'

        # Build currencies modal (always, when there are currencies)
        total_currencies = len(fiat_list) + len(crypto_list)
        if (has_fiat or has_crypto) and details["currency_mode"] != "ALL_FIAT":

            # Build fiat section for modal (ALL currencies)
            modal_fiat_html = '<div class="currency-grid modal-currency-grid">'
            for curr in fiat_list:
                symbol = get_currency_symbol(curr)
                modal_fiat_html += f'<div class="currency-btn fiat" data-code="{curr.lower()}"><span class="symbol">{symbol}</span>{curr}</div>'
            modal_fiat_html += '</div>'

            # Build crypto section for modal (ALL currencies)
            modal_crypto_html = '<div class="currency-grid modal-currency-grid">'
            for curr in crypto_list:
                symbol = get_currency_symbol(curr)
                modal_crypto_html += f'<div class="currency-btn crypto" data-code="{curr.lower()}"><span class="symbol">{symbol}</span>{curr}</div>'
            modal_crypto_html += '</div>'

            # Build modal tabs if both exist, otherwise single panel
            curr_modal_id = f"currmodal_{pid}"
            if has_fiat and has_crypto:
                modal_currency_tabs_html = (
                    f'<div class="currency-modal-tabs">'
                    f'<input type="radio" id="{curr_modal_id}-fiat" name="{curr_modal_id}" checked>'
                    f'<input type="radio" id="{curr_modal_id}-crypto" name="{curr_modal_id}">'
                    f'<div class="modal-tab-buttons">'
                    f'<label for="{curr_modal_id}-fiat" class="subtab">{svg_icon("card", "currentColor", 14)} Fiat ({len(fiat_list)})</label>'
                    f'<label for="{curr_modal_id}-crypto" class="subtab">{svg_icon("crypto", "currentColor", 14)} Crypto ({len(crypto_list)})</label>'
                    f'</div>'
                    f'<div class="fiat-panel">{modal_fiat_html}</div>'
                    f'<div class="crypto-panel">{modal_crypto_html}</div>'
                    f'</div>'
                )
            elif has_fiat:
                modal_currency_tabs_html = modal_fiat_html
            else:
                modal_currency_tabs_html = modal_crypto_html

            # Build complete currencies modal
            currencies_modal_html = f'''<div class="modal-overlay" id="currencies-modal-{pid}">
  <div class="modal-content">
    <div class="modal-header">
      <h3>Currencies - {pname}</h3>
      <span class="modal-count">{total_currencies} currencies</span>
      {currencies_export_btn}
      <button class="modal-close" data-close-modal="currencies-modal-{pid}">&times;</button>
    </div>
    <div class="modal-search">
      <input type="text" placeholder="Search currencies..." class="currency-search-input" data-modal-id="currencies-modal-{pid}">
    </div>
    <div class="modal-body">
      {modal_currency_tabs_html}
    </div>
  </div>
</div>'''

        # Build Games modal (empty shell - content loaded via JS on open)
        game_count = int(games_map.get(pid, 0))
        games_export_btn = ""

        # Generate games export CSV data if there are games
        if game_count > 0:
            try:
                games_export_df = qdf(
                    "SELECT title, rtp, volatility, themes, features FROM games WHERE provider_id=? ORDER BY title",
                    (pid,),
                )
                if not games_export_df.empty:
                    game_rows = []
                    for _, g in games_export_df.iterrows():
                        # Parse themes and features (stored as JSON arrays)
                        themes_str = ""
                        features_str = ""
                        try:
                            import json as json_module
                            themes_list = json_module.loads(g["themes"]) if g["themes"] else []
                            features_list = json_module.loads(g["features"]) if g["features"] else []
                            themes_str = ", ".join(themes_list) if themes_list else ""
                            features_str = ", ".join(features_list) if features_list else ""
                        except Exception:
                            themes_str = str(g["themes"]) if g["themes"] else ""
                            features_str = str(g["features"]) if g["features"] else ""

                        rtp_val = f"{g['rtp']}%" if g["rtp"] else ""
                        game_rows.append([
                            g["title"] or "",
                            rtp_val,
                            g["volatility"] or "",
                            themes_str,
                            features_str
                        ])

                    csv_url, csv_filename = create_csv_data_url(
                        ["Game Title", "RTP", "Volatility", "Themes", "Features"],
                        game_rows,
                        f"{pname}_games"
                    )
                    games_export_btn = f'<a href="{csv_url}" download="{csv_filename}" class="export-btn">Export to Excel</a>'
            except Exception:
                pass  # Skip export if games query fails

        games_modal_html = f'''<div class="modal-overlay" id="games-modal-{pid}" data-provider-id="{pid}" data-provider-name="{pname}">
  <div class="modal-content modal-lg">
    <div class="modal-header">
      <h3>Game List - {pname}</h3>
      <span class="modal-count">{game_count} games</span>
      {games_export_btn}
      <button class="modal-close" data-close-modal="games-modal-{pid}">&times;</button>
    </div>
    <details class="games-filter-collapse" open>
      <summary>
        <span class="filter-toggle">{svg_icon("filter", "currentColor", 16)} Filter Games</span>
        <span class="filter-chevron">{svg_icon("chevron-down", "currentColor", 16)}</span>
      </summary>
      <div class="games-filter-bar">
        <div class="filter-row">
          <div class="filter-group">
            <label>Search by Name</label>
            <input type="text" class="game-search" placeholder="Search games..." data-modal="{pid}">
          </div>
          <div class="filter-group">
            <label>RTP Range</label>
            <select class="game-filter-rtp" data-modal="{pid}">
              <option value="">All RTP</option>
              <option value="95-96">95% - 96%</option>
              <option value="96-97">96% - 97%</option>
              <option value="97+">97%+</option>
            </select>
          </div>
          <div class="filter-group">
            <label>Volatility</label>
            <select class="game-filter-volatility" data-modal="{pid}">
              <option value="">All Volatility</option>
              <option value="low">Low</option>
              <option value="medium-low">Medium Low</option>
              <option value="medium">Medium</option>
              <option value="medium-high">Medium High</option>
              <option value="high">High</option>
            </select>
          </div>
          <div class="filter-group">
            <label>Theme</label>
            <select class="game-filter-theme" data-modal="{pid}">
              <option value="">All Themes</option>
            </select>
          </div>
        </div>
        <button class="filter-apply-btn" data-modal="{pid}">Apply Filters</button>
      </div>
    </details>
    <div class="games-list" id="games-list-{pid}">
      <div class="games-loading">Loading games...</div>
    </div>
  </div>
</div>'''

        # Build gamelist panel content
        if game_count > 0:
            gamelist_panel_content = f'<p class="muted-text">Click to view {game_count} games</p>'
        else:
            gamelist_panel_content = f'<div class="games-empty">{svg_icon("gamepad", "var(--text-muted)", 48)}<p>No games available</p></div>'

        # Build currencies section HTML (with fiat/crypto sub-tabs if needed)
        currencies_html = ""
        # Build View All + Export row (only if not ALL_FIAT mode and has currencies)
        currencies_footer = ""
        if (has_fiat or has_crypto) and details["currency_mode"] != "ALL_FIAT":
            currencies_footer = (
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:0.75rem;">'
                f'<button class="view-all-btn" data-modal="currencies-modal-{pid}" style="margin-top:0;">View All ({total_currencies} currencies)</button>'
                f'{currencies_export_btn}'
                f'</div>'
            )

        if has_fiat and has_crypto:
            # Generate unique ID for this provider's currency tabs
            tab_id = f"curr_{pid}"
            currencies_html = (
                f'<div class="currency-tabs">'
                f'<input type="radio" id="{tab_id}-fiat" name="{tab_id}" checked>'
                f'<input type="radio" id="{tab_id}-crypto" name="{tab_id}">'
                f'<div class="currency-tab-buttons">'
                f'<label for="{tab_id}-fiat" class="subtab">{svg_icon("card", "currentColor", 14)} Fiat</label>'
                f'<label for="{tab_id}-crypto" class="subtab">{svg_icon("crypto", "currentColor", 14)} Crypto</label>'
                f'</div>'
                f'<div class="fiat-panel">{fiat_html}</div>'
                f'<div class="crypto-panel">{crypto_html}</div>'
                f'</div>'
                f'{currencies_footer}'
            )
        elif has_fiat:
            currencies_html = f'{fiat_html}{currencies_footer}'
        elif has_crypto:
            currencies_html = f'{crypto_html}{currencies_footer}'

        # Build top-level tabs wrapper (pure CSS radio pattern)
        main_tab_id = f"main_{pid}"
        details_html = (
            f'<div class="provider-main-tabs">'
            f'<input type="radio" id="{main_tab_id}-currencies" name="{main_tab_id}" checked>'
            f'<input type="radio" id="{main_tab_id}-countries" name="{main_tab_id}">'
            f'<input type="radio" id="{main_tab_id}-gamelist" name="{main_tab_id}">'
            f'<input type="radio" id="{main_tab_id}-assets" name="{main_tab_id}">'
            f'<div class="main-tab-buttons">'
            f'<label for="{main_tab_id}-currencies" class="main-tab">{svg_icon("wallet", "currentColor", 14)} Currencies</label>'
            f'<label for="{main_tab_id}-countries" class="main-tab">{svg_icon("globe", "currentColor", 14)} Countries</label>'
            f'<label for="{main_tab_id}-gamelist" class="main-tab">{svg_icon("gamepad", "currentColor", 14)} Game List</label>'
            f'<label for="{main_tab_id}-assets" class="main-tab">{svg_icon("folder", "currentColor", 14)} Assets</label>'
            f'</div>'
            f'<div class="main-panel currencies-panel">{currencies_html}</div>'
            f'<div class="main-panel countries-panel">{countries_html}</div>'
            f'<div class="main-panel gamelist-panel">{gamelist_panel_content}</div>'
            f'<div class="main-panel assets-panel"><p class="muted-text">Assets coming soon</p></div>'
            f'</div>'
        )

        # Build card HTML
        card_html = f'''<details class="provider-card"><summary class="card-header"><div class="card-header-top"><div class="card-header-left"><div class="provider-icon">{svg_icon("gamepad", "var(--primary)", 24)}</div><div><div class="provider-name">{pname}</div><div class="provider-games">{stats['games']} games</div></div></div><span class="expand-icon">▼</span></div><div class="card-games-section"><div class="games-label">Supported Games</div><div class="games-container">{''.join([f'<span class="game-chip">{g}</span>' for g in (supported_games or ['No data'])])}</div></div></summary><div class="card-details-content">{details_html if details_html else '<p class="muted-text">No details available</p>'}</div></details>'''
        # Append modal HTML if exists (modal must be outside the card)
        if countries_modal_html:
            card_html += countries_modal_html
        if currencies_modal_html:
            card_html += currencies_modal_html
        if games_modal_html:
            card_html += games_modal_html
        all_cards_html.append(card_html)

    # Render all cards in grid container
    st.markdown(f'<div class="provider-cards">{"".join(all_cards_html)}</div>', unsafe_allow_html=True)

    # Pagination controls
    if total_pages > 1:
        st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)
        pag_col1, pag_col2, pag_col3 = st.columns([1, 2, 1])
        with pag_col1:
            if current_page > 0:
                if st.button("← Previous", key="btn_prev_page"):
                    st.session_state.cards_page = current_page - 1
                    st.rerun()
        with pag_col2:
            st.markdown(
                f'<div style="text-align: center; color: var(--text-secondary); font-size: 0.85rem; padding: 0.5rem;">'
                f'Page {current_page + 1} of {total_pages} ({start_idx + 1}-{end_idx} of {total_providers})'
                f'</div>',
                unsafe_allow_html=True
            )
        with pag_col3:
            if current_page < total_pages - 1:
                if st.button("Next →", key="btn_next_page"):
                    st.session_state.cards_page = current_page + 1
                    st.rerun()

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

    # =================================================
    # Admin: API Sync — Sync providers and games from API
    # =================================================
    with st.expander("🔄 Admin: Sync from API", expanded=False):
        st.caption(
            "Sync providers and games from the external API. "
            "Existing restrictions and currencies are preserved."
        )

        if st.button("Sync Providers & Games", type="primary", key="btn_api_sync"):
            with st.spinner("Syncing from API..."):
                try:
                    from api_sync import sync_all
                    result = sync_all()
                    st.success(f"Synced {result['providers']} providers, {result['games']} games")
                    st.cache_data.clear()
                except Exception as e:
                    st.error(f"Sync failed: {e}")
