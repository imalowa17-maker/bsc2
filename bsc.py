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
                # Using a Status Container for silent finalization feedback
                with st.status("Finalizing submission...", expanded=True) as status:
                
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
                        
                        st.success("✅ Submission successful! Your performance will be reviewed shortly.")
                    except Exception as e:
                        st.error(f"⚠️ Error in submission: {str(e)}")
    # your main logic
    pass

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