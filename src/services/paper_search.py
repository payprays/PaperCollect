import json
import math
import os
import re
import threading
from collections import Counter
from collections.abc import Sequence
from difflib import SequenceMatcher
from functools import lru_cache
from glob import glob
from typing import Any

from src.core.conference_catalog import ConferenceEntry, find_conference, normalize_conferences

SEARCH_MODES = {"keyword", "concept", "agentic"}
MIN_CONCEPT_TOPIC_SCORE = 8.0
_INDEX_CACHE: dict[str, tuple[tuple[tuple[str, float, int], ...], list[dict[str, Any]]]] = {}
_INDEX_LOCK = threading.Lock()
TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-z0-9][a-z0-9+#.]*")
NOISE_TITLE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"^\s*poster\s*:",
        r"\bproceedings\b",
        r"\bcompanion proceedings\b",
        r"\bchair'?s?\s+message\b",
        r"\bmessage from\b",
        r"\bwelcome message\b",
        r"\bkeynote\b",
        r"\bfront matter\b",
        r"^\s*(organizing|program|technical program|steering|conference)\s+committee\b",
        r"\bcommittee\s+(members|list)\b",
        r"\bcall for papers\b",
        r"\bdoctoral consortium\b",
        r"\bstudent abstract\b",
        r"\bdissertation research description\b",
        r"^\s*\d+(st|nd|rd|th)\s+.*\b(conference|symposium|workshop)\b.*\b\d{4}\b",
        r"^\s*\d+(st|nd|rd|th)\s+international\s+(conference|symposium|workshop)\b",
    ]
]

CONCEPT_LEXICON = {
    "cloud_native": {
        "label": "Cloud Native",
        "aliases": [
            "cloud native",
            "cloud-native",
            "kubernetes",
            "k8s",
            "container orchestration",
            "containerized",
            "microservice",
            "microservices",
            "serverless",
            "function as a service",
            "faas",
            "service mesh",
            "istio",
            "helm",
            "operator",
            "云原生",
            "容器编排",
            "微服务",
            "服务网格",
            "无服务器",
        ],
    },
    "kubernetes_security": {
        "label": "Kubernetes Security",
        "aliases": [
            "kubernetes security",
            "k8s security",
            "admission controller",
            "admission control",
            "rbac",
            "pod security",
            "cluster security",
            "kubernetes policy",
            "kubernetes cluster",
            "k8s cluster",
            "k8s",
            "kubernetes",
            "准入控制",
            "集群安全",
            "权限控制",
        ],
    },
    "software_supply_chain": {
        "label": "Software Supply Chain",
        "aliases": [
            "software supply chain",
            "supply chain",
            "sbom",
            "software bill of materials",
            "dependency confusion",
            "package manager",
            "package repository",
            "npm",
            "pypi",
            "container image",
            "image provenance",
            "artifact provenance",
            "provenance",
            "slsa",
            "ci/cd",
            "build pipeline",
            "registry",
            "供应链",
            "软件供应链",
            "依赖混淆",
            "软件物料清单",
            "镜像",
            "制品",
            "来源证明",
        ],
    },
    "container_isolation": {
        "label": "Container Isolation",
        "aliases": [
            "container isolation",
            "container escape",
            "container breakout",
            "namespace isolation",
            "linux namespace",
            "cgroup",
            "seccomp",
            "apparmor",
            "sandbox",
            "sandboxing",
            "runc",
            "容器隔离",
            "容器逃逸",
            "命名空间",
            "沙箱",
        ],
    },
    "runtime_security": {
        "label": "Runtime Security",
        "aliases": [
            "runtime security",
            "runtime monitoring",
            "runtime detection",
            "ebpf",
            "eBPF",
            "kernel tracing",
            "system call",
            "syscall",
            "intrusion detection",
            "anomaly detection",
            "运行时安全",
            "运行时检测",
            "异常检测",
            "入侵检测",
            "系统调用",
        ],
    },
    "cloud_security": {
        "label": "Cloud Security",
        "aliases": [
            "cloud security",
            "cloud platform",
            "multi tenant",
            "multi-tenant",
            "tenant isolation",
            "iaas",
            "paas",
            "serverless security",
            "cloud workload",
            "云安全",
            "多租户",
            "租户隔离",
            "云平台",
        ],
    },
    "confidential_computing": {
        "label": "Confidential Computing",
        "aliases": [
            "confidential computing",
            "trusted execution",
            "trusted execution environment",
            "tee",
            "sgx",
            "sev",
            "tdx",
            "attestation",
            "enclave",
            "机密计算",
            "可信执行环境",
            "远程证明",
        ],
    },
    "vulnerability_detection": {
        "label": "Vulnerability Detection",
        "aliases": [
            "vulnerability detection",
            "vulnerability discovery",
            "bug finding",
            "fuzzing",
            "static analysis",
            "dynamic analysis",
            "taint analysis",
            "program analysis",
            "malicious",
            "attack detection",
            "threat detection",
            "漏洞检测",
            "漏洞发现",
            "模糊测试",
            "污点分析",
            "攻击检测",
            "威胁检测",
            "恶意",
        ],
    },
    "access_control": {
        "label": "Access Control",
        "aliases": [
            "access control",
            "authorization",
            "authentication",
            "identity",
            "iam",
            "permission",
            "privilege",
            "least privilege",
            "访问控制",
            "认证",
            "授权",
            "身份",
            "权限",
            "最小权限",
        ],
    },
    "program_repair": {
        "label": "Program Repair",
        "aliases": [
            "program repair",
            "automated repair",
            "patch generation",
            "bug fixing",
            "neural program repair",
            "程序修复",
            "自动修复",
            "补丁生成",
        ],
    },
}


def search_saved_papers(
    config: dict[str, Any],
    output_dir: str,
    query: str,
    category: str | None = None,
    focus: str | None = None,
    conference: str | None = None,
    conferences: Sequence[str] | None = None,
    ccf: str | None = None,
    year: int | None = None,
    limit: int = 25,
    mode: str = "keyword",
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Search saved JSON paper files without requiring embeddings or API keys."""
    if mode not in SEARCH_MODES:
        raise ValueError("Search mode must be keyword, concept, or agentic.")

    if mode == "agentic":
        return _search_agentic_or_fallback(
            config,
            output_dir,
            query,
            category=category,
            focus=focus,
            conference=conference,
            conferences=conferences,
            ccf=ccf,
            year=year,
            limit=limit,
        )

    query = _normalize_query_text(query)
    query_years = _extract_query_years(query)
    if year is None and len(query_years) == 1:
        year = next(iter(query_years))
    if query_years:
        query = _strip_query_years(query, query_years)
    tokens = _tokenize(query)
    query_concepts = _extract_concepts(query, allow_fuzzy=True) if mode == "concept" else {}
    conference_filters = _conference_filter_ids(config, conference, conferences)
    ccf_filter = _normalize_ccf_filter(ccf)
    conference_lookup = _conference_lookup(config)
    entry_concepts_cache: dict[str, dict[str, set[str]]] = {}
    candidates = []

    for record in _load_search_records(output_dir):
        paper = record["paper"]
        if _is_noise_paper(paper):
            continue
        file_conference = record["file_conference"]
        file_year = record["file_year"]
        if year and file_year != year:
            continue

        entry = conference_lookup.get(_normalize_key(file_conference))
        if conference_filters and (not entry or entry.id not in conference_filters):
            continue
        if category and (not entry or entry.category != category):
            continue
        if ccf_filter and (not entry or _normalize_ccf_filter(entry.tier.get("ccf")) != ccf_filter):
            continue
        if focus and (not entry or focus not in entry.focus_tags):
            continue

        candidates.append((record, entry))

    bm25_index = _build_bm25_index([record for record, _entry in candidates])
    expanded_tokens = _expanded_query_tokens(query, query_concepts) if mode == "concept" else []
    results = []

    for record, entry in candidates:
        paper = record["paper"]
        file_conference = record["file_conference"]
        file_year = record["file_year"]
        keyword_score = _score_paper(
            paper,
            tokens,
            query,
            entry=entry,
            file_conference=file_conference,
        )
        concept_score = 0.0
        lexical_score = 0.0
        matched_concepts: list[str] = []
        if mode == "concept":
            entry_concepts = {}
            if entry:
                if entry.id not in entry_concepts_cache:
                    entry_concepts_cache[entry.id] = _entry_concepts(entry)
                entry_concepts = entry_concepts_cache[entry.id]
            concept_score, matched_concepts = _score_concepts(
                paper,
                query_concepts,
                paper_text=record["text"],
                entry_concepts=entry_concepts,
            )
            lexical_score = _score_bm25(record, expanded_tokens, bm25_index, title_weight=1.0)
        score = (
            keyword_score
            if mode == "keyword"
            else lexical_score + (concept_score * 0.18) + (keyword_score * 0.05)
        )
        if (
            mode == "concept"
            and query_concepts
            and concept_score < MIN_CONCEPT_TOPIC_SCORE
            and keyword_score < 8.0
        ):
            continue
        if tokens and score <= 0:
            continue

        result = {
            "title": paper.get("title") or "Untitled paper",
            "authors": paper.get("authors") or [],
            "venue": paper.get("venue") or (entry.display_name if entry else file_conference),
            "year": paper.get("year") or file_year,
            "abstract": paper.get("abstract"),
            "url": paper.get("url"),
            "dblp_key": paper.get("dblp_key"),
            "score": score,
            "conference": entry.id if entry else file_conference,
            "display_name": entry.display_name if entry else file_conference,
            "category": entry.category if entry else None,
            "category_name": entry.category_name if entry else None,
            "tier": entry.tier if entry else {},
            "focus_tags": list(entry.focus_tags) if entry else [],
            "search_mode": mode,
            "matched_concepts": matched_concepts,
            "concept_score": concept_score,
            "lexical_score": lexical_score,
        }
        results.append(result)

    results.sort(key=lambda item: (item["score"], item.get("year") or 0), reverse=True)
    return results[offset:offset + limit]


def _search_agentic_or_fallback(
    config: dict[str, Any],
    output_dir: str,
    query: str,
    *,
    category: str | None,
    focus: str | None,
    conference: str | None,
    conferences: Sequence[str] | None,
    ccf: str | None,
    year: int | None,
    limit: int,
) -> list[dict[str, Any]]:
    try:
        from src.services.vector_index import VectorIndexError, search_vector_index
    except ImportError as exc:
        fallback_reason = str(exc)
    else:
        try:
            results = search_vector_index(
                config,
                output_dir,
                query,
                category=category,
                focus=focus,
                conference=conference,
                conferences=conferences,
                ccf=ccf,
                year=year,
                limit=limit,
            )
            if results:
                return _blend_agentic_with_concept_scores(
                    config,
                    output_dir,
                    query,
                    results,
                    category=category,
                    focus=focus,
                    conference=conference,
                    conferences=conferences,
                    ccf=ccf,
                    year=year,
                    limit=limit,
                )
            fallback_reason = "vector search returned no matches"
        except (VectorIndexError, OSError, RuntimeError, ValueError) as exc:
            fallback_reason = str(exc)

    fallback_results = search_saved_papers(
        config,
        output_dir,
        query,
        category=category,
        focus=focus,
        conference=conference,
        conferences=conferences,
        ccf=ccf,
        year=year,
        limit=limit,
        mode="concept",
    )
    for result in fallback_results:
        result["search_mode"] = "agentic_fallback"
        result["retrieval_backend"] = "concept_semantic"
        result["fallback_reason"] = fallback_reason
        result["score_details"] = {
            "fallback": "concept",
            "reason": fallback_reason,
        }
        result["provenance"] = {
            "dblp_key": result.get("dblp_key"),
            "url": result.get("url"),
            "conference": result.get("conference"),
            "year": result.get("year"),
        }
    return fallback_results


def _blend_agentic_with_concept_scores(
    config: dict[str, Any],
    output_dir: str,
    query: str,
    agentic_results: list[dict[str, Any]],
    *,
    category: str | None,
    focus: str | None,
    conference: str | None,
    conferences: Sequence[str] | None,
    ccf: str | None,
    year: int | None,
    limit: int,
) -> list[dict[str, Any]]:
    concept_results = search_saved_papers(
        config,
        output_dir,
        query,
        category=category,
        focus=focus,
        conference=conference,
        conferences=conferences,
        ccf=ccf,
        year=year,
        limit=max(limit * 4, 30),
        mode="concept",
    )
    concept_by_identity = {_result_identity(result): result for result in concept_results}
    concept_scores = {
        identity: float(result.get("score") or 0.0)
        for identity, result in concept_by_identity.items()
    }
    max_vector_score = max(
        (float(result.get("score") or 0.0) for result in agentic_results),
        default=0.0,
    ) or 1.0
    max_concept_score = max(concept_scores.values(), default=0.0) or 1.0
    vector_weight = 0.45 if concept_results else 1.0
    concept_weight = 0.55 if concept_results else 0.0
    merged: dict[tuple[object, object, object, object], dict[str, Any]] = {}

    for result in agentic_results:
        result = dict(result)
        identity = _result_identity(result)
        vector_score = float(result.get("score") or 0.0)
        vector_norm = vector_score / max_vector_score
        concept_result = concept_by_identity.get(identity)
        concept_score = concept_scores.get(identity, 0.0)
        concept_norm = concept_score / max_concept_score
        result["score"] = (vector_weight * vector_norm) + (concept_weight * concept_norm)
        if concept_result:
            result["matched_concepts"] = concept_result.get("matched_concepts", [])
            result["concept_score"] = concept_result.get("concept_score", 0.0)
            result["lexical_score"] = concept_result.get("lexical_score", 0.0)
        details = dict(result.get("score_details") or {})
        details.update(
            {
                "fusion": "rrf+concept",
                "vector_score": vector_score,
                "vector_norm": vector_norm,
                "concept_rerank_score": concept_score,
                "concept_norm": concept_norm,
            }
        )
        result["score_details"] = details
        merged[identity] = result

    for identity, concept_result in concept_by_identity.items():
        if identity in merged:
            continue
        concept_score = concept_scores.get(identity, 0.0)
        concept_norm = concept_score / max_concept_score
        result = dict(concept_result)
        result["score"] = concept_weight * concept_norm
        result["search_mode"] = "agentic"
        result["retrieval_backend"] = "concept_semantic_merge"
        result["snippet"] = _result_snippet(result, query)
        result["score_details"] = {
            "fusion": "vector_concept_merge",
            "vector_score": 0.0,
            "vector_norm": 0.0,
            "concept_rerank_score": concept_score,
            "concept_norm": concept_norm,
        }
        result["provenance"] = {
            "dblp_key": result.get("dblp_key"),
            "url": result.get("url"),
            "conference": result.get("conference"),
            "year": result.get("year"),
        }
        merged[identity] = result

    results = list(merged.values())
    results.sort(key=lambda item: (item["score"], item.get("year") or 0), reverse=True)
    return results[:limit]


def _result_identity(result: dict[str, Any]) -> tuple[object, object, object, object]:
    return (
        result.get("dblp_key"),
        result.get("source_id"),
        result.get("conference"),
        result.get("title"),
    )


def _result_snippet(result: dict[str, Any], query: str, length: int = 360) -> str:
    text = " ".join(
        str(value)
        for value in [result.get("title"), result.get("abstract")]
        if value
    ).strip()
    if not text:
        return ""

    tokens = _tokenize(query)
    lowered = text.lower()
    start = 0
    for token in tokens:
        index = lowered.find(token.lower())
        if index >= 0:
            start = max(index - 80, 0)
            break
    snippet = text[start : start + length].strip()
    return snippet


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


def _normalize_ccf_filter(value: object) -> str | None:
    text = str(value or "").strip().upper()
    return text or None


def _conference_lookup(config: dict[str, Any]) -> dict[str, ConferenceEntry]:
    lookup = {}
    for entry in normalize_conferences(config):
        for value in [entry.id, entry.display_name, *entry.aliases]:
            lookup[_normalize_key(value)] = entry
    return lookup


def _load_search_records(output_dir: str) -> list[dict[str, Any]]:
    signature = _data_signature(output_dir)
    with _INDEX_LOCK:
        cached = _INDEX_CACHE.get(output_dir)
        if cached and cached[0] == signature:
            return cached[1]

    records = []
    for path, _mtime, _size in signature:
        file_conference, file_year = _parse_output_filename(path)
        for paper in _load_paper_file(path):
            text = _paper_text(paper)
            records.append(
                {
                    "paper": paper,
                    "file_conference": file_conference,
                    "file_year": file_year,
                    "text": text,
                    "tokens": _tokenize(text),
                    "title_tokens": _tokenize(str(paper.get("title") or "")),
                }
            )

    with _INDEX_LOCK:
        _INDEX_CACHE[output_dir] = (signature, records)
    return records


def _data_signature(output_dir: str) -> tuple[tuple[str, float, int], ...]:
    signature = []
    for path in sorted(glob(os.path.join(output_dir, "*.json"))):
        try:
            stat = os.stat(path)
        except OSError:
            continue
        signature.append((path, stat.st_mtime, stat.st_size))
    return tuple(signature)


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


def _score_paper(
    paper: dict[str, Any],
    tokens: list[str],
    query: str,
    entry: ConferenceEntry | None = None,
    file_conference: str | None = None,
) -> float:
    if not tokens:
        return 0.0

    title = str(paper.get("title") or "")
    abstract = str(paper.get("abstract") or "")
    authors = " ".join(str(author) for author in (paper.get("authors") or []))
    venue_values = [
        paper.get("venue"),
        file_conference,
    ]
    if entry:
        venue_values.extend(
            [
                entry.id,
                entry.display_name,
                entry.full_name,
                *entry.aliases,
                entry.category,
                entry.category_name,
                " ".join(entry.focus_tags),
            ]
        )
    venue_text = " ".join(str(value or "").replace("_", " ") for value in venue_values)
    haystacks = [
        (title.lower(), 5.0),
        (abstract.lower(), 2.0),
        (venue_text.lower(), 4.0),
        (authors.lower(), 1.0),
    ]

    score = 0.0
    for token in tokens:
        for text, weight in haystacks:
            if token in text:
                score += weight

    phrase = query.lower()
    if phrase and phrase in title.lower():
        score += 8.0
    elif phrase and phrase in abstract.lower():
        score += 3.0
    elif phrase and phrase in venue_text.lower():
        score += 6.0

    return score


def _build_bm25_index(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"idf": {}, "average_doc_length": 1.0}

    document_frequency: Counter[str] = Counter()
    total_length = 0
    for record in records:
        tokens = record.get("tokens") or []
        total_length += len(tokens)
        document_frequency.update(set(tokens))

    document_count = len(records)
    return {
        "average_doc_length": total_length / document_count if document_count else 1.0,
        "idf": {
            token: math.log(1 + (document_count - count + 0.5) / (count + 0.5))
            for token, count in document_frequency.items()
        },
    }


def _score_bm25(
    record: dict[str, Any],
    query_tokens: list[str],
    index: dict[str, Any],
    title_weight: float = 1.0,
) -> float:
    if not query_tokens:
        return 0.0

    counts = Counter(record.get("tokens") or [])
    title_tokens = set(record.get("title_tokens") or [])
    document_length = max(len(record.get("tokens") or []), 1)
    average_doc_length = index["average_doc_length"] or 1.0
    idf = index["idf"]
    k1 = 1.5
    b = 0.75
    score = 0.0

    for token in query_tokens:
        term_frequency = counts.get(token, 0)
        if not term_frequency:
            continue
        token_score = idf.get(token, 0.0) * (
            (term_frequency * (k1 + 1))
            / (term_frequency + k1 * (1 - b + b * document_length / average_doc_length))
        )
        if token in title_tokens:
            token_score *= title_weight
        score += token_score

    return score


def _score_concepts(
    paper: dict[str, Any],
    query_concepts: dict[str, set[str]],
    paper_text: str | None = None,
    entry_concepts: dict[str, set[str]] | None = None,
) -> tuple[float, list[str]]:
    if not query_concepts:
        return 0.0, []

    paper_text = paper_text or _paper_text(paper)
    paper_title = str(paper.get("title") or "")
    paper_abstract = str(paper.get("abstract") or "")
    entry_concepts = entry_concepts or {}
    matched = []
    score = 0.0
    has_title_concept_match = False
    abstract_aliases: set[str] = set()

    for concept in query_concepts:
        title_matches = _matched_aliases(paper_title, concept)
        abstract_matches = _matched_aliases(paper_abstract, concept)
        if not title_matches and not abstract_matches:
            continue

        matched.append(concept)
        if title_matches:
            has_title_concept_match = True
            score += 10.0 + min(len(title_matches), 3) * 1.2
        if abstract_matches:
            abstract_aliases.update(abstract_matches)
            score += 3.0 + min(len(abstract_matches), 3) * 0.6
        score += min(
            len(query_concepts[concept])
            + len(entry_concepts.get(concept, set()))
            + len(title_matches)
            + len(abstract_matches),
            5,
        ) * 0.4

    # Light expansion: closely related cloud-native concepts should help each other
    # without turning concept search into a broad vector-style blur.
    if "cloud_native" in query_concepts and _matches_concept(paper_text, "kubernetes_security"):
        score += 4.0
    if "software_supply_chain" in query_concepts and _matches_concept(paper_text, "container_isolation"):
        score += 2.5
    if "cloud_security" in query_concepts and _matches_concept(paper_text, "confidential_computing"):
        score += 2.5

    if not has_title_concept_match and len(abstract_aliases) <= 1:
        score = min(score, 6.0)

    return score, [CONCEPT_LEXICON[concept]["label"] for concept in matched]


def _matches_concept(text: str, concept: str) -> bool:
    return bool(_matched_aliases(text, concept))


def _matched_aliases(text: str, concept: str) -> set[str]:
    normalized_text = text.lower()
    return {
        alias
        for alias in CONCEPT_LEXICON[concept]["aliases"]
        if _contains_alias_in_lower(normalized_text, alias.lower())
    }


def _entry_concepts(entry: ConferenceEntry) -> dict[str, set[str]]:
    text = " ".join(
        str(value or "").replace("_", " ")
        for value in [
            entry.display_name,
            entry.full_name,
            entry.category,
            entry.category_name,
            entry.category_name_zh,
            " ".join(entry.focus_tags),
        ]
    )
    return _extract_concepts(text)


def _extract_concepts(text: str, allow_fuzzy: bool = False) -> dict[str, set[str]]:
    normalized_text = text.lower()
    concepts: dict[str, set[str]] = {}
    for concept, definition in CONCEPT_LEXICON.items():
        aliases = definition["aliases"]
        matches = {
            alias
            for alias in aliases
            if _contains_alias_in_lower(normalized_text, alias.lower())
        }
        if allow_fuzzy and not matches:
            matches = _fuzzy_alias_matches(normalized_text, aliases)
        if matches:
            concepts[concept] = matches
    return concepts


def _expanded_query_tokens(query: str, query_concepts: dict[str, set[str]]) -> list[str]:
    terms = [query]
    for concept in query_concepts:
        terms.extend(CONCEPT_LEXICON[concept]["aliases"][:8])
    return _dedupe_preserve_order(_tokenize(" ".join(terms)))


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _paper_text(paper: dict[str, Any]) -> str:
    authors = " ".join(str(author) for author in (paper.get("authors") or []))
    focus_tags = " ".join(str(tag).replace("_", " ") for tag in (paper.get("focus_tags") or []))
    return " ".join(
        str(value or "")
        for value in [
            paper.get("title"),
            paper.get("abstract"),
            paper.get("venue"),
            authors,
            focus_tags,
        ]
    )


def _is_noise_paper(paper: dict[str, Any]) -> bool:
    title = str(paper.get("title") or "")
    if not title:
        return False
    return any(pattern.search(title) for pattern in NOISE_TITLE_PATTERNS)


def _contains_any_alias(text: str, aliases: list[str]) -> bool:
    normalized_text = text.lower()
    return any(_contains_alias_in_lower(normalized_text, alias.lower()) for alias in aliases)


def _contains_alias(text: str, alias: str) -> bool:
    if not text or not alias:
        return False
    return _contains_alias_in_lower(text.lower(), alias.lower())


def _contains_alias_in_lower(normalized_text: str, normalized_alias: str) -> bool:
    if not normalized_text or not normalized_alias:
        return False

    if _contains_cjk(normalized_alias):
        return normalized_alias in normalized_text

    if normalized_alias not in normalized_text:
        return False

    return _alias_pattern(normalized_alias).search(normalized_text) is not None


def _fuzzy_alias_matches(normalized_text: str, aliases: list[str]) -> set[str]:
    query_tokens = _tokenize(normalized_text)
    if not query_tokens:
        return set()

    matches = set()
    for alias in aliases:
        alias_tokens = _tokenize(alias.lower())
        if len(alias_tokens) != 1:
            continue
        alias_token = alias_tokens[0]
        if any(_is_fuzzy_token_match(token, alias_token) for token in query_tokens):
            matches.add(alias)
    return matches


def _is_fuzzy_token_match(token: str, alias_token: str) -> bool:
    if token == alias_token:
        return True
    if len(alias_token) < 6 or len(token) < 6:
        return False
    if token[0] != alias_token[0]:
        return False
    if abs(len(token) - len(alias_token)) > 2:
        return False
    return SequenceMatcher(None, token, alias_token).ratio() >= 0.86


@lru_cache(maxsize=None)
def _alias_pattern(alias: str) -> re.Pattern[str]:
    pattern = r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"
    return re.compile(pattern)


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _normalize_query_text(query: str) -> str:
    return re.sub(r"[_/\\-]+", " ", query.strip().lower())


def _extract_query_years(query: str) -> set[int]:
    return {
        int(value)
        for value in re.findall(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", query)
    }


def _strip_query_years(query: str, years: set[int]) -> str:
    stripped = query
    for value in years:
        stripped = re.sub(rf"(?<!\d){value}(?!\d)", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip()


def _tokenize(query: str) -> list[str]:
    normalized = _normalize_query_text(query)
    return TOKEN_RE.findall(normalized)


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())
