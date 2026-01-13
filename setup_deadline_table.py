"""
SQL script to create the settings table in Supabase for MD Awards
Run this in your Supabase SQL Editor to enable deadline management
"""

# SQL TO RUN IN SUPABASE SQL EDITOR:

CREATE_TABLE_SQL = """
-- Create settings table for system configuration
CREATE TABLE IF NOT EXISTS md_awards_settings (
    id BIGSERIAL PRIMARY KEY,
    setting_key VARCHAR(255) UNIQUE NOT NULL,
    setting_value TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Add index for faster lookups
CREATE INDEX IF NOT EXISTS idx_settings_key ON md_awards_settings(setting_key);

-- Insert default deadline record (optional - will be created automatically)
INSERT INTO md_awards_settings (setting_key, setting_value, updated_at)
VALUES ('submission_deadline', NULL, NOW())
ON CONFLICT (setting_key) DO NOTHING;

-- Grant permissions (adjust based on your security needs)
-- For authenticated users (your service account)
ALTER TABLE md_awards_settings ENABLE ROW LEVEL SECURITY;

-- Allow all operations for authenticated users (service account)
CREATE POLICY "Allow all for authenticated users" ON md_awards_settings
FOR ALL
USING (true)
WITH CHECK (true);
"""

print("=" * 80)
print("SUPABASE SETTINGS TABLE SETUP")
print("=" * 80)
print("\nCopy and paste the SQL below into your Supabase SQL Editor:\n")
print(CREATE_TABLE_SQL)
print("\n" + "=" * 80)
print("\nAfter running this SQL:")
print("1. The 'md_awards_settings' table will be created")
print("2. Evaluators can set/edit submission deadlines from the Settings tab")
print("3. Public submissions will be blocked once the deadline passes")
print("=" * 80)
