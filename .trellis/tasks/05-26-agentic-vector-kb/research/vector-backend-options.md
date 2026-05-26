# Vector Backend Options

## Context

PaperCollect has small-to-medium paper metadata JSON files, rich conference filters, and an existing Flask/CLI deployment. The vector layer should be a rebuildable derived index, not the canonical data store.

## Options

### LanceDB local-first

LanceDB is an embedded Python vector database with persistent local tables and hybrid search support. It fits a `uv` local app because it does not require a separate daemon for the MVP. It is a strong default when the project wants simple deployment, filterable payloads, and a sidecar index under `data/`.

Trade-off: it is less obviously "service database" shaped than Qdrant if we later want a separate shared vector service.

### Qdrant service-first

Qdrant is a dedicated vector database with payload filtering and a Python client. It fits a long-running deployment if we want a real vector service behind PaperCollect, especially on `k8sv6`.

Trade-off: it adds an extra service to install, configure, back up, monitor, and expose only locally to PaperCollect.

### Chroma simple local app

Chroma is simple for Python RAG prototypes and persistent local collections. It is a reasonable fast prototype choice.

Trade-off: for this repo, its main advantage over LanceDB is familiarity, while the project still needs careful metadata filtering, CLI rebuilds, and deployment hygiene.

### sqlite-vec single-file index

sqlite-vec keeps everything in SQLite and can pair naturally with FTS5.

Trade-off: more search/index glue would be ours to maintain, and this project does not already use SQLite as its canonical store.

## Final Decision

The user asked for the most advanced path, so the MVP should use Qdrant rather than LanceDB:

* `data/*.json` remains canonical.
* `data/qdrant/` is rebuildable and gitignored for embedded local mode.
* Add `pc-index` to build/sync.
* Add `mode=agentic` search path, with `mode=vector` as an alias.
* Store named dense and sparse vectors.
* Query dense and sparse vectors independently and combine them with reciprocal-rank fusion.
* Preserve rich payload filters for conference, year, category, CCF tier, and focus tags.
* Keep `concept` search as lexical fallback/reranker.
* Keep Qdrant config flexible enough to use embedded local mode or an external Qdrant service.

The default embedding path is FastEmbed with `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` dense embeddings plus hash lexical sparse vectors. This keeps the advanced Qdrant hybrid/RRF architecture while fitting the current CPU host better than the much heavier Jina/SPLADE models. Tests use deterministic hash embeddings to avoid model downloads.

Operational hardening: Web-triggered index rebuilds run as background jobs with JSON-backed status files and file locks, so multiple gunicorn workers can read job progress and avoid duplicate heavy rebuilds. FastEmbed providers are cached per process by model/cache/thread config so repeated agentic searches do not reload embedding models.

## Source Notes

* LanceDB docs describe vector and hybrid search as first-class search patterns.
* Qdrant Python client docs include local client support and payload-oriented vector search APIs.
* Chroma docs describe persistent clients and embedding-function based collections.
* sqlite-vec docs describe vector search inside SQLite.
