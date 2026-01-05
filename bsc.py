import streamlit as st
import os
import base64
import pandas as pd
from postmarker.core import PostmarkClient
import argparse
import logging

# --- CONFIGURATION ---
# Try to load a local .env file if python-dotenv is installed (development convenience).
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # dotenv is optional; falling back to environment variables
    pass


def get_postmark_token():
    """Return the Postmark API token from environment or raise a clear error."""
    token = os.getenv("POSTMARK_API_TOKEN")
    if not token:
        # Don't hard-code tokens in source. Provide actionable instructions instead.
        raise RuntimeError("POSTMARK_API_TOKEN is not set. Set it as an environment variable or create a .env file with POSTMARK_API_TOKEN=your-token. Example (PowerShell): $env:POSTMARK_API_TOKEN='your-token'")
    return token

# Token will be loaded at runtime via get_postmark_token(). Never embed secrets in source control.
POSTMARK_API_TOKEN = None
TARGET_EMAIL = "busdev3@securico.co.zw"

st.set_page_config(page_title="MD AWARDS", page_icon="🏆", layout="wide")

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

# 1. Identity Fields
col_a, col_b = st.columns(2)
with col_a:
    first_name = st.text_input("First Name", placeholder="Enter your first name")
with col_b:
    last_name = st.text_input("Surname", placeholder="Enter your surname")

# --- DYNAMIC DASHBOARD (Updates as user fills form) ---
st.write("### 📊 Submission Strength Dashboard")
m1, m2, m3, m4 = st.columns(4)

# Perspectives and goals
bsc_structure = {
    "Financial": "Grow Revenue / Manage Costs",
    "Customer": "Retain Profitable Business / Satisfy Customer",
    "Internal Business Processes": "Comply with SHEQ / Improve Efficiencies",
    "Learning & Growth": "Develop Staff Competencies / Increase Engagement"
}

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
                # Using a Status Container for "Interesting" visual feedback
                with st.status("🧠 AI Performance Analysis in Progress...", expanded=True) as status:
                
                    email_body = f"""
                    **MD’S Quality & Excellence Awards Submission**

                    **Name:** {first_name} {last_name}

                    ---

                    """
                    # Attachments
                    all_files = []
                    for p, data in user_data.items():
                        files = data["files"]
                        if files:
                            for file in files:
                                all_files.append(file)
                    
                    # If there's any file, proceed to upload
                    if all_files:
                        # --- POSTMARK EMAIL LOGIC ---
                        try:
                            client = PostmarkClient(server_token=token)
                            
                            # Send Email
                            response = client.emails.send(
                                From=TARGET_EMAIL,
                                To=TARGET_EMAIL,
                                Subject="🏆 New Submission Received for MD’s Awards",
                                HtmlBody=email_body,
                                Attachments=all_files  # Attach files here
                            )
                            
                            st.success("✅ Submission successful! Your performance will be reviewed shortly.")
                        except Exception as e:
                            st.error(f"⚠️ Error in submission: {str(e)}")
                    else:
                        st.warning("No files attached. Please upload evidence files.")
    # your main logic
    pass

def compute(a, b):
    return a + b

def test_compute_basic():
    expected_value = 5
    assert compute(2, 3) == expected_value

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