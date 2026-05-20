import argparse
import json
import math
import os
import pickle
import re
from collections import Counter
from dataclasses import dataclass, field
from glob import glob
from statistics import mean
from typing import Any, Callable

import numpy as np
import yaml

from src.core.conference_catalog import normalize_conferences
from src.services import paper_search


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+.#-]*")
EVALUATION_DEPTH = 200


TOPIC_QUERIES: list[dict[str, Any]] = [
    {
        "id": "k8s_security",
        "query": "cloud native cluster policy hardening",
        "label": lambda text: _has(
            text,
            r"\b(kubernetes|k8s|container orchestration|admission controller|rbac|pod security)\b",
        )
        and _has(text, r"\b(security|attack|vulnerab|policy|permission|misconfig|isolation|privilege)\b"),
    },
    {
        "id": "supply_chain",
        "query": "third-party package provenance and build pipeline risk",
        "label": lambda text: _has(
            text,
            r"\b(supply chain|sbom|software bill of materials|dependency confusion|package manager|package repository|npm|pypi|provenance|registry|container image)\b",
        ),
    },
    {
        "id": "container_isolation",
        "query": "sandbox boundary attacks in container runtimes",
        "label": lambda text: _has(text, r"\b(container|docker|runc|namespace|cgroup|seccomp|sandbox|sandboxing)\b")
        and _has(text, r"\b(escape|breakout|isolation|security|attack|vulnerab)\b"),
    },
    {
        "id": "serverless_security",
        "query": "multi tenant function platform attack isolation",
        "label": lambda text: _has(text, r"\b(serverless|function as a service|faas|lambda function|cloud function)\b")
        and _has(text, r"\b(security|attack|vulnerab|privacy|isolation|tenant|abuse)\b"),
    },
    {
        "id": "confidential_computing",
        "query": "hardware enclave remote attestation for private computation",
        "label": lambda text: _has(
            text,
            r"\b(confidential computing|trusted execution|tee|sgx|sev|tdx|attestation|enclave)\b",
        ),
    },
    {
        "id": "runtime_detection",
        "query": "kernel telemetry for detecting intrusions at runtime",
        "label": lambda text: _has(
            text,
            r"\b(ebpf|system call|syscall|kernel tracing|runtime monitoring|runtime detection|intrusion detection|anomaly detection)\b",
        ),
    },
    {
        "id": "prompt_injection",
        "query": "attacks that manipulate language model instructions",
        "label": lambda text: _has(
            text,
            r"\b(prompt injection|jailbreak|jailbreaking|adversarial prompt|large language model|llm|language model)\b",
        )
        and _has(text, r"\b(security|safety|attack|defense|defence|guardrail|alignment|robust)\b"),
    },
    {
        "id": "program_repair",
        "query": "automatic patch synthesis for software bugs",
        "label": lambda text: _has(
            text,
            r"\b(program repair|automated repair|bug fixing|patch generation|patch synthesis|software repair)\b",
        ),
    },
    {
        "id": "fuzzing_vuln",
        "query": "automated input generation to expose crashes and vulnerabilities",
        "label": lambda text: _has(text, r"\b(fuzzing|fuzzer|fuzz testing)\b")
        and _has(text, r"\b(vulnerab|bug|crash|defect|testing|security)\b"),
    },
    {
        "id": "access_control",
        "query": "least privilege permissions for cloud applications",
        "label": lambda text: _has(
            text,
            r"\b(access control|authorization|authentication|identity|iam|permission|privilege|least privilege)\b",
        ),
    },
]


@dataclass
class Ranker:
    name: str
    rank_func: Callable[[str, list[dict[str, Any]], int], list[str]]
    cache: dict[tuple[str, int, int], list[str]] = field(default_factory=dict)

    def rank(self, query: str, records: list[dict[str, Any]], depth: int) -> list[str]:
        key = (query, id(records), depth)
        if key not in self.cache:
            self.cache[key] = self.rank_func(query, records, depth)
        return self.cache[key]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fairly evaluate saved-paper search methods with shared candidates and weak qrels."
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML.")
    parser.add_argument("--data-dir", default="data", help="Directory containing saved paper JSON files.")
    parser.add_argument(
        "--limit",
        type=int,
        default=EVALUATION_DEPTH,
        help="Ranking depth to score per method/query.",
    )
    parser.add_argument(
        "--embedding-cache",
        default="data/embeddings.pkl",
        help="Optional existing document-embedding cache for the cached-embedding suite.",
    )
    args = parser.parse_args()

    config = _load_config(args.config)
    records = _load_records(args.data_dir)
    if not records:
        raise SystemExit(f"No papers found in {args.data_dir}.")

    full_rankers = _local_rankers(config, records)
    full_rows = _evaluate(records, full_rankers, limit=args.limit)
    _print_report("full_local", records, full_rows)

    embedding_records = _attach_cached_embeddings(records, args.embedding_cache)
    if embedding_records:
        embedding_rankers = [
            *_local_rankers(config, embedding_records),
            *_cached_embedding_rankers(config, embedding_records),
        ]
        embedding_rows = _evaluate(embedding_records, embedding_rankers, limit=args.limit)
        _print_report("cached_embedding_subset", embedding_records, embedding_rows)
    else:
        print("suite,cached_embedding_subset")
        print("status,skipped_no_embedding_cache")


def _local_rankers(config: dict[str, Any], records: list[dict[str, Any]]) -> list[Ranker]:
    bm25_index = _Bm25Index(records)
    tfidf_index = _TfIdfIndex(records)
    conference_lookup = _conference_lookup(config)
    entry_concepts_cache: dict[str, dict[str, set[str]]] = {}
    query_concepts_cache: dict[str, dict[str, set[str]]] = {}
    query_tokens_cache: dict[str, list[str]] = {}
    expanded_query_cache: dict[str, str] = {}

    def keyword_score(query: str, record: dict[str, Any]) -> float:
        if query not in query_tokens_cache:
            query_tokens_cache[query] = paper_search._tokenize(query)
        return paper_search._score_paper(record["paper"], query_tokens_cache[query], query)

    def concept_score(query: str, record: dict[str, Any]) -> float:
        if query not in query_concepts_cache:
            query_concepts_cache[query] = paper_search._extract_concepts(query)
        if query not in query_tokens_cache:
            query_tokens_cache[query] = paper_search._tokenize(query)
        if query not in expanded_query_cache:
            expanded_query_cache[query] = _expanded_query(query)
        raw_concept_score = _current_concept_score(
            query,
            query_concepts_cache[query],
            query_tokens_cache[query],
            record,
            conference_lookup,
            entry_concepts_cache,
        )
        return (
            bm25_index.score(expanded_query_cache[query], record, title_weight=1.0)
            + (raw_concept_score * 0.18)
            + (keyword_score(query, record) * 0.05)
        )

    def bm25_score(query: str, record: dict[str, Any]) -> float:
        return bm25_index.score(query, record, title_weight=1.0)

    def fielded_bm25_score(query: str, record: dict[str, Any]) -> float:
        return bm25_index.score(query, record, title_weight=2.5)

    def tfidf_score(query: str, record: dict[str, Any]) -> float:
        return tfidf_index.score(query, record)

    def expanded_bm25_score(query: str, record: dict[str, Any]) -> float:
        if query not in expanded_query_cache:
            expanded_query_cache[query] = _expanded_query(query)
        return bm25_index.score(expanded_query_cache[query], record, title_weight=1.0)

    def bm25_plus_concept_score(query: str, record: dict[str, Any]) -> float:
        return bm25_score(query, record) + 0.35 * concept_score(query, record)

    scorers: dict[str, Callable[[str, dict[str, Any]], float]] = {
        "current_keyword": keyword_score,
        "current_concept": concept_score,
        "bm25": bm25_score,
        "fielded_bm25": fielded_bm25_score,
        "tfidf": tfidf_score,
        "expanded_bm25": expanded_bm25_score,
        "bm25_plus_concept": bm25_plus_concept_score,
    }

    rankers = [
        Ranker(name, lambda query, items, depth, scorer=scorer: _rank_by_score(query, items, depth, scorer))
        for name, scorer in scorers.items()
    ]
    ranker_map = {ranker.name: ranker for ranker in rankers}
    rankers.append(
        Ranker(
            "rrf_bm25_concept",
            lambda query, items, depth: _rrf_rank(
                [
                    ranker_map["bm25"].rank(query, items, depth),
                    ranker_map["current_concept"].rank(query, items, depth),
                ],
                depth,
            ),
        )
    )
    rankers.append(
        Ranker(
            "rrf_bm25_concept_tfidf",
            lambda query, items, depth: _rrf_rank(
                [
                    ranker_map["bm25"].rank(query, items, depth),
                    ranker_map["current_concept"].rank(query, items, depth),
                    ranker_map["tfidf"].rank(query, items, depth),
                ],
                depth,
            ),
        )
    )
    return rankers


def _cached_embedding_rankers(config: dict[str, Any], records: list[dict[str, Any]]) -> list[Ranker]:
    local_ranker_map = {ranker.name: ranker for ranker in _local_rankers(config, records)}

    def embedding_prf_rank(seed_ranker_name: str, query: str, items: list[dict[str, Any]], depth: int) -> list[str]:
        seed_ranking = local_ranker_map[seed_ranker_name].rank(query, items, min(depth, 50))
        return _rank_by_embedding_centroid(seed_ranking[:10], items, depth)

    return [
        Ranker(
            "embedding_prf_bm25",
            lambda query, items, depth: embedding_prf_rank("bm25", query, items, depth),
        ),
        Ranker(
            "embedding_prf_current_concept",
            lambda query, items, depth: embedding_prf_rank("current_concept", query, items, depth),
        ),
        Ranker(
            "rrf_bm25_embedding_prf",
            lambda query, items, depth: _rrf_rank(
                [
                    local_ranker_map["bm25"].rank(query, items, depth),
                    embedding_prf_rank("bm25", query, items, depth),
                ],
                depth,
            ),
        ),
        Ranker(
            "rrf_concept_embedding_prf",
            lambda query, items, depth: _rrf_rank(
                [
                    local_ranker_map["current_concept"].rank(query, items, depth),
                    embedding_prf_rank("current_concept", query, items, depth),
                ],
                depth,
            ),
        ),
    ]


def _evaluate(records: list[dict[str, Any]], rankers: list[Ranker], limit: int) -> list[dict[str, Any]]:
    rows = []
    for query_spec in TOPIC_QUERIES:
        relevant = {
            record["uid"]
            for record in records
            if query_spec["label"](record["lower_text"])
        }
        if len(relevant) < 3:
            continue

        query = query_spec["query"]
        for ranker in rankers:
            ranking = ranker.rank(query, records, limit)
            rows.append(
                {
                    "query": query_spec["id"],
                    "rel": len(relevant),
                    "method": ranker.name,
                    **_metrics(ranking, relevant),
                }
            )
    return rows


def _print_report(suite_name: str, records: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    print(f"suite,{suite_name}")
    print(f"candidate_records,{len(records)}")
    print(f"weak_labeled_queries,{len({row['query'] for row in rows})}")
    print()

    print("aggregate")
    print("method,p@10,r@50,ndcg@10,map@50")
    method_names = sorted({row["method"] for row in rows})
    for method in method_names:
        method_rows = [row for row in rows if row["method"] == method]
        values = ",".join(
            f"{mean(row[key] for row in method_rows):.3f}"
            for key in ["p@10", "r@50", "ndcg@10", "map@50"]
        )
        print(f"{method},{values}")
    print()

    print("per_query_best")
    print("query,rel,best_method,ndcg@10,p@10")
    for query in sorted({row["query"] for row in rows}):
        query_rows = [row for row in rows if row["query"] == query]
        best = max(query_rows, key=lambda row: (row["ndcg@10"], row["map@50"]))
        print(f"{query},{best['rel']},{best['method']},{best['ndcg@10']:.3f},{best['p@10']:.3f}")
    print()

    print("details")
    print("query,rel,method,p@10,r@50,ndcg@10,map@50")
    for row in sorted(rows, key=lambda item: (item["query"], item["method"])):
        print(
            f"{row['query']},{row['rel']},{row['method']},"
            f"{row['p@10']:.3f},{row['r@50']:.3f},{row['ndcg@10']:.3f},{row['map@50']:.3f}"
        )
    print()


def _load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_records(data_dir: str) -> list[dict[str, Any]]:
    records = []
    for path in sorted(glob(os.path.join(data_dir, "*.json"))):
        file_conference, file_year = _parse_output_filename(path)
        for index, paper in enumerate(_load_paper_file(path)):
            if not paper.get("title"):
                continue
            if paper_search._is_noise_paper(paper):
                continue
            text = paper_search._paper_text(paper)
            records.append(
                {
                    "uid": f"{os.path.basename(path)}:{index}",
                    "paper": paper,
                    "title": paper.get("title") or "",
                    "file_conference": file_conference,
                    "file_year": file_year,
                    "text": text,
                    "lower_text": text.lower(),
                    "tokens": _tokenize(text),
                    "title_tokens": _tokenize(paper.get("title") or ""),
                }
            )
    return records


def _load_paper_file(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _attach_cached_embeddings(records: list[dict[str, Any]], cache_path: str) -> list[dict[str, Any]]:
    if not os.path.exists(cache_path):
        return []
    try:
        with open(cache_path, "rb") as f:
            cache = pickle.load(f)
    except (OSError, pickle.PickleError, ValueError):
        return []

    ids = cache.get("ids", [])
    embeddings = cache.get("embeddings", [])
    if len(ids) != len(embeddings):
        return []

    embedding_map = {
        title: np.asarray(embedding, dtype=float)
        for title, embedding in zip(ids, embeddings)
    }
    enriched = []
    seen_titles = set()
    for record in records:
        title = record["title"]
        embedding = embedding_map.get(title)
        if embedding is None or title in seen_titles:
            continue
        seen_titles.add(title)
        enriched_record = dict(record)
        enriched_record["embedding"] = embedding
        enriched.append(enriched_record)
    return enriched


def _parse_output_filename(path: str) -> tuple[str, int | None]:
    name = os.path.basename(path)
    match = re.match(r"(.+)_(\d{4})\.json$", name)
    if not match:
        return os.path.splitext(name)[0], None
    return match.group(1), int(match.group(2))


def _conference_lookup(config: dict[str, Any]) -> dict[str, Any]:
    lookup = {}
    for entry in normalize_conferences(config):
        for value in [entry.id, entry.display_name, *entry.aliases]:
            lookup[paper_search._normalize_key(value)] = entry
    return lookup


def _current_concept_score(
    query: str,
    query_concepts: dict[str, set[str]],
    query_tokens: list[str],
    record: dict[str, Any],
    conference_lookup: dict[str, Any],
    entry_concepts_cache: dict[str, dict[str, set[str]]],
) -> float:
    keyword_score = paper_search._score_paper(record["paper"], query_tokens, query)
    entry = conference_lookup.get(paper_search._normalize_key(record["file_conference"]))
    entry_concepts = {}
    if entry:
        if entry.id not in entry_concepts_cache:
            entry_concepts_cache[entry.id] = paper_search._entry_concepts(entry)
        entry_concepts = entry_concepts_cache[entry.id]
    concept_score, _matched = paper_search._score_concepts(
        record["paper"],
        query_concepts,
        paper_text=record["text"],
        entry_concepts=entry_concepts,
    )
    return keyword_score + concept_score


class _Bm25Index:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.doc_count = len(records)
        self.average_doc_length = (
            sum(len(record["tokens"]) for record in records) / self.doc_count
            if self.doc_count
            else 1.0
        )
        document_frequency: Counter[str] = Counter()
        for record in records:
            document_frequency.update(set(record["tokens"]))
        self.idf = {
            token: math.log(1 + (self.doc_count - count + 0.5) / (count + 0.5))
            for token, count in document_frequency.items()
        }
        self.query_tokens_cache: dict[str, list[str]] = {}

    def score(self, query: str, record: dict[str, Any], title_weight: float = 1.0) -> float:
        if query not in self.query_tokens_cache:
            self.query_tokens_cache[query] = _tokenize(query)
        query_tokens = self.query_tokens_cache[query]
        if not query_tokens:
            return 0.0

        counts = Counter(record["tokens"])
        title_tokens = set(record["title_tokens"])
        doc_length = max(len(record["tokens"]), 1)
        k1 = 1.5
        b = 0.75
        score = 0.0
        for token in query_tokens:
            term_frequency = counts.get(token, 0)
            if not term_frequency:
                continue
            token_score = self.idf.get(token, 0.0) * (
                (term_frequency * (k1 + 1))
                / (term_frequency + k1 * (1 - b + b * doc_length / self.average_doc_length))
            )
            if token in title_tokens:
                token_score *= title_weight
            score += token_score
        return score


class _TfIdfIndex:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.doc_count = len(records)
        document_frequency: Counter[str] = Counter()
        self.document_vectors: dict[str, dict[str, float]] = {}
        for record in records:
            document_frequency.update(set(record["tokens"]))

        self.idf = {
            token: math.log((self.doc_count + 1) / (count + 1)) + 1
            for token, count in document_frequency.items()
        }
        for record in records:
            weighted_tokens = list(record["tokens"]) + record["title_tokens"] * 2
            vector = _tfidf_vector(weighted_tokens, self.idf)
            self.document_vectors[record["uid"]] = _normalize_sparse_vector(vector)
        self.query_vector_cache: dict[str, dict[str, float]] = {}

    def score(self, query: str, record: dict[str, Any]) -> float:
        if query not in self.query_vector_cache:
            self.query_vector_cache[query] = _normalize_sparse_vector(_tfidf_vector(_tokenize(query), self.idf))
        query_vector = self.query_vector_cache[query]
        if not query_vector:
            return 0.0
        document_vector = self.document_vectors.get(record["uid"], {})
        return sum(query_value * document_vector.get(token, 0.0) for token, query_value in query_vector.items())


def _rank_by_score(
    query: str,
    records: list[dict[str, Any]],
    limit: int,
    scorer: Callable[[str, dict[str, Any]], float],
) -> list[str]:
    scored = []
    for record in records:
        score = scorer(query, record)
        if score > 0:
            scored.append((score, record["file_year"] or 0, record["uid"]))
    scored.sort(reverse=True)
    return [uid for _score, _year, uid in scored[:limit]]


def _rank_by_embedding_centroid(seed_uids: list[str], records: list[dict[str, Any]], limit: int) -> list[str]:
    record_by_uid = {record["uid"]: record for record in records}
    seed_embeddings = [
        record_by_uid[uid]["embedding"]
        for uid in seed_uids
        if uid in record_by_uid and "embedding" in record_by_uid[uid]
    ]
    if not seed_embeddings:
        return []

    centroid = np.mean(seed_embeddings, axis=0)
    centroid_norm = np.linalg.norm(centroid)
    if centroid_norm == 0:
        return []

    scored = []
    for record in records:
        embedding = record.get("embedding")
        if embedding is None:
            continue
        embedding_norm = np.linalg.norm(embedding)
        if embedding_norm == 0:
            continue
        score = float(np.dot(embedding, centroid) / (embedding_norm * centroid_norm))
        scored.append((score, record["file_year"] or 0, record["uid"]))
    scored.sort(reverse=True)
    return [uid for _score, _year, uid in scored[:limit]]


def _rrf_rank(rankings: list[list[str]], limit: int, k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, uid in enumerate(ranking, start=1):
            scores[uid] = scores.get(uid, 0.0) + 1 / (k + rank)
    return [
        uid
        for uid, _score in sorted(scores.items(), key=lambda item: (item[1], item[0]), reverse=True)[:limit]
    ]


def _metrics(ranking: list[str], relevant: set[str]) -> dict[str, float]:
    total_relevant = len(relevant)
    precision_at_10 = sum(uid in relevant for uid in ranking[:10]) / 10
    recall_at_50 = sum(uid in relevant for uid in ranking[:50]) / total_relevant if total_relevant else 0.0

    def dcg(limit: int) -> float:
        return sum(
            1 / math.log2(index + 2)
            for index, uid in enumerate(ranking[:limit])
            if uid in relevant
        )

    ideal_dcg = sum(1 / math.log2(index + 2) for index in range(min(total_relevant, 10)))
    ndcg_at_10 = dcg(10) / ideal_dcg if ideal_dcg else 0.0

    average_precision = 0.0
    hits = 0
    for index, uid in enumerate(ranking[:50], start=1):
        if uid in relevant:
            hits += 1
            average_precision += hits / index
    map_at_50 = average_precision / min(total_relevant, 50) if total_relevant else 0.0
    return {
        "p@10": precision_at_10,
        "r@50": recall_at_50,
        "ndcg@10": ndcg_at_10,
        "map@50": map_at_50,
    }


def _expanded_query(query: str) -> str:
    concepts = paper_search._extract_concepts(query)
    aliases = []
    for concept in concepts:
        aliases.extend(paper_search.CONCEPT_LEXICON[concept]["aliases"][:8])
    if not aliases:
        return query
    return " ".join([query, *aliases])


def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    counts = Counter(tokens)
    total = sum(counts.values()) or 1
    return {
        token: (count / total) * idf.get(token, 0.0)
        for token, count in counts.items()
        if token in idf
    }


def _normalize_sparse_vector(vector: dict[str, float]) -> dict[str, float]:
    norm = math.sqrt(sum(value * value for value in vector.values()))
    if norm == 0:
        return {}
    return {token: value / norm for token, value in vector.items()}


def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


def _has(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text, re.IGNORECASE))


if __name__ == "__main__":
    main()
