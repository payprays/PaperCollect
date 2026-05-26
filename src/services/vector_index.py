import hashlib
import json
import math
import os
import re
import threading
import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from glob import glob
from typing import Any, Protocol

from qdrant_client import QdrantClient, models

from src.core.conference_catalog import ConferenceEntry, find_conference, normalize_conferences

DEFAULT_COLLECTION = "papercollect_papers"
DEFAULT_INDEX_PATH = "data/qdrant"
DEFAULT_DENSE_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_SPARSE_MODEL = "hash"
DEFAULT_DENSE_SIZE = 1024
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-z0-9][a-z0-9+#.]*")
POINT_NAMESPACE = uuid.UUID("7f04652c-e52e-4ef0-b356-6a33e217457f")
_PROVIDER_CACHE: dict[tuple[Any, ...], "HybridEmbeddingProvider"] = {}
_PROVIDER_LOCK = threading.Lock()


class VectorIndexError(RuntimeError):
    """Raised when the agentic vector index cannot be used."""


@dataclass(frozen=True)
class SparseEmbedding:
    indices: list[int]
    values: list[float]


@dataclass(frozen=True)
class HybridEmbedding:
    dense: list[float]
    sparse: SparseEmbedding


class HybridEmbeddingProvider(Protocol):
    dense_size: int
    name: str

    def embed_documents(self, texts: Sequence[str]) -> list[HybridEmbedding]:
        ...

    def embed_query(self, text: str) -> HybridEmbedding:
        ...


def build_vector_index(
    config: dict[str, Any],
    output_dir: str,
    *,
    force: bool = True,
    provider: HybridEmbeddingProvider | None = None,
) -> dict[str, Any]:
    """Build a Qdrant hybrid dense+sparse index from saved paper JSON files."""
    index_config = _vector_config(config)
    collection_name = str(index_config.get("collection") or DEFAULT_COLLECTION)
    batch_size = int(index_config.get("batch_size") or 64)
    provider = provider or _embedding_provider(index_config)
    documents = _paper_documents(config, output_dir)

    client = _qdrant_client(index_config)
    try:
        if force and client.collection_exists(collection_name):
            client.delete_collection(collection_name)
        if not client.collection_exists(collection_name):
            _create_collection(client, collection_name, provider.dense_size, index_config)

        indexed = 0
        for batch in _batched(documents, batch_size):
            embeddings = provider.embed_documents([item["embedding_text"] for item in batch])
            points = [
                models.PointStruct(
                    id=item["point_id"],
                    vector={
                        DENSE_VECTOR_NAME: embedding.dense,
                        SPARSE_VECTOR_NAME: _qdrant_sparse_vector(embedding.sparse),
                    },
                    payload=item["payload"],
                )
                for item, embedding in zip(batch, embeddings, strict=True)
            ]
            if points:
                client.upsert(collection_name=collection_name, points=points)
                indexed += len(points)

        return {
            "backend": "qdrant",
            "collection": collection_name,
            "provider": provider.name,
            "dense_vector": DENSE_VECTOR_NAME,
            "sparse_vector": SPARSE_VECTOR_NAME,
            "paper_count": indexed,
            "source_count": len(documents),
            "index_path": index_config.get("path"),
            "url": index_config.get("url"),
        }
    finally:
        client.close()


def search_vector_index(
    config: dict[str, Any],
    output_dir: str,
    query: str,
    *,
    category: str | None = None,
    focus: str | None = None,
    conference: str | None = None,
    conferences: Sequence[str] | None = None,
    ccf: str | None = None,
    year: int | None = None,
    limit: int = 25,
    provider: HybridEmbeddingProvider | None = None,
) -> list[dict[str, Any]]:
    """Search the Qdrant hybrid index with payload filters and RRF fusion."""
    query = str(query or "").strip()
    if not query:
        return []

    index_config = _vector_config(config)
    collection_name = str(index_config.get("collection") or DEFAULT_COLLECTION)
    client = _qdrant_client(index_config)
    try:
        if not client.collection_exists(collection_name):
            raise VectorIndexError(
                f"Vector collection '{collection_name}' does not exist. Run pc-index first."
            )

        provider = provider or _embedding_provider(index_config)
        embedding = provider.embed_query(query)
        prefetch_limit = max(limit * int(index_config.get("prefetch_multiplier") or 4), limit)
        response = client.query_points(
            collection_name=collection_name,
            prefetch=[
                models.Prefetch(
                    query=embedding.dense,
                    using=DENSE_VECTOR_NAME,
                    limit=prefetch_limit,
                ),
                models.Prefetch(
                    query=_qdrant_sparse_vector(embedding.sparse),
                    using=SPARSE_VECTOR_NAME,
                    limit=prefetch_limit,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=_qdrant_filter(
                config,
                category=category,
                focus=focus,
                conference=conference,
                conferences=conferences,
                ccf=ccf,
                year=year,
            ),
            limit=limit,
            with_payload=True,
        )
    finally:
        client.close()

    results = []
    for point in response.points:
        payload = point.payload or {}
        result = {
            "id": payload.get("paper_id") or str(point.id),
            "title": payload.get("title") or "Untitled paper",
            "authors": payload.get("authors") or [],
            "venue": payload.get("venue") or payload.get("display_name"),
            "year": payload.get("year"),
            "abstract": payload.get("abstract"),
            "snippet": _snippet(payload, query),
            "url": payload.get("url"),
            "dblp_key": payload.get("dblp_key"),
            "source_id": payload.get("source_id"),
            "score": float(point.score or 0.0),
            "conference": payload.get("conference"),
            "display_name": payload.get("display_name"),
            "category": payload.get("category"),
            "category_name": payload.get("category_name"),
            "tier": payload.get("tier") or {},
            "focus_tags": payload.get("focus_tags") or [],
            "search_mode": "agentic",
            "retrieval_backend": "qdrant_hybrid_rrf",
            "score_details": {
                "fusion": "rrf",
                "dense_vector": DENSE_VECTOR_NAME,
                "sparse_vector": SPARSE_VECTOR_NAME,
                "embedding_provider": provider.name,
            },
            "provenance": {
                "paper_id": payload.get("paper_id") or str(point.id),
                "source_file": payload.get("source_file"),
                "source_index": payload.get("source_index"),
                "dblp_key": payload.get("dblp_key"),
                "url": payload.get("url"),
            },
        }
        results.append(result)
    return results


def vector_index_status(config: dict[str, Any]) -> dict[str, Any]:
    index_config = _vector_config(config)
    collection_name = str(index_config.get("collection") or DEFAULT_COLLECTION)
    client = _qdrant_client(index_config)
    try:
        if not client.collection_exists(collection_name):
            return {
                "backend": "qdrant",
                "collection": collection_name,
                "indexed": False,
                "paper_count": 0,
            }
        count = client.count(collection_name=collection_name, exact=True)
        return {
            "backend": "qdrant",
            "collection": collection_name,
            "indexed": True,
            "paper_count": int(count.count),
            "index_path": index_config.get("path"),
            "url": index_config.get("url"),
        }
    finally:
        client.close()


def _vector_config(config: dict[str, Any]) -> dict[str, Any]:
    values = dict(config.get("vector_index") or {})
    values.setdefault("backend", "qdrant")
    values.setdefault("collection", DEFAULT_COLLECTION)
    values.setdefault("path", DEFAULT_INDEX_PATH)
    values.setdefault("embedding_provider", "fastembed")
    values.setdefault("dense_model", DEFAULT_DENSE_MODEL)
    values.setdefault("sparse_model", DEFAULT_SPARSE_MODEL)
    values.setdefault("dense_size", DEFAULT_DENSE_SIZE)
    values.setdefault("prefetch_multiplier", 4)
    values.setdefault("timeout", 120)
    return values


def _qdrant_client(index_config: dict[str, Any]) -> QdrantClient:
    url = str(index_config.get("url") or "").strip()
    api_key = str(index_config.get("api_key") or "").strip() or None
    timeout = int(index_config.get("timeout") or 120)
    if url:
        return QdrantClient(url=url, api_key=api_key, timeout=timeout)
    path = str(index_config.get("path") or DEFAULT_INDEX_PATH)
    os.makedirs(path, exist_ok=True)
    return QdrantClient(path=path)


def _create_collection(
    client: QdrantClient,
    collection_name: str,
    dense_size: int,
    index_config: dict[str, Any],
) -> None:
    client.create_collection(
        collection_name=collection_name,
        vectors_config={
            DENSE_VECTOR_NAME: models.VectorParams(
                size=dense_size,
                distance=models.Distance.COSINE,
                on_disk=bool(index_config.get("on_disk_vectors", False)),
            )
        },
        sparse_vectors_config={
            SPARSE_VECTOR_NAME: models.SparseVectorParams(
                index=models.SparseIndexParams(
                    on_disk=bool(index_config.get("on_disk_sparse", False))
                )
            )
        },
        on_disk_payload=bool(index_config.get("on_disk_payload", True)),
    )
    for field_name, schema in [
        ("conference", models.PayloadSchemaType.KEYWORD),
        ("category", models.PayloadSchemaType.KEYWORD),
        ("ccf", models.PayloadSchemaType.KEYWORD),
        ("focus_tags", models.PayloadSchemaType.KEYWORD),
        ("year", models.PayloadSchemaType.INTEGER),
        ("dblp_key", models.PayloadSchemaType.KEYWORD),
    ]:
        client.create_payload_index(collection_name, field_name, field_schema=schema)


def _embedding_provider(index_config: dict[str, Any]) -> HybridEmbeddingProvider:
    cache_key = _embedding_provider_cache_key(index_config)
    if cache_key and bool(index_config.get("cache_provider", True)):
        with _PROVIDER_LOCK:
            provider = _PROVIDER_CACHE.get(cache_key)
            if provider is None:
                provider = _create_embedding_provider(index_config)
                _PROVIDER_CACHE[cache_key] = provider
            return provider
    return _create_embedding_provider(index_config)


def _embedding_provider_cache_key(index_config: dict[str, Any]) -> tuple[Any, ...] | None:
    provider = str(index_config.get("embedding_provider") or "fastembed").lower()
    if provider == "fastembed":
        return (
            provider,
            str(index_config.get("dense_model") or DEFAULT_DENSE_MODEL),
            str(index_config.get("sparse_model") or DEFAULT_SPARSE_MODEL),
            index_config.get("cache_dir"),
            index_config.get("threads"),
        )
    return None


def _create_embedding_provider(index_config: dict[str, Any]) -> HybridEmbeddingProvider:
    provider = str(index_config.get("embedding_provider") or "fastembed").lower()
    if provider == "hash":
        return HashHybridEmbeddingProvider(dense_size=int(index_config.get("dense_size") or 128))
    if provider == "fastembed":
        sparse_model = str(index_config.get("sparse_model") or DEFAULT_SPARSE_MODEL)
        if sparse_model.lower() == "hash":
            return FastEmbedDenseHashSparseProvider(
                dense_model=str(index_config.get("dense_model") or DEFAULT_DENSE_MODEL),
                cache_dir=index_config.get("cache_dir"),
                threads=index_config.get("threads"),
            )
        return FastEmbedHybridEmbeddingProvider(
            dense_model=str(index_config.get("dense_model") or DEFAULT_DENSE_MODEL),
            sparse_model=sparse_model,
            cache_dir=index_config.get("cache_dir"),
            threads=index_config.get("threads"),
        )
    raise VectorIndexError(f"Unsupported embedding provider: {provider}")


class FastEmbedHybridEmbeddingProvider:
    def __init__(
        self,
        *,
        dense_model: str,
        sparse_model: str,
        cache_dir: str | None = None,
        threads: int | None = None,
    ) -> None:
        try:
            from fastembed import SparseTextEmbedding, TextEmbedding
        except ImportError as exc:
            raise VectorIndexError(
                "FastEmbed is not installed. Install qdrant-client[fastembed] or use embedding_provider=hash."
            ) from exc

        self.name = f"fastembed:{dense_model}+{sparse_model}"
        self._dense = TextEmbedding(
            model_name=dense_model,
            cache_dir=cache_dir,
            threads=threads,
        )
        self._sparse = SparseTextEmbedding(
            model_name=sparse_model,
            cache_dir=cache_dir,
            threads=threads,
        )
        self.dense_size = _fastembed_dense_size(dense_model)

    def embed_documents(self, texts: Sequence[str]) -> list[HybridEmbedding]:
        dense_values = [list(vector.tolist()) for vector in self._dense.embed(texts)]
        sparse_values = [_sparse_from_fastembed(item) for item in self._sparse.embed(texts)]
        return [
            HybridEmbedding(dense=dense, sparse=sparse)
            for dense, sparse in zip(dense_values, sparse_values, strict=True)
        ]

    def embed_query(self, text: str) -> HybridEmbedding:
        dense = list(next(self._dense.query_embed(text)).tolist())
        sparse = _sparse_from_fastembed(next(self._sparse.query_embed(text)))
        return HybridEmbedding(dense=dense, sparse=sparse)


class FastEmbedDenseHashSparseProvider:
    def __init__(
        self,
        *,
        dense_model: str,
        cache_dir: str | None = None,
        threads: int | None = None,
    ) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise VectorIndexError(
                "FastEmbed is not installed. Install qdrant-client[fastembed] or use embedding_provider=hash."
            ) from exc

        self.name = f"fastembed:{dense_model}+hash_sparse"
        self._dense = TextEmbedding(
            model_name=dense_model,
            cache_dir=cache_dir,
            threads=threads,
        )
        self._hash_sparse = HashHybridEmbeddingProvider(dense_size=8)
        self.dense_size = _fastembed_dense_size(dense_model)

    def embed_documents(self, texts: Sequence[str]) -> list[HybridEmbedding]:
        dense_values = [list(vector.tolist()) for vector in self._dense.embed(texts)]
        sparse_values = [self._hash_sparse.embed_query(text).sparse for text in texts]
        return [
            HybridEmbedding(dense=dense, sparse=sparse)
            for dense, sparse in zip(dense_values, sparse_values, strict=True)
        ]

    def embed_query(self, text: str) -> HybridEmbedding:
        dense = list(next(self._dense.query_embed(text)).tolist())
        sparse = self._hash_sparse.embed_query(text).sparse
        return HybridEmbedding(dense=dense, sparse=sparse)


class HashHybridEmbeddingProvider:
    """Deterministic local provider for tests and offline smoke checks."""

    def __init__(self, dense_size: int = 128) -> None:
        self.dense_size = dense_size
        self.name = f"hash:{dense_size}"

    def embed_documents(self, texts: Sequence[str]) -> list[HybridEmbedding]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> HybridEmbedding:
        return self._embed(text)

    def _embed(self, text: str) -> HybridEmbedding:
        dense = [0.0] * self.dense_size
        sparse_counts: Counter[int] = Counter()
        for token in _tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dense_size
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            dense[index] += sign
            sparse_counts[int.from_bytes(digest[5:9], "big") % 1_000_003] += 1

        norm = math.sqrt(sum(value * value for value in dense)) or 1.0
        dense = [value / norm for value in dense]
        indices = sorted(sparse_counts)
        values = [float(sparse_counts[index]) for index in indices]
        return HybridEmbedding(dense=dense, sparse=SparseEmbedding(indices=indices, values=values))


def _fastembed_dense_size(model_name: str) -> int:
    from fastembed import TextEmbedding

    for model in TextEmbedding.list_supported_models():
        if model.get("model") == model_name:
            return int(model["dim"])
    raise VectorIndexError(f"Unsupported FastEmbed dense model: {model_name}")


def _sparse_from_fastembed(value: Any) -> SparseEmbedding:
    return SparseEmbedding(
        indices=[int(item) for item in value.indices.tolist()],
        values=[float(item) for item in value.values.tolist()],
    )


def _qdrant_sparse_vector(value: SparseEmbedding) -> models.SparseVector:
    return models.SparseVector(indices=value.indices, values=value.values)


def _paper_documents(config: dict[str, Any], output_dir: str) -> list[dict[str, Any]]:
    from src.services.paper_search import _is_noise_paper

    conference_lookup = _conference_lookup(config)
    documents: list[dict[str, Any]] = []
    for path in sorted(glob(os.path.join(output_dir, "*.json"))):
        file_conference, file_year = _parse_output_filename(path)
        entry = conference_lookup.get(_normalize_key(file_conference))
        for source_index, paper in enumerate(_load_paper_file(path)):
            if _is_noise_paper(paper):
                continue
            payload = _paper_payload(
                paper,
                entry=entry,
                file_conference=file_conference,
                file_year=file_year,
                source_file=path,
                source_index=source_index,
            )
            documents.append(
                {
                    "point_id": payload["paper_id"],
                    "embedding_text": _embedding_text(payload),
                    "payload": payload,
                }
            )
    return documents


def _paper_payload(
    paper: dict[str, Any],
    *,
    entry: ConferenceEntry | None,
    file_conference: str,
    file_year: int | None,
    source_file: str,
    source_index: int,
) -> dict[str, Any]:
    conference = entry.id if entry else file_conference
    display_name = entry.display_name if entry else str(paper.get("venue") or file_conference)
    year = paper.get("year") or file_year
    title = str(paper.get("title") or "Untitled paper")
    abstract = paper.get("abstract")
    payload = {
        "paper_id": _paper_id(conference, year, paper, title),
        "title": title,
        "authors": paper.get("authors") or [],
        "venue": paper.get("venue") or display_name,
        "year": year,
        "abstract": abstract,
        "url": paper.get("url"),
        "dblp_key": paper.get("dblp_key"),
        "source_id": paper.get("source_id"),
        "source": paper.get("source"),
        "source_url": paper.get("source_url"),
        "conference": conference,
        "display_name": display_name,
        "category": entry.category if entry else None,
        "category_name": entry.category_name if entry else None,
        "tier": entry.tier if entry else {},
        "ccf": (entry.tier.get("ccf") if entry else None),
        "focus_tags": list(entry.focus_tags) if entry else [],
        "source_file": os.path.relpath(source_file),
        "source_index": source_index,
    }
    return {key: value for key, value in payload.items() if value is not None}


def _paper_id(conference: str, year: object, paper: dict[str, Any], title: str) -> str:
    raw = json.dumps(
        [
            conference,
            year,
            paper.get("dblp_key"),
            paper.get("source_id"),
            title,
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    return str(uuid.uuid5(POINT_NAMESPACE, raw))


def _embedding_text(payload: dict[str, Any]) -> str:
    authors = ", ".join(str(author) for author in (payload.get("authors") or []))
    tier = payload.get("tier") or {}
    fields = [
        f"Title: {payload.get('title') or ''}",
        f"Abstract: {payload.get('abstract') or ''}",
        f"Authors: {authors}",
        f"Venue: {payload.get('display_name') or payload.get('venue') or ''}",
        f"Year: {payload.get('year') or ''}",
        f"Category: {payload.get('category') or ''} {payload.get('category_name') or ''}",
        f"CCF: {tier.get('ccf') or payload.get('ccf') or ''}",
        f"Focus: {' '.join(payload.get('focus_tags') or [])}",
    ]
    return "\n".join(fields)


def _qdrant_filter(
    config: dict[str, Any],
    *,
    category: str | None,
    focus: str | None,
    conference: str | None,
    conferences: Sequence[str] | None,
    ccf: str | None,
    year: int | None,
) -> models.Filter | None:
    conditions: list[models.FieldCondition] = []
    conference_ids = _conference_filter_ids(config, conference, conferences)
    if conference_ids:
        conditions.append(
            models.FieldCondition(
                key="conference",
                match=models.MatchAny(any=sorted(conference_ids)),
            )
        )
    if category:
        conditions.append(models.FieldCondition(key="category", match=models.MatchValue(value=category)))
    if ccf:
        conditions.append(models.FieldCondition(key="ccf", match=models.MatchValue(value=ccf.upper())))
    if focus:
        conditions.append(models.FieldCondition(key="focus_tags", match=models.MatchAny(any=[focus])))
    if year is not None:
        conditions.append(models.FieldCondition(key="year", match=models.MatchValue(value=int(year))))
    return models.Filter(must=conditions) if conditions else None


def _conference_filter_ids(
    config: dict[str, Any],
    conference: str | None,
    conferences: Sequence[str] | None,
) -> set[str]:
    values = []
    if conference:
        values.append(conference)
    if conferences:
        values.extend(conferences)

    ids = set()
    for value in values:
        entry = find_conference(config, value)
        if entry:
            ids.add(entry.id)
    return ids


def _conference_lookup(config: dict[str, Any]) -> dict[str, ConferenceEntry]:
    lookup = {}
    for entry in normalize_conferences(config):
        for value in [entry.id, entry.display_name, *entry.aliases]:
            lookup[_normalize_key(value)] = entry
    return lookup


def _parse_output_filename(path: str) -> tuple[str, int | None]:
    name = os.path.basename(path)
    match = re.match(r"(.+)_(\d{4})\.json$", name)
    if not match:
        return os.path.splitext(name)[0], None
    return match.group(1), int(match.group(2))


def _load_paper_file(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _normalize_key(value: object) -> str:
    return str(value or "").lower().replace("&", "and").replace(" ", "").replace("_", "").replace("-", "")


def _tokenize(value: str) -> list[str]:
    return TOKEN_RE.findall(str(value or "").lower().replace("_", " "))


def _batched(values: Sequence[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    size = max(size, 1)
    for index in range(0, len(values), size):
        yield list(values[index : index + size])


def _snippet(payload: dict[str, Any], query: str, length: int = 360) -> str:
    abstract = str(payload.get("abstract") or "")
    title = str(payload.get("title") or "")
    text = abstract or title
    if len(text) <= length:
        return text

    tokens = _tokenize(query)
    lowered = text.lower()
    first_match = min((lowered.find(token) for token in tokens if token in lowered), default=-1)
    if first_match < 0:
        return f"{text[: length - 3]}..."

    start = max(first_match - length // 3, 0)
    end = min(start + length, len(text))
    prefix = "..." if start else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"
