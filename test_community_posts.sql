-- Test CommunityPosts table functionality
-- Run this SQL to check the structure and data

-- Check if CommunityPosts table exists and its structure
DESCRIBE CommunityPosts;

-- Check current data in CommunityPosts table
SELECT * FROM CommunityPosts ORDER BY date_posted DESC LIMIT 10;

-- Check relationship with Posts and Communities
SELECT 
    cp.id as community_post_id,
    cp.community_id,
    cp.post_id,
    cp.date_posted,
    cp.is_author_original,
    p.content,
    p.authorId,
    p.inCommunity,
    c.name as community_name
FROM CommunityPosts cp
LEFT JOIN Posts p ON cp.post_id = p.id
LEFT JOIN Communities c ON cp.community_id = c.id
ORDER BY cp.date_posted DESC
LIMIT 10;
