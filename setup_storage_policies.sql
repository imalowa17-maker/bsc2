-- ============================================
-- SUPABASE STORAGE RLS POLICIES
-- Run this in Supabase SQL Editor
-- ============================================

-- 1. Make sure the bucket is public
UPDATE storage.buckets 
SET public = true 
WHERE id = 'md-awards-files';

-- 2. Drop existing policies if any (in case of duplicates)
DROP POLICY IF EXISTS "Public Access" ON storage.objects;
DROP POLICY IF EXISTS "Allow public read access" ON storage.objects;
DROP POLICY IF EXISTS "Allow public uploads" ON storage.objects;
DROP POLICY IF EXISTS "Authenticated Upload" ON storage.objects;

-- 3. Allow ANYONE to read files (public access)
CREATE POLICY "Allow public read access" 
ON storage.objects FOR SELECT 
USING (bucket_id = 'md-awards-files');

-- 4. Allow ANYONE to upload files (for anonymous submissions)
CREATE POLICY "Allow public uploads" 
ON storage.objects FOR INSERT 
WITH CHECK (bucket_id = 'md-awards-files');

-- 5. Allow ANYONE to update files (for re-uploads)
CREATE POLICY "Allow public updates" 
ON storage.objects FOR UPDATE 
USING (bucket_id = 'md-awards-files');

-- 6. Allow ANYONE to delete files (for cleanup)
CREATE POLICY "Allow public deletes" 
ON storage.objects FOR DELETE 
USING (bucket_id = 'md-awards-files');

-- 7. Verify the policies were created
SELECT 
    schemaname, 
    tablename, 
    policyname, 
    permissive, 
    roles, 
    cmd 
FROM pg_policies 
WHERE tablename = 'objects' 
AND schemaname = 'storage';

-- 8. Verify bucket configuration
SELECT id, name, public, file_size_limit, allowed_mime_types 
FROM storage.buckets 
WHERE id = 'md-awards-files';
