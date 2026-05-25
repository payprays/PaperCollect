# brainstorm: agentic vector knowledge base

## Goal

Upgrade PaperCollect from a conference-paper RSS/search tool into an agent-friendly paper knowledge base: collected JSON papers remain the canonical source, while a rebuildable vector index exposes structured semantic retrieval, metadata filters, provenance, and APIs that an agent can call safely.

## What I already know

* PaperCollect collects papers by conference/year, stores them as `data/*.json`, exposes RSS feeds, and has a Flask Web UI.
* Current search is local `Concept semantic`: expanded BM25 plus a curated concept lexicon, with no external embeddings or `OPENAI_API_KEY`.
* The current UI/API already supports category, focus tag, CCF tier, year, and multi-conference filtering.
* The user wants a "good agentic vector library", which implies more than embedding search: agents need provenance, stable IDs, filters, incremental indexing, and machine-readable result contracts.

## Assumptions (temporary)

* The JSON paper files should stay the source of truth; vector data can be deleted and rebuilt.
* The MVP should be usable on the existing `k8sv6` deployment and locally via `uv`.
* The default path should not require a paid hosted API, while still allowing custom embedding providers later.
* Paper-level retrieval is the first target; full-PDF chunking can be a later task.

## Open Questions

* Resolved: use Qdrant as the first backend. Support embedded local mode for tests/local use and service mode through config for production.

## Requirements (evolving)

* Add a vector index build/sync path from saved JSON papers.
* Preserve conference metadata as filterable payload: conference, display name, year, category, CCF tier, focus tags, DBLP key, URL.
* Expose a search mode suitable for agents, returning stable IDs, scores, provenance, and source snippets.
* Keep current concept search available as fallback or lexical reranker.
* Avoid indexing empty/non-paper noise entries.
* Use dense+sparse hybrid retrieval with reciprocal-rank fusion rather than single-vector nearest-neighbor search.
* Default user-facing search mode should be `agentic`, with `vector` accepted as an alias.
* Use models that can actually finish on `k8sv6`; Jina v3/Jina v2 and SPLADE were too heavy/slow during full indexing, so the practical default is `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` plus hash lexical sparse vectors.

## Acceptance Criteria (evolving)

* [x] A command can build or refresh the vector index from `data/*.json`.
* [x] A Web/API search can query the vector index with the existing filters.
* [x] Search results include stable IDs, source fields, score details, and enough text for citation.
* [x] The feature works without `OPENAI_API_KEY` by default.
* [x] Tests cover indexing, filtering, search response shape, and fallback behavior.

## Definition of Done (team quality bar)

* Tests added/updated (unit/integration where appropriate)
* Lint / typecheck / CI green
* Docs/notes updated if behavior changes
* Rollout/rollback considered if risky

## Out of Scope (explicit)

* Full paper PDF crawling, parsing, and chunk-level retrieval.
* Autonomous summarization or answer generation over retrieved papers.
* Replacing the RSS feed model or collected JSON source of truth.
* Hosted multi-user auth/tenant management.

## Technical Notes

* Existing search code: `src/services/paper_search.py`.
* Existing Web API: `src/web/app.py`.
* Existing CLI entrypoints: `pyproject.toml` currently exposes `pc-collect`, `pc-search`, and `pc-web`.
* Current dependency set is small; adding a vector backend should be deliberate and justified.

## Research References

* [`research/vector-backend-options.md`](research/vector-backend-options.md) — backend comparison and final Qdrant hybrid decision.
