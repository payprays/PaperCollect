import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ConferenceEntry:
    id: str
    display_name: str
    full_name: str | None = None
    dblp_stream: str | None = None
    dblp_query: str | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)
    category: str | None = None
    category_name: str | None = None
    category_name_zh: str | None = None
    tier: dict[str, str] = field(default_factory=dict)
    focus_tags: tuple[str, ...] = field(default_factory=tuple)
    official_source: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    enabled: bool = True
    years: tuple[int, ...] = field(default_factory=tuple)

    def option(self, default_years: list[int]) -> dict[str, Any]:
        years = list(self.years) if self.years else default_years
        return {
            "id": self.id,
            "display_name": self.display_name,
            "full_name": self.full_name,
            "category": self.category,
            "category_name": self.category_name,
            "category_name_zh": self.category_name_zh,
            "tier": self.tier,
            "focus_tags": list(self.focus_tags),
            "years": years,
        }

    def lookup_values(self) -> set[str]:
        values = {self.id, self.display_name, *(self.aliases or ())}
        return {_normalize_lookup(value) for value in values if value}


def normalize_conferences(config: dict[str, Any], include_disabled: bool = False) -> list[ConferenceEntry]:
    entries = []
    by_id = {}
    by_lookup = {}

    for raw in config.get("conferences", []):
        entry = normalize_conference(raw)
        entries.append(entry)
        by_id[entry.id] = entry
        for value in entry.lookup_values():
            by_lookup[value] = entry

    if config.get("include_ccfddl_catalog", True):
        for raw in load_ccfddl_catalog().get("conferences", []):
            entry = normalize_conference(raw)
            existing = by_id.get(entry.id)
            if existing is None:
                existing = next((by_lookup.get(value) for value in entry.lookup_values() if value in by_lookup), None)

            if existing is not None:
                merged = _merge_entries(existing, entry)
                index = entries.index(existing)
                entries[index] = merged
                by_id[merged.id] = merged
                for value in merged.lookup_values():
                    by_lookup[value] = merged
            else:
                entries.append(entry)
                by_id[entry.id] = entry
                for value in entry.lookup_values():
                    by_lookup[value] = entry

    if include_disabled:
        return entries
    return [entry for entry in entries if entry.enabled]


def normalize_conference(raw: str | dict[str, Any] | ConferenceEntry) -> ConferenceEntry:
    if isinstance(raw, ConferenceEntry):
        return raw

    if isinstance(raw, str):
        display_name = raw
        entry_id = _slugify(display_name)
        defaults = _LEGACY_DEFAULTS.get(_normalize_lookup(display_name), {})
        aliases = _unique_strings([display_name, *defaults.get("aliases", [])])
        return ConferenceEntry(
            id=entry_id,
            display_name=display_name,
            full_name=defaults.get("full_name"),
            dblp_stream=defaults.get("dblp_stream"),
            aliases=tuple(aliases),
            category=defaults.get("category"),
            category_name=defaults.get("category_name"),
            category_name_zh=defaults.get("category_name_zh"),
            tier=defaults.get("tier", {}),
            focus_tags=tuple(defaults.get("focus_tags", ())),
            official_source=dict(defaults.get("official_source", {})),
            source=defaults.get("source"),
        )

    if not isinstance(raw, dict):
        raise ValueError(f"Unsupported conference entry: {raw!r}")

    display_name = str(raw.get("display_name") or raw.get("name") or raw.get("id") or "").strip()
    if not display_name:
        raise ValueError("Conference entry must define display_name or id.")

    entry_id = str(raw.get("id") or _slugify(display_name)).strip()
    aliases = _unique_strings([display_name, *raw.get("aliases", [])])
    years = tuple(int(year) for year in raw.get("years", []) if str(year).strip())
    focus_tags = _unique_strings([*raw.get("focus_tags", []), *_infer_focus_tags(raw)])

    return ConferenceEntry(
        id=entry_id,
        display_name=display_name,
        full_name=raw.get("full_name"),
        dblp_stream=raw.get("dblp_stream"),
        dblp_query=raw.get("dblp_query"),
        aliases=tuple(aliases),
        category=raw.get("category"),
        category_name=raw.get("category_name"),
        category_name_zh=raw.get("category_name_zh"),
        tier=dict(raw.get("tier") or raw.get("rank") or {}),
        focus_tags=tuple(focus_tags),
        official_source=dict(raw.get("official_source") or {}),
        source=raw.get("source"),
        enabled=bool(raw.get("enabled", True)),
        years=years,
    )


def find_conference(config: dict[str, Any], value: str) -> ConferenceEntry | None:
    lookup = _normalize_lookup(value)
    for entry in normalize_conferences(config):
        if lookup in entry.lookup_values():
            return entry
    return None


def configured_years(config: dict[str, Any], entry: ConferenceEntry | None = None) -> list[int]:
    if entry and entry.years:
        return list(entry.years)
    return [int(year) for year in config.get("years", [])]


def valid_collection_year(year: int) -> bool:
    return 1900 <= year <= date.today().year + 2


def catalog_categories(config: dict[str, Any]) -> list[dict[str, str]]:
    categories = load_ccfddl_catalog().get("categories", {}).copy()
    for entry in normalize_conferences(config):
        if entry.category and entry.category not in categories:
            categories[entry.category] = {
                "name": entry.category_name_zh or entry.category,
                "name_en": entry.category_name or entry.category,
            }

    return [
        {
            "id": key,
            "name": value.get("name", key),
            "name_en": value.get("name_en", key),
        }
        for key, value in categories.items()
    ]


def focus_tag_options(config: dict[str, Any]) -> list[dict[str, str]]:
    present = set()
    for entry in normalize_conferences(config):
        present.update(entry.focus_tags)

    options = []
    for tag, label in FOCUS_TAGS.items():
        if tag in present:
            options.append({"id": tag, "label": label})
    return options


def load_ccfddl_catalog() -> dict[str, Any]:
    catalog_path = Path(__file__).resolve().parents[1] / "data" / "ccf_conferences.yaml"
    if not catalog_path.exists():
        return {"categories": {}, "conferences": []}

    with open(catalog_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"categories": {}, "conferences": []}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return slug.strip("-")


def _normalize_lookup(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _unique_strings(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value).strip()
        key = _normalize_lookup(text)
        if text and key not in seen:
            result.append(text)
            seen.add(key)
    return result


def _merge_entries(preferred: ConferenceEntry, fallback: ConferenceEntry) -> ConferenceEntry:
    aliases = _unique_strings([*preferred.aliases, fallback.display_name, *fallback.aliases])
    tier = {**fallback.tier, **preferred.tier}
    years = preferred.years or fallback.years
    focus_tags = tuple(_unique_strings([*preferred.focus_tags, *fallback.focus_tags]))
    official_source = preferred.official_source or fallback.official_source

    return ConferenceEntry(
        id=preferred.id,
        display_name=preferred.display_name,
        full_name=preferred.full_name or fallback.full_name,
        dblp_stream=preferred.dblp_stream or fallback.dblp_stream,
        dblp_query=preferred.dblp_query or fallback.dblp_query,
        aliases=tuple(aliases),
        category=preferred.category or fallback.category,
        category_name=preferred.category_name or fallback.category_name,
        category_name_zh=preferred.category_name_zh or fallback.category_name_zh,
        tier=tier,
        focus_tags=focus_tags,
        official_source=dict(official_source),
        source=preferred.source or fallback.source,
        enabled=preferred.enabled,
        years=years,
    )


def _infer_focus_tags(raw: dict[str, Any]) -> list[str]:
    text = " ".join(
        str(value or "")
        for value in [
            raw.get("id"),
            raw.get("display_name") or raw.get("title"),
            raw.get("full_name") or raw.get("description"),
            raw.get("category") or raw.get("sub"),
            raw.get("category_name"),
        ]
    ).lower()

    tags = []
    category = raw.get("category") or raw.get("sub")
    rank = raw.get("tier") or raw.get("rank") or {}

    if category == "SC":
        tags.append("security")
    if category in {"DS", "NW", "SE"}:
        tags.append("distributed_systems")
    if category == "SE":
        tags.append("software_engineering")
    if "cloud" in text or raw.get("id") in {"socc", "cloud", "cscloud", "ccgrid"}:
        tags.append("cloud_native")
    if ("cloud" in text and category == "SC") or raw.get("id") in {"cscloud", "trustcom"}:
        tags.append("cloud_security")
    if any(token in text for token in ["kubernetes", "container", "serverless", "microservice", "service oriented", "web services", "middleware"]):
        tags.append("cloud_native")
    if raw.get("id") in {"sp", "ccs", "ndss", "uss", "usenix-security", "raid", "esorics", "acsac", "dsn", "eurosp"}:
        tags.append("security")
        if (rank.get("ccf") in {"A", "B"}) or raw.get("id") == "dsn":
            tags.append("cloud_security")
    if raw.get("id") in {"socc", "eurosys", "osdi", "sosp", "nsdi", "middleware", "icdcs", "hpdc", "ccgrid", "sec", "icsoc", "icws"}:
        tags.append("cloud_native")
    if raw.get("id") in {"icse", "fse", "ase", "issta", "icsme", "issre", "icse"}:
        tags.append("software_engineering")

    return tags


FOCUS_TAGS = {
    "cloud_security": "Cloud Security",
    "cloud_native": "Cloud Native",
    "distributed_systems": "Distributed Systems",
    "software_engineering": "Software Engineering",
    "security": "Security",
}


_LEGACY_DEFAULTS: dict[str, dict[str, Any]] = {
    "neurips": {
        "full_name": "Conference on Neural Information Processing Systems",
        "dblp_stream": "conf/nips",
        "aliases": ["NIPS"],
        "category": "ai_ml",
    },
    "icml": {
        "full_name": "International Conference on Machine Learning",
        "dblp_stream": "conf/icml",
        "category": "ai_ml",
    },
    "iclr": {
        "full_name": "International Conference on Learning Representations",
        "dblp_stream": "conf/iclr",
        "category": "ai_ml",
    },
    "aaai": {
        "full_name": "AAAI Conference on Artificial Intelligence",
        "dblp_stream": "conf/aaai",
        "category": "ai_ml",
    },
    "acl": {
        "full_name": "Annual Meeting of the Association for Computational Linguistics",
        "dblp_stream": "conf/acl",
        "category": "nlp_llm",
    },
    "emnlp": {
        "full_name": "Conference on Empirical Methods in Natural Language Processing",
        "dblp_stream": "conf/emnlp",
        "category": "nlp_llm",
    },
    "naacl": {
        "full_name": "Annual Conference of the North American Chapter of the ACL",
        "dblp_stream": "conf/naacl",
        "category": "nlp_llm",
    },
    "colm": {
        "full_name": "Conference on Language Modeling",
        "dblp_stream": "conf/colm",
        "aliases": ["CoLM"],
        "category": "nlp_llm",
    },
    "sp": {
        "full_name": "IEEE Symposium on Security and Privacy",
        "dblp_stream": "conf/sp",
        "aliases": ["IEEE S&P", "S&P"],
        "category": "security",
    },
    "ndss": {
        "full_name": "Network and Distributed System Security Symposium",
        "dblp_stream": "conf/ndss",
        "category": "security",
    },
    "usenixsecurity": {
        "full_name": "USENIX Security Symposium",
        "dblp_stream": "conf/uss",
        "aliases": ["USENIX Security Symposium"],
        "category": "security",
    },
    "ccs": {
        "full_name": "ACM Conference on Computer and Communications Security",
        "dblp_stream": "conf/ccs",
        "aliases": ["ACM CCS"],
        "category": "security",
    },
    "issta": {
        "full_name": "International Symposium on Software Testing and Analysis",
        "dblp_stream": "conf/issta",
        "category": "software_engineering",
    },
    "icse": {
        "full_name": "International Conference on Software Engineering",
        "dblp_stream": "conf/icse",
        "category": "software_engineering",
    },
    "fse": {
        "full_name": "ACM International Conference on the Foundations of Software Engineering",
        "dblp_stream": "conf/sigsoft",
        "aliases": ["ESEC/FSE", "ESEC/SIGSOFT FSE", "SIGSOFT FSE"],
        "category": "software_engineering",
    },
    "ase": {
        "full_name": "IEEE/ACM International Conference on Automated Software Engineering",
        "dblp_stream": "conf/kbse",
        "aliases": ["KBSE"],
        "category": "software_engineering",
    },
    "esorics": {
        "full_name": "European Symposium on Research in Computer Security",
        "dblp_stream": "conf/esorics",
        "category": "security",
    },
    "raid": {
        "full_name": "International Symposium on Research in Attacks, Intrusions and Defenses",
        "dblp_stream": "conf/raid",
        "category": "security",
    },
    "acsac": {
        "full_name": "Annual Computer Security Applications Conference",
        "dblp_stream": "conf/acsac",
        "category": "security",
    },
    "asiaccs": {
        "full_name": "ACM Asia Conference on Computer and Communications Security",
        "dblp_stream": "conf/asiaccs",
        "aliases": ["AsiaCCS", "ASIACCS"],
        "category": "security",
    },
    "eurosp": {
        "full_name": "IEEE European Symposium on Security and Privacy",
        "dblp_stream": "conf/eurosp",
        "aliases": ["EuroS&P", "Euro S&P"],
        "category": "security",
    },
    "dimva": {
        "full_name": "Conference on Detection of Intrusions and Malware & Vulnerability Assessment",
        "dblp_stream": "conf/dimva",
        "category": "security",
    },
    "dsn": {
        "full_name": "International Conference on Dependable Systems and Networks",
        "dblp_stream": "conf/dsn",
        "category": "systems",
    },
}
