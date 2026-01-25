import os
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path("db") / "database.sqlite"

st.set_page_config(page_title="Game Providers", layout="wide")
st.markdown(
    """
    <style>
      /* Page padding */
      .block-container { padding-top: 1.25rem; padding-bottom: 2.5rem; }

      /* Reduce top empty space */
      header[data-testid="stHeader"] { height: 0rem; }

      /* Sidebar styling */
      section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(17,26,51,1) 0%, rgba(11,16,32,1) 100%);
        border-right: 1px solid rgba(255,255,255,0.06);
      }

      /* Make titles look nicer */
      h1, h2, h3 { letter-spacing: -0.02em; }

      /* Card look for containers (we'll use st.container(border=True)) */
      div[data-testid="stVerticalBlockBorderWrapper"] {
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 16px;
        background: rgba(255,255,255,0.02);
      }

      /* Buttons */
      .stButton>button {
        border-radius: 12px;
        padding: 0.55rem 0.95rem;
        border: 1px solid rgba(255,255,255,0.10);
      }

      /* Inputs */
      .stTextInput input, .stSelectbox div, .stMultiSelect div {
        border-radius: 12px !important;
      }

      /* Dataframe rounding */
      div[data-testid="stDataFrame"] {
        border-radius: 16px;
        overflow: hidden;
        border: 1px solid rgba(255,255,255,0.08);
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# -------------------------
# Auth helpers
# -------------------------
def get_admin_password() -> str:
    """
    Reads admin password from Streamlit Cloud Secrets first, then env var.
    - Streamlit Cloud: Secrets -> ADMIN_PASSWORD = "..."
    - Local: set environment variable ADMIN_PASSWORD
    """
    if "ADMIN_PASSWORD" in st.secrets:
        return str(st.secrets["ADMIN_PASSWORD"])
    return os.getenv("ADMIN_PASSWORD", "")


def is_admin() -> bool:
    return bool(st.session_state.get("is_admin", False))


def logout():
    st.session_state["is_admin"] = False
    st.session_state["admin_user"] = ""
    st.session_state["login_error"] = ""


def login_box():
    """
    Sidebar login UI. Admin panel is visible only if is_admin() is True.
    """
    st.sidebar.markdown("## Access")

    if is_admin():
        st.sidebar.success("Logged in as Admin")
        if st.sidebar.button("Logout"):
            logout()
        return

    st.sidebar.info("Login required for Admin editing")

    user = st.sidebar.text_input("Username", value="", key="admin_user")
    pw = st.sidebar.text_input("Password", value="", type="password", key="admin_password")

    if st.sidebar.button("Login"):
        real_pw = get_admin_password()
        if not real_pw:
            st.session_state["login_error"] = (
                "ADMIN_PASSWORD is not configured. Add it in Streamlit Secrets."
            )
        elif pw == real_pw:
            st.session_state["is_admin"] = True
            st.session_state["login_error"] = ""
            st.sidebar.success("Login successful ✅")
        else:
            st.session_state["login_error"] = "Wrong password ❌"

    err = st.session_state.get("login_error", "")
    if err:
        st.sidebar.error(err)


# -------------------------
# DB helpers
# -------------------------
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON;")
    return con


def qdf(query: str, params=()):
    with db() as con:
        return pd.read_sql_query(query, con, params=params)


@st.cache_data
def load_countries_table() -> pd.DataFrame:
    """
    Returns countries reference table with iso3 + name (if table exists).
    """
    if not DB_PATH.exists():
        return pd.DataFrame(columns=["iso3", "name", "label"])

    try:
        df = qdf("SELECT iso3, name FROM countries ORDER BY name")
        if df.empty:
            return pd.DataFrame(columns=["iso3", "name", "label"])
        df["label"] = df["name"] + " (" + df["iso3"] + ")"
        return df
    except Exception:
        # countries table might not exist yet
        return pd.DataFrame(columns=["iso3", "name", "label"])


@st.cache_data
def load_country_labels_from_restrictions() -> pd.DataFrame:
    """
    Uses restrictions table values (ISO3 codes) and joins to countries table if available.
    Returns columns: iso3, label
    """
    codes = qdf(
        "SELECT DISTINCT country_code AS iso3 FROM restrictions "
        "WHERE country_code IS NOT NULL AND country_code <> '' "
        "ORDER BY country_code"
    )
    countries_ref = load_countries_table()

    if countries_ref.empty:
        codes["label"] = codes["iso3"]
        return codes[["iso3", "label"]]

    merged = codes.merge(countries_ref[["iso3", "label"]], on="iso3", how="left")
    merged["label"] = merged["label"].fillna(merged["iso3"])
    return merged[["iso3", "label"]]


# -------------------------
# App start
# -------------------------
login_box()  # sidebar auth

st.markdown("## Game Providers")
st.caption("Browse providers by country restriction and supported FIAT currency.")


if not DB_PATH.exists():
    st.error("Database not found. Run: py db_init.py  then  py importer.py")
    st.stop()

countries_ref = load_countries_table()

# -------------------------
# Filters
# -------------------------
country_choices_df = load_country_labels_from_restrictions()
# --- Build country labels safely (so we never get NameError) ---
if country_choices_df is None or country_choices_df.empty:
    country_labels = []
    country_label_to_iso3 = {}
else:
    country_labels = country_choices_df["label"].dropna().tolist()
    country_label_to_iso3 = dict(zip(country_choices_df["label"], country_choices_df["iso3"]))

fiat = qdf(
    "SELECT DISTINCT currency_code FROM currencies WHERE currency_type='FIAT' ORDER BY currency_code"
)["currency_code"].tolist()

with st.container(border=True):
    st.subheader("Filters")
    f1, f2, f3 = st.columns([2, 1, 1])

    selected_country_label = f1.selectbox(
        "Country",
        [""] + country_labels,
        index=0,
    )
    country_iso3 = country_label_to_iso3.get(selected_country_label, "")

    currency = f2.selectbox("Currency (FIAT)", [""] + fiat, index=0)

    provider_search = f3.text_input("Search provider", value="")



st.caption(
    "Rules: providers with currency_mode=ALL_FIAT match any FIAT currency (even if not listed). "
    "Crypto is hidden by default."
)

# -------------------------
# Query building
if provider_search:
    where.append("LOWER(p.provider_name) LIKE ?")
    params.append(f"%{provider_search.lower()}%")

# -------------------------
params = []
where = []


# country restriction: exclude providers that have that country in restrictions
if country_iso3:
    where.append("p.provider_id NOT IN (SELECT provider_id FROM restrictions WHERE country_code = ?)")
    params.append(country_iso3)

# currency support:
if currency:
    where.append(
        """
        (
          p.currency_mode = 'ALL_FIAT'
          OR
          (p.currency_mode = 'LIST' AND EXISTS (
             SELECT 1 FROM currencies c
             WHERE c.provider_id = p.provider_id
               AND c.currency_type='FIAT'
               AND c.currency_code = ?
          ))
        )
        """
    )
    params.append(currency)

where_sql = ("WHERE " + " AND ".join(where)) if where else ""

df = qdf(
    f"""
    SELECT
      p.provider_id,
      p.provider_name
    FROM providers p
    {where_sql}
    ORDER BY p.provider_name
    """,
    tuple(params),
)
# Rename columns for UI
df = df.rename(columns={
    "provider_id": "ID",
    "provider_name": "Game Provider",
})


st.subheader("Results")
st.dataframe(
    df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "ID": st.column_config.NumberColumn("ID", width="small"),
        "Game Provider": st.column_config.TextColumn("Game Provider", width="large"),
    },
)


# -------------------------
# Admin panel (ONLY if logged in)
# -------------------------
if is_admin():
    with st.expander("Admin: Edit provider data", expanded=False):
        pid = st.number_input("provider_id", min_value=1, step=1)
        if pid:
            prov = qdf("SELECT * FROM providers WHERE provider_id=?", (pid,))
            if prov.empty:
                st.warning("Provider not found.")
            else:
                st.write("Provider:", prov.iloc[0].to_dict())

                # Add restriction
                st.markdown("### Add restriction")

                if not countries_ref.empty:
                    admin_country_label = st.selectbox(
                        "Country to restrict",
                        [""] + countries_ref["label"].tolist(),
                        key="admin_add_country_label",
                    )
                    new_cc = ""
                    if admin_country_label:
                        new_cc = admin_country_label.split("(")[-1].replace(")", "").strip()
                else:
                    new_cc = st.text_input("Country code (ISO3, e.g. GBR, USA)", value="").strip().upper()

                if st.button("Add restricted country"):
                    if new_cc:
                        with db() as con:
                            con.execute(
                                "INSERT OR IGNORE INTO restrictions(provider_id, country_code, source) VALUES (?, ?, ?)",
                                (pid, new_cc, "manual"),
                            )
                            con.commit()
                        st.success(f"Added restriction: {new_cc}")
                        st.cache_data.clear()
                    else:
                        st.warning("Choose a country (or enter ISO3) first.")

                # Remove restriction
                st.markdown("### Remove restriction")
                existing_df = qdf(
                    "SELECT country_code FROM restrictions WHERE provider_id=? ORDER BY country_code",
                    (pid,),
                )
                existing_codes = existing_df["country_code"].tolist()

                if existing_codes:
                    if not countries_ref.empty:
                        tmp = pd.DataFrame({"iso3": existing_codes})
                        tmp = tmp.merge(countries_ref[["iso3", "label"]], on="iso3", how="left")
                        tmp["label"] = tmp["label"].fillna(tmp["iso3"])
                        rem_label = st.selectbox("Choose to remove", [""] + tmp["label"].tolist(), key="admin_remove_country")
                        rem_code = ""
                        if rem_label:
                            rem_code = rem_label.split("(")[-1].replace(")", "").strip() if "(" in rem_label else rem_label
                    else:
                        rem_code = st.selectbox("Choose to remove (ISO3)", [""] + existing_codes, key="admin_remove_country")

                    if st.button("Remove selected restriction"):
                        if rem_code:
                            with db() as con:
                                con.execute(
                                    "DELETE FROM restrictions WHERE provider_id=? AND country_code=?",
                                    (pid, rem_code),
                                )
                                con.commit()
                            st.success(f"Removed restriction: {rem_code}")
                            st.cache_data.clear()
                        else:
                            st.warning("Pick a restriction to remove.")
                else:
                    st.info("No restrictions found for this provider.")

                # Add currency
                st.markdown("### Add currency")
                ccode = st.text_input("Currency code (e.g. BRL, USD)", key="ccode").strip().upper()
                ctype = st.selectbox("Type", ["FIAT", "CRYPTO"])
                display = st.checkbox("Display (show in app)", value=(ctype == "FIAT"))

                if st.button("Add currency"):
                    if ccode:
                        with db() as con:
                            con.execute(
                                """
                                INSERT OR IGNORE INTO currencies(provider_id, currency_code, currency_type, display, source)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (pid, ccode, ctype, 1 if display else 0, "manual"),
                            )
                            con.commit()
                        st.success(f"Added currency: {ccode} ({ctype})")
                        st.cache_data.clear()
                    else:
                        st.warning("Enter a currency code first.")

                # Remove currency
                st.markdown("### Remove currency")
                cur = qdf(
                    "SELECT currency_code || ' (' || currency_type || ')' AS label "
                    "FROM currencies WHERE provider_id=? ORDER BY currency_type, currency_code",
                    (pid,),
                )
                labels = cur["label"].tolist()
                pick = st.selectbox("Choose to remove currency", [""] + labels)

                if st.button("Remove selected currency"):
                    if pick:
                        code = pick.split(" ")[0]
                        ctype2 = pick.split("(")[-1].replace(")", "").strip()
                        with db() as con:
                            con.execute(
                                "DELETE FROM currencies WHERE provider_id=? AND currency_code=? AND currency_type=?",
                                (pid, code, ctype2),
                            )
                            con.commit()
                        st.success(f"Removed currency: {code} ({ctype2})")
                        st.cache_data.clear()
                    else:
                        st.warning("Pick a currency to remove.")
else:
    st.info("Admin editing is hidden. Login in the sidebar to edit provider data.")

st.caption(
    "Re-import from files by running: py importer.py (replaces imported restrictions/currencies for those providers)."
)
