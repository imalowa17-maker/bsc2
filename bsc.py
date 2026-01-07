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
import io
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError
import logging
import argparse
import socket
import time

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


def _evaluate_perspective(action_text, files):
    """Private evaluator that follows MD's Quality & Excellence Awards BSC rules.

    Scoring (0-25):
    - 10 points if the 'Action Taken' field is filled (non-empty after stripping).
    - 10 points if the 'Action Taken' text is over 150 characters.
    - 5 points if the user uploaded 2 or more files for that section.
    Returns an int score between 0 and 25.
    """
    pts = 0
    text = (action_text or "").strip()
    if text:
        pts += 10
    if len(text) > 150:
        pts += 10
    try:
        num_files = len(files) if files else 0
    except Exception:
        num_files = 0
    if num_files >= 2:
        pts += 5
    return int(min(25, pts))

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
    # 1. Define the permissions your app needs
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    try:
        # 2. Check if the secret exists
        if "gcp_service_account" in st.secrets:
            # Convert the Streamlit Secret object to a standard Python dictionary
            secret_dict = dict(st.secrets["gcp_service_account"])
            
            # 3. Create the credentials and authorize gspread
            creds = Credentials.from_service_account_info(secret_dict, scopes=scopes)
            return gspread.authorize(creds)
        else:
            st.error("❌ Key 'gcp_service_account' not found in Secrets.")
            return None
    except Exception as e:
        st.error(f"❌ Connection Failed: {e}")
        return None


def create_drive_service(attempts: int = 3, backoff: float = 1.0):
    """Create a Google Drive service client using the same service account in secrets.
    This function will retry transient network/DNS failures a few times with exponential backoff.
    Raises ConnectionError on persistent network failures, or returns a Resource on success.
    """
    scopes = ["https://www.googleapis.com/auth/drive"]
    if "gcp_service_account" not in st.secrets:
        st.error("❌ Key 'gcp_service_account' not found in Secrets; Drive uploads disabled.")
        return None

    secret_dict = dict(st.secrets["gcp_service_account"])

    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            # Explicitly use from_service_account_info as required
            creds = Credentials.from_service_account_info(secret_dict, scopes=scopes)
            service = build("drive", "v3", credentials=creds)

            # Quick connectivity test: attempt a tiny listing to ensure service + network are reachable
            try:
                service.files().list(pageSize=1, fields="nextPageToken").execute()
            except Exception as e:
                # Treat DNS/connection problems as transient and retry
                last_exc = e
                # If this is clearly a network-related error, retry; otherwise surface it
                if isinstance(e, (OSError, socket.gaierror)) or (hasattr(e, 'resp') and getattr(e, 'resp', None) and getattr(e, 'resp', None).status >= 500):
                    if attempt < attempts:
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                    else:
                        raise ConnectionError(f"Network/Drive connectivity check failed: {e}") from e
                else:
                    raise

            return service
        except Exception as e:
            last_exc = e
            # If network-like, retry; otherwise break and show a helpful message
            if isinstance(e, (OSError, socket.gaierror)):
                if attempt < attempts:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                else:
                    raise ConnectionError(f"Could not create Drive service due to network/DNS error: {e}") from e
            # For HttpError with 5xx treat as transient
            if isinstance(e, HttpError):
                try:
                    status = int(e.resp.status)
                except Exception:
                    status = None
                if status and 500 <= status < 600 and attempt < attempts:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
            # Non-network error - inform user and return None
            st.error(f"❌ Could not create Drive service: {e}")
            return None

    # If we exit loop, raise last exception
    raise last_exc


def _is_network_error(e):
    """Return True if exception looks like a network/DNS/temporary transport error."""
    if isinstance(e, HttpError):
        try:
            status = int(e.resp.status)
            return 500 <= status < 600
        except Exception:
            return False
    if isinstance(e, (OSError, socket.gaierror, ConnectionError)):
        return True
    return False


def _retry_api_call(callable_fn, attempts: int = 3, backoff: float = 1.0):
    """Generic retry wrapper for Drive API calls. Retries on network-like exceptions."""
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return callable_fn()
        except Exception as e:
            last_exc = e
            if _is_network_error(e) and attempt < attempts:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise
    raise last_exc


def _drive_connectivity_check(service):
    """Perform a lightweight connectivity check against the Drive API."""
    try:
        _retry_api_call(lambda: service.files().list(pageSize=1, fields="nextPageToken").execute(), attempts=3)
        return True
    except Exception as e:
        raise ConnectionError(f"Drive connectivity check failed: {e}") from e


def upload_to_gdrive(all_files_dict, first_name, last_name):
    """Upload files to a uniquely named sub-folder in GDRIVE_HOLDER_ID.

    Args:
        all_files_dict: dict mapping perspective -> list of Streamlit UploadedFile objects
        first_name, last_name: strings for folder naming

    Returns: (folder_url, files_meta)
        - folder_url: URL of the created folder (or holder folder on no files)
        - files_meta: dict mapping perspective -> list of {name, id, webViewLink}
    """
    service = create_drive_service()
    if not service:
        raise RuntimeError("Google Drive service not available")

    # Ensure that the Drive service is reachable first
    _drive_connectivity_check(service)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"{first_name.strip()}_{last_name.strip()}_{timestamp}"
    try:
        folder_meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder", "parents": [GDRIVE_HOLDER_ID]}
        folder = _retry_api_call(lambda: service.files().create(body=folder_meta, fields="id,webViewLink", supportsAllDrives=True).execute(), attempts=3)
        folder_id = folder.get("id")
        folder_url = f"https://drive.google.com/drive/folders/{folder_id}"

        files_meta = {}
        for perspective, flist in (all_files_dict or {}).items():
            files_meta[perspective] = []
            if not flist:
                continue
            for up in flist:
                try:
                    bio = io.BytesIO(up.getvalue())
                    media = MediaIoBaseUpload(bio, mimetype=up.type or "application/octet-stream", resumable=False)
                    file_metadata = {"name": up.name, "parents": [folder_id]}
                    created = _retry_api_call(lambda: service.files().create(body=file_metadata, media_body=media, fields="id,name,webViewLink", supportsAllDrives=True).execute(), attempts=3)
                    file_id = created.get("id")
                    webViewLink = created.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
                    # Make file viewable by anyone with link (best-effort; may fail in restricted domains)
                    try:
                        _retry_api_call(lambda: service.permissions().create(fileId=file_id, body={"type": "anyone", "role": "reader"}, fields="id", supportsAllDrives=True).execute(), attempts=2)
                    except HttpError:
                        # ignore permission issues
                        pass
                    files_meta[perspective].append({"name": created.get("name"), "id": file_id, "webViewLink": webViewLink})
                except Exception as e:
                    # If a network error occurs mid-upload, bubble it up so the caller can apply the fault-tolerant fallback.
                    if _is_network_error(e):
                        raise
                    st.warning(f"⚠️ Could not upload file {getattr(up, 'name', 'unknown')}: {e}")
        return folder_url, files_meta
    except Exception as e:
        # Normalize network-like issues as ConnectionError so callers can detect them
        if _is_network_error(e):
            raise ConnectionError(e)
        raise RuntimeError(f"Drive upload failed: {e}")


def log_submission(first_name, last_name, score_breakdown, actions_dict, folder_url, files_map=None):
    """Append a submission record to the Google Sheet 'MD Awards Voting'.
    Falls back to local CSV if Google Sheets API is unavailable.

    files_map should be a dict mapping perspective -> list of {name,id,webViewLink}
    and will be serialized to JSON in the 'Files_JSON' column.
    """
    name = f"{first_name.strip()} {last_name.strip()}".strip()
    timestamp = datetime.now().isoformat()
    total_score = round(sum(score_breakdown.values()), 1)

    files_json = json.dumps(files_map) if files_map else ""

    # Row layout written to Google Sheet (Files_JSON & Folder_URL added)
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
        folder_url,
        files_json,
        "",  # Evaluator Vote (to be set by evaluators)
        "",  # Evaluator Comment (to be set by evaluators)
        "",  # Stage 1 Recommendation
        "",  # Stage 1 Comment
        "",  # Committee Votes
        ""   # Current Status
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
        "Folder_URL",
        "Files_JSON",
        "Evaluator Vote",
        "Evaluator Comment",
        "Stage 1 Recommendation",
        "Stage 1 Comment",
        "Committee Votes",
        "Current Status"
    ]

    try:
        gc = get_gspread_client()
        if not gc:
            raise RuntimeError("GCP Sheets client unavailable")
        sh = gc.open("MD Awards Voting")
        worksheet = sh.sheet1

        # Ensure headers exist and add missing ones if needed
        existing_headers = worksheet.row_values(1)
        if not existing_headers:
            worksheet.append_row(headers)
        else:
            last_col = len(existing_headers)
            for h in headers:
                if h not in existing_headers:
                    last_col += 1
                    worksheet.update_cell(1, last_col, h)

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
                "Folder_URL": folder_url,
                "Files_JSON": files_json,
                "Stage 1 Recommendation": "",
                "Stage 1 Comment": "",
                "Committee Votes": "",
                "Current Status": ""
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


def update_evaluator_vote(name, timestamp, vote=None, comment=None, lock_token=None, stage1_rec=None, stage1_comment=None, committee_vote=None, evaluator_name=None, current_status=None):
    """Update evaluator-related fields for a submission.
    Supports: Evaluator Vote, Evaluator Comment, Stage 1 Recommendation/Comment, Committee Votes (appends evaluator:name:vote), and Current Status.
    Enforces lock when available. Tries Google Sheet first; falls back to local CSV.
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

        # Ensure all relevant columns exist (append if missing)
        col_map = {}
        targets = ["Evaluator Vote", "Evaluator Comment", "Stage 1 Recommendation", "Stage 1 Comment", "Committee Votes", "Current Status"]
        last_col = len(headers)
        for t in targets:
            col_idx = None
            for idx, h in enumerate(headers, start=1):
                if h == t:
                    col_idx = idx
                    break
            if col_idx is None:
                last_col += 1
                worksheet.update_cell(1, last_col, t)
                col_idx = last_col
            col_map[t] = col_idx

        # Apply updates
        if vote is not None:
            worksheet.update_cell(row_idx, col_map["Evaluator Vote"], vote)
        if comment is not None:
            worksheet.update_cell(row_idx, col_map["Evaluator Comment"], comment)
        if stage1_rec is not None:
            worksheet.update_cell(row_idx, col_map["Stage 1 Recommendation"], stage1_rec)
        if stage1_comment is not None:
            worksheet.update_cell(row_idx, col_map["Stage 1 Comment"], stage1_comment)
        if committee_vote is not None:
            existing = worksheet.cell(row_idx, col_map["Committee Votes"]).value or ""
            new_entry = f"{evaluator_name or 'Evaluator'}:{committee_vote}"
            updated = existing + (";" if existing else "") + new_entry
            worksheet.update_cell(row_idx, col_map["Committee Votes"], updated)
        if current_status is not None:
            worksheet.update_cell(row_idx, col_map["Current Status"], current_status)

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
                # Ensure columns exist
                for c in ["Evaluator Vote", "Evaluator Comment", "Lock Token", "Lock Expiry", "Stage 1 Recommendation", "Stage 1 Comment", "Committee Votes", "Current Status"]:
                    if c not in df.columns:
                        df[c] = ""

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
                else:
                    idx = df[mask].index[0]

                # Apply updates to CSV row
                if vote is not None:
                    df.at[idx, "Evaluator Vote"] = vote
                if comment is not None:
                    df.at[idx, "Evaluator Comment"] = comment
                if stage1_rec is not None:
                    df.at[idx, "Stage 1 Recommendation"] = stage1_rec
                if stage1_comment is not None:
                    df.at[idx, "Stage 1 Comment"] = stage1_comment
                if committee_vote is not None:
                    existing = str(df.at[idx, "Committee Votes"] or "")
                    new_entry = f"{evaluator_name or 'Evaluator'}:{committee_vote}"
                    updated = existing + (";" if existing else "") + new_entry
                    df.at[idx, "Committee Votes"] = updated
                if current_status is not None:
                    df.at[idx, "Current Status"] = current_status

                # clear locks if provided
                if lock_token:
                    df.at[idx, "Lock Token"] = ""
                    df.at[idx, "Lock Expiry"] = ""

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
    # --- SIDEBAR LOGO (TOP) ---
    # Display logo at the very top of the sidebar; fallback to title text if missing.
    # Accepts filenames with spaces and attempts to match base name 'LOGO WHITE PNG' with any extension.
    script_dir = os.path.dirname(__file__)
    logo_path = None
    for fname in ["LOGO WHITE PNG.png", "LOGO WHITE PNG"]:
        p = os.path.join(script_dir, fname)
        if os.path.exists(p):
            logo_path = p
            break
    if not logo_path:
        try:
            for f in os.listdir(script_dir):
                if os.path.splitext(f)[0].lower() == "logo white png":
                    logo_path = os.path.join(script_dir, f)
                    break
        except Exception:
            logo_path = None

    if logo_path and os.path.exists(logo_path):
        st.markdown(
            """
            <style>
            /* Make sidebar images sit on a dark tile so white logos are visible on light themes */
            div[data-testid="stSidebar"] img {
                background-color: #111 !important;
                padding: 8px;
                border-radius: 6px;
                display: block;
                margin-left: auto;
                margin-right: auto;
            }
            </style>
            """,
            unsafe_allow_html=True
        )
        st.image(logo_path, use_container_width=True)
    else:
        st.markdown("# 🏆 MD AWARDS")

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
    tab1, tab2, tab3 = st.tabs(["Summary Table", "Detailed Review", "Final Results"])
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
                st.caption(f"Latest submission: {latest['Name']} — {latest['Date']}")
                st.dataframe(display_df[["Latest", "Name", "Date"]])
    with tab2:
        if df is None or df.empty:
            st.info("Informing: No submissions found yet.")
        else:
            names = df["Name"].unique().tolist()
            selected = st.selectbox("Select Candidate", names)
            if selected:
                rec = df[df["Name"] == selected].sort_values("Date", ascending=False).iloc[0]
                st.subheader(f"Review: {selected}")

                # --- Scores & Metrics ---
                def _num(x):
                    try:
                        return float(x)
                    except Exception:
                        return 0.0

                fin_score = _num(rec.get("Financial Score", 0))
                cust_score = _num(rec.get("Customer Score", 0))
                ibp_score = _num(rec.get("Internal Business Processes Score", 0))
                lg_score = _num(rec.get("Learning & Growth Score", 0))
                total_score = _num(rec.get("Total Score", fin_score + cust_score + ibp_score + lg_score))

                cols = st.columns(5)
                cols[0].metric("Total Score", f"{total_score:.1f}/100")
                cols[1].metric("Financial", f"{fin_score:.1f}/25")
                cols[2].metric("Customer", f"{cust_score:.1f}/25")
                cols[3].metric("Internal BP", f"{ibp_score:.1f}/25")
                cols[4].metric("Learning & Growth", f"{lg_score:.1f}/25")

                st.write("**Action Taken (Full Text)**")
                st.write(f"**Financial ({fin_score:.1f}/25):** {rec.get('Financial Action', '')}")
                st.write(f"**Customer ({cust_score:.1f}/25):** {rec.get('Customer Action', '')}")
                st.write(f"**Internal Business Processes ({ibp_score:.1f}/25):** {rec.get('Internal Business Processes Action', '')}")
                st.write(f"**Learning & Growth ({lg_score:.1f}/25):** {rec.get('Learning & Growth Action', '')}")

                # Show per-perspective uploaded files (if any) with preview links
                files_json_raw = rec.get('Files_JSON') or rec.get('Files') or ""
                files_by_persp = {}
                if files_json_raw and not pd.isna(files_json_raw):
                    try:
                        if isinstance(files_json_raw, str):
                            files_by_persp = json.loads(files_json_raw)
                        else:
                            files_by_persp = files_json_raw
                    except Exception:
                        files_by_persp = {}

                # Determine folder URL exactly as stored in the record (do not auto-fallback here)
                raw_folder = rec.get('Folder_URL') or ""
                is_folder_blank = pd.isna(raw_folder) or str(raw_folder).strip() == "" or str(raw_folder).strip().lower() == "nan"
                # Treat an explicit fallback message as 'no folder' as requested
                is_folder_fallback_msg = isinstance(raw_folder, str) and 'check email for attachments' in raw_folder.lower()

                # If there's no folder recorded, show a simple info note (and do not display the folder button)
                if is_folder_blank or is_folder_fallback_msg:
                    # If there are no file metadata to show either, display an info message
                    if not files_by_persp:
                        st.info('ℹ️ No digital evidence was uploaded by this candidate.')
                    else:
                        # Still allow previewing of any inline Files_JSON entries but do not show a folder button
                        st.markdown("**Uploaded Evidence by Perspective**")
                        left_col, right_col = st.columns([4,6])
                        with left_col:
                            for p in bsc_structure.keys():
                                flist = files_by_persp.get(p) or []
                                if not flist:
                                    continue
                                st.markdown(f"**{p}:**")
                                for i, fmeta in enumerate(flist):
                                    name = fmeta.get('name') or fmeta.get('Name') or ''
                                    preview = fmeta.get('webViewLink') or (fmeta.get('id') and f"https://drive.google.com/file/d/{fmeta.get('id')}/preview") or ''
                                    rcols = st.columns([6,1])
                                    rcols[0].write(name)
                                    if preview:
                                        btn_key = f"preview_btn_{selected}_{p}_{i}"
                                        if rcols[1].button("👁️ Preview", key=btn_key):
                                            st.session_state[f"preview_url_{selected}"] = preview
                                            st.session_state[f"preview_name_{selected}"] = name
                        with right_col:
                            preview_key = f"preview_url_{selected}"
                            if preview_key in st.session_state and st.session_state.get(preview_key):
                                st.markdown(f"**Preview: {st.session_state.get(f'preview_name_{selected}', '')}**")
                                try:
                                    st.components.v1.iframe(st.session_state[preview_key], height=700)
                                except Exception as e:
                                    st.error(f"⚠️ Could not render preview iframe: {e}")

                                if st.button("Close Preview", key=f"close_preview_{selected}"):
                                    try:
                                        del st.session_state[preview_key]
                                    except Exception:
                                        pass
                                    name_key = f"preview_name_{selected}"
                                    if name_key in st.session_state:
                                        try:
                                            del st.session_state[name_key]
                                        except Exception:
                                            pass
                            else:
                                st.info("Select a file to preview from the list on the left.")
                else:
                    # Folder is present — show side-by-side file list and preview, and provide the folder link
                    folder_url = str(raw_folder).strip()

                    # If a previous submission recorded an upload error, instruct evaluators to check email attachments instead
                    if isinstance(folder_url, str) and 'Upload Error' in folder_url:
                        st.warning('Files were successfully sent via email, but a temporary network error prevented them from being saved to the Cloud Folder. Please check the submission email attachments.')

                    left_col, right_col = st.columns([4,6])
                    with left_col:
                        if files_by_persp:
                            st.markdown("**Uploaded Evidence by Perspective**")
                            for p in bsc_structure.keys():
                                flist = files_by_persp.get(p) or []
                                if not flist:
                                    continue
                                st.markdown(f"**{p}:**")
                                for i, fmeta in enumerate(flist):
                                    name = fmeta.get('name') or fmeta.get('Name') or ''
                                    preview = fmeta.get('webViewLink') or (fmeta.get('id') and f"https://drive.google.com/file/d/{fmeta.get('id')}/preview") or ''
                                    rcols = st.columns([6,1])
                                    rcols[0].write(name)
                                    if preview:
                                        btn_key = f"preview_btn_{selected}_{p}_{i}"
                                        if rcols[1].button("👁️ Preview", key=btn_key):
                                            st.session_state[f"preview_url_{selected}"] = preview
                                            st.session_state[f"preview_name_{selected}"] = name
                        else:
                            st.info('No files are listed for this candidate in the record. Use the folder button to inspect uploads in Drive if any exist.')

                        try:
                            st.link_button("📂 Open Candidate Evidence", url=folder_url, use_container_width=True)
                        except Exception:
                            st.markdown(f"[📂 Open Candidate Evidence]({folder_url})")

                    with right_col:
                        preview_key = f"preview_url_{selected}"
                        if preview_key in st.session_state and st.session_state.get(preview_key):
                            st.markdown(f"**Preview: {st.session_state.get(f'preview_name_{selected}', '')}**")
                            try:
                                st.components.v1.iframe(st.session_state[preview_key], height=700)
                            except Exception as e:
                                st.error(f"⚠️ Could not render preview iframe: {e}")

                            if st.button("Close Preview", key=f"close_preview_{selected}"):
                                try:
                                    del st.session_state[preview_key]
                                except Exception:
                                    pass
                                name_key = f"preview_name_{selected}"
                                if name_key in st.session_state:
                                    try:
                                        del st.session_state[name_key]
                                    except Exception:
                                        pass
                        else:
                            st.info("Select a file to preview from the list on the left. Click 'Open Candidate Evidence' to open the folder in a new tab.")

                # --- Evaluator vote & comment UI with locking + 2-stage flow ---
                st.divider()
                st.subheader("Evaluator Vote & Comment")

                # Pre-fill existing evaluator vote/comment if present
                existing_vote = rec.get("Evaluator Vote", "") if rec is not None else ""
                existing_comment = rec.get("Evaluator Comment", "") if rec is not None else ""

                # Stage 1 fields if present
                stage1_rec = rec.get("Stage 1 Recommendation", "")
                stage1_comment_existing = rec.get("Stage 1 Comment", "")

                # Lock state in session
                lock_key = f"lock_token_{selected}"
                expiry_key = f"lock_expiry_{selected}"
                locked_token = st.session_state.get(lock_key)
                locked_expiry = st.session_state.get(expiry_key)

                timestamp = rec.get("Timestamp") or rec.get("Date")

                # Lock controls
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

                # Stage 1 UI: Primary evaluator recommends for shortlist
                if not stage1_rec or pd.isna(stage1_rec) or str(stage1_rec).strip() == "":
                    st.markdown("#### Stage 1 — Primary Review")
                    st.caption("Primary evaluator: recommend candidate for finals or reject.")
                    rec_choice = st.radio("Stage 1 Recommendation", ["", "Recommend for Finals", "Reject"], index=0, key=f"stage1_choice_{selected}", disabled=not locked_token)
                    rec_comment = st.text_area("Stage 1 Comment (optional)", value=(stage1_comment_existing or ""), key=f"stage1_comment_{selected}", disabled=not locked_token)
                    if st.button("Submit Stage 1 Recommendation", key=f"submit_stage1_{selected}"):
                        if not locked_token:
                            st.error("⚠️ Acquire an edit lock before submitting.")
                        elif rec_choice == "" :
                            st.error("⚠️ Select a recommendation before submitting.")
                        else:
                            ok = update_evaluator_vote(selected, timestamp, lock_token=locked_token, stage1_rec=rec_choice, stage1_comment=rec_comment, current_status="Stage 1 Recommended" if "Recommend" in rec_choice else "Stage 1 Rejected")
                            if ok:
                                # release lock
                                released = release_lock(selected, timestamp, locked_token)
                                if lock_key in st.session_state:
                                    del st.session_state[lock_key]
                                if expiry_key in st.session_state:
                                    del st.session_state[expiry_key]
                                if released:
                                    st.success("✅ Stage 1 Recommendation submitted and lock released.")
                                else:
                                    st.success("✅ Stage 1 Recommendation submitted.")
                                df = read_records()
                            else:
                                st.error("⚠️ Could not submit Stage 1 recommendation.")
                else:
                    st.success(f"✅ Stage 1 recommendation: {stage1_rec}")
                    if pd.isna(stage1_comment_existing) or not stage1_comment_existing:
                        st.write("_No Stage 1 comment provided._")
                    else:
                        st.write(f"**Stage 1 Comment:** {stage1_comment_existing}")

                    # Stage 2 UI: Committee evaluators cast final vote
                    st.markdown("#### Stage 2 — Committee Review")
                    st.caption("If you are a Stage 2 evaluator, cast your final vote below.")
                    evaluator_name = st.text_input("Your Name", placeholder="Enter your name", key=f"evaluator_name_{selected}")
                    final_vote_options = ["", "Winner", "Runner-up", "Reject"]
                    final_vote = st.selectbox("Final Vote", final_vote_options, index=0, key=f"final_vote_{selected}", disabled=not locked_token)
                    stage2_comment = st.text_area("Comment (optional)", value="", key=f"stage2_comment_{selected}", disabled=not locked_token)
                    if st.button("Submit Committee Vote", key=f"submit_committee_{selected}"):
                        if not locked_token:
                            st.error("⚠️ Acquire an edit lock before submitting.")
                        elif final_vote == "":
                            st.error("⚠️ Select a final vote before submitting.")
                        elif not evaluator_name:
                            st.error("⚠️ Please enter your name for committee records.")
                        else:
                            ok = update_evaluator_vote(selected, timestamp, lock_token=locked_token, committee_vote=final_vote, evaluator_name=evaluator_name, comment=stage2_comment, current_status="Stage 2 In Progress")
                            if ok:
                                # Optional: keep lock or release? release for now
                                released = release_lock(selected, timestamp, locked_token)
                                if lock_key in st.session_state:
                                    del st.session_state[lock_key]
                                if expiry_key in st.session_state:
                                    del st.session_state[expiry_key]
                                if released:
                                    st.success("✅ Committee vote submitted and lock released.")
                                else:
                                    st.success("✅ Committee vote submitted.")
                                df = read_records()
                            else:
                                st.error("⚠️ Could not submit committee vote.")

                # Legacy submit (keeps previous behaviour — single-editor vote & comment)
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
                            df = read_records()
                        else:
                            st.error("⚠️ Could not submit vote/comment. See messages above.")

    # --- Final Results tab ---
    with tab3:
        st.subheader("Final Results — Recommended Candidates")
        if df is None or df.empty:
            st.info("No submissions found yet.")
        else:
            df_view = df.copy()
            if "Stage 1 Recommendation" in df_view.columns:
                mask = df_view["Stage 1 Recommendation"].fillna("").str.lower().str.contains("recommend")
            else:
                mask = pd.Series([False] * len(df_view))
            recs = df_view[mask]
            if recs.empty:
                st.info("No candidates have been recommended for finals yet.")
            else:
                def vote_to_weight(v):
                    v = str(v or "").strip().lower()
                    if "winner" in v:
                        return 1.0
                    if "runner" in v:
                        return 0.7
                    if "shortlist" in v:
                        return 0.5
                    return 0.0

                rows = []
                for _, r in recs.iterrows():
                    name = r.get("Name")
                    sys_score = None
                    for key in ("Total Score",):
                        try:
                            sys_score = float(r.get(key))
                            break
                        except Exception:
                            sys_score = None
                    if sys_score is None:
                        try:
                            sys_score = sum([float(r.get("Financial Score", 0)), float(r.get("Customer Score", 0)), float(r.get("Internal Business Processes Score", 0)), float(r.get("Learning & Growth Score", 0))])
                        except Exception:
                            sys_score = 0.0

                    committee = str(r.get("Committee Votes", "") or "")
                    weights = []
                    if committee:
                        for part in committee.split(";"):
                            if ":" in part:
                                _, v = part.split(":", 1)
                            else:
                                v = part
                            weights.append(vote_to_weight(v))
                    else:
                        if r.get("Evaluator Vote"):
                            weights.append(vote_to_weight(r.get("Evaluator Vote")))

                    avg_w = float(sum(weights) / len(weights)) if weights else 0.0
                    final_rank = sys_score * 0.4 + (avg_w * 100) * 0.6
                    rows.append({"Name": name, "Total Score": sys_score, "Committee Votes": committee, "Avg Vote Weight": round(avg_w, 2), "Final Rank": round(final_rank, 1), "Current Status": r.get("Current Status", "")})

                result_df = pd.DataFrame(rows).sort_values("Final Rank", ascending=False)
                st.dataframe(result_df)
                top = result_df.iloc[0]
                st.metric("Top Candidate", top["Name"], delta=f"Score: {top['Final Rank']}")

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

                for p, data in user_data.items():
                    action_text = (data.get("action") or "").strip()
                    files = data.get("files") or []
                    score = _evaluate_perspective(action_text, files)
                    score_breakdown[p] = int(score)

                    # collect files
                    if files:
                        for file in files:
                            all_files.append(file)

                total_score = sum(score_breakdown.values())

                # Build email body including the score breakdown
                breakdown_lines = "\n".join([f"{p}: {int(score)}/25%" for p, score in score_breakdown.items()])
                email_body = f"""
                MD’S Quality & Excellence Awards Submission

                Name: {first_name} {last_name}

                ---
                Score Breakdown (per perspective):
                {breakdown_lines}

                Total Score: {int(total_score)}/100%
                """

                # --- POSTMARK EMAIL LOGIC ---
                try:
                    status = st.empty()
                    status.info("Finalizing submission...")

                    client = PostmarkClient(server_token=token)

                    # Build a per-perspective files dict and upload to Drive
                    all_files_dict = {p: (user_data[p].get("files") or []) for p in user_data}
                    try:
                        folder_url, uploaded_files_meta = upload_to_gdrive(all_files_dict, first_name, last_name)
                    except Exception as e:
                        logging.exception("Drive upload failed")
                        # If it's a network/DNS/connection issue, mark for manual review and continue
                        if _is_network_error(e) or isinstance(e, (ConnectionError, OSError, socket.gaierror)):
                            folder_url = 'Manual Review Required (Upload Error)'
                            uploaded_files_meta = {}
                            st.warning('Files were successfully sent via email, but a temporary network error prevented them from being saved to the Cloud Folder.')
                        else:
                            st.warning(f"⚠️ Could not upload to Google Drive: {e}")
                        # No Drive folder available for this submission; instruct evaluators to check email attachments
                        folder_url = "Check Email for Attachments"
                    # Append a simple listing of uploaded files to the email body for easy access
                    if uploaded_files_meta:
                        email_body += "\n\nEvidence Files:\n"
                        for p, flist in uploaded_files_meta.items():
                            if flist:
                                email_body += f"\n{p}:\n"
                                for f in flist:
                                    link = f.get('webViewLink') or (f.get('id') and f"https://drive.google.com/file/d/{f.get('id')}/view")
                                    email_body += f"- {f.get('name')}: {link}\n"

                    # Convert Streamlit UploadedFile objects into Postmark-friendly dicts
                    pm_attachments = []
                    for pfiles in all_files_dict.values():
                        for up in pfiles:
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

                    # Log submission (includes folder URL and per-perspective files JSON)
                    actions_only = {p: (user_data[p]["action"] or "") for p in user_data}
                    log_submission(first_name, last_name, score_breakdown, actions_only, folder_url, files_map=uploaded_files_meta)

                    status.success("✅ Finalizing submission...")
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