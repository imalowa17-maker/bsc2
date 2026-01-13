"""
List all buckets and check permissions
"""
import streamlit as st
from supabase import create_client

try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

def list_all_buckets():
    try:
        url = st.secrets["supabase"]["url"].rstrip('/')
        key = st.secrets["supabase"]["key"]
        supabase = create_client(url, key)
        
        print(f"Connected to: {url}")
        print(f"Using key: {key[:20]}...")
        print("\n--- Listing ALL buckets ---")
        
        # List all buckets
        buckets = supabase.storage.list_buckets()
        
        if buckets:
            print(f"Found {len(buckets)} bucket(s):\n")
            for bucket in buckets:
                print(f"  📦 {bucket.get('name', bucket.get('id', 'unknown'))}")
                print(f"     ID: {bucket.get('id', 'N/A')}")
                print(f"     Public: {bucket.get('public', False)}")
                print(f"     Created: {bucket.get('created_at', 'N/A')}")
                print()
        else:
            print("❌ No buckets found!")
            print("\nThis could mean:")
            print("1. The service key doesn't have storage permissions")
            print("2. No buckets exist yet")
            print("\n💡 Go to Supabase Dashboard → Storage to:")
            print("   - Verify buckets exist")
            print("   - Check if you're using the correct project")
            print("   - Create 'md-awards-files' bucket if needed")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    list_all_buckets()
