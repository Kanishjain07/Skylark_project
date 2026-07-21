# Skylark — Monday.com Business Intelligence Agent

A conversational AI agent that answers founder-level business questions by
reading **live data** from two monday.com boards (Work Orders + Deals),
cleaning messy real-world data on the fly, and returning insights — not just
raw numbers.

> Ask _"How's our pipeline looking for the energy sector this quarter?"_ and get
> a clean, sourced answer with data-quality caveats.

---

## Architecture

```
┌─────────────────────┐      HTTPS       ┌──────────────────────────────┐
│  Frontend (React)   │  ───────────────▶│  Backend (FastAPI, Python)   │
│  minimalist chat UI │                  │                              │
│  /api/chat          │◀───────────────  │  /chat  /leadership-update   │
└─────────────────────┘   reply + data   │  /health                     │
                          quality         │                              │
                                          │  ┌────────────────────────┐  │
                                          │  │ Gemini agent           │  │
                                          │  │ (function calling)     │  │
                                          │  └───────────┬────────────┘  │
                                          │    get_deals │ get_work_orders│
                                          │  ┌───────────▼────────────┐  │
                                          │  │ Data cleaning layer    │  │
                                          │  │ dates/numbers/labels/  │  │
                                          │  │ nulls + quality report │  │
                                          │  └───────────┬────────────┘  │
                                          │  ┌───────────▼────────────┐  │
                                          │  │ monday.com GraphQL     │  │
                                          │  │ client (read-only)     │  │
                                          │  └────────────────────────┘  │
                                          └──────────────┬───────────────┘
                                                         │ GraphQL API v2
                                                  ┌──────▼───────┐
                                                  │  monday.com  │
                                                  │  2 boards    │
                                                  └──────────────┘
```

**How a question flows:** the React UI sends the conversation to `/chat`. The
Gemini agent decides which board(s) it needs and calls `get_deals` /
`get_work_orders`. Those tools fetch **live** data from monday.com's GraphQL API,
run it through the cleaning layer (normalizing dates, numbers, labels, nulls and
producing a data-quality report), and return it to the model. Gemini reasons
over the cleaned records and replies with an insight plus caveats.

### Tech choices (justification)
- **Python + FastAPI** — async-native (efficient concurrent monday.com +
  Gemini calls), typed request/response models, auto OpenAPI docs at `/docs`.
- **Google Gemini + function calling** — the model pulls data only when needed,
  keeping answers grounded in live board data instead of hallucinated numbers.
- **React (JS) + Vite** — fast, componentized chat UI, trivial to host.
- **Cleaning in the backend, not the model** — deterministic, testable
  normalization; the model gets trustworthy data and an explicit quality report.

---

## Project layout

```
exam/
├── backend/                 # Python FastAPI service
│   ├── app/
│   │   ├── main.py          # FastAPI app: /chat, /leadership-update, /health
│   │   ├── agent.py         # Gemini agent + function-calling loop
│   │   ├── data_service.py  # fetch + clean orchestration
│   │   ├── data_cleaning.py # messy-data normalization + quality report
│   │   ├── monday_client.py # monday.com GraphQL client (read-only, paginated)
│   │   └── config.py        # env-based settings
│   ├── requirements.txt
│   └── .env.example
└── frontend/                # React (Vite) chat UI
    ├── src/
    │   ├── App.jsx
    │   ├── api.js
    │   └── components/      # Message, Composer, DataQuality
    └── package.json
```

---

## Setup

### 1. Import the CSVs into monday.com
1. Create two boards from the provided files:
   - **Work Orders** — from `Work_Order_Tracker Data.csv`
   - **Deals** — from `Deal funnel Data.csv`
2. When importing, let monday.com map columns; set obvious types where you can
   (dates → Date, amounts → Numbers, sector/stage/status → Status/Dropdown).
   The cleaning layer is tolerant of Text columns too, so exact types are not
   required.
3. Grab each board's ID from its URL: `monday.com/boards/<BOARD_ID>`.

### 2. Get API credentials
- **monday.com token:** Avatar → Developers → My Access Tokens.
- **Gemini API key:** https://aistudio.google.com/app/apikey

### 3. Run the backend
```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then edit .env with your real values
uvicorn app.main:app --reload --port 8000
```
Verify config + live connection: open http://localhost:8000/health

### 4. Run the frontend
```bash
cd frontend
npm install
npm run dev
```
Open http://localhost:5173. The Vite dev server proxies `/api` → `http://localhost:8000`.

For production, set `VITE_API_BASE` to the deployed backend URL at build time.

---

## Endpoints

| Method | Path                  | Purpose                                            |
|--------|-----------------------|----------------------------------------------------|
| POST   | `/chat`               | `{ messages: [{role, content}] }` → agent reply    |
| POST   | `/leadership-update`  | One-click board-ready executive digest             |
| GET    | `/health`             | Config + live monday.com connectivity check        |

---

## Data resilience (how "messy data" is handled)

- **Dates:** parses `01/02/2024`, `Feb 1 2024`, `2024-03-05`, `15/06/2024`, etc.
  Day-first is auto-detected when the first component is > 12. Unparseable
  dates become `null` and are counted in the quality report.
- **Numbers:** strips `$`, commas, `%`, and expands `1.2k` / `2M`.
- **Labels:** merges case/whitespace variants (`ENERGY`, `energy`, `Energy `→
  `Energy`).
- **Nulls:** common tokens (`N/A`, `-`, `TBD`, `unknown`, blanks) → `null`.
- **Quality report:** every answer can surface completeness %, and which fields
  have gaps — shown to the user as a caveat under the answer.

---

## Notes / limitations
- monday.com access is **read-only** by design.
- Board data is cached in-process for `BOARD_CACHE_TTL_SECONDS` (default 120s)
  to reduce API calls; the agent still queries dynamically (no hardcoded CSV).
- See `DECISION_LOG.md` for assumptions, trade-offs, and the "leadership
  updates" interpretation.
