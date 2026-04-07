# Real-Time Chat System — System Design

**Author:** Daylor Williams
**Date:** March 17, 2026
**Stack:** Python (FastAPI) + PostgreSQL + Redis
**Target scale:** < 10,000 users

---

## 1. Requirements

### Functional
- 1:1 direct messages between users
- Group channels / rooms with multiple participants
- Persistent message history (searchable, paginated)
- File and media sharing (images, attachments)
- User presence (online / offline / last seen)
- Basic auth (registration, login, JWT sessions)

### Non-Functional
- **Latency:** Message delivery < 200 ms on same region
- **Availability:** 99.9% uptime (≈ 8.7 hrs downtime/year)
- **Concurrency:** Up to 10,000 simultaneous WebSocket connections
- **Message throughput:** ~1,000 messages/sec peak (well within single-node Redis capacity)
- **Storage:** ~1 KB/message avg; 10K users × 100 msgs/day = ~1 GB/month of text data

### Constraints & Assumptions
- Single region deployment to start
- File uploads capped at 25 MB per file
- No end-to-end encryption (server holds plaintext) — revisit if needed
- Small team; simplicity and maintainability are first-class concerns

---

## 2. High-Level Architecture

```
┌────────────────────────────────────────────────────────┐
│                        Clients                         │
│          (Browser / Mobile / Desktop)                  │
└───────────┬────────────────────────┬───────────────────┘
            │ HTTPS / REST           │ WSS / WebSocket
            ▼                        ▼
┌───────────────────────────────────────────────────────┐
│                    Nginx (reverse proxy)               │
│             TLS termination, load balancing            │
└───────────────────────┬───────────────────────────────┘
                        │
            ┌───────────▼───────────┐
            │    FastAPI App Server  │
            │  (REST + WS handlers)  │
            │  Uvicorn / Gunicorn    │
            └───┬───────────────┬───┘
                │               │
         ┌──────▼──────┐  ┌─────▼──────┐
         │ PostgreSQL  │  │   Redis     │
         │  (primary   │  │  Pub/Sub +  │
         │   storage)  │  │   Cache     │
         └─────────────┘  └─────────────┘
                                │
                    (optional, future)
                  ┌─────────────▼──────────────┐
                  │  Object Storage (S3 / GCS)  │
                  │  File & media uploads       │
                  └─────────────────────────────┘
```

**Data flows:**
1. REST calls handle auth, channel management, and history fetching.
2. WebSocket connections carry real-time events (new messages, presence updates, typing indicators).
3. Redis pub/sub fans out messages from one WS connection to all other subscribers in a channel.
4. PostgreSQL is the source of truth for all persisted data.
5. Files are uploaded via a pre-signed URL flow directly to object storage; only the URL is stored in Postgres.

---

## 3. Data Model

### `users`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `username` | VARCHAR(32) UNIQUE | |
| `email` | VARCHAR(255) UNIQUE | |
| `password_hash` | TEXT | bcrypt |
| `avatar_url` | TEXT | nullable |
| `created_at` | TIMESTAMPTZ | |
| `last_seen_at` | TIMESTAMPTZ | updated on disconnect |

### `channels`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR(128) | nullable for DMs |
| `type` | ENUM('direct', 'group') | |
| `created_by` | UUID FK → users | |
| `created_at` | TIMESTAMPTZ | |

### `channel_members`
| Column | Type | Notes |
|---|---|---|
| `channel_id` | UUID FK → channels | composite PK |
| `user_id` | UUID FK → users | composite PK |
| `role` | ENUM('owner', 'member') | |
| `joined_at` | TIMESTAMPTZ | |

### `messages`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `channel_id` | UUID FK → channels | indexed |
| `sender_id` | UUID FK → users | |
| `content` | TEXT | nullable (media-only messages) |
| `type` | ENUM('text', 'image', 'file') | |
| `media_url` | TEXT | nullable |
| `media_filename`| VARCHAR(255) | nullable |
| `media_size_bytes`| BIGINT | nullable |
| `created_at` | TIMESTAMPTZ | indexed (for pagination) |
| `deleted_at` | TIMESTAMPTZ | soft delete; nullable |

**Key indexes:**
```sql
-- Fast message history retrieval (cursor-based pagination)
CREATE INDEX idx_messages_channel_created
  ON messages (channel_id, created_at DESC);

-- Fast member lookup
CREATE INDEX idx_channel_members_user
  ON channel_members (user_id);
```

---

## 4. API Design

### REST Endpoints

**Auth**
```
POST   /auth/register          — create account
POST   /auth/login             — returns JWT access + refresh tokens
POST   /auth/refresh           — refresh access token
POST   /auth/logout            — invalidate refresh token
```

**Users**
```
GET    /users/me               — current user profile
PATCH  /users/me               — update profile / avatar
GET    /users/{id}             — get user by ID
GET    /users/search?q=        — search users by username
```

**Channels**
```
GET    /channels               — list channels the caller is in
POST   /channels               — create group channel
GET    /channels/{id}          — channel detail + members
POST   /channels/direct        — create or fetch existing DM with user_id
POST   /channels/{id}/members  — add member (owner only)
DELETE /channels/{id}/members/{user_id} — remove member
```

**Messages**
```
GET    /channels/{id}/messages?before=<cursor>&limit=50
                               — paginated history (cursor = message ID)
POST   /channels/{id}/messages — send message (text or media URL)
DELETE /messages/{id}          — soft delete (sender or owner only)
```

**Files**
```
POST   /files/upload-url       — get pre-signed S3 PUT URL
                                 { channel_id, filename, content_type }
                               → { upload_url, media_url }
```

### WebSocket

**Endpoint:** `wss://yourdomain.com/ws?token=<jwt>`

**Connection lifecycle:**
1. Client connects and authenticates via token query param (or first message).
2. Server resolves the user's channel memberships, subscribes server-side to `channel:<id>` Redis topics.
3. Server sends an initial `connected` event with user info.
4. On disconnect, server unsubscribes from Redis and updates `last_seen_at`.

**Event envelope:**
```json
{
  "type": "<event_type>",
  "payload": { ... }
}
```

**Client → Server events:**
| Type | Payload | Description |
|---|---|---|
| `message.send` | `{ channel_id, content, type, media_url? }` | Send a message |
| `typing.start` | `{ channel_id }` | Broadcast typing indicator |
| `typing.stop` | `{ channel_id }` | Stop typing indicator |
| `presence.ping` | — | Heartbeat to maintain presence |

**Server → Client events:**
| Type | Payload | Description |
|---|---|---|
| `connected` | `{ user, channels[] }` | Sent on successful auth |
| `message.new` | `{ message }` | New message in a subscribed channel |
| `message.deleted` | `{ message_id, channel_id }` | Message soft-deleted |
| `typing` | `{ user_id, channel_id, is_typing }` | Typing indicator |
| `presence.update` | `{ user_id, status, last_seen_at }` | Presence change |
| `error` | `{ code, message }` | Error response |

---

## 5. Real-Time Message Flow

```
 Client A                  FastAPI Server             Redis               Client B
    │                           │                       │                    │
    │── WS: message.send ──────►│                       │                    │
    │                           │── INSERT messages ──► DB                   │
    │                           │                       │                    │
    │                           │── PUBLISH channel:xyz ►                    │
    │                           │                       │── message.new ────►│
    │◄── WS: message.new ───────│                       │                    │
    │   (echo back to sender)   │                       │                    │
```

**Why echo back to the sender?** The sender's UI should update from the server-confirmed message (which now has `id`, `created_at`, etc.) rather than optimistically inserting, to keep all clients in sync.

---

## 6. Presence System

Presence is kept **lightweight** at this scale:

- On WS connect: set `Redis key user:<id>:online = 1` with a 30s TTL; publish `presence.update` to the user's channels.
- Every 20s, the client sends `presence.ping`; server refreshes the TTL.
- On WS disconnect: delete the key; publish `presence.update` with `status: offline`; write `last_seen_at` to Postgres.
- Any server can query `EXISTS user:<id>:online` in Redis to check presence.

---

## 7. File / Media Sharing Flow

```
1. Client requests a pre-signed upload URL from REST API
   POST /files/upload-url { channel_id, filename, content_type }
   ← { upload_url, media_url }

2. Client uploads file directly to S3 (bypasses your server)
   PUT <upload_url>  (binary file)

3. Client sends WS message:
   { type: "message.send", channel_id, type: "image", media_url }

4. Server saves message to DB and fans out via Redis as usual
```

This keeps large binary data off your app server entirely.

---

## 8. Caching Strategy

| What | Where | TTL | Rationale |
|---|---|---|---|
| User profile | Redis `user:<id>` | 5 min | Avoid PG hit on every message |
| Channel membership | Redis `channel:<id>:members` | 60 s | Used on every WS message send |
| Online presence | Redis `user:<id>:online` | 30 s | TTL acts as the presence heartbeat |
| Recent messages | None | — | PG with index is fast enough at this scale |

---

## 9. Scale & Reliability

### Load Estimation (10K users)
- **Peak concurrent WS connections:** ~3,000 (30% DAU online simultaneously)
- **Messages/sec at peak:** ~500–1,000 (generous estimate)
- **Redis pub/sub throughput:** easily handles 100K msg/sec on a single node
- **Postgres writes:** ~1,000 inserts/sec — well within single-instance capacity

### Deployment (Single Region, Small Scale)

```
┌──────────────────────────────────┐
│  Cloud Provider (AWS / GCP)      │
│                                  │
│  ┌─────────────────────────┐     │
│  │  App Server (2–4 vCPU)  │     │
│  │  FastAPI + Uvicorn       │     │
│  └─────────────────────────┘     │
│                                  │
│  ┌──────────────┐  ┌──────────┐  │
│  │  PostgreSQL  │  │  Redis   │  │
│  │  (managed)   │  │ (managed)│  │
│  │  RDS / Cloud │  │ Elasticache│ │
│  │  SQL         │  │ / Memstore│ │
│  └──────────────┘  └──────────┘  │
└──────────────────────────────────┘
```

**Start with a single app server.** At < 10K users you don't need horizontal scaling. If you do need a second app server (for deploys, not capacity), each server must share the same Redis instance for pub/sub — that's already handled by the design.

### Reliability
- **DB backups:** Daily automated snapshots + point-in-time recovery (PITR) via managed Postgres.
- **Redis:** In-memory only (pub/sub is ephemeral); acceptable since messages are persisted in Postgres. Consider Redis persistence (AOF) only if you add rate limiting or session data.
- **Health checks:** Nginx actively health-checks the app server; swap to a new instance in < 30s if it fails.
- **Graceful shutdown:** On SIGTERM, stop accepting new WS connections, drain in-flight messages, then exit. Clients reconnect automatically.

---

## 10. Security

| Concern | Approach |
|---|---|
| Authentication | JWT (access token 15 min, refresh token 30 days) |
| Transport | TLS everywhere (HTTPS + WSS) |
| Authorization | Check `channel_members` before any read/write |
| Password storage | bcrypt with cost factor 12 |
| File uploads | Pre-signed URLs scoped to specific S3 bucket/path with 5-min expiry |
| Rate limiting | Nginx or FastAPI middleware: 60 REST req/min, 10 WS messages/sec per user |
| SQL injection | SQLAlchemy ORM / parameterized queries — never raw string interpolation |
| XSS | Sanitize message content server-side before storing |

---

## 11. Trade-Off Analysis

| Decision | What was chosen | Alternative | Why |
|---|---|---|---|
| WebSockets over SSE | WebSockets | Server-Sent Events | Bidirectional — needed for typing indicators and presence pings |
| Redis pub/sub | Redis | PostgreSQL LISTEN/NOTIFY | Redis is simpler to reason about at scale; LISTEN/NOTIFY gets messy with connection pooling |
| Single app server | 1 instance | Horizontally scaled fleet | Overkill at < 10K users; adds complexity (session affinity, shared state) with no benefit yet |
| Soft deletes | `deleted_at` column | Hard delete | Allows audit trail and "message deleted" tombstones in the UI |
| Cursor-based pagination | `before=<message_id>` | Offset pagination | Offset is unreliable when new messages arrive; cursor is stable |
| Pre-signed S3 for files | S3 direct upload | Stream through server | Keeps binary data off the app server; S3 handles CDN, durability, and bandwidth |

---

## 12. What to Revisit as You Grow

1. **Horizontal scaling (> 50K users):** Add a second app server, use Redis Cluster, add sticky sessions or make WS stateless via Redis.
2. **Message search:** Add full-text search with `pg_trgm` or migrate to Elasticsearch for richer search.
3. **Push notifications:** Integrate Firebase Cloud Messaging (FCM) / APNs for mobile users who are offline.
4. **End-to-end encryption:** Signal Protocol or similar — major architectural change, plan early if required.
5. **Read receipts:** Track per-user read cursors per channel in a `channel_member_reads` table.
6. **Message reactions:** Simple join table `message_reactions (message_id, user_id, emoji)`.
7. **Multi-region:** If latency matters globally, consider a CRDT-based approach or a managed global DB (e.g., CockroachDB, PlanetScale).

---

*Design complete as of March 17, 2026. Revisit scale assumptions at 5K MAU.*
