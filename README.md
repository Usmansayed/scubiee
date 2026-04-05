# Scubiee — The News Distribution Platform

> A dedicated, feature-rich platform built to make news distribution effortless for local channels, independent journalists, and media organizations.

---

## Why We Built Scubiee

The media landscape is fragmented. Local news channels, independent journalists, and small media outlets struggle to reach their audiences without depending on generic social platforms that weren't built for news. Algorithms bury important local stories. Monetization is opaque. Audiences are scattered.

**Scubiee was built to fix that.**

We built Scubiee because local news deserves a home — a platform designed from the ground up for the way news actually works: breaking stories, community discussion, short video clips, curated newsletters, and real-time audience engagement. Instead of forcing news organizations to adapt to platforms built for entertainment, we built the platform around news itself.

Whether you're a local TV channel, a community blogger, or an independent investigative journalist, Scubiee gives you professional-grade tools to publish, distribute, and grow — without the noise.

---

## What Scubiee Does

Scubiee is a full-stack news and content platform where channels publish articles, short video clips, curated papers, and community discussions — all in one place, all reaching the right audience.

### For News Channels & Publishers
- Publish articles with rich media (images, video embeds, formatted text)
- Automatically categorized by topic using AI — no manual tagging required
- Schedule and send curated **Papers** (newsletters) to subscribers at defined intervals
- Real-time analytics on views, engagement, and audience growth
- Verified channel badges to build trust with readers

### For Audiences
- Follow specific channels and journalists
- Subscribe to topic categories: Politics, Technology, Sports, Business, Science, Health, Entertainment, and more
- Engage through comments, reactions, and shares
- Discover local and global stories in a clean, distraction-free feed
- Receive real-time notifications for breaking news from followed sources

---

## Core Features

### Rich Content Publishing
- Full rich-text editor with support for images, videos, embeds, and formatting
- AI-powered automatic category and topic detection (powered by Google Vertex AI / Gemini)
- Location tagging to surface locally relevant stories
- Hashtag and mention support for content discovery
- Post threading for follow-up coverage and developing stories

### Shorts — Breaking News in Seconds
- Short-form vertical video format designed for quick news clips and field reporting
- Dedicated Shorts feed with smooth vertical scrolling
- Ideal for real-time coverage: protests, press conferences, breaking events
- Like, share, comment, and bookmark

### Papers — Curated Newsletters
- Bundle multiple articles into a single delivered Paper
- Configure delivery schedules and story count (10–100 articles per issue)
- AI-generated summaries of each Paper for at-a-glance reading
- Processing pipeline with full status tracking

### Communities — Local & Topic-Based Hubs
- Create public, private, or restricted communities around topics or localities
- Moderated posting rules: open discussion or channel-controlled publishing
- Community-specific feeds, trending discussions, and hot topics
- Ideal for hyper-local coverage (neighborhoods, cities, districts)

### Real-Time Engagement
- Live comment threads with nested replies
- Real-time notifications (likes, comments, shares, follows, breaking alerts)
- Direct messaging between publishers and their audience
- Group chat rooms for editorial teams or community moderators
- Online/offline presence tracking

### Discovery & Search
- Full-text search powered by Elasticsearch and Fuse.js
- Search across articles, hashtags, channels, and communities
- Recommended channels and communities based on user interests
- Trending topics surfaced automatically

### Stories — Ephemeral Updates
- Publish time-sensitive updates as Stories (image or video)
- Stories expire automatically — perfect for live event coverage
- View and engagement tracking

### Profiles & Channels
- Verified channel profiles with bio, cover image, and social links
- Follower/following system with audience growth tracking
- Achievement badges for credibility and milestones
- Interest and preference management for personalized feeds

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, Vite, Redux Toolkit, Tailwind CSS, Material-UI, Chakra UI |
| Animations | Framer Motion |
| Rich Text | Tiptap, EditorJS |
| Video Processing | FFmpeg.js |
| Real-Time | Socket.io |
| Backend | Node.js, Express.js |
| Database | MySQL, Sequelize ORM |
| Search | Elasticsearch, Fuse.js |
| AI / ML | Google Vertex AI (Gemini), Google GenAI |
| Storage | Google Cloud Storage, Backblaze B2 |
| Auth | JWT, Passport.js (Google, Facebook, GitHub OAuth) |
| Security | Helmet.js, rate limiting, HTTPS enforcement |
| Logging | Winston |
| Deployment | PWA-ready (Progressive Web App) |

---

## Project Structure

```
scubiee/
├── client/                   # React frontend application
│   └── src/
│       ├── pages/            # Page-level components
│       ├── components/       # Reusable UI components
│       ├── Slices/           # Redux state slices
│       └── hooks/            # Custom React hooks
│
├── server/                   # Node.js + Express backend
│   ├── routes/               # REST API endpoints
│   ├── models/               # Sequelize database models
│   ├── middlewares/          # Auth, validation, AI middleware
│   ├── utils/                # Helper utilities
│   └── config/               # App configuration
│
└── config/                   # Shared configuration
```

---

## Getting Started

### Prerequisites
- Node.js 18+
- MySQL database
- Google Cloud project (for AI features and storage)
- Backblaze B2 account (for media storage)
- Elasticsearch instance (for search)

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/scubiee.git
cd scubiee

# Install dependencies for both client and server
cd client && npm install
cd ../server && npm install
```

### Environment Variables

Create a `.env` file in the `server/` directory:

```env
# Database
DB_HOST=your_db_host
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_NAME=scubiee

# Auth
JWT_SECRET=your_jwt_secret

# Google OAuth
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret

# Google Cloud
GOOGLE_CLOUD_BUCKET=your_bucket_name
GOOGLE_APPLICATION_CREDENTIALS=path/to/credentials.json

# Backblaze B2
B2_APPLICATION_KEY_ID=your_key_id
B2_APPLICATION_KEY=your_app_key
B2_BUCKET_NAME=your_bucket

# Elasticsearch
ELASTICSEARCH_URL=http://localhost:9200

# App
API_BASE_URL=http://localhost:5000
CLIENT_URL=http://localhost:5173
```

### Run in Development

```bash
# Start the backend
cd server && npm run dev

# Start the frontend (separate terminal)
cd client && npm run dev
```

---

## The Vision

Scubiee is more than a publishing tool — it's infrastructure for local journalism.

We believe communities deserve access to reliable, locally relevant news. We believe news organizations — no matter how small — deserve a platform that respects their editorial voice, helps them reach their audience, and gives them the tools to grow sustainably.

That's what Scubiee is built for.

---

## Contributing

We welcome contributions from developers, journalists, and media technologists. Open an issue or submit a pull request to get started.

---

## License

MIT License. See `LICENSE` for details.
