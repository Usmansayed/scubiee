# Post Creation Flow Testing Guide

## Test Scenarios

### 1. Normal Create Post - Profile Only
**URL:** `/create-post`
**Expected UI:**
- Title: "Create Post"
- Community selector: Visible
- User action: Skip community selection

**Expected Backend:**
- `isDirectCommunityPost`: false
- `inCommunity`: false
- `CommunityPosts`: No entries
- **Result**: Post appears only in profile and general feed

### 2. Normal Create Post - With Community Selection
**URL:** `/create-post`
**Expected UI:**
- Title: "Create Post"
- Community selector: Visible
- User action: Select one or more communities

**Expected Backend:**
- `isDirectCommunityPost`: false
- `inCommunity`: false
- `CommunityPosts`: Entries for selected communities
- **Result**: Post appears in profile, general feed, AND selected communities

### 3. Community Create Post - Community Only
**URL:** `/create-post/:communityId` (e.g., `/create-post/123`)
**Expected UI:**
- Title: "Post in Community"
- Shows community name and icon
- Community selector: Hidden (not shown at all)
- Single step process - no community selection step

**Expected Backend:**
- `isDirectCommunityPost`: true
- `inCommunity`: true
- `CommunityPosts`: Entry for the specific community only
- **Result**: Post appears ONLY in that community (not in profile or general feed)

## Key Points:
- `inCommunity = true` ONLY when posting directly from a community using `/create-post/:communityId`
- `inCommunity = false` for all normal create post flows using `/create-post` (regardless of community selection)
- Community selection step is SKIPPED when using the `/create-post/:communityId` route
- UI title and flow are different for community vs normal posts
- Community posts use route parameters instead of query parameters for cleaner URLs
