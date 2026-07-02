# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

(To be filled by the team)

---

## Forbidden Patterns

<!-- Patterns that should never be used and why -->

(To be filled by the team)

---

## Required Patterns

<!-- Patterns that must always be used -->

(To be filled by the team)

---

## Testing Requirements

<!-- What level of testing is expected -->

(To be filled by the team)

---

## Code Review Checklist

<!-- What reviewers should check -->

(To be filled by the team)

---

## Scenario: Local Web Collection and RSS Contracts

### 1. Scope / Trigger
- Trigger: changes that add or modify the local Flask web UI, collection API, or RSS feed routes.
- Applies to `web.py`, `src/web/`, `src/services/rss_service.py`, and `src/core/conference_catalog.py`.

### 2. Signatures
- Command: `uv run python web.py --config config.yaml --host 0.0.0.0 --port 5000`
- Command alias: `uv run pc-web --config config.yaml --host 0.0.0.0 --port 5000`
- Command alias: `uv run pc-collect --config config.yaml`
- Command alias: `uv run pc-index --config config.yaml`
- Command alias: `uv run pc-search "<query>" --mode <agentic|concept|keyword> --top_k <n>`
- API: `GET /api/options`
- API: `POST /api/collect`
- API: `GET /api/jobs/<job_id>`
- API: `POST /api/jobs/<job_id>/stop`
- API: `GET /api/feeds`
- RSS: `GET /feed/<conference>/<year>.xml`
- Catalog parser: `normalize_conferences(config) -> list[ConferenceEntry]`
- Catalog lookup: `find_conference(config, value) -> ConferenceEntry | None`
- Catalog categories: `catalog_categories(config) -> list[dict]`
- Focus options: `focus_tag_options(config) -> list[dict]`
- Search API: `GET /api/search?q=<query>&mode=<agentic|keyword|concept>&category=<sub>&focus=<tag>&ccf=<A|B|C|N>&conference=<id>&conference=<id>&year=<year>&limit=<n>`
- Vector status API: `GET /api/index/status`
- Vector build API: `POST /api/index`
- Config: `url_base` optional path prefix such as `/papercollect`.
- Config: `job_store_dir` optional path for JSON-backed web job status and lock files; default is `<output_dir>/jobs`.

### 3. Contracts
- `POST /api/collect` request fields:
  - `conference`: string id or alias, must resolve through `find_conference`; keep this legacy single-conference field working.
  - `conferences`: optional array of string ids or aliases for batch collection; when present, validate every item through `find_conference`, ignore duplicates by normalized conference id, and reject an empty resulting selection.
  - `year`: integer, must pass `valid_collection_year`; it does not need to be present in `config.yaml` `years`.
  - `tasks`: optional array of explicit `{conference|conference_id, year}` objects for non-rectangular queues such as per-conference missing-year collection. When present, validate every conference through `find_conference`, validate every year through `valid_collection_year`, de-duplicate by normalized `(conference_id, year)`, and build exactly those queue items instead of the `conferences x years` cross product.
  - `limit`: optional non-negative integer; empty means `limit_per_conference`.
- Conference catalog fields:
  - `id`: lowercase stable slug for filenames, RSS paths, and API values.
  - `display_name`: human-readable UI/feed title.
  - `full_name`: optional descriptive title.
  - `dblp_stream`: preferred authoritative DBLP stream key such as `conf/icse`.
  - `aliases`: optional accepted inputs and legacy output-file fallback names.
  - `category`, `tier`, `enabled`, `years`: optional metadata/filtering fields.
  - `focus_tags`: optional project-specific tags; supported values include `cloud_security`, `cloud_native`, `distributed_systems`, `software_engineering`, and `security`.
- Bundled CCFDDL catalog:
  - Local file: `src/data/ccf_conferences.yaml`.
  - Enabled by default through `include_ccfddl_catalog: true`.
  - Local `config.yaml` entries override bundled entries by `id`/alias, but missing rank/category metadata should be merged from the bundled entry.
- Search response:
  - `results`: list of saved paper matches with `title`, `authors`, `venue`, `year`, `abstract`, `url`, `score`, `conference`, `display_name`, and `category`.
  - Results should include `tier` and `focus_tags` when the conference has them.
  - `mode=keyword` uses local exact/token scoring over saved JSON.
  - `mode=concept` uses local expanded BM25 over saved JSON plus SemRank-lite concept reranking; it must not require embeddings, external vector stores, or `OPENAI_API_KEY`.
  - `mode=agentic` uses the Qdrant hybrid vector index when available: named dense and sparse vectors are queried independently, then fused with reciprocal-rank fusion. If the index is missing or unavailable, it must fall back to `mode=concept` and include `fallback_reason`/`score_details` in each result.
  - Agentic search must merge strong concept-search candidates into the final reranked result set, not only boost Qdrant-returned candidates, so a relevant title/topic match is not lost when vector prefetch misses it.
  - `mode=vector` is accepted by the Web API/CLI as an alias for `agentic`.
  - Concept results include `matched_concepts`, `concept_score`, `lexical_score`, and `search_mode`.
  - Agentic results include `retrieval_backend`, `score_details`, `provenance`, and `snippet`.
  - Search uses saved JSON files and rebuildable local indexes only; it must not require `OPENAI_API_KEY`.
  - Search may receive repeated `conference` parameters or comma-separated `conference`/`conferences` values; all provided conferences must resolve through `find_conference`.
  - Search supports `ccf`/`tier` filtering against `ConferenceEntry.tier["ccf"]`, including non-CCF `N` entries from the CCFDDL catalog.
  - Search should suppress non-paper metadata entries such as proceedings, poster records, chair messages, keynote/front-matter entries, and student/dissertation abstracts.
  - Concept search must treat title/topic matches as stronger than incidental abstract mentions; a paper that only mentions a query concept once in an abstract example should not rank as a topic match.
  - Four-digit years typed in the query, such as `kubernetes 2026`, should be treated as a year filter and removed from scoring tokens.
- Vector index:
  - `uv run pc-index` builds a rebuildable Qdrant index from `data/*.json`; JSON files remain the source of truth.
  - `POST /api/index` starts a background vector rebuild job and returns `job_id` plus `status_url`; job status is read through `GET /api/jobs/<job_id>`.
  - The default local index path is `data/qdrant/`; it must be ignored by git.
  - Index payloads must preserve stable paper IDs, conference, display name, year, category, CCF tier, focus tags, DBLP key, URL, source file, and source index.
  - Qdrant HTTP/server mode should use a configurable request timeout because collection creation and large upserts can exceed short client defaults.
  - `sparse_model: hash` means dense embeddings come from FastEmbed while the sparse side is a local lexical hash vector; use this as the production-safe default on small CPU hosts.
  - FastEmbed providers should be cached per process by model/cache/thread config so Web search does not reload embedding models on every request.
  - Web background jobs must store status in `job_store_dir` and use file locks for collection/index mutual exclusion so gunicorn workers can read each other's job status and avoid duplicate heavy jobs.
  - Web-triggered index rebuilds should run `pc-index` in a subprocess instead of calling the index builder inside the request worker process; the Web process records subprocess output to the job log and refreshes status after completion.
  - Unit tests must use deterministic hash embeddings or a mocked provider, never download FastEmbed/HuggingFace models.
- CLI search:
  - `uv run pc-search` must call the same `search_saved_papers` implementation as the Web API.
  - Default CLI mode is `agentic`; it must not require `OPENAI_API_KEY` and must fall back to concept search if no vector index exists.
  - Legacy CLI mode values `search` and `ask` are accepted as aliases for `concept` to avoid breaking older commands, but they must not use the old OpenAI RAG path.
- Saved data tracking:
  - Track collected paper data as `data/*.json` so RSS/search state can be synchronized with git.
  - Do not track `data/qdrant/`, `data/vector/`, `data/embeddings.pkl`, temporary files, or other generated caches; concept search must not depend on them.
- Collection response:
  - Success: HTTP 202 with `job_id` and `status_url`.
  - Validation failure: HTTP 400 with `error`.
  - Existing running job: HTTP 409 with `error`.
  - Stop: `POST /api/jobs/<job_id>/stop` marks a queued/running collection job with `cancel_requested=true`; the worker stops cooperatively before starting the next conference and marks the job `cancelled`.
- Collect UI selection controls:
  - `Select shown` replaces the current collect-conference selection with exactly the conferences visible under the current category/focus/CCF filters, then selects all configured years for those visible conferences.
  - `Missing only` does not filter the conference list. It changes the selected year chips to years reported as missing for the currently selected conferences, or for the currently visible conferences if no conference is selected, and it submits explicit `{conference, year}` tasks for each missing conference/year pair.
  - Collect preview must describe the exact conference x year queue that will be submitted to `/api/collect`; do not label the preview as "missing tasks" unless the submitted payload is also restricted to those exact missing conference/year pairs.
  - Async `/api/year-progress` refreshes must not overwrite a year selection made by a user action such as `Select shown`, `Missing only`, manual year chip toggles, or custom year add.
- DBLP search collection:
  - DBLP search requests must paginate with `f` until all hits are read according to DBLP `@total`, `@sent`, and `@first`; do not treat a single page as the full result set.
  - Use a conservative DBLP search page size that the service reliably accepts; large `h` values may be capped or disconnected by DBLP and must not be confused with completion.
  - If any DBLP search page after the first page fails, raise a collection error instead of returning the already-fetched partial page set. A partial DBLP search result must not be written as a successful complete conference/year file.
  - Do not treat the DBLP single-page size as the total per-conference paper limit.
  - Command alias: `uv run pc-backfill-limited --config config.yaml --metadata none --search-page-delay 5` backfills known previously-limited conference/year files with `limit=0`, preserves existing entries, writes `backfill_limited_status.json`, and uses a slower DBLP page delay by default to avoid rate-limit truncation.
  - Command alias: `uv run pc-backfill-metadata --config config.yaml --source-set openalex --max-papers 500` backfills missing `abstract` and `citation_count` fields in already-saved paper JSON files. It must process only incomplete records, save after each chunk, preserve existing paper rows, append status to `backfill_metadata_status.json`, and support repeated runs until the remaining missing count reaches zero.
  - Use `uv run python backfill_limited_papers.py ...` when validating local source edits before the console script has been rebuilt.
  - If a configured DBLP stream has no TOC XML yet or the TOC request fails, collection should try a venue-name DBLP search fallback before giving up.
  - DBLP `conf/nips` TOC volumes use `neurips<year>.xml` for modern NeurIPS years; do not derive `nips<year>.xml` blindly.
  - NeurIPS should use the official proceedings page as a fallback source because DBLP can lag or omit current-year main-conference TOC data.
- Job response fields:
  - `id`, `status`, `conference`, `display_name`, `year`, `limit`, `logs`, `feed_url`.
  - Batch jobs also include `conferences`, `display_names`, `conference_count`, `completed_count`, `failed_count`, `results`, `errors`, and `feed_urls`.
  - Cancelled collection jobs include `cancel_requested: true`, `status: cancelled`, `stopped_count`, and any partial `results`/`feed_urls` already saved before the stop request took effect.
  - `logs` must be incrementally visible while a job is still `queued` or `running`; do not buffer all stdout until completion.
  - Completed single-conference jobs include `paper_count` and `output_path`; completed batch jobs include total `paper_count` plus per-conference `results` and `output_paths`.
  - Batch collection should run selected conferences sequentially inside one background job. If one conference fails, record it in `errors`, continue the remaining conferences, and complete the job when at least one selected conference produced saved output.
  - Failed jobs include `error`.
- RSS response:
  - Success: HTTP 200, `application/rss+xml`, RSS 2.0 XML.
  - No saved JSON data: HTTP 404.
- Feeds response:
  - `GET /api/feeds` must only include saved conference/year JSON files that contain at least one paper.
  - Empty saved JSON files (`[]`) must not appear as RSS feeds with `paper_count: 0`.
  - Any web collection path that writes or changes saved paper JSON must invalidate the feeds and year-progress caches for that `output_dir` before the UI refreshes `/api/feeds` or `/api/year-progress`.
- URL base response/link behavior:
  - Empty or `/` `url_base` means root-path behavior.
  - Non-empty `url_base` must be a path prefix, not a full URL.
  - Frontend API fetches, static assets, `status_url`, and RSS `feed_url` must include the configured prefix.
  - Prefixed routes such as `/papercollect/api/options` and root routes such as `/api/options` should both remain available for local and reverse-proxy compatibility.

### 4. Validation & Error Matrix
- Conference missing or not configured -> 400.
- `conferences` is present but empty, not an array/string, or resolves to no known entries -> 400.
- Year missing, non-integer, before 1900, or more than two years ahead of the current year -> 400.
- Limit non-integer or negative -> 400.
- Second collection request while one is running -> 409.
- Second vector index request while one is running -> 409.
- DBLP network/API failure during collection -> job status `failed`; never convert the failure into an empty paper list.
- Missing saved JSON for RSS -> 404.
- Invalid search conference -> 400.
- Invalid search CCF tier -> 400.
- Search mode other than `keyword`, `concept`, `agentic`, or alias `vector` -> 400.
- Search limit outside 1..100 -> 400.
- Full URL in `url_base` -> app construction error; use a path prefix such as `/papercollect`.

### 5. Good/Base/Bad Cases
- Good: configured `ICSE` and `2025` with saved JSON returns RSS items.
- Base: valid collection request starts a background job and returns a status URL.
- Batch: valid `conferences=["icse","fse"]` request starts one background job that processes the two conferences sequentially and exposes per-conference `results`/`errors`.
- Bad: unknown conference is rejected before any network collection starts.
- Legacy: string-only `conferences: ["ICSE"]` still normalizes to `id="icse"` and `dblp_stream="conf/icse"`.
- Search: query `fuzzing` with category `SE` returns matching saved ICSE papers when present.
- Search: focus `cloud_native` only returns conferences tagged with `cloud_native`.
- Search: repeated `conference=icse&conference=fse` limits saved-paper search to those conferences.
- Search: `ccf=A` filters results to CCF-A conference entries.
- Search: `mode=concept` maps Chinese/natural-language cloud-native security queries to English paper concepts such as Kubernetes, SBOM, provenance, and container images.
- Search: `mode=agentic` returns Qdrant hybrid matches with provenance when `pc-index` has been built, and returns concept fallback results with a clear fallback reason when the index is missing.
- Index: `POST /api/index` returns immediately while `GET /api/jobs/<job_id>` shows queued/running/completed/failed state.

### 6. Tests Required
- RSS builder escapes XML and includes title/link/authors/abstract.
- Options endpoint reads configured conferences and years.
- Options endpoint returns conference catalog objects, not raw strings.
- Collection endpoint validates conference/year/limit.
- Collection endpoint accepts a reasonable year that is not listed in config so the UI can crawl newly published proceedings.
- Collection endpoint accepts a batch `conferences` array, de-duplicates repeated ids, streams per-conference logs, records partial failures, and keeps successful feeds visible.
- Collection endpoint success path is tested with the collection function mocked; do not hit DBLP in unit tests.
- Collection endpoint log streaming is tested with a mocked long-running collection function; assert `/api/jobs/<job_id>` includes captured output before the job completes.
- Collection stop endpoint is tested with a mocked long-running batch collection; assert the current conference can finish and later conferences are not started.
- Collection endpoint failure path is tested with the collection function mocked to raise; assert `/api/jobs/<job_id>` becomes `failed` and includes the captured DBLP-stage log.
- Feed endpoint serves saved JSON as RSS and returns 404 for missing saved data.
- Feeds endpoint skips saved empty JSON files and never returns `paper_count: 0` entries.
- Browser UI tests cover a completed collection refreshing the task queue, RSS feed list, year progress, and job history without waiting for cache TTL expiry.
- Browser UI tests cover `Select shown` replacing stale/default conference selections, selecting all configured years for the visible conferences, and rendering a preview that matches the actual submitted conference x year queue.
- Browser UI tests cover `Missing only` changing only the selected year chips while keeping the selected conference set unchanged, and submitting exact missing conference/year tasks rather than the cross product of selected conferences and selected year chips.
- URL-base tests cover prefixed index, static assets, API routes, collect `status_url`, and RSS `feed_url`.
- Catalog tests cover object configs, aliases, and legacy string defaults.
- Search tests cover keyword scoring and category filters without network calls.
- Search tests cover `mode=concept`, `matched_concepts`, and rejection of unknown search modes without network calls.
- Search tests cover repeated conference filters and CCF tier filters without network calls.
- Vector index tests cover Qdrant local build/search with deterministic hash embeddings, filter payloads, provenance, and fallback when the collection is missing.
- Agentic search tests cover merging concept candidates into vector results when Qdrant prefetch misses a strong title/topic match.
- Web index job tests cover `POST /api/index`, duplicate-job 409, file-backed status polling, and completed stats with the build function mocked.
- Vector provider tests cover FastEmbed provider caching without downloading models.
- CLI search tests cover `pc-search` concept results without `OPENAI_API_KEY` or embeddings.
- Search tests cover underscore/hyphen query normalization, local BM25 expansion for paraphrased concept queries, and suppression of proceedings/poster metadata.
- Search tests cover incidental abstract-only concept mentions and query-embedded year filters.

### 7. Wrong vs Correct

#### Wrong
```python
# Do not let arbitrary user input choose output file paths or feed paths.
conference = request.json["conference"]
year = request.json["year"]
process_conference_year(conference, year, ...)
```

#### Correct
```python
# Validate against config.yaml first, then reuse existing collection helpers.
entry = find_conference(config, conference)
if entry is None:
    return jsonify({"error": "Choose a conference from config.yaml."}), 400
```

---

## Scenario: Collection Task Queue with Stop / Resume / Retry

### 1. Scope / Trigger
- Trigger: changes that add or modify the per-conference task queue inside a collection job, including pause/resume/retry semantics and per-task status visibility.
- Applies to `src/services/job_store.py`, `src/web/app.py`, `src/web/static/app.js`, and `src/web/templates/index.html`.
- Extends the existing batch collection model (one job → N conferences sequential) with per-conference queue items that track independent lifecycle states.

### 2. Signatures
- API: `POST /api/collect` — unchanged request shape; internally creates a queue of per-conference tasks.
- API: `GET /api/jobs/<job_id>` — returns `queue` array with per-task status.
- API: `POST /api/jobs/<job_id>/stop` — stops the job cooperatively; remaining queued tasks stay `pending`.
- API: `POST /api/jobs/<job_id>/resume` — **new**; resumes a `stopped` or `failed` job, re-queuing `pending`/`failed` tasks.
- API: `POST /api/jobs/<job_id>/retry` — **new**; re-queues only `failed` tasks from a `stopped`/`failed`/`completed` job.
- API: `POST /api/jobs/<job_id>/queue/<task_id>/retry` — **new**; retries a single failed task.
- JobStore: no new public methods; queue state is stored inside the job JSON `queue` field.

### 3. Contracts

#### 3.1 Queue Item Schema (stored in `job.queue[]`)
```
{
  "task_id": string,           // 8-char hex, unique within the job
  "conference_id": string,     // ConferenceEntry.id
  "display_name": string,      // ConferenceEntry.display_name
  "status": string,            // "pending" | "running" | "completed" | "failed" | "skipped"
  "paper_count": int | null,   // filled on completion
  "output_path": string | null,// filled on completion
  "feed_url": string | null,   // filled on completion
  "error": string | null,      // filled on failure
  "started_at": float | null,  // epoch seconds
  "finished_at": float | null  // epoch seconds
}
```

#### 3.2 Job-level Status Machine
```
queued → running → completed
                  → failed        (all tasks failed)
                  → stopped       (user requested stop; some tasks remain pending/failed)
```
- `stopped` is a terminal state for the current run; `resume` or `retry` transitions it back to `running`.
- A job with status `completed` may still contain `failed` tasks (partial success); `retry` can re-run those.

#### 3.3 Task-level Status Machine
```
pending → running → completed
                  → failed    (exception during collection)
        → skipped            (user stopped before this task started)
```
- `skipped` is set on all `pending` tasks when the job is stopped.
- `retry` resets `failed`/`skipped` tasks to `pending`.

#### 3.4 `POST /api/collect` — Internal Changes
- After validation, build `queue[]` from the resolved conference list.
- Each item gets a unique `task_id`, initial `status: "pending"`.
- Job JSON stores `queue` alongside existing fields.
- Background thread iterates `queue[]` instead of the raw `conferences` list.
- Between tasks, check `cancel_requested`; if set, mark remaining `pending` tasks as `skipped` and set job `status: "stopped"`.

#### 3.5 `GET /api/jobs/<job_id>` — Extended Response
New fields in the response:
- `queue`: array of queue item objects (see 3.1).
- `task_summary`: `{ "pending": int, "running": int, "completed": int, "failed": int, "skipped": int }`.
- Existing fields (`results`, `errors`, `completed_count`, `failed_count`, `stopped_count`) are derived from `queue`.

#### 3.6 `POST /api/jobs/<job_id>/stop` — Extended Behavior
- Sets `cancel_requested: true` on the job.
- The worker thread, after finishing the current task, marks all remaining `pending` tasks as `skipped`.
- Job status becomes `stopped` (not `cancelled`; `cancelled` is removed in favor of `stopped`).
- The collection lock is released so a new job can be started.

#### 3.7 `POST /api/jobs/<job_id>/resume` — New Endpoint
- **Precondition**: job `status` is `stopped` or `failed`.
- **Precondition**: at least one task has `status` in `{ "pending", "failed", "skipped" }`.
- Resets all `skipped` tasks to `pending`; leaves `completed` tasks untouched.
- Sets job `status: "running"`, `cancel_requested: false`.
- Acquires the collection lock; if another job holds it, return 409.
- Spawns a new background thread that picks up from the first non-completed task.
- Returns 202 with `job_id` and `status_url`.

#### 3.8 `POST /api/jobs/<job_id>/retry` — New Endpoint
- **Precondition**: job `status` is `stopped`, `failed`, or `completed`.
- Resets only `failed` and `skipped` tasks to `pending`; leaves `completed` tasks untouched.
- Same lock acquisition and thread spawn as `resume`.
- Returns 202 with `job_id` and `status_url`.

#### 3.9 `POST /api/jobs/<job_id>/queue/<task_id>/retry` — New Endpoint
- **Precondition**: task exists and has `status` in `{ "failed", "skipped" }`.
- Resets that single task to `pending`.
- If the job is not currently running, acquires the lock and spawns a worker.
- Returns 202 with the updated queue item.

### 4. Validation & Error Matrix
| Condition | HTTP | Error |
|---|---|---|
| `resume` on a `running` job | 409 | "Job is already running." |
| `resume` on a `completed` job with no failed/skipped tasks | 400 | "No tasks to resume." |
| `retry` when no tasks are `failed`/`skipped` | 400 | "No failed tasks to retry." |
| `resume`/`retry` while another collection job holds the lock | 409 | "A collection job is already running." |
| `queue/<task_id>/retry` with unknown `task_id` | 404 | "Task not found." |
| `queue/<task_id>/retry` on a `completed` or `running` task | 400 | "Task cannot be retried in its current state." |
| `stop` on a `completed`/`failed`/`stopped` job | 409 | "Collection job is not running." |

### 5. Good/Base/Bad Cases
- **Good**: submit 5 conferences, stop after 2 complete → job `stopped`, 2 `completed`, 3 `skipped` → resume → remaining 3 run → job `completed`.
- **Good**: submit 3 conferences, 1 fails → job `completed` with 1 `failed` task → retry → failed task re-runs.
- **Good**: single conference fails → `queue/<task_id>/retry` → only that conference re-runs.
- **Base**: submit 1 conference → queue has 1 item → runs → completes.
- **Bad**: resume a `running` job → 409.
- **Bad**: retry when all tasks are `completed` → 400.
- **Edge**: stop while first conference is running → current conference finishes (or fails), remaining marked `skipped`, lock released.

### 6. Tests Required
- Queue creation: `POST /api/collect` with batch conferences produces `queue[]` with correct `task_id`, `conference_id`, `status: "pending"`.
- Queue progression: mocked collection processes tasks sequentially; each task transitions `pending → running → completed` with `paper_count` filled.
- Stop mid-batch: mock slow collection; stop after first task completes; assert second task is `running` (finishes), remaining are `skipped`, job `status: "stopped"`.
- Resume: from `stopped` state, resume re-queues `skipped` tasks; assert `completed` tasks are not re-run.
- Retry failed: from `completed` state with 1 failed task, retry re-queues only that task.
- Single task retry: `POST /api/jobs/<id>/queue/<task_id>/retry` resets only the target task.
- Lock contention: resume/retry while another job holds the lock → 409.
- Task summary: `GET /api/jobs/<id>` returns correct `task_summary` counts at each state.
- Log streaming: per-task logs appear in `job.logs` during execution.
- Idempotent stop: calling stop on an already-stopped job returns 409 with current state.
- Frontend: job status panel renders per-task progress (pending/running/completed/failed/skipped icons).
- Frontend: resume/retry buttons appear when job is `stopped`/`failed`/`completed` with retryable tasks.
- Frontend: clicking resume/retry sends the correct POST and re-starts polling.

### 7. Wrong vs Correct

#### Wrong
```python
# Storing queue state only in memory — lost on process restart.
self._task_queue = {task_id: "pending" for task_id in task_ids}

# Or: treating stop the same as cancel — no way to resume.
def stop_job(job_id):
    job_store.update(job_id, status="cancelled")
    # All progress lost; must re-submit the entire batch.
```

#### Correct
```python
# Queue state persisted in job JSON; survives restarts and multi-worker reads.
queue = [
    {"task_id": uuid.uuid4().hex[:8], "conference_id": c.id,
     "display_name": c.display_name, "status": "pending",
     "paper_count": None, "output_path": None, "feed_url": None,
     "error": None, "started_at": None, "finished_at": None}
    for c in conferences
]
job = job_store.create({..., "queue": queue})

# Stop marks remaining tasks as skipped; lock is released; resume can pick up.
def stop_job(job_id):
    job = job_store.get(job_id)
    for item in job["queue"]:
        if item["status"] == "pending":
            item["status"] = "skipped"
    job_store.update(job_id, status="stopped", queue=job["queue"])
    collection_lock.release()
```
