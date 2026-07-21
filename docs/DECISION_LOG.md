# Decision Log — Skylark Monday.com BI Agent

_A conversational agent that answers founder-level questions from two live
monday.com boards (Work Orders + Deals), cleaning messy data on the fly and
returning sourced insight with data-quality caveats._

---

## 1. Key assumptions

- **The boards are the source of truth, not the CSVs.** The task shipped CSV
  exports, but the requirement was a *live* monday.com integration. I import the
  CSVs into monday.com and query the GraphQL API v2 at request time. Nothing is
  hardcoded from the CSVs.
- **Read-only is sufficient.** Founders want to *understand* the business, not
  mutate boards. The monday.com client only reads (with pagination), which also
  removes any risk of the agent corrupting real data.
- **Column types are unreliable.** Real imports leave dates, amounts, and
  categories as free text with inconsistent casing, `$`/`%`/`k`/`M` formatting,
  and null tokens (`N/A`, `-`, `TBD`). I assumed *every* field is potentially
  dirty and built a deterministic cleaning layer rather than trusting the schema.
- **Accuracy matters more than the model doing math.** I assumed an LLM asked to
  sum hundreds of rows will drift. So Python computes all aggregates; the model
  only interprets pre-computed summaries.
- **"Two boards, known shape" — but tolerant.** Deals ≈ pipeline (value, stage,
  sector); Work Orders ≈ execution (status). The analytics layer auto-detects
  numeric vs. label columns instead of hardcoding column names, so it survives
  renamed columns.
- **Small scale.** Board sizes are in the hundreds of rows, so a 120s in-process
  cache and per-request re-aggregation are fine; no database is warranted.

---

## 2. Trade-offs chosen (and why)

| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| **Number crunching** | Python computes aggregates; LLM interprets | Feed raw rows to the LLM | Deterministic, auditable, and keeps the payload well under Groq's tokens-per-minute limit. Trades some flexibility for trustworthy numbers. |
| **Grounding** | Function-calling tools (`deals_summary`, `work_orders_summary`, `get_examples`) | Single prompt with all data | The model pulls only the board(s) it needs, so answers stay grounded and cheap. Costs an extra round-trip per question. |
| **Cleaning location** | Backend, before the model | Ask the model to normalize | Testable, repeatable normalization + an explicit quality report. More code, but no silent hallucinated fixes. |
| **LLM provider** | **Groq** (OpenAI-compatible API, `openai/gpt-oss-120b`) | Hosted GPT-4-class / Gemini | Fast and low-cost for interpretation-only work; OpenAI-compatible SDK keeps it swappable. _Note: README still says "Gemini" — that is stale doc drift; the code uses Groq._ |
| **Caching** | 120s in-process TTL | Persistent store / no cache | Cuts monday.com calls during a chat session with near-zero infra. Doesn't survive serverless cold starts — acceptable at this scale. |
| **Frontend** | React + Vite, same-origin `/api` | SSR / Next.js | Trivial static host, fast dev proxy, no framework overhead for a single chat view. |
| **Deploy** | One same-origin Vercel project (static build + Python function) | Two services / container host | Simplest path to a shareable URL; no CORS. Bound by Vercel's 60s function limit on slow LLM calls. |

---

## 3. How I interpreted "leadership updates"

The brief listed "help prepare data for leadership updates" as an optional
capability. I read it as: **founders should get a board-ready executive digest
in one click, without having to ask the right questions.**

So `/leadership-update` (POST) drives the same agent with a fixed, structured
prompt that:

1. Pulls **both** boards first (deals + work orders).
2. Produces a fixed briefing shape:
   **Headline** → **Pipeline & Revenue** (total value, top sectors by value, win
   rate, stage concentration, risks) → **Operations** (work-order status) →
   **Data caveats** (real completeness figures + which key fields, e.g. close
   dates, are mostly missing).
3. Is **strictly grounded**: the prompt forbids inventing sectors, stages, or
   numbers, and forbids fabricating time buckets the data can't support — it must
   use only figures/labels returned by the tools (`headline_metrics`).

The design intent: a leadership update that a founder can paste into a board
email verbatim, where every number is traceable and its gaps are stated
honestly rather than glossed over.

---

## 4. What I'd do differently with more time

- **Fix the doc drift**: update the README + architecture diagram from "Gemini"
  to Groq, since the code and config are the real contract.
- **Automated tests** for the cleaning layer (date day-first detection,
  `k`/`M` expansion, label merging) and analytics (win rate, sector ranking) —
  the highest-value, most regression-prone code.
- **Streaming responses** (SSE) so long agent turns feel responsive instead of
  waiting on one blocking call — especially important under Vercel's 60s cap.
- **Persistent/shared cache** (e.g. Vercel KV) so cold starts don't re-fetch, and
  add rate-limit/back-off handling around the monday.com and Groq calls.
- **Trend awareness**: the data lacks reliable close dates, so "this quarter"
  questions are weak. I'd detect that gap explicitly and, where dates exist,
  compute period-over-period movement instead of point-in-time only.
- **Auth + audit**: even read-only, a real leadership tool needs login and a log
  of who asked what.
- **Config hardening**: pin the Python version, add a `/ready` vs `/health`
  split, and surface partial-data warnings as structured fields, not just prose.

---

_See `README.md` for setup and architecture; `vercel.json` + `api/index.py` for
the production deployment._
