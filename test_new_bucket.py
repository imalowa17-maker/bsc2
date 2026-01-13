"""
Test the new md-awards-storage bucket
Run this after creating the bucket manually
"""
import streamlit as st
from supabase import create_client
import urllib.parse

def test_new_bucket():
    try:
        url = st.secrets["supabase"]["url"].rstrip('/')
        key = st.secrets["supabase"]["key"]
        supabase = create_client(url, key)
        
        bucket_name = "md-awards-storage"
        
        print("="*60)
        print("TESTING NEW BUCKET: md-awards-storage")
        print("="*60)
        
        # Check if bucket exists
        print("\n1️⃣  Checking if bucket exists...")
        try:
            buckets = supabase.storage.list_buckets()
            bucket_names = [b.get('name') for b in buckets]
            
            if bucket_name in bucket_names:
                print(f"   ✅ Bucket '{bucket_name}' exists!")
                
                # Find the bucket details
                bucket_info = next((b for b in buckets if b.get('name') == bucket_name), None)
                if bucket_info:
                    is_public = bucket_info.get('public', False)
                    print(f"   📊 Public: {is_public}")
                    
                    if not is_public:
                        print("   ⚠️  WARNING: Bucket is NOT public!")
                        print("   Go to dashboard and toggle 'Public bucket' to ON")
            else:
                print(f"   ❌ Bucket '{bucket_name}' NOT FOUND!")
                print(f"   Available buckets: {bucket_names}")
                print("\n   Please create the bucket manually:")
                print("   https://irvcekjiqfjbdifbpgas.supabase.co/project/_/storage/buckets")
                return False
        except Exception as e:
            print(f"   ⚠️  Could not list buckets: {e}")
        
        # Test upload
        print("\n2️⃣  Testing file upload...")
        test_content = b"This is a test file to verify bucket access"
        test_path = f"test/test_{int(__import__('time').time())}.txt"
        
        try:
            upload_result = supabase.storage.from_(bucket_name).upload(
                path=test_path,
                file=test_content,
                file_options={
                    "content-type": "text/plain",
                    "upsert": "true"
                }
            )
            print(f"   ✅ Upload successful!")
            print(f"   📁 Path: {test_path}")
        except Exception as e:
            print(f"   ❌ Upload failed: {e}")
            return False
        
        # Test public URL
        print("\n3️⃣  Testing public URL access...")
        encoded_path = urllib.parse.quote(test_path)
        public_url = f"{url}/storage/v1/object/public/{bucket_name}/{encoded_path}"
        
        print(f"   🔗 Public URL: {public_url}")
        print(f"\n   📋 Copy this URL and open it in your browser")
        print(f"   You should see: 'This is a test file to verify bucket access'")
        
        # Try to fetch the content
        try:
            import requests
            response = requests.get(public_url, timeout=10)
            
            if response.status_code == 200:
                print(f"\n   ✅ SUCCESS! Public URL is accessible!")
                print(f"   📄 Content: {response.text[:50]}...")
            else:
                print(f"\n   ❌ ERROR: Got status code {response.status_code}")
                print(f"   Response: {response.text[:200]}")
                
                if response.status_code == 404:
                    print("\n   🔧 FIX:")
                    print("   1. Go to your Supabase dashboard")
                    print("   2. Storage → Buckets → md-awards-storage")
                    print("   3. Click settings (gear icon)")
                    print("   4. Toggle 'Public bucket' to ON")
                    print("   5. Save and run this test again")
                return False
        except Exception as e:
            print(f"\n   ⚠️  Could not fetch URL: {e}")
            print(f"   Try opening the URL manually in your browser")
        
        # Clean up test file
        print("\n4️⃣  Cleaning up test file...")
        try:
            supabase.storage.from_(bucket_name).remove([test_path])
            print(f"   ✅ Test file removed")
        except Exception as e:
            print(f"   ⚠️  Could not remove test file: {e}")
        
        print("\n" + "="*60)
        print("✨ BUCKET TEST COMPLETE!")
        print("="*60)
        print("\nIf all tests passed, you can now:")
        print("1. Update bsc.py to use 'md-awards-storage'")
        print("2. Test your application")
        print("\nIf tests failed, follow the fix instructions above.")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_new_bucket()
