# MD Awards - Supabase Migration Notes

## Summary
The application has been successfully migrated from Google Sheets to Supabase for all data operations, while retaining Google Drive for file storage. This ensures better scalability, performance, and modern database features.

## What Changed

### 1. **Database Backend: Google Sheets → Supabase**
   - All submission records are now stored in a Supabase PostgreSQL table
   - Table name: `md_awards_submissions`
   - Enables real-time updates, better querying, and row-level security

### 2. **File Storage: Still Google Drive**
   - File uploads continue to use Google Drive
   - Files are organized in folders by candidate and timestamp
   - Public links are stored in the database for easy access

### 3. **Functions Migrated**
   - ✅ `log_submission()` - Now writes to Supabase table
   - ✅ `read_records()` - Reads from Supabase table
   - ✅ `update_evaluator_vote()` - Updates Supabase records
   - ✅ `acquire_lock()` - Manages locks in Supabase
   - ✅ `release_lock()` - Releases locks in Supabase

### 4. **Backup Mechanism Retained**
   - CSV fallback still works if Supabase is unavailable
   - Located at: `evaluator_records.csv`

## Setup Instructions

### 1. **Supabase Setup**

#### A. Create a Supabase Project
1. Go to https://supabase.com
2. Create a new project
3. Note your project URL and API key (anon public key)

#### B. Create the Database Table
Run this SQL in the Supabase SQL Editor:

```sql
CREATE TABLE md_awards_submissions (
    id BIGSERIAL PRIMARY KEY,
    "Name" TEXT,
    "Timestamp" TEXT,
    "Total Score" NUMERIC,
    "Financial Score" NUMERIC,
    "Financial Action" TEXT,
    "Customer Score" NUMERIC,
    "Customer Action" TEXT,
    "Internal Business Processes Score" NUMERIC,
    "Internal Business Processes Action" TEXT,
    "Learning & Growth Score" NUMERIC,
    "Learning & Growth Action" TEXT,
    "Folder_URL" TEXT,
    "Files_JSON" TEXT,
    "Evaluator Vote" TEXT,
    "Evaluator Comment" TEXT,
    "Stage 1 Recommendation" TEXT,
    "Stage 1 Comment" TEXT,
    "Committee Votes" TEXT,
    "Current Status" TEXT,
    "Lock Token" TEXT,
    "Lock Expiry" TEXT,
    "Lock Holder" TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create index on Name and Timestamp for faster lookups
CREATE INDEX idx_name ON md_awards_submissions("Name");
CREATE INDEX idx_timestamp ON md_awards_submissions("Timestamp");
```

#### C. Enable Row Level Security (Optional but Recommended)
```sql
-- Enable RLS
ALTER TABLE md_awards_submissions ENABLE ROW LEVEL SECURITY;

-- Allow all operations with service key (server-side)
CREATE POLICY "Enable all for service role" 
ON md_awards_submissions 
FOR ALL 
TO service_role 
USING (true);

-- Allow reads for authenticated users
CREATE POLICY "Enable read for authenticated" 
ON md_awards_submissions 
FOR SELECT 
TO authenticated 
USING (true);
```

### 2. **Streamlit Secrets Configuration**

Add these secrets to `.streamlit/secrets.toml` or Streamlit Cloud:

```toml
[supabase]
url = "https://your-project.supabase.co"
key = "your-anon-public-key"

[postmark]
token = "your-postmark-server-token"

[auth]
evaluator_password = "your-secure-password"

[gcp_service_account]
type = "service_account"
project_id = "your-project"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "your-service-account@..."
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/..."
```

### 3. **Install Dependencies**

```bash
pip install -r requirements.txt
```

### 4. **Run the Application**

```bash
streamlit run bsc.py
```

## Key Features Preserved

- ✅ Employee submission form with scoring
- ✅ File upload to Google Drive
- ✅ Email notifications via Postmark
- ✅ Evaluator workspace with locking mechanism
- ✅ Two-stage evaluation process
- ✅ Final results with weighted voting
- ✅ CSV backup fallback
- ✅ All original business logic

## Benefits of Supabase

1. **Real-time Capabilities**: Can add real-time subscriptions if needed
2. **Better Performance**: PostgreSQL is faster than Google Sheets API
3. **Advanced Queries**: Full SQL support for complex reporting
4. **Scalability**: No rate limits like Google Sheets API
5. **Security**: Row-level security policies
6. **Backup**: Built-in automated backups
7. **Cost**: More generous free tier

## Migration Checklist

- [x] Replace Google Sheets client with Supabase client
- [x] Migrate `log_submission()` to Supabase
- [x] Migrate `read_records()` to Supabase
- [x] Migrate `update_evaluator_vote()` to Supabase
- [x] Migrate `acquire_lock()` and `release_lock()` to Supabase
- [x] Update requirements.txt
- [x] Preserve Google Drive integration
- [x] Maintain CSV fallback
- [x] Test all functionality
- [x] Add Final Results tab

## Troubleshooting

### Issue: "Supabase client unavailable"
- Check that secrets are properly configured
- Verify Supabase URL and API key are correct

### Issue: Records not appearing
- Verify the table exists in Supabase
- Check that column names match exactly (case-sensitive)
- Review Supabase logs in the dashboard

### Issue: Lock conflicts
- Locks expire after 120 seconds automatically
- Can manually clear locks by updating the table in Supabase dashboard

## Data Migration (If needed)

If you have existing data in Google Sheets:

1. Export Google Sheet to CSV
2. Use Supabase dashboard to import CSV
3. Ensure column names match exactly
4. Verify data integrity after import

## Support

For issues or questions:
- Check Supabase dashboard logs
- Review application errors in Streamlit
- Check CSV backup file if Supabase fails

---

**Migration Date**: January 8, 2026
**Version**: 2.0 (Supabase Edition)
