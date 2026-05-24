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
- Command: `uv run python web.py --config config.yaml --host 127.0.0.1 --port 5000`
- API: `GET /api/options`
- API: `POST /api/collect`
- API: `GET /api/jobs/<job_id>`
- API: `GET /api/feeds`
- RSS: `GET /feed/<conference>/<year>.xml`
- Catalog parser: `normalize_conferences(config) -> list[ConferenceEntry]`
- Catalog lookup: `find_conference(config, value) -> ConferenceEntry | None`
- Catalog categories: `catalog_categories(config) -> list[dict]`
- Focus options: `focus_tag_options(config) -> list[dict]`
- Search API: `GET /api/search?q=<query>&mode=<keyword|concept>&category=<sub>&focus=<tag>&conference=<id>&year=<year>&limit=<n>`
- Config: `url_base` optional path prefix such as `/papercollect`.

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
  - Results should include `focus_tags` when the conference has them.
  - `mode=keyword` uses local exact/token scoring over saved JSON.
  - `mode=concept` uses local expanded BM25 over saved JSON plus SemRank-lite concept reranking; it must not require embeddings, external vector stores, or `OPENAI_API_KEY`.
  - Concept results include `matched_concepts`, `concept_score`, `lexical_score`, and `search_mode`.
  - Search uses saved JSON files only; it must not require embeddings or `OPENAI_API_KEY`.
  - Search should suppress non-paper metadata entries such as proceedings, poster records, chair messages, keynote/front-matter entries, and student/dissertation abstracts.
  - Concept search must treat title/topic matches as stronger than incidental abstract mentions; a paper that only mentions a query concept once in an abstract example should not rank as a topic match.
  - Four-digit years typed in the query, such as `kubernetes 2026`, should be treated as a year filter and removed from scoring tokens.
- Collection response:
  - Success: HTTP 202 with `job_id` and `status_url`.
  - Validation failure: HTTP 400 with `error`.
  - Existing running job: HTTP 409 with `error`.
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
- DBLP network/API failure during collection -> job status `failed`; never convert the failure into an empty paper list.
- Missing saved JSON for RSS -> 404.
- Invalid search conference -> 400.
- Search mode other than `keyword` or `concept` -> 400.
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
- Search: `mode=concept` maps Chinese/natural-language cloud-native security queries to English paper concepts such as Kubernetes, SBOM, provenance, and container images.

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
