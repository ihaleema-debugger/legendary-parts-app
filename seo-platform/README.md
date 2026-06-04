# SEO Platform — KeyGap + Inkwell

A unified SEO intelligence platform built for **Legendary Parts** (legendary-parts.com).

**KeyGap** identifies keyword gaps by crawling competitors, extracting keywords, enriching with Semrush data, and comparing against your site's index. **Inkwell** turns those gaps into published content using multi-LLM writing with SEO validation and plagiarism checking. The **Admin Panel** provides user management, API key vault, billing tracking, job monitoring, and audit logging.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    NGINX (SSL)                       │
├──────────────┬──────────────┬───────────────────────┤
│   Frontend   │   REST API   │      WebSocket        │
│   React SPA  │   FastAPI    │   (crawl + write)     │
├──────────────┴──────────────┴───────────────────────┤
│              Celery Workers (Redis)                  │
│   crawl │ research │ write │ validate │ plagiarism   │
├─────────────────────────────────────────────────────┤
│                 PostgreSQL 16                        │
│   users │ projects │ keywords │ briefs │ audit_log   │
└─────────────────────────────────────────────────────┘
```

**Three Pillars:**

| Pillar | What it covers |
|--------|---------------|
| **Backend** | FastAPI, Celery workers, auth (JWT + RBAC), all business logic |
| **Frontend** | React 18 + TypeScript, CMS-style dashboard, TipTap editor |
| **Admin** | User management, API key vault, job queue, billing, audit log |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy, Celery |
| Frontend | React 18, TypeScript, Tailwind CSS, TipTap, Recharts |
| Database | PostgreSQL 16 |
| Cache/Queue | Redis 7 |
| Crawler | Scrapy + Playwright |
| NLP | spaCy + TF-IDF |
| SEO Data | Semrush API |
| LLM Gateway | LiteLLM (Claude, GPT, Gemini, Mistral) |
| Research | SerpAPI + Playwright |
| Plagiarism | Copyscape + MinHash |
| Auth | JWT + bcrypt, role-based (admin/editor/viewer) |
| Deployment | Docker Compose, Nginx, Let's Encrypt |
| CI/CD | GitHub Actions |

---

## Directory Structure

```
seo-platform/
├── docker-compose.yml
├── .env.example
├── .github/workflows/deploy.yml
├── nginx/nginx.conf
│
├── database/
│   └── init.sql              # Full schema (runs on first startup)
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/env.py
│   └── app/
│       ├── main.py           # FastAPI entry point
│       ├── config.py          # Pydantic settings
│       ├── database.py        # Async SQLAlchemy engine
│       ├── models/            # SQLAlchemy ORM models
│       ├── schemas/           # Pydantic request/response schemas
│       ├── middleware/
│       │   ├── auth.py        # JWT, password hashing, role guards
│       │   └── audit.py       # Audit log service
│       ├── api/
│       │   ├── shared/        # Auth, dashboard, health, bridge
│       │   ├── keygap/        # Projects, crawls, keywords, gaps
│       │   ├── inkwell/       # Briefs, pipeline, sections, export
│       │   └── admin/         # Users, API keys, jobs, billing, audit, settings
│       └── tasks/
│           ├── worker.py      # Celery config + beat schedule
│           └── __init__.py    # Task stubs (crawl, research, write, etc.)
│
└── frontend/
    ├── Dockerfile
    ├── package.json
    ├── vite.config.ts
    ├── tailwind.config.js
    ├── index.html
    └── src/
        ├── main.tsx           # App entry + all routes
        ├── styles/globals.css
        ├── api/client.ts      # Typed API client with auto-refresh
        ├── stores/
        │   ├── auth.ts        # Zustand auth store
        │   └── theme.ts       # Dark/light + sidebar state
        ├── guards/index.tsx   # AuthGuard, AdminGuard
        ├── components/layout/AppLayout.tsx  # Sidebar + header
        └── pages/
            ├── shared/        # Login, Dashboard
            ├── keygap/        # Projects, Crawls, Keywords, Gaps, SiteIndex
            ├── inkwell/       # Briefs, Editor, Library
            └── admin/         # Users, ApiKeys, Jobs, Billing, Audit, Database, Settings
```

---

## Quick Start (Local Development)

### Prerequisites
- Docker & Docker Compose V2
- Node.js 20+ (for frontend dev)
- Python 3.12+ (for backend dev)

### 1. Clone and configure

```bash
git clone git@github.com:YOUR_USERNAME/seo-platform.git
cd seo-platform
cp .env.example .env
# Edit .env with your API keys and passwords
```

### 2. Start everything

```bash
docker compose up -d
```

This starts PostgreSQL, Redis, the API, Celery worker/beat, and Nginx.

The database is initialised automatically from `database/init.sql` on first run.

A default admin user is created from `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` in `.env`.

### 3. Frontend development

```bash
cd frontend
npm install
npm run dev
```

Vite runs on `http://localhost:5173` and proxies API requests to `http://localhost:8000`.

### 4. Backend development

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs: `http://localhost:8000/api/docs`

---

## User Roles

| Role | KeyGap | Inkwell | Admin Panel |
|------|--------|---------|-------------|
| **Admin** | Full access | Full access | Full access |
| **Editor** | Full access | Create/edit/publish | No access |
| **Viewer** | Read-only, export | Read-only, export | No access |

---

## Admin Panel

Accessible at `/admin/*` routes (admin role only):

- **User Management** — invite, assign roles, deactivate, reset passwords
- **API Key Vault** — encrypted storage, rotate, deactivate (AES-256)
- **Job Queue Monitor** — view, retry, kill Celery jobs
- **Billing & Usage** — per-service, per-user, per-module cost breakdown
- **Audit Log** — every significant action logged with user, resource, IP
- **Database Management** — manual backups, prune stale data
- **System Settings** — crawl defaults, LLM model, thresholds, cache TTL

---

## API Endpoints

### Auth
| Method | Endpoint | Description |
|--------|---------|-------------|
| POST | `/api/auth/login` | Login (returns JWT) |
| POST | `/api/auth/register` | Register user |
| POST | `/api/auth/refresh` | Refresh access token |
| GET | `/api/auth/me` | Current user profile |

### KeyGap
| Method | Endpoint | Description |
|--------|---------|-------------|
| CRUD | `/api/projects` | Analysis projects |
| POST | `/api/crawls` | Start crawl job |
| GET | `/api/keywords` | Browse keywords |
| GET/POST | `/api/gaps/:project_id` | Gap results |
| POST | `/api/index/refresh` | Re-index main site |

### Inkwell
| Method | Endpoint | Description |
|--------|---------|-------------|
| CRUD | `/api/briefs` | Content briefs |
| POST | `/api/briefs/:id/research` | Start research |
| POST | `/api/briefs/:id/write` | Start writing |
| POST | `/api/sections/:id/revise` | Revise section |
| POST | `/api/briefs/:id/validate` | SEO validation |

### Bridge
| Method | Endpoint | Description |
|--------|---------|-------------|
| POST | `/api/gaps/:id/create-brief` | Gap → Inkwell brief |

### Admin (`/api/admin/*`)
User CRUD, API key vault, usage stats, audit log, job management, system settings, database ops.

---

## Deployment

### VPS Setup

1. Provision: 4 vCPU, 8 GB RAM, 160 GB SSD (Hetzner/DigitalOcean, ~$25/mo)
2. Create `deploy` user, disable root SSH, configure UFW
3. Install Docker
4. Point DNS: `seo.legendary-parts.com` → server IP
5. Install SSL: `certbot certonly --standalone -d seo.legendary-parts.com`

### CI/CD

Push to `main` triggers GitHub Actions:
1. Lint + type check + test
2. SSH into VPS → pull code → write `.env` → `docker compose up -d`
3. Run Alembic migrations → health check

### Rollback

```bash
ssh seo-platform
cd /home/deploy/apps/seo-platform
git log --oneline -5
git checkout HEAD~1
docker compose build && docker compose up -d
```

---

## Development Phases (16 weeks)

| Phase | Weeks | Focus |
|-------|-------|-------|
| 1 | 1–3 | Foundation + Auth + Admin shell |
| 2 | 4–5 | KeyGap crawl engine |
| 3 | 6–7 | KeyGap NLP + Semrush |
| 4 | 8–9 | KeyGap gap analysis + Inkwell research |
| 5 | 10–11 | Inkwell writing pipeline |
| 6 | 12–13 | Inkwell validation + plagiarism |
| 7 | 14–15 | Integration + admin completion |
| 8 | 16 | Polish + ship |

---

## License

Proprietary — Legendary Parts. All rights reserved.
