"""
Create a brand new bucket to replace md-awards-files
This will create a fresh bucket with proper permissions
"""
import streamlit as st
from supabase import create_client

def create_new_bucket():
    try:
        url = st.secrets["supabase"]["url"].rstrip('/')
        key = st.secrets["supabase"]["key"]
        supabase = create_client(url, key)
        
        # Use a new bucket name to avoid any configuration issues
        bucket_name = "md-awards-files"
        
        print(f"🚀 Creating new bucket '{bucket_name}'...")
        print(f"📡 Connected to: {url}")
        
        # First, list existing buckets
        print("\n📋 Current buckets:")
        try:
            existing = supabase.storage.list_buckets()
            for b in existing:
                print(f"   - {b.get('name')} (public: {b.get('public', False)})")
        except Exception as e:
            print(f"   Could not list: {e}")
        
        # Create the new bucket
        try:
            result = supabase.storage.create_bucket(
                bucket_name,
                options={
                    "public": True,
                    "file_size_limit": 52428800,  # 50MB
                    "allowed_mime_types": None  # Allow all file types
                }
            )
            print(f"\n✅ SUCCESS! Bucket '{bucket_name}' created!")
            print(f"   - Public: YES")
            print(f"   - File size limit: 50MB")
            print(f"   - All file types allowed")
            
        except Exception as e:
            error_msg = str(e)
            if "already exists" in error_msg.lower():
                print(f"\nℹ️  Bucket '{bucket_name}' already exists")
                print("   Checking if it's properly configured...")
                
                # Try to update it to be public
                try:
                    supabase.storage.update_bucket(
                        bucket_name,
                        options={"public": True}
                    )
                    print("   ✅ Updated to public!")
                except Exception as update_e:
                    print(f"   ⚠️  Could not update: {update_e}")
            else:
                print(f"\n❌ Error creating bucket: {e}")
                print("\n🔧 Manual creation steps:")
                print(f"   1. Go to: {url}/project/_/storage/buckets")
                print("   2. Click 'New Bucket'")
                print(f"   3. Name: {bucket_name}")
                print("   4. Toggle 'Public bucket' to ON")
                print("   5. Click 'Create bucket'")
                return False
        
        # Test the bucket by uploading a test file
        print(f"\n🧪 Testing bucket with a test upload...")
        try:
            test_content = b"Test file from create_new_bucket.py"
            test_path = "test/test.txt"
            
            upload_result = supabase.storage.from_(bucket_name).upload(
                path=test_path,
                file=test_content,
                file_options={
                    "content-type": "text/plain",
                    "upsert": "true"
                }
            )
            
            # Build the public URL
            import urllib.parse
            encoded_path = urllib.parse.quote(test_path)
            test_url = f"{url}/storage/v1/object/public/{bucket_name}/{encoded_path}"
            
            print(f"   ✅ Test file uploaded successfully!")
            print(f"   📎 Test URL: {test_url}")
            print(f"\n   Try opening this URL in your browser to verify it works!")
            
            # Clean up test file
            try:
                supabase.storage.from_(bucket_name).remove([test_path])
                print(f"   🧹 Test file cleaned up")
            except:
                pass
                
        except Exception as e:
            print(f"   ⚠️  Test upload failed: {e}")
            print(f"   This might indicate a permission issue")
        
        print(f"\n✨ All done! Update your bsc.py to use bucket: '{bucket_name}'")
        return True
        
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = create_new_bucket()
    if success:
        print("\n" + "="*60)
        print("NEXT STEPS:")
        print("="*60)
        print("1. Run this script and verify the test URL works")
        print("2. Update bsc.py to change:")
        print('   bucket_name = "md-awards-files"')
        print('   TO:')
        print('   bucket_name = "md-awards-storage"')
        print("3. Test your application!")
