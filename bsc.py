import streamlit as st
import os
import json
import pandas as pd
from postmarker.core import PostmarkClient
from datetime import datetime, timedelta
import uuid
import base64
import io
import logging
import argparse
import socket
import time
# Supabase Import
from supabase import create_client

# --- CONFIGURATION ---
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# --- 1. SUPABASE CONNECTION (Replaces Google Sheets) ---
@st.cache_resource
def get_supabase_client():
    """Connect to Supabase. Cached to prevent reloading."""
    try:
        url = st.secrets["supabase"]["url"]
        # Ensure URL has trailing slash for storage endpoint
        if not url.endswith('/'):
            url = url + '/'
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"⚠️ Supabase Config Error: {e}")
        return None

def get_postmark_token():
    token = None
    try:
        token = st.secrets["postmark"]["token"]
    except Exception:
        token = os.getenv("POSTMARK_API_TOKEN")
    if not token:
        # Fallback/Warning if missing
        return None
    return token

def score_perspective(action_text, files, keywords):
    text = (action_text or "").lower()
    if not text:
        return 0.0
    matches = 0
    for kw in keywords:
        if kw.lower() in text:
            matches += 1
    keyword_points = min(matches, 5) / 5.0 * 15.0 
    length_points = min(len(text), 300) / 300.0 * 10.0
    score = keyword_points + length_points
    try:
        num_files = len(files) if files else 0
    except Exception:
        num_files = 0
    if len(text) > 200 and num_files >= 2:
        score = min(25.0, score + 3.0)
    return round(min(25.0, score), 1)

def _evaluate_perspective(action_text, files):
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

# Constants
TARGET_EMAIL = "busdev3@securico.co.zw"
GDRIVE_HOLDER_ID = "1Ll1N63MviMMNH7zmYxwh2TqVSOTglXtg"
CSV_LOG_PATH = "evaluator_records.csv"
SUPABASE_TABLE = "md_awards_submissions"
SUPABASE_SETTINGS_TABLE = "md_awards_settings"

bsc_structure = {
    "Financial": "Improve profitability and financial performance",
    "Customer": "Enhance customer satisfaction and retention",
    "Internal Business Processes": "Optimize operational efficiency and compliance",
    "Learning & Growth": "Develop employee skills and organizational capacity"
}

st.set_page_config(page_title="MD AWARDS", page_icon="🏆", layout="wide")

# --- 2. SUPABASE STORAGE (For File Uploads) ---
def _is_network_error(e):
    """Return True if exception looks like a network/DNS/temporary transport error."""
    if isinstance(e, (OSError, socket.gaierror, ConnectionError)):
        return True
    return False


def upload_to_supabase(all_files_dict, first_name, last_name):
    """Upload files to Supabase Storage in a uniquely named folder.

    Args:
        all_files_dict: dict mapping perspective -> list of Streamlit UploadedFile objects
        first_name, last_name: strings for folder naming

    Returns: (folder_url, files_meta)
        - folder_url: URL to view files (Supabase project URL)
        - files_meta: dict mapping perspective -> list of {name, path, publicUrl}
    """
    supabase = get_supabase_client()
    if not supabase:
        raise RuntimeError("Supabase client not available")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"{first_name.strip()}_{last_name.strip()}_{timestamp}"
    
    # Create a bucket name (ensure it exists in your Supabase project)
    bucket_name = "md-awards-files"  # You'll need to create this bucket in Supabase
    
    try:
        supabase_url = st.secrets["supabase"]["url"].rstrip('/')
        files_meta = {}
        uploaded_files = []
        
        for perspective, flist in (all_files_dict or {}).items():
            files_meta[perspective] = []
            if not flist:
                continue
            for up in flist:
                try:
                    # Create a unique path for each file
                    # URL encode the file name to handle special characters
                    import urllib.parse
                    file_path = f"{folder_name}/{perspective}/{up.name}"
                    
                    # Upload file to Supabase Storage
                    file_bytes = up.getvalue()
                    
                    # Try to upload with upsert option
                    response = supabase.storage.from_(bucket_name).upload(
                        path=file_path,
                        file=file_bytes,
                        file_options={
                            "content-type": up.type or "application/octet-stream",
                            "upsert": "true"
                        }
                    )
                    
                    # Build the public URL manually to ensure it's correct
                    # Format: https://[project-ref].supabase.co/storage/v1/object/public/[bucket]/[path]
                    # Important: Preserve forward slashes in the path, only encode special characters
                    encoded_path = urllib.parse.quote(file_path, safe='/')
                    public_url = f"{supabase_url}/storage/v1/object/public/{bucket_name}/{encoded_path}"
                    
                    files_meta[perspective].append({
                        "name": up.name,
                        "path": file_path,
                        "publicUrl": public_url
                    })
                    uploaded_files.append(file_path)
                    
                    st.success(f"✅ Uploaded: {up.name}")
                    
                except Exception as e:
                    error_msg = str(e)
                    st.error(f"⚠️ Upload failed for {getattr(up, 'name', 'unknown')}: {error_msg}")
                    
                    # If bucket doesn't exist, provide helpful message
                    if "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
                        st.error(f"❌ Bucket '{bucket_name}' not found. Please create it in Supabase Dashboard (Storage → New Bucket) and make it PUBLIC.")
        
        if not uploaded_files:
            st.warning("⚠️ No files were successfully uploaded")
        else:
            st.info(f"📁 Successfully uploaded {len(uploaded_files)} file(s)")
        
        # Return Supabase Dashboard URL for folder browsing
        # Extract project reference from URL (e.g., irvcekjiqfjbdifbpgas from https://irvcekjiqfjbdifbpgas.supabase.co)
        import urllib.parse
        project_ref = supabase_url.split("//")[-1].split(".")[0]
        encoded_folder = urllib.parse.quote(folder_name, safe='')
        folder_url = f"https://supabase.com/dashboard/project/{project_ref}/storage/buckets/{bucket_name}/{encoded_folder}"
        
        return folder_url, files_meta
    except Exception as e:
        error_msg = str(e)
        st.error(f"❌ Supabase upload error: {error_msg}")
        raise RuntimeError(f"Supabase upload failed: {error_msg}")

# --- 4. DATA LOGGING (Using Supabase) ---
def log_submission(first_name, last_name, score_breakdown, actions_dict, folder_url, files_map=None):
    """Append a submission record to the Supabase table.
    Falls back to local CSV if Supabase is unavailable.

    files_map should be a dict mapping perspective -> list of {name,id,webViewLink}
    and will be serialized to JSON.
    """
    name = f"{first_name.strip()} {last_name.strip()}".strip()
    timestamp = datetime.now().isoformat()
    total_score = round(sum(score_breakdown.values()), 1)

    files_json = json.dumps(files_map) if files_map else ""

    record = {
        "full_name": name,
        "submission_date": timestamp,
        "total_score": total_score,
        "financial_score": score_breakdown.get("Financial", 0.0),
        "financial_action": actions_dict.get("Financial", ""),
        "customer_score": score_breakdown.get("Customer", 0.0),
        "customer_action": actions_dict.get("Customer", ""),
        "internal_processes_score": score_breakdown.get("Internal Business Processes", 0.0),
        "internal_processes_action": actions_dict.get("Internal Business Processes", ""),
        "learning_growth_score": score_breakdown.get("Learning & Growth", 0.0),
        "learning_growth_action": actions_dict.get("Learning & Growth", ""),
        "folder_url": folder_url,
        "files_json": files_json,
        "evaluator_vote": "",
        "evaluator_comment": "",
        "stage_1_recommendation": "",
        "stage_1_comment": "",
        "committee_votes": "",
        "current_status": ""
    }

    try:
        supabase = get_supabase_client()
        if not supabase:
            raise RuntimeError("Supabase client unavailable")
        
        supabase.table(SUPABASE_TABLE).insert(record).execute()
    except Exception as e:
        st.error(f"⚠️ Could not write submission to Supabase: {e}")
        # Fallback to local CSV to avoid data loss
        try:
            if os.path.exists(CSV_LOG_PATH):
                df = pd.read_csv(CSV_LOG_PATH)
                df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
            else:
                df = pd.DataFrame([record])
            df.to_csv(CSV_LOG_PATH, index=False)
        except Exception as e2:
            st.error(f"⚠️ Could not write submission to backup CSV: {e2}")

def read_records():
    """Read submissions from the Supabase table and return as a DataFrame.
    Falls back to local CSV if Supabase is unavailable.
    """
    try:
        supabase = get_supabase_client()
        if not supabase:
            raise RuntimeError("Supabase client unavailable")
        
        response = supabase.table(SUPABASE_TABLE).select("*").execute()
        records = response.data
        df = pd.DataFrame.from_records(records)
        # Map database columns to display-friendly names
        if not df.empty:
            df.rename(columns={
                "full_name": "Name",
                "submission_date": "Timestamp",
                "total_score": "Total Score",
                "financial_score": "Financial Score",
                "financial_action": "Financial Action",
                "customer_score": "Customer Score",
                "customer_action": "Customer Action",
                "internal_processes_score": "Internal Business Processes Score",
                "internal_processes_action": "Internal Business Processes Action",
                "learning_growth_score": "Learning & Growth Score",
                "learning_growth_action": "Learning & Growth Action",
                "folder_url": "Folder_URL",
                "files_json": "Files_JSON",
                "evaluator_vote": "Evaluator Vote",
                "evaluator_comment": "Evaluator Comment",
                "stage_1_recommendation": "Stage 1 Recommendation",
                "stage_1_comment": "Stage 1 Comment",
                "committee_votes": "Committee Votes",
                "current_status": "Current Status",
                "lock_token": "Lock Token",
                "lock_expiry": "Lock Expiry",
                "lock_holder": "Lock Holder"
            }, inplace=True)
        if df.empty:
            return None
        return df
    except Exception as e:
        st.error(f"⚠️ Error reading records from Supabase: {e}")
        # Fallback to CSV
        try:
            if os.path.exists(CSV_LOG_PATH):
                return pd.read_csv(CSV_LOG_PATH)
            return None
        except Exception as e2:
            st.error(f"⚠️ Error reading local CSV: {e2}")
            return None

# --- 5. EVALUATOR UPDATE LOGIC (Using Supabase with Locking) ---
def update_evaluator_vote(name, timestamp, vote=None, comment=None, lock_token=None, stage1_rec=None, stage1_comment=None, committee_vote=None, evaluator_name=None, current_status=None):
    """Update evaluator-related fields for a submission.
    Supports: Evaluator Vote, Evaluator Comment, Stage 1 Recommendation/Comment, Committee Votes (appends evaluator:name:vote), and Current Status.
    Enforces lock when available. Tries Supabase first; falls back to local CSV.
    Returns True on success, False on failure.
    """
    try:
        supabase = get_supabase_client()
        if not supabase:
            raise RuntimeError("Supabase client unavailable")
        
        # Find the record by name and timestamp
        response = supabase.table(SUPABASE_TABLE).select("*").eq("full_name", name).eq("submission_date", timestamp).execute()
        
        if not response.data:
            # Try finding by name only (latest)
            response = supabase.table(SUPABASE_TABLE).select("*").eq("full_name", name).order("submission_date", desc=True).limit(1).execute()
            if not response.data:
                raise RuntimeError("Could not locate submission row for candidate")
        
        record = response.data[0]
        record_id = record.get("id")
        
        # Check Lock
        current_lock_token = record.get("lock_token") or ""
        if current_lock_token:
            if not lock_token or str(lock_token) != str(current_lock_token):
                raise RuntimeError("Row is locked by another editor; acquire lock before updating")
        
        # Build update dict
        updates = {}
        if vote is not None:
            updates["evaluator_vote"] = vote
        if comment is not None:
            updates["evaluator_comment"] = comment
        if stage1_rec is not None:
            updates["stage_1_recommendation"] = stage1_rec
        if stage1_comment is not None:
            updates["stage_1_comment"] = stage1_comment
        if current_status is not None:
            updates["current_status"] = current_status
        
        if committee_vote is not None:
            existing = record.get("committee_votes") or ""
            new_entry = f"{evaluator_name or 'Evaluator'}:{committee_vote}"
            updates["committee_votes"] = existing + (";" if existing else "") + new_entry
        
        # Clear lock if provided
        if lock_token:
            updates["lock_token"] = ""
            updates["lock_expiry"] = ""
        
        # Apply updates
        supabase.table(SUPABASE_TABLE).update(updates).eq("id", record_id).execute()
        return True
        
    except Exception as e:
        st.error(f"⚠️ Could not update Supabase: {e}")
        # Fallback to CSV
        try:
            if os.path.exists(CSV_LOG_PATH):
                df = pd.read_csv(CSV_LOG_PATH)
                # Ensure columns exist
                for c in ["Evaluator Vote", "Evaluator Comment", "Lock Token", "Lock Expiry", "Stage 1 Recommendation", "Stage 1 Comment", "Committee Votes", "Current Status"]:
                    if c not in df.columns:
                        df[c] = ""

                mask = df["Name"] == name
                if timestamp and "Timestamp" in df.columns:
                    mask = mask & (df["Timestamp"] == timestamp)

                # If locked, verify
                if "Lock Token" in df.columns and mask.any():
                    current = df.loc[mask, "Lock Token"].astype(str).iloc[0]
                    if current and (not lock_token or str(lock_token) != str(current)):
                        raise RuntimeError("Row is locked by another editor; acquire lock before updating")

                if not mask.any():
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
        supabase = get_supabase_client()
        if not supabase:
            raise RuntimeError("Supabase client unavailable")
        
        # Find record
        response = supabase.table(SUPABASE_TABLE).select("*").eq("full_name", name).eq("submission_date", timestamp).execute()
        
        if not response.data:
            # fallback to latest by name
            response = supabase.table(SUPABASE_TABLE).select("*").eq("full_name", name).order("submission_date", desc=True).limit(1).execute()
            if not response.data:
                raise RuntimeError("Could not locate submission row for candidate")
        
        record = response.data[0]
        record_id = record.get("id")
        
        # Check current lock
        current_token = record.get("lock_token") or ""
        current_expiry = record.get("lock_expiry") or ""
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

        supabase.table(SUPABASE_TABLE).update({
            "lock_token": token,
            "lock_expiry": expiry_iso,
            "lock_holder": holder
        }).eq("id", record_id).execute()

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
                if timestamp and "Timestamp" in df.columns:
                    mask = mask & (df["Timestamp"] == timestamp)

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
        supabase = get_supabase_client()
        if not supabase:
            raise RuntimeError("Supabase client unavailable")
        
        response = supabase.table(SUPABASE_TABLE).select("*").eq("full_name", name).eq("submission_date", timestamp).execute()
        
        if not response.data:
            # fallback to latest by name
            response = supabase.table(SUPABASE_TABLE).select("*").eq("full_name", name).order("submission_date", desc=True).limit(1).execute()
            if not response.data:
                raise RuntimeError("Could not locate submission row for candidate")
        
        record = response.data[0]
        record_id = record.get("id")
        
        current = record.get("lock_token") or ""
        if not current or str(current) != str(token):
            st.error("Cannot release lock: token does not match current lock")
            return False

        supabase.table(SUPABASE_TABLE).update({
            "lock_token": "",
            "lock_expiry": ""
        }).eq("id", record_id).execute()
        return True
    except Exception as e:
        st.error(f"⚠️ Could not release lock on Supabase: {e}")
        # CSV fallback
        try:
            if os.path.exists(CSV_LOG_PATH):
                df = pd.read_csv(CSV_LOG_PATH)
                if "Lock Token" not in df.columns:
                    return False
                mask = df["Name"] == name
                if timestamp and "Timestamp" in df.columns:
                    mask = mask & (df["Timestamp"] == timestamp)
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

# --- DEADLINE MANAGEMENT ---
def get_submission_deadline():
    """Get the submission deadline from Supabase settings. Returns datetime object or None."""
    try:
        supabase = get_supabase_client()
        if not supabase:
            return None
        
        response = supabase.table(SUPABASE_SETTINGS_TABLE).select("*").eq("setting_key", "submission_deadline").execute()
        
        if response.data and len(response.data) > 0:
            deadline_str = response.data[0].get("setting_value")
            if deadline_str:
                return datetime.fromisoformat(deadline_str)
        return None
    except Exception as e:
        # If table doesn't exist or error, return None (no deadline)
        return None

def set_submission_deadline(deadline_datetime):
    """Set the submission deadline in Supabase settings. Returns True on success."""
    try:
        supabase = get_supabase_client()
        if not supabase:
            raise RuntimeError("Supabase client unavailable")
        
        deadline_str = deadline_datetime.isoformat() if deadline_datetime else ""
        
        # Check if setting exists
        response = supabase.table(SUPABASE_SETTINGS_TABLE).select("*").eq("setting_key", "submission_deadline").execute()
        
        if response.data and len(response.data) > 0:
            # Update existing
            supabase.table(SUPABASE_SETTINGS_TABLE).update({
                "setting_value": deadline_str,
                "updated_at": datetime.now().isoformat()
            }).eq("setting_key", "submission_deadline").execute()
        else:
            # Insert new
            supabase.table(SUPABASE_SETTINGS_TABLE).insert({
                "setting_key": "submission_deadline",
                "setting_value": deadline_str,
                "updated_at": datetime.now().isoformat()
            }).execute()
        
        return True
    except Exception as e:
        st.error(f"⚠️ Could not set deadline: {e}")
        return False

def is_submission_open():
    """Check if submissions are currently open based on deadline. Returns True if open."""
    deadline = get_submission_deadline()
    if deadline is None:
        return True  # No deadline set, submissions always open
    
    return datetime.now() < deadline

# --- UI IMPLEMENTATION ---
st.set_page_config(page_title="MD AWARDS", page_icon="🏆", layout="wide")

with st.sidebar:
    # LOGO LOGIC
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
    st.divider()
    
    st.markdown("# 🔐 Evaluator Access")
    eval_pwd = st.text_input("Evaluator Password", type="password", help="Enter evaluator password to access workspace")
    try:
        is_evaluator = bool(eval_pwd and eval_pwd == st.secrets["auth"]["evaluator_password"])
    except Exception:
        is_evaluator = False

st.title("🏆 MD'S Quality & Excellence Awards")
st.markdown("---")

if is_evaluator:
    st.header("Evaluator Workspace")
    tab1, tab2, tab3, tab4 = st.tabs(["Summary Table", "Detailed Review", "Final Results", "⚙️ Settings"])
    df = read_records()

    with tab1:
        if df is None or df.empty:
            st.info("Informing: No submissions found yet.")
        else:
            # Mark the latest submission with an indicator
            display_df = df.copy()
            # Ensure proper datetime parsing for robust sorting
            display_df["Date_parsed"] = pd.to_datetime(display_df["Timestamp"], errors="coerce")
            display_df = display_df.sort_values("Date_parsed", ascending=False)
            if not display_df.empty:
                latest = display_df.iloc[0]
                display_df["Latest"] = ""
                display_df.loc[display_df.index[0], "Latest"] = "🏅"
                st.caption(f"Latest submission: {latest['Name']} — {latest['Timestamp']}")
                st.dataframe(display_df[["Latest", "Name", "Timestamp", "Total Score", "Current Status"]])

    with tab2:
        if df is None or df.empty:
            st.info("Informing: No submissions found yet.")
        else:
            names = df["Name"].unique().tolist()
            selected = st.selectbox("Select Candidate", names)
            if selected:
                rec = df[df["Name"] == selected].sort_values("Timestamp", ascending=False).iloc[0]
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

                # Determine folder URL
                raw_folder = rec.get('Folder_URL') or ""
                is_folder_blank = pd.isna(raw_folder) or str(raw_folder).strip() == "" or str(raw_folder).strip().lower() == "nan"
                is_folder_fallback_msg = isinstance(raw_folder, str) and 'check email for attachments' in raw_folder.lower()

                st.divider()
                st.markdown("**Uploaded Evidence by Perspective**")
                left_col, right_col = st.columns([4, 6])
                
                with left_col:
                    if not is_folder_blank and not is_folder_fallback_msg:
                        if files_by_persp:
                            all_file_urls = []
                            for p in bsc_structure.keys():
                                flist = files_by_persp.get(p) or []
                                if not flist:
                                    continue
                                st.markdown(f"**{p}:**")
                                for i, fmeta in enumerate(flist):
                                    name = fmeta.get('name') or fmeta.get('Name') or ''
                                    # Support both Supabase (publicUrl) and Google Drive (webViewLink)
                                    file_url = fmeta.get('publicUrl') or fmeta.get('webViewLink') or (fmeta.get('id') and f"https://drive.google.com/file/d/{fmeta.get('id')}/view") or ''
                                    preview = fmeta.get('publicUrl') or fmeta.get('webViewLink') or (fmeta.get('id') and f"https://drive.google.com/file/d/{fmeta.get('id')}/preview") or ''
                                    
                                    if file_url:
                                        all_file_urls.append(f"{p}/{name}: {file_url}")
                                    
                                    rcols = st.columns([5, 1, 1])
                                    rcols[0].write(name)
                                    if file_url:
                                        if rcols[1].button("🔗", key=f"link_btn_{selected}_{p}_{i}", help="Open file"):
                                            st.write(f"[Open {name}]({file_url})")
                                    if preview:
                                        btn_key = f"preview_btn_{selected}_{p}_{i}"
                                        if rcols[2].button("👁️", key=btn_key, help="Preview"):
                                            st.session_state[f"preview_url_{selected}"] = preview
                                            st.session_state[f"preview_name_{selected}"] = name
                            
                            # Add button to show all file URLs
                            st.divider()
                            if all_file_urls and st.button("📋 Show All File URLs", key=f"show_urls_{selected}"):
                                st.text_area("All File URLs (Copy to share)", "\n\n".join(all_file_urls), height=200)
                        else:
                            st.info('No files are listed for this candidate in the record. Use the folder button to inspect uploads in storage if any exist.')
                        
                        folder_url = str(raw_folder).strip()
                        if isinstance(folder_url, str) and 'Upload Error' in folder_url:
                            st.warning('Files were successfully sent via email, but a temporary network error prevented them from being saved to the Cloud Folder. Please check the submission email attachments.')
                        elif folder_url and 'dashboard' in folder_url:
                            st.info("💡 View all files in Supabase Dashboard (login required):")
                            try:
                                st.link_button("📂 Open Storage Dashboard", url=folder_url, use_container_width=True)
                            except Exception:
                                st.markdown(f"[📂 Open Storage Dashboard]({folder_url})")
                    elif is_folder_blank or is_folder_fallback_msg:
                        if not files_by_persp:
                            st.info('ℹ️ No digital evidence was uploaded by this candidate.')
                        else:
                            all_file_urls = []
                            for p in bsc_structure.keys():
                                flist = files_by_persp.get(p) or []
                                if not flist:
                                    continue
                                st.markdown(f"**{p}:**")
                                for i, fmeta in enumerate(flist):
                                    name = fmeta.get('name') or fmeta.get('Name') or ''
                                    # Support both Supabase (publicUrl) and Google Drive (webViewLink)
                                    file_url = fmeta.get('publicUrl') or fmeta.get('webViewLink') or (fmeta.get('id') and f"https://drive.google.com/file/d/{fmeta.get('id')}/view") or ''
                                    preview = fmeta.get('publicUrl') or fmeta.get('webViewLink') or (fmeta.get('id') and f"https://drive.google.com/file/d/{fmeta.get('id')}/preview") or ''
                                    
                                    if file_url:
                                        all_file_urls.append(f"{p}/{name}: {file_url}")
                                    
                                    rcols = st.columns([5, 1, 1])
                                    rcols[0].write(name)
                                    if file_url:
                                        if rcols[1].button("🔗", key=f"link_btn_blank_{selected}_{p}_{i}", help="Open file"):
                                            st.write(f"[Open {name}]({file_url})")
                                    if preview:
                                        btn_key = f"preview_btn_blank_{selected}_{p}_{i}"
                                        if rcols[2].button("👁️", key=btn_key, help="Preview"):
                                            st.session_state[f"preview_url_{selected}"] = preview
                                            st.session_state[f"preview_name_{selected}"] = name
                            
                            if all_file_urls:
                                st.divider()
                                if st.button("📋 Show All File URLs", key=f"show_urls_blank_{selected}"):
                                    st.text_area("All File URLs (Copy to share)", "\n\n".join(all_file_urls), height=200)
                
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

                st.divider()
                st.subheader("Evaluator Vote & Comment")
                lock_key = f"lock_token_{selected}"
                timestamp = rec.get("Timestamp")
                locked_token = st.session_state.get(lock_key)

                if locked_token:
                    st.info("🔒 You have the edit lock.")
                    if st.button("Release Lock", key=f"rel_{selected}"):
                        release_lock(selected, timestamp, locked_token)
                        del st.session_state[lock_key]
                        st.rerun()
                else:
                    if st.button("Acquire Edit Lock", key=f"acq_{selected}"):
                        tok, exp = acquire_lock(selected, timestamp)
                        if tok:
                            st.session_state[lock_key] = tok
                            st.rerun()

                # Form fields
                disabled = (locked_token is None)
            
            # Stage 1
            st.markdown("#### Stage 1")
            rec_choice = st.radio("Recommendation", ["", "Recommend for Finals", "Reject"], key=f"s1_{selected}", disabled=disabled)
            rec_comment = st.text_area("Stage 1 Comment", key=f"c1_{selected}", disabled=disabled)
            
            if st.button("Submit Stage 1", disabled=disabled):
                update_evaluator_vote(selected, timestamp, lock_token=locked_token, stage1_rec=rec_choice, stage1_comment=rec_comment, current_status="Stage 1 Complete")
                st.success("Saved!")
                release_lock(selected, timestamp, locked_token)
                del st.session_state[lock_key]

            # Stage 2
            st.markdown("#### Stage 2 (Committee)")
            comm_vote = st.selectbox("Vote", ["", "Winner", "Runner-up", "Reject"], key=f"s2_{selected}", disabled=disabled)
            eval_name = st.text_input("Evaluator Name", key=f"en_{selected}", disabled=disabled)
            
            if st.button("Submit Committee Vote", disabled=disabled):
                if eval_name:
                    update_evaluator_vote(selected, timestamp, lock_token=locked_token, committee_vote=comm_vote, evaluator_name=eval_name, current_status="Stage 2 In Progress")
                    st.success("Vote Recorded!")
                    release_lock(selected, timestamp, locked_token)
                    del st.session_state[lock_key]
                else:
                    st.error("Name required.")

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

                    committee_val = r.get("Committee Votes", "")
                    # Handle potential Series/scalar values properly
                    if isinstance(committee_val, pd.Series):
                        committee_val = committee_val.iloc[0] if not committee_val.empty else ""
                    committee = str(committee_val) if (committee_val != "" if isinstance(committee_val, str) else bool(committee_val)) and pd.notna(committee_val) else ""
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
                
                # Highlight winner with visual indicators
                if not result_df.empty:
                    st.success("🏆 **WINNER ANNOUNCEMENT**")
                    winner = result_df.iloc[0]
                    
                    # Display winner prominently
                    col1, col2, col3 = st.columns([2, 1, 1])
                    with col1:
                        st.metric("🥇 Winner", winner["Name"], delta=f"Final Rank: {winner['Final Rank']}")
                    with col2:
                        st.metric("Total Score", f"{winner['Total Score']:.1f}/100")
                    with col3:
                        st.metric("Avg Vote Weight", f"{winner['Avg Vote Weight']:.2f}")
                    
                    st.info(f"**Committee Votes:** {winner['Committee Votes'] if winner['Committee Votes'] else 'No committee votes yet'}")
                    st.divider()
                
                # Show full ranking table
                st.subheader("📊 Complete Ranking")
                st.dataframe(result_df, use_container_width=True)

    # --- Settings tab ---
    with tab4:
        st.subheader("⚙️ System Settings")
        
        st.markdown("### 📅 Submission Deadline")
        current_deadline = get_submission_deadline()
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            if current_deadline:
                st.info(f"Current deadline: **{current_deadline.strftime('%B %d, %Y at %I:%M %p')}**")
                if datetime.now() > current_deadline:
                    st.error("⚠️ Submissions are currently CLOSED (deadline passed)")
                else:
                    time_left = current_deadline - datetime.now()
                    days_left = time_left.days
                    hours_left = time_left.seconds // 3600
                    st.success(f"✅ Submissions are OPEN ({days_left} days, {hours_left} hours remaining)")
            else:
                st.warning("No deadline set - submissions are always open")
        
        with col2:
            if current_deadline:
                if st.button("🗑️ Remove Deadline", use_container_width=True):
                    if set_submission_deadline(None):
                        st.success("Deadline removed! Submissions are now always open.")
                        st.rerun()
        
        st.divider()
        
        st.markdown("#### Set New Deadline")
        deadline_col1, deadline_col2 = st.columns(2)
        
        with deadline_col1:
            deadline_date = st.date_input(
                "Deadline Date",
                value=current_deadline.date() if current_deadline else datetime.now().date(),
                min_value=datetime.now().date()
            )
        
        with deadline_col2:
            deadline_time = st.time_input(
                "Deadline Time",
                value=current_deadline.time() if current_deadline else datetime.now().time()
            )
        
        if st.button("💾 Save Deadline", type="primary"):
            new_deadline = datetime.combine(deadline_date, deadline_time)
            if set_submission_deadline(new_deadline):
                st.success(f"✅ Deadline set to {new_deadline.strftime('%B %d, %Y at %I:%M %p')}")
                st.rerun()
        
        st.divider()
        st.caption("💡 Tip: Once the deadline passes, the public submission form will be automatically disabled.")

else:
    # --- EMPLOYEE FORM ---
    # Check if submissions are open
    if not is_submission_open():
        deadline = get_submission_deadline()
        st.error("🚫 Submissions are currently closed.")
        if deadline:
            st.info(f"The submission deadline was **{deadline.strftime('%B %d, %Y at %I:%M %p')}**")
        st.warning("Please contact the administrator if you believe this is an error.")
        st.stop()
    
    # Show deadline info if set
    deadline = get_submission_deadline()
    if deadline:
        time_left = deadline - datetime.now()
        if time_left.days > 0:
            st.info(f"⏰ Submissions close in **{time_left.days} days** (Deadline: {deadline.strftime('%B %d, %Y at %I:%M %p')})")
        elif time_left.total_seconds() > 3600:
            hours_left = int(time_left.total_seconds() // 3600)
            st.warning(f"⏰ Submissions close in **{hours_left} hours** (Deadline: {deadline.strftime('%B %d, %Y at %I:%M %p')})")
        else:
            st.error(f"⏰ Submissions close in **{int(time_left.total_seconds() // 60)} minutes**!")
    
    col_a, col_b = st.columns(2)
    first_name = col_a.text_input("First Name")
    last_name = col_b.text_input("Surname")
    
    st.write("### 📊 Submission Strength Dashboard")
    st.columns(4) # Placeholders

    with st.form("bsc_form"):
        user_data = {}
        for p, goal in bsc_structure.items():
            st.subheader(f"🔹 {p} Perspective")
            st.markdown(f"**Strategic Goal:** `{goal}`")
            c1, c2 = st.columns([2, 1])
            act = c1.text_area("Action Taken", key=f"txt_{p}")
            fils = c2.file_uploader("Evidence", accept_multiple_files=True, key=f"f_{p}")
            user_data[p] = {"action": act, "files": fils}
            st.divider()
        
        submit = st.form_submit_button("🚀 Submit Final Performance for Evaluation")

    if submit:
        if not first_name or not last_name:
            st.error("⚠️ Identity Required.")
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
                MD'S Quality & Excellence Awards Submission

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

                    # Build a per-perspective files dict and upload to Supabase
                    all_files_dict = {p: (user_data[p].get("files") or []) for p in user_data}
                    try:
                        folder_url, uploaded_files_meta = upload_to_supabase(all_files_dict, first_name, last_name)
                    except Exception as e:
                        logging.exception("Supabase upload failed")
                        # If it's a network/DNS/connection issue, mark for manual review and continue
                        if _is_network_error(e) or isinstance(e, (ConnectionError, OSError, socket.gaierror)):
                            folder_url = 'Manual Review Required (Upload Error)'
                            uploaded_files_meta = {}
                            st.warning('Files were successfully sent via email, but a temporary network error prevented them from being saved to the Cloud Storage.')
                        else:
                            st.warning(f"⚠️ Could not upload to Supabase Storage: {e}")
                            folder_url = "Check Email for Attachments"
                            uploaded_files_meta = {}
                    
                    # Append a simple listing of uploaded files to the email body for easy access
                    if uploaded_files_meta:
                        email_body += "\n\nEvidence Files:\n"
                        for p, flist in uploaded_files_meta.items():
                            if flist:
                                email_body += f"\n{p}:\n"
                                for f in flist:
                                    # Support both Supabase (publicUrl) and Google Drive (webViewLink)
                                    link = f.get('publicUrl') or f.get('webViewLink') or (f.get('id') and f"https://drive.google.com/file/d/{f.get('id')}/view")
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
                        Subject="🏆 New Submission Received for MD's Awards",
                        HtmlBody=email_body,
                        Attachments=pm_attachments
                    )

                    # Log submission (includes folder URL and per-perspective files JSON)
                    actions_only = {p: (user_data[p]["action"] or "") for p in user_data}
                    log_submission(first_name, last_name, score_breakdown, actions_only, folder_url, files_map=uploaded_files_meta)

                    status.success("✅ Finalizing submission...")
                except Exception as e:
                    st.error(f"⚠️ Error in submission: {str(e)}")