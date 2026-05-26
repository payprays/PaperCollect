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
- DBLP search collection:
  - DBLP search requests use `h=1000` as the page size and must paginate with `f` until all hits are read.
  - Do not treat the DBLP single-page size as the total per-conference paper limit.
- Job response fields:
  - `id`, `status`, `conference`, `display_name`, `year`, `limit`, `logs`, `feed_url`.
  - Batch jobs also include `conferences`, `display_names`, `conference_count`, `completed_count`, `failed_count`, `results`, `errors`, and `feed_urls`.
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
- Collection endpoint failure path is tested with the collection function mocked to raise; assert `/api/jobs/<job_id>` becomes `failed` and includes the captured DBLP-stage log.
- Feed endpoint serves saved JSON as RSS and returns 404 for missing saved data.
- Feeds endpoint skips saved empty JSON files and never returns `paper_count: 0` entries.
- URL-base tests cover prefixed index, static assets, API routes, collect `status_url`, and RSS `feed_url`.
- Catalog tests cover object configs, aliases, and legacy string defaults.
- Search tests cover keyword scoring and category filters without network calls.
- Search tests cover `mode=concept`, `matched_concepts`, and rejection of unknown search modes without network calls.
- Search tests cover repeated conference filters and CCF tier filters without network calls.
- Vector index tests cover Qdrant local build/search with deterministic hash embeddings, filter payloads, provenance, and fallback when the collection is missing.
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
