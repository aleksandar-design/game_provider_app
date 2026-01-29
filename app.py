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
from openai import OpenAI

DB_PATH = Path("db") / "database.sqlite"

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
        width: 40px;
        height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
      }}
      .logo-icon img {{
        width: 100%;
        height: 100%;
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

      /* Filter container - style bordered containers */
      [data-testid="stVerticalBlockBorderWrapper"] {{
        border-radius: 16px !important;
        border: 1px solid {t["border"]} !important;
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
      }}
      .stDownloadButton > button:hover {{
        background: {t["primary"]}dd !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px {t["primary"]}40;
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
    </style>
    """,
    unsafe_allow_html=True,
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
# No additional CSS needed - the spacer column handles alignment

# Header with columns - logo left, spacer grows to push buttons right
logo_col, spacer, theme_col, logout_col = st.columns([2, 12, 0.5, 1])

with logo_col:
    st.markdown(logo_html, unsafe_allow_html=True)

with theme_col:
    def toggle_theme():
        new_theme = "light" if get_theme() == "dark" else "dark"
        set_theme(new_theme)
    # Moon icon for current dark mode, sun for light mode
    theme_icon = "☀" if current_theme == "dark" else "☾"
    st.button(theme_icon, key="btn_theme", help="Toggle theme", on_click=toggle_theme)

with logout_col:
    if st.button("→ Logout", key="btn_logout"):
        st.session_state["is_admin"] = False
        if "session" in st.query_params:
            del st.query_params["session"]
        st.rerun()

# Header divider
st.markdown(f'<div style="border-bottom: 1px solid {t["border"]}; margin-bottom: 1rem;"></div>', unsafe_allow_html=True)

# =================================================
# Filters (match mock layout)
# =================================================

# Defaults
st.session_state.setdefault("f_mode", "Supported")
st.session_state.setdefault("f_search", "")
st.session_state.setdefault("f_country", "All Countries")
st.session_state.setdefault("f_currency", "All Fiat Currencies")
st.session_state.setdefault("f_crypto", "All Crypto Currencies")

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

with st.container(border=True):
    st.markdown(f'''
    <div class="filter-title">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="{t["primary"]}" stroke-width="2">
            <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon>
        </svg>
        Filters
    </div>
    ''', unsafe_allow_html=True)

    left, right = st.columns([1, 1], gap="large")

    with left:
        search = st.text_input(
            "Search Provider:",
            placeholder="Search by name...",
            key="f_search",
            label_visibility="visible",
        )

        country_label = st.selectbox(
            "Country:",
            country_options,
            key="f_country",
        )

        # Mode row (Supported button + Restricted text/button)
        m1, m2 = st.columns([1, 1])
        with m1:
            supported_style = "primary" if filter_mode == "Supported" else "secondary"
            if st.button("Supported", key="btn_supported", type=supported_style, use_container_width=True):
                st.session_state["f_mode"] = "Supported"
                st.rerun()
        with m2:
            restricted_style = "primary" if filter_mode == "Restricted" else "secondary"
            if st.button("Restricted", key="btn_restricted", type=restricted_style, use_container_width=True):
                st.session_state["f_mode"] = "Restricted"
                st.rerun()

    with right:
        fiat_label = st.selectbox(
            "Fiat Currency:",
            fiat_options,
            key="f_currency",
        )

        crypto_label = st.selectbox(
            "Crypto Currency:",
            crypto_options,
            key="f_crypto",
        )

    # Active filter badges + Clear all (same row)
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

        af1, af2 = st.columns([8, 1], gap="small")
        with af1:
            st.markdown(badges_html, unsafe_allow_html=True)
        with af2:
            st.button("Clear all", key="btn_clear_all", type="secondary", on_click=clear_all_filters)

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
        "Export to Excel",
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
    provider_ids = df["ID"].tolist()
    placeholders = ",".join(["?"] * len(provider_ids))

    # Bulk load provider metadata
    provider_meta_df = qdf(
        f"SELECT provider_id, currency_mode FROM providers WHERE provider_id IN ({placeholders})",
        tuple(provider_ids),
    )
    provider_currency_mode = dict(
        zip(provider_meta_df["provider_id"], provider_meta_df["currency_mode"])
    )

    # Bulk load restrictions
    restrictions_df = qdf(
        f"""
        SELECT provider_id, country_code, restriction_type
        FROM restrictions
        WHERE provider_id IN ({placeholders})
        """,
        tuple(provider_ids),
    )
    restricted_map = {}
    regulated_map = {}
    restrictions_count_map = {}
    if not restrictions_df.empty:
        for row in restrictions_df.itertuples(index=False):
            restrictions_count_map[row.provider_id] = restrictions_count_map.get(row.provider_id, 0) + 1
            if row.restriction_type == "REGULATED":
                regulated_map.setdefault(row.provider_id, []).append(row.country_code)
            else:
                restricted_map.setdefault(row.provider_id, []).append(row.country_code)

    # Bulk load currencies
    empty_currencies_df = pd.DataFrame(columns=["currency_code", "currency_type"])
    try:
        fiat_df = qdf(
            f"""
            SELECT provider_id, currency_code, 'FIAT' as currency_type
            FROM fiat_currencies
            WHERE provider_id IN ({placeholders})
            """,
            tuple(provider_ids),
        )
        crypto_df = qdf(
            f"""
            SELECT provider_id, currency_code, 'CRYPTO' as currency_type
            FROM crypto_currencies
            WHERE provider_id IN ({placeholders})
            """,
            tuple(provider_ids),
        )
        currencies_df = pd.concat([fiat_df, crypto_df], ignore_index=True)
    except Exception:
        currencies_df = qdf(
            f"""
            SELECT provider_id, currency_code, currency_type
            FROM currencies
            WHERE provider_id IN ({placeholders})
            """,
            tuple(provider_ids),
        )
    currencies_grouped = (
        {pid: grp for pid, grp in currencies_df.groupby("provider_id")}
        if not currencies_df.empty
        else {}
    )
    currency_count_map = (
        currencies_df.groupby("provider_id").size().to_dict()
        if not currencies_df.empty
        else {}
    )

    # Bulk load games count
    try:
        games_df = qdf(
            f"""
            SELECT provider_id, COUNT(*) as games
            FROM games
            WHERE provider_id IN ({placeholders})
            GROUP BY provider_id
            """,
            tuple(provider_ids),
        )
        games_map = dict(zip(games_df["provider_id"], games_df["games"]))
    except Exception:
        games_map = {}

    # Bulk load game types per provider
    game_types_map = {}
    try:
        game_types_df = qdf(
            f"""
            SELECT provider_id, LOWER(game_type) as game_type
            FROM games
            WHERE provider_id IN ({placeholders})
            GROUP BY provider_id, LOWER(game_type)
            """,
            tuple(provider_ids),
        )
        if not game_types_df.empty:
            for row in game_types_df.itertuples(index=False):
                game_types_map.setdefault(row.provider_id, []).append(row.game_type or "")
    except Exception:
        game_types_map = {}

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

    # Create two columns for the grid
    col1, col2 = st.columns(2)

    for idx, row in df.iterrows():
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
            "currencies": currencies_grouped.get(pid, empty_currencies_df),
            "currency_mode": provider_currency_mode.get(pid, "ALL_FIAT"),
        }
        supported_games = sorted(
            {format_game_type(gt) for gt in game_types_map.get(pid, []) if gt}
        )

        # Alternate between columns
        target_col = col1 if idx % 2 == 0 else col2

        with target_col:
            # Build details HTML content
            details_html = ""
            # Restricted Countries
            if details["restricted"]:
                details_html += f'<div style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; font-weight: 600; color: {t["text_primary"]}; margin: 0.75rem 0;"><span style="color: {t["chart_yellow"]};">⚠</span> Restricted Countries ({len(details["restricted"])})</div>'
                restricted_countries = get_country_info(details["restricted"][:20])
                details_html += f'<div class="country-tags">'
                for c in restricted_countries:
                    details_html += f'<span class="country-tag" style="border-color: {t["tag_restricted_text"]};"><span class="iso" style="background: {t["tag_restricted_text"]};">{c["iso2"]}</span>{c["name"]}</span>'
                if len(details["restricted"]) > 20:
                    details_html += f'<span class="country-tag">+{len(details["restricted"]) - 20} more</span>'
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
            if details["currency_mode"] == "ALL_FIAT" or fiat_list:
                details_html += f'<div style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; font-weight: 600; color: {t["text_primary"]}; margin: 0.75rem 0;"><span style="color: {t["chart_green"]};">✓</span> Supported Currencies</div>'
                if details["currency_mode"] == "ALL_FIAT":
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
                        <div style="font-size: 0.75rem; color: {t["text_secondary"]}; margin-bottom: 0.5rem; font-weight: 600;">Supported Games</div>
                        <div class="games-container">
                            {''.join([f'<span class="game-chip">{g}</span>' for g in (supported_games or ['No data'])])}
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
