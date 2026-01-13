"""
Enable Row Level Security (RLS) on MD Awards tables
This will execute the SQL to secure your database tables
"""
import streamlit as st
from supabase import create_client

def enable_rls():
    try:
        url = st.secrets["supabase"]["url"].rstrip('/')
        key = st.secrets["supabase"]["key"]
        supabase = create_client(url, key)
        
        print("="*60)
        print("ENABLING ROW LEVEL SECURITY (RLS)")
        print("="*60)
        
        # Read the SQL file
        with open('enable_rls.sql', 'r') as f:
            sql_content = f.read()
        
        # Split into individual statements (before verification queries)
        sql_statements = sql_content.split('-- VERIFICATION QUERIES')[0]
        
        print("\n📋 SQL Commands to Execute:")
        print("-" * 60)
        print(sql_statements)
        print("-" * 60)
        
        print("\n⚠️  IMPORTANT: This script may not have permission to execute SQL directly.")
        print("If you see errors, please run the SQL manually:\n")
        print("1. Go to: https://irvcekjiqfjbdifbpgas.supabase.co/project/_/sql/new")
        print("2. Copy the contents of 'enable_rls.sql'")
        print("3. Paste into the SQL Editor")
        print("4. Click 'Run' or press Ctrl+Enter")
        print("\nAttempting to execute via API...\n")
        
        # Try to execute using the REST API
        # Note: This might not work depending on API permissions
        try:
            # Split into individual statements for execution
            statements = [s.strip() for s in sql_statements.split(';') if s.strip() and not s.strip().startswith('--')]
            
            for i, stmt in enumerate(statements, 1):
                if not stmt:
                    continue
                    
                print(f"\n{i}. Executing: {stmt[:80]}...")
                
                try:
                    # Use the RPC or query method
                    result = supabase.rpc('exec_sql', {'query': stmt}).execute()
                    print(f"   ✅ Success")
                except Exception as e:
                    error_msg = str(e)
                    if 'exec_sql' in error_msg or 'not found' in error_msg.lower():
                        print(f"   ⚠️  API execution not available")
                        print(f"   Please run the SQL manually (see instructions above)")
                        break
                    else:
                        print(f"   ❌ Error: {e}")
            
        except Exception as e:
            print(f"\n❌ Could not execute SQL via API: {e}")
            print("\n📝 Please run the SQL manually using the Supabase Dashboard SQL Editor")
        
        # Verify RLS status
        print("\n" + "="*60)
        print("VERIFICATION")
        print("="*60)
        print("\nChecking RLS status for tables...")
        
        # Try to query the tables to see if RLS is working
        try:
            # This should work if RLS is properly configured
            result = supabase.table('md_awards_submissions').select('*').limit(1).execute()
            print("✅ md_awards_submissions table is accessible")
        except Exception as e:
            print(f"⚠️  md_awards_submissions: {e}")
        
        try:
            result = supabase.table('md_awards_settings').select('*').limit(1).execute()
            print("✅ md_awards_settings table is accessible")
        except Exception as e:
            print(f"⚠️  md_awards_settings: {e}")
        
        print("\n" + "="*60)
        print("NEXT STEPS")
        print("="*60)
        print("\n1. Go to Supabase Dashboard:")
        print("   https://irvcekjiqfjbdifbpgas.supabase.co/project/_/database/tables")
        print("\n2. Check each table:")
        print("   - md_awards_submissions")
        print("   - md_awards_settings")
        print("\n3. Verify RLS is enabled (look for shield icon)")
        print("\n4. If not enabled, run the SQL manually:")
        print("   https://irvcekjiqfjbdifbpgas.supabase.co/project/_/sql/new")
        print("\n5. Test your application to ensure it still works")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    enable_rls()
