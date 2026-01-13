"""
Quick test to verify Supabase storage permissions
Run this after applying the SQL fix
"""
import streamlit as st
from supabase import create_client
import io

def test_upload():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        supabase = create_client(url, key)
        
        # Create a test file
        test_content = b"This is a test file for MD Awards uploads"
        test_filename = "test_upload_verification.txt"
        
        # Try to upload
        response = supabase.storage.from_("md-awards-files").upload(
            path=test_filename,
            file=test_content,
            file_options={"upsert": "true"}
        )
        
        print("✅ Upload successful!")
        print(f"Response: {response}")
        
        # Try to list files
        files = supabase.storage.from_("md-awards-files").list()
        print(f"\n✅ Files in bucket: {len(files)}")
        
        # Try to delete the test file
        supabase.storage.from_("md-awards-files").remove([test_filename])
        print(f"✅ Test file cleaned up")
        
        print("\n🎉 All storage permissions are working correctly!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\n🔍 Troubleshooting:")
        print("1. Did you run fix_storage_rls.sql in Supabase SQL Editor?")
        print("2. Check if the bucket 'md-awards-files' exists")
        print("3. Verify your Supabase credentials in .streamlit/secrets.toml")

if __name__ == "__main__":
    test_upload()
