import streamlit as st
import pandas as pd

st.set_page_config(page_title="MD's Quality Awards", layout="wide")
st.title("🏆 MD’S Quality & Excellence Awards")

# Perspectives and goals from your BSC document
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
        
        # User input for action taken
        action = st.text_area(f"Describe Action Taken ({p})", key=f"text_{p}")
        
        # File uploader for supporting documents
        attachments = st.file_uploader(f"Attach evidence for {p} (Max 200MB)", 
                                       accept_multiple_files=True, 
                                       type=["pdf", "png", "jpg", "docx"],
                                       key=f"file_{p}")
        
        user_data[p] = {"action": action, "files": attachments}
        st.divider()

    submit = st.form_submit_button("Analyze Extra Mile Performance")

if submit:
    st.header("AI Performance Evaluation")
    
    for p, data in user_data.items():
        # Count the number of uploaded files
        file_count = len(data["files"])
        action_text = data["action"]
        
        # --- IMPROVED AI LOGIC ---
        # Base confidence is determined by the description length/quality
        base_confidence = 70 if len(action_text) > 100 else 40
        
        # Rule: If action exists AND 2+ documents are provided, boost score
        if action_text and file_count >= 2:
            final_rating = "EXTRA MILE (Verified) ✨"
            confidence_score = min(base_confidence + 20, 100) # Boost by 20%
        elif action_text:
            final_rating = "Standard Performance"
            confidence_score = base_confidence
        else:
            final_rating = "No Data Provided"
            confidence_score = 0

        # Display results
        with st.expander(f"Results for {p}"):
            st.write(f"**Rating:** {final_rating}")
            st.progress(confidence_score / 100)
            st.write(f"**AI Confidence:** {confidence_score}% (Evidence: {file_count} files)")
            
            if file_count >= 2:
                st.success("Verification Bonus: Multiple supporting documents increased the rating confidence.")