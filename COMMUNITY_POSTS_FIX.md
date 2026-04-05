# CommunityPosts Table Fix Summary

## Issues Found and Fixed:

### 1. **Incorrect Field Name**
- **Problem**: Code was using `posted_by: userId` but the model has `reposted_by` (for reposts)
- **Fix**: Updated to use correct fields:
  ```javascript
  {
    community_id: communityId,
    post_id: newPost.id,
    reposted_by: null,           // null for original posts
    is_author_original: true     // true for original posts
  }
  ```

### 2. **Missing Model Imports**
- **Problem**: `CommunityPosts`, `CommunityMemberships`, and `Communities` were imported locally
- **Fix**: Added to top-level imports for better consistency

### 3. **Enhanced Debugging**
- **Added**: More detailed logging for community post creation
- **Added**: Error handling around CommunityPost creation
- **Added**: Logging for cases with no communities selected

## Expected Behavior Now:

### Normal Create Post (`/create-post`):
- If communities selected → Creates entries in CommunityPosts table
- If no communities → No CommunityPosts entries (profile-only post)
- `inCommunity: false` (always)

### Community Create Post (`/create-post/:communityId`):
- Always creates entry in CommunityPosts table for the specific community
- `inCommunity: true` (always)

## Testing:
1. Create a normal post with community selection
2. Create a community-specific post
3. Check the console logs for debugging output
4. Verify CommunityPosts table entries using the SQL test script

## Database Fields Used:
- `community_id`: UUID of the community
- `post_id`: UUID of the post  
- `reposted_by`: NULL (for original posts)
- `is_author_original`: true (for original posts)
- `date_posted`: Auto-generated timestamp
