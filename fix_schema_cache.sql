-- ============================================================================
-- Fix 'Committee Votes' Column and Reload Schema Cache
-- ============================================================================
-- Run this SQL in your Supabase SQL Editor to fix the PGRST204 error
-- ============================================================================

-- 1. Ensure the 'Committee Votes' column exists
ALTER TABLE md_awards_submissions 
ADD COLUMN IF NOT EXISTS "Committee Votes" TEXT;

-- 2. Force PostgREST to reload the schema cache
NOTIFY pgrst, 'reload schema';

-- 3. Verify the column exists
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'md_awards_submissions' 
  AND column_name = 'Committee Votes';

-- ============================================================================
-- Expected Result:
-- You should see: Committee Votes | text
-- ============================================================================
-- After running this:
-- 1. Wait 10-30 seconds for the cache to refresh
-- 2. Try your submission again
-- ============================================================================
