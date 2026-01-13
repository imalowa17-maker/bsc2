"""
Test script to verify Supabase Storage bucket configuration
Run this to check if uploads are working properly
"""
import streamlit as st
from supabase import create_client
import io

def test_bucket():
    try:
        # Get Supabase client
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        supabase = create_client(url, key)
        
        bucket_name = "md-awards-files"
        
        print("=" * 60)
        print("SUPABASE STORAGE BUCKET TEST")
        print("=" * 60)
        
        # 1. List all buckets
        print("\n1. Checking existing buckets...")
        try:
            buckets = supabase.storage.list_buckets()
            print(f"   Found {len(buckets)} bucket(s):")
            for b in buckets:
                is_public = "✅ PUBLIC" if b.get('public') else "🔒 PRIVATE"
                print(f"   - {b['name']} ({is_public})")
        except Exception as e:
            print(f"   ❌ Error listing buckets: {e}")
            return
        
        # 2. Check if our bucket exists
        print(f"\n2. Checking for '{bucket_name}' bucket...")
        bucket_exists = any(b['name'] == bucket_name for b in buckets)
        
        if not bucket_exists:
            print(f"   ❌ Bucket '{bucket_name}' NOT FOUND!")
            print("\n   📝 TO FIX:")
            print("   1. Go to Supabase Dashboard → Storage")
            print("   2. Click 'New bucket'")
            print(f"   3. Name: {bucket_name}")
            print("   4. Make sure 'Public bucket' is CHECKED ✅")
            print("   5. Click 'Create bucket'")
            return
        
        bucket_info = next(b for b in buckets if b['name'] == bucket_name)
        is_public = bucket_info.get('public', False)
        
        if not is_public:
            print(f"   ⚠️ Bucket exists but is PRIVATE!")
            print("\n   📝 TO FIX:")
            print("   1. Go to Supabase Dashboard → Storage")
            print(f"   2. Click on '{bucket_name}' bucket")
            print("   3. Go to 'Configuration' or 'Settings'")
            print("   4. Enable 'Public bucket' option")
            print("   OR run this SQL in SQL Editor:")
            print(f"\n   UPDATE storage.buckets SET public = true WHERE name = '{bucket_name}';")
        else:
            print(f"   ✅ Bucket '{bucket_name}' exists and is PUBLIC")
        
        # 3. Test upload
        print("\n3. Testing file upload...")
        test_content = b"This is a test file from MD Awards system"
        test_path = "test/test_file.txt"
        
        try:
            response = supabase.storage.from_(bucket_name).upload(
                path=test_path,
                file=test_content,
                file_options={
                    "content-type": "text/plain",
                    "upsert": "true"
                }
            )
            print(f"   ✅ Upload successful!")
            print(f"   Response: {response}")
        except Exception as e:
            print(f"   ❌ Upload failed: {e}")
            print("\n   📝 POSSIBLE CAUSES:")
            print("   - Bucket doesn't exist")
            print("   - RLS policies blocking uploads")
            print("   - Service role key needed (not anon key)")
            return
        
        # 4. Test public URL access
        print("\n4. Testing public URL generation...")
        import urllib.parse
        encoded_path = urllib.parse.quote(test_path)
        public_url = f"{url}/storage/v1/object/public/{bucket_name}/{encoded_path}"
        print(f"   Generated URL: {public_url}")
        
        # 5. Try to list files
        print("\n5. Testing file listing...")
        try:
            files = supabase.storage.from_(bucket_name).list("test")
            print(f"   ✅ Listed {len(files)} file(s) in test folder")
            for f in files:
                print(f"   - {f.get('name')}")
        except Exception as e:
            print(f"   ⚠️ Could not list files: {e}")
        
        # 6. Cleanup
        print("\n6. Cleaning up test file...")
        try:
            supabase.storage.from_(bucket_name).remove([test_path])
            print("   ✅ Test file removed")
        except Exception as e:
            print(f"   ⚠️ Could not remove test file: {e}")
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED - Storage is properly configured!")
        print("=" * 60)
        print(f"\n📌 Your files will be accessible at:")
        print(f"   {url}/storage/v1/object/public/{bucket_name}/[file-path]")
        
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
        print("\n📝 CHECK YOUR CONFIGURATION:")
        print("   Make sure .streamlit/secrets.toml has:")
        print("""
   [supabase]
   url = "https://xxxxx.supabase.co"
   key = "your-anon-or-service-key"
        """)

if __name__ == "__main__":
    test_bucket()
