import streamlit as st
import smtplib
import os
from email.message import EmailMessage

# --- CONFIGURATION ---
# This pulls the 'Secret' you named EMAIL_PASSWORD from GitHub
EMAIL_PASS = os.getenv("EMAIL_PASSWORD") 
TARGET_EMAIL = "busdev3@securico.co.zw"
SMTP_SERVER = "smtp.office365.com"
SMTP_PORT = 587

st.set_page_config(page_title="MD's Quality Awards", layout="wide")
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
                                       type=["pdf", "png", "jpg", "docx"],
                                       key=f"file_{p}")
        
        user_data[p] = {"action": action, "files": attachments}
        st.divider()

    # 2. Submission Button
    submit = st.form_submit_button("Submit Performance for Evaluation")

if submit:
    if not first_name or not last_name:
        st.error("Please provide your Name and Surname before submitting.")
    elif not EMAIL_PASS:
        st.error("Email configuration missing. Please ensure EMAIL_PASSWORD is set in GitHub Secrets.")
    else:
        # --- AI ANALYSIS (RUNNING IN BACKGROUND) ---
        email_body = f"MD'S QUALITY AWARDS SUBMISSION\n"
        email_body += f"Submitted by: {first_name} {last_name}\n"
        email_body += "="*40 + "\n\n"
        
        all_attachments = []

        for p, data in user_data.items():
            action_text = data["action"]
            file_list = data["files"]
            file_count = len(file_list)
            all_attachments.extend(file_list)

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

            # Add analysis to the email body (not shown on screen)
            email_body += f"PERSPECTIVE: {p}\n"
            email_body += f"Action: {action_text}\n"
            email_body += f"AI Rating: {rating}\n"
            email_body += f"AI Confidence Score: {score}%\n"
            email_body += f"Evidence provided: {file_count} files\n"
            email_body += "-"*20 + "\n\n"

        # --- SENDING THE EMAIL ---
        with st.spinner("Uploading evidence and sending analysis..."):
            msg = EmailMessage()
            msg['Subject'] = f"Award Submission: {first_name} {last_name}"
            msg['From'] = TARGET_EMAIL
            msg['To'] = TARGET_EMAIL
            msg.set_content(email_body)

            for f in all_attachments:
                f.seek(0)
                msg.add_attachment(f.read(), maintype='application', 
                                   subtype='octet-stream', filename=f.name)

            try:
                with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                    server.starttls()
                    server.login(TARGET_EMAIL, EMAIL_PASS)
                    server.send_message(msg)
                
                # Success message to user (without showing marks)
                st.balloons()
                st.success(f"Thank you, {first_name}! Your submission has been sent to the MD's office for review.")
            except Exception as e:
                st.error(f"Error sending email: {e}")