-- ============================================
-- FIX SUPABASE STORAGE RLS POLICIES
-- Run this ENTIRE script in Supabase SQL Editor
-- ============================================

-- Step 1: Make sure the bucket exists and is public
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('md-awards-files', 'md-awards-files', true, 52428800, NULL)
ON CONFLICT (id) DO UPDATE
SET public = true,
    file_size_limit = 52428800;

-- Step 2: Drop ALL existing policies on storage.objects
DROP POLICY IF EXISTS "Public Access" ON storage.objects;
DROP POLICY IF EXISTS "Allow public read access" ON storage.objects;
DROP POLICY IF EXISTS "Allow public uploads" ON storage.objects;
DROP POLICY IF EXISTS "Allow public updates" ON storage.objects;
DROP POLICY IF EXISTS "Allow public deletes" ON storage.objects;
DROP POLICY IF EXISTS "Authenticated Upload" ON storage.objects;

-- Step 3: Create new permissive policies that allow ANYONE to do anything
-- (This is safe for a submission system where you want anonymous uploads)

-- Allow ANYONE to read files
CREATE POLICY "Public read access for md-awards"
ON storage.objects FOR SELECT
TO public
USING (bucket_id = 'md-awards-files');

-- Allow ANYONE to upload files (INSERT)
CREATE POLICY "Public upload access for md-awards"
ON storage.objects FOR INSERT
TO public
WITH CHECK (bucket_id = 'md-awards-files');

-- Allow ANYONE to update files
CREATE POLICY "Public update access for md-awards"
ON storage.objects FOR UPDATE
TO public
USING (bucket_id = 'md-awards-files')
WITH CHECK (bucket_id = 'md-awards-files');

-- Allow ANYONE to delete files
CREATE POLICY "Public delete access for md-awards"
ON storage.objects FOR DELETE
TO public
USING (bucket_id = 'md-awards-files');

-- Step 4: Verify the policies were created
SELECT 
    schemaname, 
    tablename, 
    policyname, 
    permissive, 
    roles, 
    cmd,
    qual,
    with_check
FROM pg_policies 
WHERE tablename = 'objects' 
AND schemaname = 'storage'
AND policyname LIKE '%md-awards%';

-- Step 5: Verify bucket configuration
SELECT 
    id, 
    name, 
    public, 
    file_size_limit, 
    allowed_mime_types,
    created_at
FROM storage.buckets 
WHERE id = 'md-awards-files';

-- Expected output:
-- You should see 4 policies (SELECT, INSERT, UPDATE, DELETE) all with role 'public'
-- The bucket should show public = true
