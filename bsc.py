import streamlit as st
import os
import json
import pandas as pd
from postmarker.core import PostmarkClient
from datetime import datetime, timedelta
import uuid
import gspread
from google.oauth2.service_account import Credentials
import base64
import logging
import argparse

# --- CONFIGURATION ---
# Try to load a local .env file if python-dotenv is installed (development convenience).
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # dotenv is optional; falling back to environment variables
    pass


def get_postmark_token():
    """Return the Postmark API token from Streamlit secrets or environment variable.
    Prefer `st.secrets['postmark']['token']` in deployment. Raises RuntimeError with guidance if missing.
    """
    token = None
    try:
        token = st.secrets["postmark"]["token"]
    except Exception:
        token = os.getenv("POSTMARK_API_TOKEN")
    if not token:
        raise RuntimeError("POSTMARK API token is not set. Put it in `st.secrets['postmark']['token']` or set POSTMARK_API_TOKEN env var.")
    return token


def score_perspective(action_text, files, keywords):
    """Return a score (0-25) for the given action_text and list of UploadedFile-like objects.
    Scoring is based on keyword relevance (up to 15 pts) and length (up to 10 pts).
    If the action is >200 chars and there are 2+ attachments, apply a small extra-mile boost (up to +3 within the 25 cap).
    """
    text = (action_text or "").lower()
    if not text:
        return 0.0

    # Keyword relevance (scale to 0-15 pts)
    matches = 0
    for kw in keywords:
        if kw.lower() in text:
            matches += 1
    keyword_points = min(matches, 5) / 5.0 * 15.0  # up to 15 points

    # Length score (scale to 0-10 pts, target 300 chars)
    length_points = min(len(text), 300) / 300.0 * 10.0

    score = keyword_points + length_points

    # Extra mile: if long description and 2+ attachments, give a small boost within the 25-point cap
    try:
        num_files = len(files) if files else 0
    except Exception:
        num_files = 0

    if len(text) > 200 and num_files >= 2:
        score = min(25.0, score + 3.0)

    return round(min(25.0, score), 1)

# Token will be loaded at runtime via get_postmark_token(). Never embed secrets in source control.
POSTMARK_API_TOKEN = None
TARGET_EMAIL = "busdev3@securico.co.zw"
GDRIVE_HOLDER_ID = "1Ll1N63MviMMNH7zmYxwh2TqVSOTglXtg"

CSV_LOG_PATH = "evaluator_records.csv"

# Define the Balanced Scorecard (BSC) structure with perspectives and strategic goals
bsc_structure = {
    "Financial": "Improve profitability and financial performance",
    "Customer": "Enhance customer satisfaction and retention",
    "Internal Business Processes": "Optimize operational efficiency and compliance",
    "Learning & Growth": "Develop employee skills and organizational capacity"
}

st.set_page_config(page_title="MD AWARDS", page_icon="🏆", layout="wide")


def get_gspread_client():
    """Return an authorized gspread client using st.secrets['gcp_service_account'] or env var fallback.
    Robustly handles dicts, JSON strings, base64-encoded JSON, or paths to a JSON file.
    Fixes common private_key newline escaping ("\\n") coming from Streamlit secrets.

    Fallback order (attempts in this order):
      1. st.secrets['gcp_service_account'] (preferred)
      2. GCP_SERVICE_ACCOUNT or GCP_SERVICE_ACCOUNT_FILE env var (JSON string, base64 string, or path to JSON file)
    """
    try:
        sa = st.secrets.get("gcp_service_account")

        # If not found in Streamlit secrets, try environment variable (JSON string, base64, or file path)
        if not sa:
            env_val = os.getenv("GCP_SERVICE_ACCOUNT") or os.getenv("GCP_SERVICE_ACCOUNT_FILE")
            if env_val:
                # If env_val points to an existing file, load it
                if os.path.exists(env_val):
                    with open(env_val, "r", encoding="utf-8") as fh:
                        sa = json.load(fh)
                else:
                    # Try parsing as JSON string
                    try:
                        sa = json.loads(env_val)
                    except Exception:
                        # Try base64-decoded JSON
                        try:
                            decoded = base64.b64decode(env_val).decode("utf-8")
                            sa = json.loads(decoded)
                        except Exception:
                            raise RuntimeError("Environment variable GCP_SERVICE_ACCOUNT is not valid JSON, base64 JSON, nor a readable file path")

        if not sa:
            raise RuntimeError("GCP service account credentials not found. Set st.secrets['gcp_service_account'] or the GCP_SERVICE_ACCOUNT env var (JSON string, base64, or path to JSON file)")

        # If the secret is a single-key mapping that contains the real dict inside, try to unwrap it
        if isinstance(sa, dict) and len(sa) == 1:
            inner = next(iter(sa.values()))
            if isinstance(inner, dict) and "private_key" in inner:
                sa = inner

        # Normalize to dict (handle JSON strings or base64-encoded strings stored in secrets)
        sa_info = None
        if isinstance(sa, str):
            # Could be raw JSON, base64 JSON, or a filepath string
            try:
                sa_info = json.loads(sa)
            except Exception:
                try:
                    sa_info = json.loads(base64.b64decode(sa).decode("utf-8"))
                except Exception:
                    # If the string is a path to a file, load it
                    if os.path.exists(sa):
                        with open(sa, "r", encoding="utf-8") as fh:
                            sa_info = json.load(fh)
                    else:
                        raise RuntimeError("GCP service account string could not be parsed as JSON, base64 JSON, or a file path")
        elif isinstance(sa, dict):
            sa_info = sa
        else:
            raise RuntimeError("GCP service account credential is in an unsupported format")

        # Fix escaped newlines in private_key which commonly come from Streamlit secrets or env storage
        if "private_key" in sa_info and isinstance(sa_info["private_key"], str):
            sa_info["private_key"] = sa_info["private_key"].replace("\\n", "\n")

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
        ]

        # Try to create a client using the convenience helper, falling back to explicit Credentials
        try:
            # newer gspread versions accept scopes here
            return gspread.service_account_from_dict(sa_info, scopes=scopes)
        except TypeError:
            # some versions don't accept scopes argument
            try:
                return gspread.service_account_from_dict(sa_info)
            except Exception:
                creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
                return gspread.authorize(creds)
        except Exception:
            creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
            return gspread.authorize(creds)
    except Exception as e:
        logging.exception("Error initializing gspread client")
        st.error(f"❌ Could not initialize Google Sheets client: {e}. Ensure st.secrets['gcp_service_account'] or the GCP_SERVICE_ACCOUNT env var (JSON/base64/path) is set and that the service account has access to the spreadsheet.")
        return None


def log_submission(first_name, last_name, score_breakdown, actions_dict, folder_url):
    """Append a submission record to the Google Sheet 'MD Awards Voting'.
    Falls back to local CSV if Google Sheets API is unavailable.
    """
    name = f"{first_name.strip()} {last_name.strip()}".strip()
    timestamp = datetime.now().isoformat()
    total_score = round(sum(score_breakdown.values()), 1)

    # Row layout written to Google Sheet
    row = [
        name,
        timestamp,
        total_score,
        score_breakdown.get("Financial", 0.0),
        actions_dict.get("Financial", ""),
        score_breakdown.get("Customer", 0.0),
        actions_dict.get("Customer", ""),
        score_breakdown.get("Internal Business Processes", 0.0),
        actions_dict.get("Internal Business Processes", ""),
        score_breakdown.get("Learning & Growth", 0.0),
        actions_dict.get("Learning & Growth", ""),
        "",  # Evaluator Vote (to be set by evaluators)
        ""   # Evaluator Comment (to be set by evaluators)
    ]

    headers = [
        "Name",
        "Timestamp",
        "Total Score",
        "Financial Score",
        "Financial Action",
        "Customer Score",
        "Customer Action",
        "Internal Business Processes Score",
        "Internal Business Processes Action",
        "Learning & Growth Score",
        "Learning & Growth Action",
        "Evaluator Vote",
        "Evaluator Comment"
    ]

    try:
        gc = get_gspread_client()
        if not gc:
            raise RuntimeError("GCP Sheets client unavailable")
        sh = gc.open("MD Awards Voting")
        worksheet = sh.sheet1
        existing = worksheet.get_all_values()
        if not existing:
            worksheet.append_row(headers)
        worksheet.append_row(row)
    except Exception as e:
        st.error(f"⚠️ Could not write submission to Google Sheet: {e}")
        # Fallback to local CSV to avoid data loss
        try:
            record = {
                "Name": name,
                "Date": timestamp,
                "Total Score": total_score,
                "Financial Score": score_breakdown.get("Financial", 0.0),
                "Financial Action": actions_dict.get("Financial", ""),
                "Customer Score": score_breakdown.get("Customer", 0.0),
                "Customer Action": actions_dict.get("Customer", ""),
                "Internal Business Processes Score": score_breakdown.get("Internal Business Processes", 0.0),
                "Internal Business Processes Action": actions_dict.get("Internal Business Processes", ""),
                "Learning & Growth Score": score_breakdown.get("Learning & Growth", 0.0),
                "Learning & Growth Action": actions_dict.get("Learning & Growth", ""),
                "Folder_URL": folder_url
            }
            if os.path.exists(CSV_LOG_PATH):
                df = pd.read_csv(CSV_LOG_PATH)
                df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
            else:
                df = pd.DataFrame([record])
            df.to_csv(CSV_LOG_PATH, index=False)
        except Exception as e2:
            st.error(f"⚠️ Could not write submission to backup CSV: {e2}")


def read_records():
    """Read submissions from the Google Sheet 'MD Awards Voting' and return as a DataFrame.
    Falls back to local CSV if the sheet is unavailable.
    """
    try:
        gc = get_gspread_client()
        if not gc:
            raise RuntimeError("GCP Sheets client unavailable")
        sh = gc.open("MD Awards Voting")
        worksheet = sh.sheet1
        records = worksheet.get_all_records()
        df = pd.DataFrame.from_records(records)
        if df.empty:
            return None
        return df
    except Exception as e:
        st.error(f"⚠️ Error reading records from Google Sheet: {e}")
        # Fallback to CSV
        try:
            if os.path.exists(CSV_LOG_PATH):
                return pd.read_csv(CSV_LOG_PATH)
            return None
        except Exception as e2:
            st.error(f"⚠️ Error reading local CSV: {e2}")
            return None


def update_evaluator_vote(name, timestamp, vote, comment, lock_token=None):
    """Update the Evaluator Vote and Evaluator Comment for a given submission.
    Enforces lock when available (requires valid `lock_token` to update locked rows).
    Tries Google Sheet first; falls back to updating the local CSV file.
    Returns True on success, False on failure.
    """
    try:
        gc = get_gspread_client()
        if not gc:
            raise RuntimeError("GCP Sheets client unavailable")
        sh = gc.open("MD Awards Voting")
        worksheet = sh.sheet1

        headers = worksheet.row_values(1)
        records = worksheet.get_all_records()

        # Find matching row: prefer exact timestamp match, else latest by name
        row_idx = None
        for i, r in enumerate(records, start=2):
            if r.get("Name") == name and timestamp and str(r.get("Timestamp")) == str(timestamp):
                row_idx = i
                break
        if not row_idx:
            # fallback to latest by name
            for i, r in enumerate(reversed(records), start=1):
                if r.get("Name") == name:
                    # convert reversed index to actual row index
                    row_idx = len(records) - i + 2
                    break
        if not row_idx:
            raise RuntimeError("Could not locate submission row for candidate")

        # Determine lock columns (if present)
        lock_col = None
        lock_expiry_col = None
        for idx, h in enumerate(headers, start=1):
            if h == "Lock Token":
                lock_col = idx
            if h == "Lock Expiry":
                lock_expiry_col = idx

        # If locked, verify provided lock_token matches
        if lock_col is not None:
            current_token = worksheet.cell(row_idx, lock_col).value or ""
            if current_token:
                if not lock_token or str(lock_token) != str(current_token):
                    raise RuntimeError("Row is locked by another editor; acquire lock before updating")

        # Ensure vote/comment columns exist (append if missing)
        vote_col = None
        comment_col = None
        for idx, h in enumerate(headers, start=1):
            if h == "Evaluator Vote":
                vote_col = idx
            if h == "Evaluator Comment":
                comment_col = idx

        last_col = len(headers)
        if vote_col is None:
            vote_col = last_col + 1
            worksheet.update_cell(1, vote_col, "Evaluator Vote")
            last_col = vote_col
        if comment_col is None:
            comment_col = last_col + 1
            worksheet.update_cell(1, comment_col, "Evaluator Comment")

        worksheet.update_cell(row_idx, vote_col, vote)
        worksheet.update_cell(row_idx, comment_col, comment)

        # If a lock token was provided, clear it after a successful update
        if lock_col is not None and lock_token:
            worksheet.update_cell(row_idx, lock_col, "")
            if lock_expiry_col is not None:
                worksheet.update_cell(row_idx, lock_expiry_col, "")
        return True
    except Exception as e:
        st.error(f"⚠️ Could not update Google Sheet: {e}")
        # Fallback to CSV
        try:
            if os.path.exists(CSV_LOG_PATH):
                df = pd.read_csv(CSV_LOG_PATH)
                # Add columns if missing
                if "Evaluator Vote" not in df.columns:
                    df["Evaluator Vote"] = ""
                if "Evaluator Comment" not in df.columns:
                    df["Evaluator Comment"] = ""
                if "Lock Token" not in df.columns:
                    df["Lock Token"] = ""
                if "Lock Expiry" not in df.columns:
                    df["Lock Expiry"] = ""

                mask = df["Name"] == name
                if timestamp and "Date" in df.columns:
                    mask = mask & (df["Date"] == timestamp)

                # If locked, verify
                if "Lock Token" in df.columns and mask.any():
                    current = df.loc[mask, "Lock Token"].astype(str).iloc[0]
                    if current and (not lock_token or str(lock_token) != str(current)):
                        raise RuntimeError("Row is locked by another editor; acquire lock before updating")

                if not mask.any():
                    # pick last occurrence
                    idx = df[df["Name"] == name].last_valid_index()
                    if idx is None:
                        raise RuntimeError("No matching record in CSV to update")
                    df.at[idx, "Evaluator Vote"] = vote
                    df.at[idx, "Evaluator Comment"] = comment
                    # clear locks
                    if lock_token:
                        df.at[idx, "Lock Token"] = ""
                        df.at[idx, "Lock Expiry"] = ""
                else:
                    df.loc[mask, "Evaluator Vote"] = vote
                    df.loc[mask, "Evaluator Comment"] = comment
                    if lock_token:
                        df.loc[mask, "Lock Token"] = ""
                        df.loc[mask, "Lock Expiry"] = ""

                df.to_csv(CSV_LOG_PATH, index=False)
                return True
        except Exception as e2:
            st.error(f"⚠️ Could not write vote to backup CSV: {e2}")
        return False


def acquire_lock(name, timestamp, holder="Evaluator", timeout_seconds=120):
    """Attempt to acquire an edit lock for a submission row.
    Returns (token, expiry_iso) on success, (None, None) on failure.
    """
    try:
        gc = get_gspread_client()
        if not gc:
            raise RuntimeError("GCP Sheets client unavailable")
        sh = gc.open("MD Awards Voting")
        worksheet = sh.sheet1

        headers = worksheet.row_values(1)
        records = worksheet.get_all_records()

        # Find row
        row_idx = None
        for i, r in enumerate(records, start=2):
            if r.get("Name") == name and timestamp and str(r.get("Timestamp")) == str(timestamp):
                row_idx = i
                break
        if not row_idx:
            for i, r in enumerate(reversed(records), start=1):
                if r.get("Name") == name:
                    row_idx = len(records) - i + 2
                    break
        if not row_idx:
            raise RuntimeError("Could not locate submission row for candidate")

        # Ensure lock columns exist
        lock_col = None
        expiry_col = None
        holder_col = None
        for idx, h in enumerate(headers, start=1):
            if h == "Lock Token":
                lock_col = idx
            if h == "Lock Expiry":
                expiry_col = idx
            if h == "Lock Holder":
                holder_col = idx

        last_col = len(headers)
        if lock_col is None:
            lock_col = last_col + 1
            worksheet.update_cell(1, lock_col, "Lock Token")
            last_col = lock_col
        if expiry_col is None:
            expiry_col = last_col + 1
            worksheet.update_cell(1, expiry_col, "Lock Expiry")
            last_col = expiry_col
        if holder_col is None:
            holder_col = last_col + 1
            worksheet.update_cell(1, holder_col, "Lock Holder")

        # Check current lock
        current_token = worksheet.cell(row_idx, lock_col).value or ""
        current_expiry = worksheet.cell(row_idx, expiry_col).value or ""
        if current_token:
            try:
                exp = datetime.fromisoformat(current_expiry)
                if exp > datetime.utcnow():
                    st.error("Row is currently locked by another evaluator.")
                    return None, None
            except Exception:
                # If expiry unparsable, treat as locked
                st.error("Row appears locked; try again later or contact an admin.")
                return None, None

        token = str(uuid.uuid4())
        expiry_dt = datetime.utcnow() + timedelta(seconds=timeout_seconds)
        expiry_iso = expiry_dt.isoformat()

        worksheet.update_cell(row_idx, lock_col, token)
        worksheet.update_cell(row_idx, expiry_col, expiry_iso)
        worksheet.update_cell(row_idx, holder_col, holder)

        return token, expiry_iso
    except Exception as e:
        st.error(f"⚠️ Could not acquire lock: {e}")
        # CSV fallback
        try:
            if os.path.exists(CSV_LOG_PATH):
                df = pd.read_csv(CSV_LOG_PATH)
                if "Lock Token" not in df.columns:
                    df["Lock Token"] = ""
                if "Lock Expiry" not in df.columns:
                    df["Lock Expiry"] = ""
                if "Lock Holder" not in df.columns:
                    df["Lock Holder"] = ""

                mask = df["Name"] == name
                if timestamp and "Date" in df.columns:
                    mask = mask & (df["Date"] == timestamp)

                if mask.any():
                    idx = df[mask].index[0]
                    current_token = str(df.at[idx, "Lock Token"]) or ""
                    current_expiry = str(df.at[idx, "Lock Expiry"]) or ""
                    if current_token:
                        try:
                            exp = datetime.fromisoformat(current_expiry)
                            if exp > datetime.utcnow():
                                st.error("Row is currently locked by another evaluator.")
                                return None, None
                        except Exception:
                            st.error("Row appears locked; try again later or contact an admin.")
                            return None, None

                    token = str(uuid.uuid4())
                    expiry_dt = datetime.utcnow() + timedelta(seconds=timeout_seconds)
                    expiry_iso = expiry_dt.isoformat()
                    df.at[idx, "Lock Token"] = token
                    df.at[idx, "Lock Expiry"] = expiry_iso
                    df.at[idx, "Lock Holder"] = holder
                    df.to_csv(CSV_LOG_PATH, index=False)
                    return token, expiry_iso
        except Exception as e2:
            st.error(f"⚠️ Could not acquire lock in CSV fallback: {e2}")
        return None, None


def release_lock(name, timestamp, token):
    """Release an edit lock if token matches. Returns True on success."""
    try:
        gc = get_gspread_client()
        if not gc:
            raise RuntimeError("GCP Sheets client unavailable")
        sh = gc.open("MD Awards Voting")
        worksheet = sh.sheet1

        headers = worksheet.row_values(1)
        records = worksheet.get_all_records()

        row_idx = None
        for i, r in enumerate(records, start=2):
            if r.get("Name") == name and timestamp and str(r.get("Timestamp")) == str(timestamp):
                row_idx = i
                break
        if not row_idx:
            for i, r in enumerate(reversed(records), start=1):
                if r.get("Name") == name:
                    row_idx = len(records) - i + 2
                    break
        if not row_idx:
            raise RuntimeError("Could not locate submission row for candidate")

        lock_col = None
        expiry_col = None
        for idx, h in enumerate(headers, start=1):
            if h == "Lock Token":
                lock_col = idx
            if h == "Lock Expiry":
                expiry_col = idx

        if lock_col is None:
            return False

        current = worksheet.cell(row_idx, lock_col).value or ""
        if not current or str(current) != str(token):
            st.error("Cannot release lock: token does not match current lock")
            return False

        worksheet.update_cell(row_idx, lock_col, "")
        if expiry_col is not None:
            worksheet.update_cell(row_idx, expiry_col, "")
        return True
    except Exception as e:
        st.error(f"⚠️ Could not release lock on Google Sheet: {e}")
        # CSV fallback
        try:
            if os.path.exists(CSV_LOG_PATH):
                df = pd.read_csv(CSV_LOG_PATH)
                if "Lock Token" not in df.columns:
                    return False
                mask = df["Name"] == name
                if timestamp and "Date" in df.columns:
                    mask = mask & (df["Date"] == timestamp)
                if not mask.any():
                    idx = df[df["Name"] == name].last_valid_index()
                    if idx is None:
                        return False
                else:
                    idx = df[mask].index[0]
                current = str(df.at[idx, "Lock Token"]) or ""
                if not current or str(current) != str(token):
                    st.error("Cannot release lock: token does not match current lock in CSV")
                    return False
                df.at[idx, "Lock Token"] = ""
                df.at[idx, "Lock Expiry"] = ""
                df.to_csv(CSV_LOG_PATH, index=False)
                return True
        except Exception as e2:
            st.error(f"⚠️ Could not release lock in CSV fallback: {e2}")
        return False

# --- SIDEBAR MOTIVATION ---
with st.sidebar:
    st.markdown("# 💡 Winning Tips")
    st.info("""
    **To reach 'Extra Mile' status:**
    * 📝 Write detailed descriptions (>100 chars).
    * 📎 Attach 2+ files per perspective.
    * 🎯 Align actions with the listed Goal.
    """)
    st.divider()
    st.caption("Business Development 2026")

# --- APP HEADER ---
st.title("🏆 MD’S Quality & Excellence Awards")
st.markdown("---")

# 1. Identity Fields & Authentication

# Authentication in the sidebar
with st.sidebar:
    st.markdown("# 🔐 Evaluator Access")
    eval_pwd = st.text_input("Evaluator Password", type="password", help="Enter evaluator password to access workspace")

# Check evaluator password using st.secrets
try:
    is_evaluator = bool(eval_pwd and eval_pwd == st.secrets["auth"]["evaluator_password"])
except Exception:
    is_evaluator = False

if is_evaluator:
    st.header("Evaluator Workspace")
    tab1, tab2 = st.tabs(["Summary Table", "Detailed Review"])
    df = read_records()

    with tab1:
        if df is None or df.empty:
            st.info("Informing: No submissions found yet.")
        else:
            # Mark the latest submission with an indicator
            display_df = df.copy()
            # Ensure proper datetime parsing for robust sorting
            display_df["Date_parsed"] = pd.to_datetime(display_df["Date"], errors="coerce")
            display_df = display_df.sort_values("Date_parsed", ascending=False)
            if not display_df.empty:
                latest = display_df.iloc[0]
                display_df["Latest"] = ""
                display_df.loc[display_df.index[0], "Latest"] = "🏅"
                st.caption(f"Latest submission: {latest['Name']} — {latest['Date']} — Total Score: {latest['Total Score']}")
            st.dataframe(display_df[["Latest", "Name", "Total Score", "Date"]])

    with tab2:
        if df is None or df.empty:
            st.info("Informing: No submissions found yet.")
        else:
            names = df["Name"].unique().tolist()
            selected = st.selectbox("Select Candidate", names)
            if selected:
                rec = df[df["Name"] == selected].sort_values("Date", ascending=False).iloc[0]
                st.subheader(f"Review: {selected}")
                st.metric("Total Score", rec.get("Total Score", ""))

                st.write("**Individual Scores**")
                st.write(f"Financial: {rec.get('Financial Score', '')} / 25")
                st.write(f"Customer: {rec.get('Customer Score', '')} / 25")
                st.write(f"Internal Business Processes: {rec.get('Internal Business Processes Score', '')} / 25")
                st.write(f"Learning & Growth: {rec.get('Learning & Growth Score', '')} / 25")

                st.write("**Action Taken (Full Text)**")
                st.write(f"**Financial:** {rec.get('Financial Action', '')}")
                st.write(f"**Customer:** {rec.get('Customer Action', '')}")
                st.write(f"**Internal Business Processes:** {rec.get('Internal Business Processes Action', '')}")
                st.write(f"**Learning & Growth:** {rec.get('Learning & Growth Action', '')}")

                folder_url = rec.get('Folder_URL') or f"https://drive.google.com/drive/folders/{GDRIVE_HOLDER_ID}"
                try:
                    st.link_button("📂 Open Candidate Evidence", url=folder_url)
                except Exception:
                    st.markdown(f"[📂 Open Candidate Evidence]({folder_url})")

                # --- Evaluator vote & comment UI with locking ---
                st.divider()
                st.subheader("Evaluator Vote & Comment")

                # Pre-fill existing evaluator vote/comment if present
                existing_vote = rec.get("Evaluator Vote", "") if rec is not None else ""
                existing_comment = rec.get("Evaluator Comment", "") if rec is not None else ""

                # Lock state in session
                lock_key = f"lock_token_{selected}"
                expiry_key = f"lock_expiry_{selected}"
                locked_token = st.session_state.get(lock_key)
                locked_expiry = st.session_state.get(expiry_key)

                timestamp = rec.get("Timestamp") or rec.get("Date")

                if locked_token:
                    st.info(f"🔒 You hold the edit lock. Expires: {locked_expiry}")
                    if st.button("Release Lock", key=f"release_lock_{selected}"):
                        ok = release_lock(selected, timestamp, locked_token)
                        if ok:
                            st.success("✅ Lock released.")
                            del st.session_state[lock_key]
                            if expiry_key in st.session_state:
                                del st.session_state[expiry_key]
                            df = read_records()
                        else:
                            st.error("⚠️ Could not release lock. See messages above.")
                else:
                    if st.button("Acquire Edit Lock", key=f"acquire_lock_{selected}"):
                        token, expiry = acquire_lock(selected, timestamp, holder="Evaluator", timeout_seconds=120)
                        if token:
                            st.session_state[lock_key] = token
                            st.session_state[expiry_key] = expiry
                            st.success("✅ Lock acquired. You can now edit and submit.")
                            df = read_records()
                        else:
                            st.error("⚠️ Could not acquire lock. See messages above.")

                vote_options = ["", "Shortlist", "Winner", "Reject"]
                disabled = False if locked_token else True
                vote_choice = st.selectbox("Your vote", vote_options, index=vote_options.index(existing_vote) if existing_vote in vote_options else 0, key=f"vote_{selected}", disabled=disabled)
                evaluator_comment = st.text_area("Comment (optional)", value=(existing_comment or ""), key=f"comment_{selected}", disabled=disabled)

                if st.button("Submit Vote & Comment", key=f"submit_vote_{selected}"):
                    if not locked_token:
                        st.error("⚠️ Acquire an edit lock before submitting to avoid conflicts.")
                    else:
                        success = update_evaluator_vote(selected, timestamp, vote_choice, evaluator_comment, lock_token=locked_token)
                        if success:
                            # release lock after successful update
                            released = release_lock(selected, timestamp, locked_token)
                            if lock_key in st.session_state:
                                del st.session_state[lock_key]
                            if expiry_key in st.session_state:
                                del st.session_state[expiry_key]
                            if released:
                                st.success("✅ Vote & Comment submitted and lock released.")
                            else:
                                st.success("✅ Vote & Comment submitted.")
                            # Refresh the DataFrame so changes appear immediately
                            df = read_records()
                        else:
                            st.error("⚠️ Could not submit vote/comment. See messages above.")

else:
    # Employee Submission Form
    col_a, col_b = st.columns(2)
    with col_a:
        first_name = st.text_input("First Name", placeholder="Enter your first name")
    with col_b:
        last_name = st.text_input("Surname", placeholder="Enter your surname")

    # --- DYNAMIC DASHBOARD (Updates as user fills form) ---
    st.write("### 📊 Submission Strength Dashboard")
    m1, m2, m3, m4 = st.columns(4)

    # --- FORM SECTION ---
    with st.form("bsc_form"):
        user_data = {}
        for p, goal in bsc_structure.items():
            st.subheader(f"🔹 {p} Perspective")
            st.markdown(f"**Strategic Goal:** `{goal}`")

            col1, col2 = st.columns([2, 1])
            with col1:
                action = st.text_area(f"Describe Action Taken", key=f"text_{p}", help="Be specific about your contribution.")
            with col2:
                attachments = st.file_uploader(f"Upload Evidence", 
                                               accept_multiple_files=True, 
                                               key=f"file_{p}")

            user_data[p] = {"action": action, "files": attachments}
            st.divider()

        submit = st.form_submit_button("🚀 Submit Final Performance for Evaluation")

    # --- POST-SUBMISSION LOGIC ---
    if submit:
        if not first_name or not last_name:
            st.error("⚠️ Identity Required: Please provide your Name and Surname.")
        else:
            try:
                token = get_postmark_token()
            except RuntimeError as e:
                st.error(f"⚠️ System Config Error: {e}")
            else:
                # Compute scores for each perspective
                score_breakdown = {}
                all_files = []

                keyword_map = {
                    "Financial": ["revenue", "cost", "profit", "margin", "budget", "pricing", "savings", "income", "expense"],
                    "Customer": ["customer", "client", "satisfaction", "retention", "feedback", "complaint", "loyalty", "support", "nps"],
                    "Internal Business Processes": ["process", "efficien", "compliance", "safety", "audit", "quality", "procedure", "automation", "sheq"],
                    "Learning & Growth": ["train", "develop", "workshop", "ment", "competenc", "engag", "learning", "upskill", "coaching"]
                }

                for p, data in user_data.items():
                    action_text = (data.get("action") or "").strip()
                    files = data.get("files") or []
                    kw = keyword_map.get(p, [])
                    score = score_perspective(action_text, files, kw)
                    score_breakdown[p] = score

                    # collect files
                    if files:
                        for file in files:
                            all_files.append(file)

                total_score = sum(score_breakdown.values())

                # Build email body including the score breakdown
                breakdown_lines = "\n".join([f"**{p}:** {score:.1f} / 25" for p, score in score_breakdown.items()])
                email_body = f"""
                **MD’S Quality & Excellence Awards Submission**

                **Name:** {first_name} {last_name}

                ---
                **Score Breakdown (per perspective):**
                {breakdown_lines}

                **Total Score:** {total_score:.1f} / 100

                """

                # --- POSTMARK EMAIL LOGIC ---
                try:
                    client = PostmarkClient(server_token=token)

                    # Convert Streamlit UploadedFile objects into Postmark-friendly dicts
                    pm_attachments = []
                    for up in all_files:
                        raw = up.getvalue()  # bytes
                        pm_attachments.append({
                            "Name": up.name,
                            "Content": base64.b64encode(raw).decode("ascii"),
                            "ContentType": up.type or "application/octet-stream"
                        })

                    # Send Email (attachments optional)
                    response = client.emails.send(
                        From=TARGET_EMAIL,
                        To=TARGET_EMAIL,
                        Subject="🏆 New Submission Received for MD’s Awards",
                        HtmlBody=email_body,
                        Attachments=pm_attachments
                    )

                    # Log submission to CSV including action text and folder URL
                    folder_url = f"https://drive.google.com/drive/folders/{GDRIVE_HOLDER_ID}"
                    actions_only = {p: (user_data[p]["action"] or "") for p in user_data}
                    log_submission(first_name, last_name, score_breakdown, actions_only, folder_url)

                    st.success("✅ Submission successful! Your performance will be reviewed shortly.")
                except Exception as e:
                    st.error(f"⚠️ Error in submission: {str(e)}")

def compute(a, b):
    return a + b


def test_compute_basic():
    expected_value = 5
    assert compute(2, 3) == expected_value


def test_score_empty():
    assert score_perspective("", [], []) == 0.0


def test_score_keywords_and_length():
    kw = ["revenue", "budget"]
    action = "We increased revenue and reduced budget spend significantly to improve margins."
    score = score_perspective(action, [], kw)
    assert score > 0
    assert score <= 25


def test_extra_mile_bonus():
    kw = ["training"]
    short_score = score_perspective("Short training note", [], kw)
    long_action = "x" * 210 + " training program to upskill staff"
    # simulate attachments
    attachments = [object(), object()]
    long_score = score_perspective(long_action, attachments, kw)
    assert long_score >= short_score


def main(args):
    logging.info(f"Running with input: {args.input}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger(__name__)
    logger.info("Starting...")
    
    parser = argparse.ArgumentParser(description="Short description")
    parser.add_argument("--input", "-i", help="Input file", required=True)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    main(args)