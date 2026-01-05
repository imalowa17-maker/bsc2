import streamlit as st
import os
from postmarker.core import PostmarkClient

# --- CONFIGURATION ---
# Ensure 'POSTMARK_API_TOKEN' is added to Streamlit/GitHub Secrets
POSTMARK_API_TOKEN = os.getenv("POSTMARK_API_TOKEN")
TARGET_EMAIL = "busdev3@securico.co.zw"

st.set_page_config(page_title="SecuriEx", page_icon="🏆", layout="wide")
st.title("🏆 MD’S Quality & Excellence Awards")

# 1. Identity Fields
st.header("Employee Details")
col1, col2 = st.columns(2)
with col1:
    first_name = st.text_input("First Name", placeholder="Enter your first name")
with col2:
    last_name = st.text_input("Surname", placeholder="Enter your surname")

# Perspectives and goals
bsc_structure = {
    "Financial": "Grow Revenue / Manage Costs",
    "Customer": "Retain Profitable Business / Satisfy Customer",
    "Internal Business Processes": "Comply with SHEQ / Improve Efficiencies",
    "Learning & Growth": "Develop Staff Competencies / Increase Engagement"
}

with st.form("bsc_form"):
    user_data = {}
    
    for p, goal in bsc_structure.items():
        st.subheader(f"{p} Perspective")
        st.caption(f"Goal: {goal}")
        
        action = st.text_area(f"Describe Action Taken ({p})", key=f"text_{p}")
        attachments = st.file_uploader(f"Attach evidence for {p}", 
                                       accept_multiple_files=True, 
                                       key=f"file_{p}")
        
        user_data[p] = {"action": action, "files": attachments}
        st.divider()

    submit = st.form_submit_button("Submit Performance for Evaluation")

if submit:
    if not first_name or not last_name:
        st.error("Please provide your Name and Surname.")
    elif not POSTMARK_API_TOKEN:
        st.error("Postmark API Token missing. Please check your Secrets settings.")
    else:
        # --- AI ANALYSIS (RUNNING IN BACKGROUND) ---
        email_body = f"MD'S QUALITY AWARDS SUBMISSION\n"
        email_body += f"Submitted by: {first_name} {last_name}\n"
        email_body += "="*40 + "\n\n"
        
        postmark_attachments = []

        for p, data in user_data.items():
            action_text = data["action"]
            file_list = data["files"]
            file_count = len(file_list)

            # AI Calculation Logic
            base_confidence = 70 if len(action_text) > 100 else 40
            if action_text and file_count >= 2:
                rating = "EXTRA MILE (Verified) ✨"
                score = min(base_confidence + 20, 100)
            elif action_text:
                rating = "Standard Performance"
                score = base_confidence
            else:
                rating = "No Data"
                score = 0

            # Building the Email Report
            email_body += f"PERSPECTIVE: {p}\n"
            email_body += f"Action Taken: {action_text}\n"
            email_body += f"AI Rating: {rating}\n"
            email_body += f"Confidence Score: {score}%\n"
            email_body += f"Evidence: {file_count} files provided\n"
            email_body += "-"*20 + "\n\n"

            # Adding attachments to the list
            for f in file_list:
                f.seek(0)
                postmark_attachments.append({
                    "Name": f.name,
                    "Content": f.read(),
                    "ContentType": f.type
                })

        # --- SENDING VIA POSTMARK ---
        with st.spinner("Submitting to MD's office..."):
            try:
                # Initialize Postmark Client
                postmark = PostmarkClient(server_token=POSTMARK_API_TOKEN)
                
                # Send Email
                postmark.emails.send(
                    From=TARGET_EMAIL, # This must be verified in Postmark
                    To=TARGET_EMAIL,
                    Subject=f"New Award Submission: {first_name} {last_name}",
                    TextBody=email_body,
                    Attachments=postmark_attachments
                )
                
                st.balloons()
                st.success(f"Successfully submitted! Thank you, {first_name}.")
            except Exception as e:
                st.error(f"Postmark Error: {e}")
                st.info("Ensure busdev3@securico.co.zw is verified in your Postmark Sender Signatures.")