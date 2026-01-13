"""
Test if files uploaded by the app are accessible via public URLs
"""
import streamlit as st
from supabase import create_client
import urllib.parse
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

def test_public_urls():
    try:
        url = st.secrets["supabase"]["url"].rstrip('/')
        key = st.secrets["supabase"]["key"]
        supabase = create_client(url, key)
        
        bucket_name = "md-awards-files"
        
        print(f"Testing public URLs for bucket: {bucket_name}")
        print(f"Base URL: {url}\n")
        
        # List files in bucket
        print("Fetching files from bucket...")
        files = supabase.storage.from_(bucket_name).list()
        
        if not files:
            print("❌ No files found in bucket")
            return
        
        print(f"✓ Found {len(files)} folder(s)/file(s)\n")
        
        # Test first few files
        test_count = 0
        for item in files[:3]:  # Test first 3 items
            if item.get('id'):  # It's a folder or file
                name = item.get('name')
                print(f"📁 {name}")
                
                # If it's a folder, list files inside
                try:
                    sub_files = supabase.storage.from_(bucket_name).list(name)
                    for sub_item in sub_files[:2]:  # Test 2 files from folder
                        if sub_item.get('id'):
                            sub_name = sub_item.get('name')
                            file_path = f"{name}/{sub_name}"
                            
                            # Generate public URL (same as app does)
                            encoded_path = urllib.parse.quote(file_path)
                            public_url = f"{url}/storage/v1/object/public/{bucket_name}/{encoded_path}"
                            
                            print(f"  📄 {sub_name}")
                            print(f"     URL: {public_url}")
                            
                            # Test if URL is accessible
                            try:
                                response = requests.head(public_url, timeout=5)
                                if response.status_code == 200:
                                    print(f"     ✅ Accessible (Status: {response.status_code})")
                                else:
                                    print(f"     ⚠️  Status: {response.status_code}")
                                test_count += 1
                            except Exception as e:
                                print(f"     ❌ Error accessing: {e}")
                            
                            if test_count >= 2:
                                break
                except:
                    pass
                    
            if test_count >= 2:
                break
        
        print("\n" + "="*60)
        print("RESULT:")
        print("="*60)
        print("If you see ✅ above, your app's public URLs work correctly!")
        print("Files uploaded by your Streamlit app will be accessible.")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_public_urls()
