# Paper crawl frontend and RSS feed

## Goal

Add a small local web interface for selecting one configured conference and one year, running the existing paper collection pipeline for that pair, and exposing the saved papers as an RSS feed.

## Requirements

* Fix the local runtime blockers found before implementation:
  * `.venv/bin/python*` must be executable enough for `uv run` to work.
  * `src/__init__.py` must not print environment variables or secrets on import.
  * Project dependencies must include packages used by the RAG service.
* Provide a web UI served by the Python app.
  * Conference options come from `config.yaml`.
  * Conference options use a normalized catalog format with `id`, `display_name`, `full_name`, `dblp_stream`, `aliases`, `category`, and optional `tier`.
  * Year suggestions come from `config.yaml`, but the user can type any reasonable year to fetch latest proceedings.
  * The user can choose one conference and enter one year, optionally set a paper limit, then trigger collection.
* Use DBLP stream keys as the canonical crawl source when configured.
  * UI labels use `display_name`.
  * Saved JSON and RSS URLs use stable lowercase `id` slugs.
  * Legacy string-only conference config remains supported through normalization defaults.
* Merge a bundled CCFDDL-derived conference catalog.
  * Categories follow CCFDDL `sub` groups such as `AI`, `SC`, `SE`, `DB`, `DS`, `NW`, `CT`, `CG`, `HI`, and `MX`.
  * The bundled catalog expands selectable conferences beyond the hand-written config.
  * Local `config.yaml` entries override bundled entries while missing rank/category metadata is filled from the bundled catalog.
* Provide a local saved-paper searcher.
  * Search scans saved JSON files in `output_dir`.
  * Search can filter by CCFDDL category, conference, and year.
  * Search can filter by project-specific focus tags such as cloud security and cloud native.
  * Search must not require OpenAI credentials.
* Reuse the existing collection pipeline instead of duplicating DBLP or metadata logic.
* Save results in the existing `output_dir` JSON format.
* Expose RSS XML for a selected conference/year.
  * Feed items should include title, authors, venue/year, abstract summary when available, and a stable link when available.
  * Missing data should degrade gracefully rather than failing the feed.
* Keep the app local-first and simple; no database, queue worker, or frontend build pipeline for this MVP.

## Acceptance Criteria

* [x] `uv run python -c "import src"` does not print environment variables.
* [x] `uv run python -c "import src.services.rag_service"` succeeds after sync.
* [x] `uv run pytest` can be invoked without the venv permission failure.
* [x] A local web page lists configured conferences and years.
* [x] Conference options are normalized and exposed as catalog objects.
* [x] Year input accepts reasonable years that are not listed in config.
* [x] CCFDDL categories are exposed to the frontend.
* [x] Project focus tags are exposed to the frontend.
* [x] Search endpoint returns saved papers filtered by query/category/conference/year.
* [x] Submitting a conference/year triggers collection and reports saved paper count.
* [x] `/feed/<conference>/<year>.xml` returns valid RSS XML for saved results.
* [x] README documents how to run the web UI and RSS feed.

## Definition of Done

* Runtime blockers fixed.
* Code is implemented with existing project patterns where practical.
* Tests cover RSS generation and API behavior that does not require live network access.
* Project tests or targeted tests run successfully.

## Technical Approach

Use a small Flask app because the feature needs a browser UI and a couple of HTTP endpoints, but the repo currently has no frontend build system. The Flask app will serve one HTML page with static JavaScript, expose JSON endpoints for config/status/collection, and expose RSS XML from saved paper JSON files.

The collection endpoint will call the existing `process_conference_year` function with `DBLPClient` and `MetadataManager`. To avoid concurrent writes to the same output file from multiple browser clicks, the web layer will serialize collection jobs with an in-process lock.

## Out of Scope

* Background job queue with persistent progress after process restart.
* Authentication or public deployment hardening.
* Database storage.
* Scheduled crawling.
* Rich frontend framework.

## Technical Notes

* Existing collection entry point: `main.py`.
* Existing saved JSON path helper: `get_output_path(output_dir, conference, year)`.
* Existing data model: `src/core/models.py`.
* Existing config file: `config.yaml`.
* Current repo dependency manager: `uv` with `pyproject.toml` and `uv.lock`.
