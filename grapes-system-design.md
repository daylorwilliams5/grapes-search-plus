# GRAPES Fellowship Finder — System Design

**Prepared for:** UCLA Dean of Graduate Education (DGE)
**Author:** Daylor Williams
**Date:** March 17, 2026
**Stack:** Python + PostgreSQL (existing team familiarity)

---

## 1. What We're Building

GRAPES currently lives as a manually maintained Excel spreadsheet (~540 fellowships) that powers the UCLA DGE fellowship database. The goal is to transform it into a **self-maintaining, searchable web system** that:

- Gives grad students a fast, natural-language way to find fellowships ("3rd year PhD looking for travel funding")
- Automatically flags which records need review based on the season
- Links every result directly to the fellowship website
- Integrates cleanly with UCLA DGE's existing GoGrad infrastructure (SSO, branding)

---

## 2. Requirements

### Functional
- Natural-language + keyword search across all fellowship fields
- Filter by season (Fall, Winter, Spring, Summer, Open/Rolling)
- Filter by status (Published, Pending)
- Each result links to the fellowship website (or a Google search as fallback)
- Admin panel for the DGE team to update records
- Seasonal update reminders: auto-flag records that are due for review
- Fellowship detail pages (full description, eligibility, award amount, link)
- Optional: email digest sent to grad students at the start of each season

### Non-Functional
- Simple enough for a small DGE team to maintain without an engineer
- Should feel like part of GoGrad (UCLA SSO, UCLA branding)
- Fast search results (< 300ms)
- Works on mobile

### What's Out of Scope (Phase 1)
- End-to-end application tracking for students
- Integration with fellowship portals
- AI recommendation engine (addressed in Phase 2)

---

## 3. Current State vs. Target State

| | Today | Target |
|---|---|---|
| Data home | Excel spreadsheet | PostgreSQL database |
| Search | Ctrl+F in a spreadsheet | Full-text + keyword search UI |
| URLs | Copy/paste to Google | Direct link per fellowship |
| Season updates | Manual calendar reminders | Automated review queue |
| Student access | None (DGE-internal only) | Public search at `gograd.ucla.edu/fellowships` |
| Admin access | Edit the spreadsheet | Web-based admin panel |

---

## 4. System Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                          USERS                                 │
│           Grad Students            DGE Admin Staff             │
│         (public search UI)     (admin panel, SSO protected)    │
└──────────┬────────────────────────────────┬───────────────────┘
           │ HTTPS                          │ HTTPS + UCLA SSO
           ▼                                ▼
┌──────────────────────────────────────────────────────────────┐
│                     Web Application                           │
│                   (Django / FastAPI)                          │
│                                                               │
│   ┌──────────────┐    ┌──────────────┐    ┌───────────────┐  │
│   │  Search API  │    │  Admin Panel │    │ Seasonal Jobs │  │
│   │  /search     │    │  /admin      │    │  (scheduler)  │  │
│   └──────────────┘    └──────────────┘    └───────────────┘  │
└──────────────┬──────────────────────────────────┬────────────┘
               │                                  │
    ┌──────────▼──────────┐           ┌──────────▼──────────┐
    │     PostgreSQL       │           │   Search Index       │
    │  (fellowship data,  │           │   (PostgreSQL        │
    │   users, audit log) │           │    full-text search  │
    └─────────────────────┘           │   or Meilisearch)   │
                                      └─────────────────────┘
```

**Why Django?** It ships with a polished admin panel out of the box — the DGE team can manage all fellowship records through a browser UI without touching code. FastAPI is a lighter alternative if the team prefers.

---

## 5. Data Model

### `fellowships`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Matches existing GRAPES Record # |
| `title` | VARCHAR(512) | Fellowship name |
| `agency_primary` | VARCHAR(512) | Main sponsoring organization |
| `agency_secondary` | VARCHAR(512) | Co-sponsor, if any |
| `season` | ENUM | Fall, Winter, Spring, Summer, Open/Rolling |
| `deadline` | DATE | Nullable (TBD for many) |
| `deadline_notes` | TEXT | "Two deadlines", "rolling", etc. |
| `status` | ENUM | Published, Pending, Deleted |
| `active_status` | ENUM | Active, Inactive, Review |
| `url` | TEXT | Direct fellowship website URL |
| `description` | TEXT | Longer description (Phase 2) |
| `eligibility` | TEXT | Who can apply |
| `award_amount` | TEXT | Dollar amount or description |
| `notes` | TEXT | Internal DGE notes |
| `last_updated` | TIMESTAMPTZ | |
| `updated_by` | VARCHAR(64) | Initials or user ID |
| `created_at` | TIMESTAMPTZ | |

### `fellowship_tags` (Phase 2)
| Column | Type | Notes |
|---|---|---|
| `fellowship_id` | INT FK | |
| `tag` | VARCHAR(64) | e.g. "travel", "STEM", "diversity", "postdoc" |

### `update_log`
| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `fellowship_id` | INT FK | |
| `changed_by` | VARCHAR(64) | Staff initials / user ID |
| `changed_at` | TIMESTAMPTZ | |
| `field_name` | VARCHAR(64) | Which field changed |
| `old_value` | TEXT | |
| `new_value` | TEXT | |

### `seasonal_review_tasks`
| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `fellowship_id` | INT FK | |
| `season` | ENUM | Which season triggered this |
| `due_date` | DATE | When the review should be done |
| `completed` | BOOLEAN | |
| `completed_by` | VARCHAR(64) | |
| `completed_at` | TIMESTAMPTZ | |

---

## 6. Seasonal Auto-Update System

The current update timeline (from the Instructions sheet) is:

| Season | Review Window | What Gets Reviewed |
|---|---|---|
| Summer (July 1) | July–September | Open deadlines + Fall fellowships |
| Fall (October 1) | October–December | Winter fellowships (heaviest volume) |
| Winter/Spring (January) | January–March | Spring fellowships |
| Spring (April 1) | April–June | Summer fellowships |

### How It Works

A scheduled job runs on the 1st of July, October, January, and April. It:

1. Queries all fellowships in the upcoming season whose status is `Published` or `Pending`
2. Creates a `seasonal_review_task` row for each one
3. Sends an email digest to the DGE admin team listing which records need verification
4. In the admin panel, the review queue appears as a dedicated tab ("Reviews Due")

**Dead link detection (Phase 2):** The job also attempts an HTTP HEAD request against each stored URL. If the response is 404 or times out, it flags the record as "URL may be broken" in the review queue.

```
Seasonal Scheduler (cron)
        │
        ▼
  Query DB for upcoming-season fellowships
        │
        ▼
  Create review task rows for each
        │
        ├──► Send email digest to DGE staff
        │
        └──► Show "Review Queue" tab in admin panel
```

---

## 7. Search Design

### Phase 1: PostgreSQL Full-Text Search

PostgreSQL's built-in `tsvector` is fast enough for 500–2,000 records and requires no new infrastructure.

```sql
-- Add a computed search column
ALTER TABLE fellowships ADD COLUMN search_vector tsvector
  GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(agency_primary, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(description, '')), 'C') ||
    setweight(to_tsvector('english', coalesce(notes, '')), 'D')
  ) STORED;

CREATE INDEX idx_fellowships_search ON fellowships USING GIN(search_vector);
```

A search for "travel funding humanities" runs as:
```sql
SELECT * FROM fellowships
WHERE search_vector @@ plainto_tsquery('english', 'travel funding humanities')
ORDER BY ts_rank(search_vector, plainto_tsquery('english', 'travel funding humanities')) DESC;
```

**Synonym expansion** (same approach as the prototype): "STEM" → science, engineering, technology, mathematics; "travel" → travel, conference, international; "postdoc" → postdoctoral, post-doctoral.

### Phase 2: Meilisearch (optional upgrade)

If the DGE team wants typo-tolerance, semantic ranking, and instant-as-you-type results, swap the search backend for Meilisearch (self-hosted, open source). The API layer stays the same — only the search call changes. This can be added without changing the database or the UI.

---

## 8. URL Strategy

The current spreadsheet has no URLs. The recommended approach:

**Short term (now):** Each fellowship card links to `google.com/search?q=<title>+<agency>`. This is what the team already does manually and is consistently more accurate than stale stored URLs.

**Medium term (next 6 months):** Add a `url` field to the database. During the seasonal review process, staff paste in the verified URL as they check each record. A URL health check job flags broken links each season.

**Long term:** Automated URL discovery — when a new fellowship is added without a URL, a background job searches the web and suggests the top candidate for a staff member to confirm. This keeps the database clean without manual research per record.

---

## 9. Admin Panel

Django's built-in admin, customized with:

- **Review Queue tab** — fellowships flagged for seasonal review, grouped by season, with checkboxes to mark complete
- **Bulk status update** — select multiple records and change from Pending → Published
- **Import from Excel** — upload a new version of the GRAPES spreadsheet; the importer matches on Record Number and only updates changed fields
- **Audit trail** — every field change is logged in `update_log` with the editor's name and timestamp
- **Search within admin** — full-text search by title/agency to find a record to edit
- **Deleted Programs archive** — soft-delete instead of hard delete; deleted records move to an archive view

---

## 10. UCLA DGE Integration

The public-facing search tool should live at `gograd.ucla.edu/fellowships` (or equivalent) and:

- Use UCLA Shibboleth/SSO for admin access (not needed for the public search page)
- Match UCLA brand colors and typography (blue `#2774AE`, gold `#FFD100`)
- Be embeddable as an iframe in the existing GoGrad portal if a full integration isn't immediately possible
- Include a "Suggest a Fellowship" form so students can submit opportunities they find

---

## 11. API Design (for future integrations)

```
GET  /api/fellowships?q=travel+humanities&season=fall&status=published&page=1
GET  /api/fellowships/{id}
POST /api/fellowships          (admin only)
PUT  /api/fellowships/{id}     (admin only)
DEL  /api/fellowships/{id}     (admin only, soft delete)

GET  /api/review-queue?season=winter    (admin only)
POST /api/review-queue/{task_id}/complete (admin only)
```

---

## 12. Migration Plan

### Phase 0 — Now (Prototype)
- ✅ Working HTML search tool built from current spreadsheet data (360 active fellowships)
- ✅ Keyword search, season filters, Google search links

### Phase 1 — Weeks 1–6: Core System
- Set up Django + PostgreSQL on UCLA infrastructure (or Heroku/Render for a quick start)
- Migrate spreadsheet data into database via import script
- Staff add URLs during first seasonal review cycle
- Public search page live at GoGrad

### Phase 2 — Weeks 7–14: Automation + Quality
- Seasonal scheduler + email digest
- Dead URL detection
- Tags/categorization (funding type, career stage, discipline)
- Advanced filters in the UI (tag-based filtering)

### Phase 3 — Future: Intelligence
- AI-powered "Tell me about yourself" matching: student fills out a short profile (year, department, interests, citizenship) and gets a ranked list of relevant fellowships
- Meilisearch upgrade for better search relevance
- Student-facing email subscriptions ("Notify me when Fall fellowships open")

---

## 13. Trade-Off Analysis

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Django vs. FastAPI | Django | FastAPI | Admin panel is 80% of the value — Django's admin saves weeks of custom UI work |
| PG full-text vs. Meilisearch | PG (Phase 1) | Meilisearch | No new infra; plenty fast for < 2K records |
| Google search links vs. stored URLs | Google links (Phase 1) | Stored URLs | URLs go stale constantly; Google is what staff already do and is more reliable |
| Hard delete vs. soft delete | Soft delete | Hard delete | Matches the "Deleted Programs" tab workflow; allows recovery |
| UCLA hosting vs. cloud | Cloud (Render/Heroku) initially | UCLA servers | Faster to launch; can migrate to UCLA infrastructure after stakeholder approval |

---

## 14. Effort Estimate

| Phase | Work | Estimated Time |
|---|---|---|
| Phase 1 | Django setup, DB migration, search, admin panel | 4–6 weeks (1 developer) |
| Phase 2 | Scheduler, URL health check, tags, advanced filters | 4–6 weeks |
| Phase 3 | AI matching, email subscriptions | 6–10 weeks |

The Phase 1 prototype HTML tool is already built and usable today with no server required.

---

*GRAPES Fellowship Finder — System Design v1.0 | March 17, 2026*
