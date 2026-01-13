-- Enable Row Level Security (RLS) for MD Awards Tables
-- This prevents unauthorized access to your data

-- ============================================
-- 1. ENABLE RLS ON SUBMISSIONS TABLE
-- ============================================
ALTER TABLE public.md_awards_submissions ENABLE ROW LEVEL SECURITY;

-- Create policy to allow anyone to INSERT (submit applications)
CREATE POLICY "Allow public submissions"
ON public.md_awards_submissions
FOR INSERT
TO public
WITH CHECK (true);

-- Create policy to allow anyone to SELECT (read submissions)
-- You might want to restrict this later
CREATE POLICY "Allow public read"
ON public.md_awards_submissions
FOR SELECT
TO public
USING (true);

-- Create policy to allow updates (if needed for editing submissions)
CREATE POLICY "Allow public updates"
ON public.md_awards_submissions
FOR UPDATE
TO public
USING (true)
WITH CHECK (true);

-- ============================================
-- 2. CHECK AND ENABLE RLS ON SETTINGS TABLE
-- ============================================
ALTER TABLE public.md_awards_settings ENABLE ROW LEVEL SECURITY;

-- Allow public to read settings (like deadline, active status)
CREATE POLICY "Allow public read settings"
ON public.md_awards_settings
FOR SELECT
TO public
USING (true);

-- Only allow authenticated users to update settings (optional)
-- Uncomment if you want stricter control:
-- CREATE POLICY "Allow authenticated updates to settings"
-- ON public.md_awards_settings
-- FOR UPDATE
-- TO authenticated
-- USING (true)
-- WITH CHECK (true);

-- ============================================
-- VERIFICATION QUERIES
-- ============================================
-- Run these to verify RLS is enabled:

-- Check RLS status
SELECT schemaname, tablename, rowsecurity
FROM pg_tables
WHERE tablename IN ('md_awards_submissions', 'md_awards_settings');

-- Check policies
SELECT schemaname, tablename, policyname, permissive, roles, cmd
FROM pg_policies
WHERE tablename IN ('md_awards_submissions', 'md_awards_settings');
