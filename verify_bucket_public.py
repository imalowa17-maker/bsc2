"""
Verify if md-awards-files bucket is public and fix if needed
"""
import streamlit as st
from supabase import create_client

try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

def check_and_fix_bucket():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        supabase = create_client(url, key)
        
        bucket_name = "md-awards-files"
        
        print(f"Checking bucket: {bucket_name}")
        
        # Try to get bucket info
        try:
            bucket_info = supabase.storage.get_bucket(bucket_name)
            print(f"✓ Bucket exists: {bucket_info}")
            
            # Check if public
            is_public = bucket_info.get('public', False)
            print(f"  Public: {is_public}")
            
            if not is_public:
                print("\n⚠️  Bucket is PRIVATE - this causes 404 errors on public URLs!")
                print("   Attempting to make it public...")
                
                # Update bucket to be public
                supabase.storage.update_bucket(
                    bucket_name,
                    {"public": True}
                )
                print("✅ Bucket is now PUBLIC!")
            else:
                print("✅ Bucket is already public - URLs should work!")
                
        except Exception as e:
            print(f"❌ Error checking bucket: {e}")
            if "not found" in str(e).lower():
                print(f"\n⚠️  Bucket '{bucket_name}' doesn't exist!")
                print("   Creating it now...")
                supabase.storage.create_bucket(
                    bucket_name,
                    {"public": True}
                )
                print(f"✅ Created public bucket: {bucket_name}")
        
        # List some files to verify
        print("\n--- Files in bucket ---")
        files = supabase.storage.from_(bucket_name).list()
        if files:
            for f in files[:5]:  # Show first 5
                print(f"  📄 {f['name']}")
            if len(files) > 5:
                print(f"  ... and {len(files) - 5} more")
        else:
            print("  (no files yet)")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_and_fix_bucket()
