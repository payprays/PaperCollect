from src.core.conference_catalog import (
    catalog_categories,
    find_conference,
    focus_tag_options,
    load_ccfddl_catalog,
    normalize_conference,
    normalize_conferences,
)


def test_normalize_object_conference_preserves_dblp_stream_and_aliases():
    entry = normalize_conference(
        {
            "id": "sp",
            "display_name": "IEEE S&P",
            "full_name": "IEEE Symposium on Security and Privacy",
            "dblp_stream": "conf/sp",
            "aliases": ["SP", "S&P"],
            "category": "security",
            "tier": {"ccf": "A"},
        }
    )

    assert entry.id == "sp"
    assert entry.display_name == "IEEE S&P"
    assert entry.dblp_stream == "conf/sp"
    assert "SP" in entry.aliases
    assert entry.tier["ccf"] == "A"


def test_find_conference_accepts_id_display_name_and_alias():
    config = {
        "conferences": [
            {
                "id": "sp",
                "display_name": "IEEE S&P",
                "dblp_stream": "conf/sp",
                "aliases": ["SP"],
            }
        ]
    }

    assert find_conference(config, "sp").display_name == "IEEE S&P"
    assert find_conference(config, "IEEE S&P").id == "sp"
    assert find_conference(config, "SP").id == "sp"


def test_legacy_string_config_gets_known_default_stream():
    entries = normalize_conferences({"include_ccfddl_catalog": False, "conferences": ["ICSE"]})

    assert entries[0].id == "icse"
    assert entries[0].display_name == "ICSE"
    assert entries[0].dblp_stream == "conf/icse"


def test_bundled_ccfddl_catalog_expands_conferences_and_categories():
    catalog = load_ccfddl_catalog()
    entries = normalize_conferences({"conferences": []})
    categories = catalog_categories({"conferences": []})

    assert catalog["source"]["name"] == "ccfddl/ccf-deadlines"
    assert len(entries) > 300
    assert any(entry.id == "sigmod" for entry in entries)
    assert any(category["id"] == "SC" for category in categories)


def test_focus_tags_mark_cloud_native_and_cloud_security_conferences():
    entries = normalize_conferences({"conferences": []})
    options = focus_tag_options({"conferences": []})
    by_id = {entry.id: entry for entry in entries}

    assert "cloud_native" in by_id["socc"].focus_tags
    assert "cloud_security" in by_id["cscloud"].focus_tags
    assert any(option["id"] == "cloud_native" for option in options)


def test_local_catalog_override_keeps_rank_while_refining_category_and_focus():
    entries = normalize_conferences(
        {
            "conferences": [
                {
                    "id": "www",
                    "display_name": "WWW",
                    "category": "NW",
                    "category_name": "Network System",
                    "category_name_zh": "计算机网络",
                    "focus_tags": ["distributed_systems"],
                },
                {
                    "id": "mlsys",
                    "display_name": "MLSys",
                    "focus_tags": ["distributed_systems", "cloud_native"],
                    "official_source": {"type": "miniconf", "papers_url": "https://example.com/{year}.json"},
                },
            ]
        }
    )
    by_id = {entry.id: entry for entry in entries}

    assert by_id["www"].category == "NW"
    assert by_id["www"].category_name == "Network System"
    assert by_id["www"].tier["ccf"] == "A"
    assert "distributed_systems" in by_id["www"].focus_tags
    assert by_id["mlsys"].tier["ccf"] == "N"
    assert "cloud_native" in by_id["mlsys"].focus_tags
    assert by_id["mlsys"].official_source["type"] == "miniconf"
    assert by_id["mlsys"].official_source["papers_url"] == "https://example.com/{year}.json"
