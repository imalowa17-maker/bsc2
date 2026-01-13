"""
Create the md-awards-files bucket in Supabase
This script will create the storage bucket needed for file uploads
"""
import streamlit as st
from supabase import create_client

def create_bucket():
    try:
        url = st.secrets["supabase"]["url"].rstrip('/')
        key = st.secrets["supabase"]["key"]
        supabase = create_client(url, key)
        
        bucket_name = "md-awards-files"
        
        print(f"🚀 Creating bucket '{bucket_name}'...")
        
        try:
            # Create a public bucket
            result = supabase.storage.create_bucket(
                bucket_name,
                options={
                    "public": True,
                    "file_size_limit": 52428800  # 50MB limit
                }
            )
            print(f"✅ Bucket created successfully!")
            print(f"   Name: {bucket_name}")
            print(f"   Public: Yes")
            print(f"   File size limit: 50MB")
            
        except Exception as e:
            error_msg = str(e)
            if "already exists" in error_msg.lower():
                print(f"ℹ️  Bucket '{bucket_name}' already exists")
            else:
                print(f"❌ Error creating bucket: {e}")
                print("\n🔧 Alternative: Create it manually:")
                print(f"   1. Go to: {url}")
                print("   2. Click 'Storage' → 'New Bucket'")
                print(f"   3. Name: {bucket_name}")
                print("   4. Check 'Public bucket'")
                return False
        
        # Verify bucket exists
        print(f"\n🔍 Verifying bucket...")
        buckets = supabase.storage.list_buckets()
        bucket_names = [b['name'] for b in buckets]
        
        if bucket_name in buckets:
            print(f"✅ Bucket verified and ready to use!")
            return True
        else:
            print(f"⚠️  Bucket not found in list: {bucket_names}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = create_bucket()
    if success:
        print("\n✅ Setup complete! You can now upload files.")
    else:
        print("\n⚠️  Please create the bucket manually in Supabase Dashboard")
