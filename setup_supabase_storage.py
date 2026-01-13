"""
Script to help set up Supabase Storage bucket for MD Awards
Run this to check if your bucket exists and create it if needed
"""
import streamlit as st
from supabase import create_client

def setup_storage():
    try:
        # Get Supabase client
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        supabase = create_client(url, key)
        
        bucket_name = "md-awards-files"
        
        # Try to list buckets
        buckets = supabase.storage.list_buckets()
        print(f"Existing buckets: {[b['name'] for b in buckets]}")
        
        # Check if our bucket exists
        bucket_exists = any(b['name'] == bucket_name for b in buckets)
        
        if bucket_exists:
            print(f"✅ Bucket '{bucket_name}' already exists!")
        else:
            print(f"⚠️ Bucket '{bucket_name}' not found.")
            print("\nTo create it:")
            print("1. Go to your Supabase Dashboard → Storage")
            print(f"2. Click 'Create bucket'")
            print(f"3. Name it: {bucket_name}")
            print("4. Make it 'Public' for easy file access")
            print("\nOr create it with SQL policy:")
            print(f"""
-- Create bucket
INSERT INTO storage.buckets (id, name, public)
VALUES ('{bucket_name}', '{bucket_name}', true);

-- Allow public read access
CREATE POLICY "Public Access" ON storage.objects
FOR SELECT USING (bucket_id = '{bucket_name}');

-- Allow authenticated uploads
CREATE POLICY "Authenticated Upload" ON storage.objects
FOR INSERT WITH CHECK (bucket_id = '{bucket_name}');
            """)
        
        print(f"\n✅ Supabase connection successful!")
        print(f"URL: {url}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nMake sure your Supabase credentials are in .streamlit/secrets.toml:")
        print("""
[supabase]
url = "https://your-project.supabase.co"
key = "your-anon-key"
        """)

if __name__ == "__main__":
    setup_storage()
