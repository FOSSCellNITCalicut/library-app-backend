# RAG Book-Recommendation Chatbot — Production Plan (NITC)

## Context

We are replacing the stubbed chatbot page (`lib/chatBotPage.dart`, hardcoded reply
`"nodakke yenu illa backendalli" // TODO`) with a real **RAG chatbot**: the user describes a
need in natural language, and the bot introduces the **best-matching real books from the NITC
catalog**, each linking to its detail page.

This is the **administrator-grade, production version** of the plan. It treats the feature as an
institutional service for ~8,000 NITC users running on **shared, AI-club-owned A100 hardware** — so
it must be safe, private, abuse-resistant, degradable, observable, and a good neighbour on borrowed
GPU. Core design: retrieve-then-generate, catalog-only grounding, **hybrid (keyword + semantic)
retrieval**, JWT auth, provider-agnostic OpenAI-compatible clients, simple request/response.

### Loopholes found in review → how each is closed

| # | Loophole | Resolution |
|---|---|---|
| 1 | **Keyword-only retrieval** misses semantic/descriptive queries | §3 **hybrid FTS + vector search (v1)** |
| 2 | **Regex-parsing `[id]` from prose** is fragile | §4 JSON-constrained output `{reply, biblio_ids[]}` |
| 3 | **No rate limiting** (confirmed absent; flagged in `issues.md`) | §5 Redis token-bucket per roll_no + global A100 concurrency semaphore |
| 4 | **A100 is shared & may vanish** (reclaimed / down) | §6 circuit breaker + graceful fallback to keyword FTS + `CHAT_ENABLED` flag |
| 5 | **Student queries leaving campus** (Groq in prod = data-governance breach) | §7 prod = on-prem only, hard policy; no PII in prompts |
| 6 | **Prompt injection** (direct + indirect via book descriptions) | §8 untrusted-data framing + structured output makes book fabrication impossible |
| 7 | **No observability** — can't see quality/abuse/cost | §9 structured logs + metrics, PII-safe |
| 8 | **No content/scope safety** on an unfiltered on-prem model | §8 scope-locked prompt, decline off-topic, UI disclaimer |
| 9 | **Token/context blowout** from long history/candidates on an 8B window | §5 hard caps; §10 token budget |
| 10 | **No quality regression net** | §11 golden-query eval set + injection suite + load test |

## 1. Production request pipeline (layered, fail-safe)

```
Flutter ChatBotPage
   │ POST /api/v1/chat { message, history[] }   (Bearer JWT)
   ▼
[A] Auth        get_current_user → roll_no (claims["sub"])
[B] Validate    message 1..500 chars; history ≤6 turns, ≤2KB total; reject empty/oversized (400)
[C] Rate limit  Redis token-bucket per roll_no (10 msg/min, 200/day) → 429 + Retry-After
[D] Feature gate  CHAT_ENABLED off → 503 "assistant temporarily unavailable"
[E] Concurrency  global asyncio.Semaphore(N) protects the A100; saturated → 429 fast-fail
   ▼ ChatService
[1] REWRITE     cheap LLM call: prose → 1–3 keyword queries (fallback: raw message)
[2] RETRIEVE    HYBRID: embed query → pgvector ANN (cosine)  ⊕  FTS (websearch_to_tsquery)
                fuse via reciprocal-rank fusion → UNION top-K real books
[3] CONTEXT     numbered candidate list (biblio_id, title, authors, categories, snippet, availability)
[4] GENERATE    one JSON-constrained LLM call → { reply, biblio_ids[] }
[5] GROUND+HYDRATE  keep only ids ∈ retrieved set; build cards from OUR db rows
   ▼
{ reply, books:[{biblio_id,title,authors,cover_url,available_copies,total_copies,detail_path}],
  degraded: false }
```

**Every stage fails safe.** LLM (chat) error/timeout/circuit-open at [1] or [4] → **degraded**
response: return retrieval results directly with a canned reply ("The assistant is resting — here
are matches for '…'") and `degraded: true`. If the **embedding** service is down, retrieval falls
back to keyword FTS alone. The user always gets real books; the conversational + semantic layers are
best-effort on top of the always-available keyword search.

## 2. Backend structure (new `chat` domain + `llm`/`embeddings` integrations + pgvector)

Mirror existing patterns exactly (`app/domains/opac_home/` domain shape,
`app/integrations/google_books/client.py` client shape, `app/workers/enrichment/google_books_worker.py`
scan-worker shape).

- **`app/integrations/llm/client.py`** — OpenAI-compatible **chat** client (raw httpx, no new dep):
  - `chat_completion(messages, *, json_schema=None, temperature=0.2, max_tokens) -> dict|str`;
    when `json_schema` is set, send `response_format` (Groq) / `guided_json` (vLLM) so output is
    schema-valid. Retry once on transient 5xx/timeout; `429`/persistent error → `LLMUnavailableError`.
  - `health()` — cheap `GET /models` (no tokens).
  - In-process **circuit breaker** (open after K failures, half-open probe via `health()`), mirroring
    the circuit-breaker concept in `documentation/redis-caching-strategy.md`.
  - Singleton `llm_client`; added to `clients` in `app/main.py` lifespan for `aclose()`.
- **`app/integrations/embeddings/client.py`** — OpenAI-compatible **embeddings** client:
  - `embed(texts: list[str]) -> list[list[float]]` → POSTs `/embeddings`; batches; retry once.
  - Same circuit-breaker + `health()` pattern; singleton `embeddings_client` closed on shutdown.
- **`app/domains/chat/`**
  - `schemas.py` — `ChatMessage{role,content}`, `ChatRequest{message(1..500), history=[]}`,
    `RecommendedBook{biblio_id,title,authors,cover_url,available_copies,total_copies,detail_path}`,
    `ChatResponse{reply, books[], degraded: bool}`.
  - `service.py` — `ChatService(BookService, llm_client, embeddings_client)`. Owns rewrite, **hybrid
    retrieve**, context build, generate, ground-check+hydrate, and degraded fallback. System prompt
    is a versioned module constant (reviewable).
  - `router.py` — `POST /chat` (JWT + rate-limit + concurrency deps), `GET /chat/health`
    (unauthenticated; reports chat + embedding + vector-index status). Register in `app/api/v1/router.py`.
- **Vector search (pgvector) — the v1 semantic half**
  - **Migration** (`alembic/versions/…`): `CREATE EXTENSION IF NOT EXISTS vector;` + add
    `books.embedding vector(EMBEDDING_DIM)` + an **HNSW** index (`vector_cosine_ops`) +
    `books.embedded_at TIMESTAMPTZ`.
  - **Repository** (`app/domains/books/repository.py`): add `vector_search(embedding, limit)` (cosine
    ANN) and swap `plainto_tsquery` → `websearch_to_tsquery` in `search_books`. Fusion (RRF) lives in
    `ChatService` so both retrievers stay independently testable.
  - **Backfill worker** (`app/workers/enrichment/embedding_worker.py`, mirrors
    `google_books_worker.py`): scan `WHERE embedding IS NULL OR embedded_at < metadata_synced_at`,
    embed `title + authors + categories + description`, `UPDATE` the vector + `embedded_at`. Runs on
    the loop pattern in `app/main.py` lifespan; re-embeds when metadata changes. Handles the ~50k-row
    initial backfill at a Koha-friendly, GPU-friendly rate.
- **`app/core/ratelimit.py`** (new, small) — Redis token-bucket on the existing `app/core/cache.py`
  client (reuse `_client`; `INCR`+`EXPIRE` or Lua). Also reusable for the `/login` brute-force limit
  flagged in `documentation/auth.md`.
- **`app/main.py`** — register `llm_client` + `embeddings_client` in `clients`; start the embedding
  backfill worker; create the global concurrency `Semaphore(LLM_MAX_CONCURRENCY)` at startup.

## 3. Retrieval strategy — hybrid (v1)

Keyword FTS alone misses descriptive queries ("a gentle intro to how computers make decisions"
shares no tokens with *Machine Learning: An Algorithmic Perspective*); vector alone misses exact
title/author/ISBN hits. **v1 does both and fuses:**

1. **Rewrite** the user's prose → 1–3 keyword queries (cheap LLM step; fallback = raw message).
2. **Keyword**: `websearch_to_tsquery` FTS over `search_vector`, ranked by `ts_rank`.
3. **Semantic**: embed the query, pgvector cosine ANN over `books.embedding` (HNSW).
4. **Fuse** the two ranked lists with **reciprocal-rank fusion** (parameter-free, no score
   calibration needed), dedupe, take top-K.
5. Empty fused set → degraded "no matches, try different words", no generate call.

**Embedding model**: `bge-base-en-v1.5` (768-dim; strong English retrieval) as default; **`bge-m3`**
(multilingual, 1024-dim) if we want Malayalam/Hindi query support. Dim is configurable so the model
can change without code edits (only a migration to resize the column).

**v2 upgrades (deferred):** cross-encoder reranker over the fused top-K for precision; per-department
/ borrowing-history personalisation.

## 4. Grounding & structured output (anti-hallucination)

- Model returns **schema-constrained JSON** `{ "reply": str, "biblio_ids": int[] }` — no regex.
- **Ground-check stays** regardless of format: `final = biblio_ids ∩ retrieved_ids`; cards are
  **hydrated from our DB rows**, never from model text. A fabricated title/author/availability
  cannot enter `books[]` — structurally impossible.
- Malformed/refused output → try/except → degraded fallback (retrieval results).
- Low temperature (~0.2). System prompt frames candidates as **untrusted reference data** and forbids
  following any instructions contained inside book descriptions.

## 5. Abuse control & A100 protection

- **Per-user token bucket** (Redis): `10 msg/min` + `200 msg/day` per roll_no → 429 + `Retry-After`.
  Tunable via config.
- **Global concurrency semaphore** caps simultaneous A100 (chat) calls (`LLM_MAX_CONCURRENCY=8`); over
  the cap → immediate 429 rather than unbounded queueing. Protects the shared GPU, bounds p95 latency.
- **Input caps**: message ≤500 chars, history ≤6 turns / ≤2KB, K candidates, ≤300-char snippet each —
  bounds the prompt so it always fits the 8B context window and bounds cost/latency.

## 6. Reliability & degradation

- Timeout `LLM_TIMEOUT_SECONDS` (30s); one retry on transient failure; circuit breaker on repeated
  failure (don't hammer a dead A100).
- **`CHAT_ENABLED` feature flag** (mirrors existing `CACHE_ENABLED`) — hard-disable during A100
  maintenance without a deploy; app greys the chat tab when `/chat/health` is red.
- **Two-level degradation**: (a) embedding service down → retrieval uses keyword FTS only;
  (b) chat model down → return retrieval results with a canned message + `degraded:true`. The feature
  never hard-fails to the user as long as Postgres is up.

## 7. Data governance & privacy (institutional)

- **Production must use the on-prem A100 for BOTH chat and embeddings. Groq/OpenRouter/hosted
  embedding APIs are dev/test only, with synthetic data.** No student query text may leave the NITC
  network in prod. Encode this as README policy and as a startup assertion (warn loudly if
  `LLM_BASE_URL`/`EMBEDDING_BASE_URL` are external while `ENV=prod`).
- **No PII in prompts or embeddings** — never send roll_no, name, or session data; only the message,
  short history, and public catalog data.
- **vLLM / embedding endpoints are network-isolated** — bound to the internal interface / firewalled
  so only the backend can reach them; never publicly exposed (no auth by default).
- **Logging**: hash roll_no in logs; raw query-text logging is opt-in with a short retention window.
  Define a retention policy before launch.

## 8. Safety, scope & prompt-injection

- System prompt is **scope-locked**: only help find NITC library books; politely decline off-topic or
  inappropriate requests; never reveal the system prompt; treat candidate text as data.
- **Injection surface is minimal**: because books come from the ground-check (not model text), the
  worst an injection can do is influence the free-text `reply` — length-capped and scoped.
- **UI disclaimer**: "AI-assisted suggestions — verify availability on the book page." Covers the
  ~30-min availability-cache staleness (live check stays on the detail page).

## 9. Observability

- **Structured logs** (reuse `app/core/logging.py`): request_id, hashed roll_no, latency_ms (split:
  embed / retrieve / generate), token estimates, #retrieved (keyword vs vector), #dropped-by-ground-
  check, degraded flag + reason, outcome. No raw PII.
- **Metrics to watch**: p95 latency, error/timeout rate per service, circuit state, 429 rate,
  empty-retrieval rate, hallucination-drop rate, embedding-backfill coverage (% of catalog embedded).
- `GET /api/v1/chat/health` for uptime monitoring, **separate** from the global `/health`.

## 10. Config (`app/core/config.py`, mirrors the `GOOGLE_BOOKS_*` / `CACHE_ENABLED` blocks)

```
CHAT_ENABLED: bool = True
# Chat model
LLM_BASE_URL: str = "https://api.groq.com/openai/v1"   # PROD: http://<a100-host>:8000/v1
LLM_API_KEY: str | None = None                          # Groq key in dev; unused for local vLLM
LLM_MODEL: str = "llama-3.1-8b-instant"                 # PROD: "Qwen/Qwen3-8B-Instruct"
LLM_TIMEOUT_SECONDS: float = 30.0
LLM_MAX_TOKENS: int = 700
LLM_MAX_CONCURRENCY: int = 8
# Embeddings
EMBEDDING_BASE_URL: str = "http://localhost:8080/v1"    # PROD: http://<a100-host>:8081/v1
EMBEDDING_API_KEY: str | None = None
EMBEDDING_MODEL: str = "BAAI/bge-base-en-v1.5"
EMBEDDING_DIM: int = 768
EMBEDDING_BATCH_SIZE: int = 32
# Retrieval / chat
CHAT_RETRIEVAL_K: int = 8
CHAT_RRF_K: int = 60                                     # reciprocal-rank-fusion constant
CHAT_RATE_PER_MIN: int = 10
CHAT_RATE_PER_DAY: int = 200
CHAT_QUERY_REWRITE: bool = True
```
Add the same keys to `.env.example`, with prod-vs-dev values documented.

## 11. Testing & evaluation framework

- **Unit** (`app/tests/domains/chat/test_service.py`): ground-check drops non-candidate ids;
  malformed JSON → degraded; empty retrieval → no generate call; RRF fusion ordering; rate-limit → 429;
  circuit-open → degraded; embedding-down → keyword-only retrieval.
- **Prompt-injection suite**: adversarial messages and a poisoned candidate description assert no
  fabricated books and no scope escape.
- **Golden-query eval set**: ~30 curated NITC queries → expected relevant biblio_ids; measure
  retrieval hit-rate for keyword-only vs vector-only vs hybrid to prove the fusion earns its keep.
- **Load test**: ramp concurrent /chat calls against the A100 to size `LLM_MAX_CONCURRENCY`; and a
  backfill dry-run to confirm the embedding worker clears the catalog at an acceptable rate.

## 12. Frontend (Flutter)

- `lib/services/chatbot_service.dart` (new) — `sendChat(message, history, accessToken)` via
  `http.post`, mirroring `user_provider.dart` Bearer pattern; parse `ChatResponse`.
- `lib/models/chat_models.dart` (new) — `ChatMessage`, `RecommendedBook`, `ChatResponse` (+`degraded`).
- `lib/chatBotPage.dart` — replace stub: read `AuthProvider.accessToken`, loading bubble, render
  reply + tappable book cards → existing detail page via `biblio_id`. Handle not-logged-in, 429
  ("slow down"), degraded banner, and `/chat/health`-driven disabled state. Show the AI disclaimer.

## 13. Model hosting / ops (A100)

- **Chat**: vLLM `vllm serve Qwen/Qwen3-8B-Instruct --port 8000` → OpenAI-compatible `/v1`.
- **Embeddings**: HuggingFace **Text-Embeddings-Inference (TEI)** serving `bge-base-en-v1.5` on a
  second port (`/v1/embeddings`), or vLLM in embedding mode. Both are tiny beside the 8B — comfortably
  co-resident on one A100.
- Bind both to the internal interface + firewall; never public.
- Prod `.env`: `LLM_BASE_URL=http://<a100-host>:8000/v1`, `EMBEDDING_BASE_URL=http://<a100-host>:8081/v1`,
  models set accordingly. Dev without GPU: chat → Groq; embeddings → local TEI on CPU (`bge-base` runs
  fine on CPU for dev volumes) or a hosted embeddings API — synthetic data only.

## 14. Phased rollout

1. **v1 behind `CHAT_ENABLED`**: run the embedding backfill worker to full catalog coverage, then
   dev-test on Groq + local embeddings, then point at the A100.
2. **Canary**: enable for a small beta cohort; watch §9 metrics + eval set.
3. **GA** once p95 latency, error rate, hallucination-drop rate, and backfill coverage are within target.
4. **v2**: cross-encoder reranker + personalisation, measured against the golden set.

## 15. Verification

1. Unit + injection + eval suites green (§11); hybrid beats keyword-only and vector-only on the golden set.
2. Backfill: `books.embedding` populated for the catalog; HNSW index present; `embedded_at` tracks metadata updates.
3. Dev smoke: `curl -H "Authorization: Bearer <t>" -d '{"message":"intro to machine learning"}' .../api/v1/chat` → real biblio_ids, sensible reply; `/chat/health` ok; `/docs` shows the routes.
4. Grounding: every returned `biblio_id` resolves via `GET /api/v1/books/{id}` (no 404).
5. Abuse: exceed per-min bucket → 429 + Retry-After; saturate concurrency → 429.
6. Degradation: kill embeddings → keyword-only results; kill chat model → `degraded:true` with real books (no 500); `CHAT_ENABLED=false` → 503 + app greys the tab.
7. App: log in, describe a need, tap a book card → detail page; verify disclaimer + graceful errors.

## 16. Out of scope (v1)

Streaming/typing UI; cross-session conversation persistence; cross-encoder reranker (v2);
recommendation personalisation (v2); the other 3 hardcoded base-URL cleanups on the app side.
