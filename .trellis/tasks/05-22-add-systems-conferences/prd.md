# add systems conferences

## Goal

Add high-quality systems conferences to the PaperCollect catalog so the web UI, collection API, RSS feeds, and local search can target OS, distributed systems, cloud systems, storage systems, and systems/architecture venues.

## What I Already Know

* The user wants systems conferences added to the existing conference picker/catalog.
* `config.yaml` is the local override catalog used by the UI and collectors.
* Conference entries use stable lowercase `id`, human-readable `display_name`, `dblp_stream`, category metadata, and `focus_tags`.
* `src/core/conference_catalog.py` already infers `cloud_native` for IDs such as `socc`, `eurosys`, `osdi`, `sosp`, `nsdi`, `middleware`, `icdcs`, and `hpdc`.
* Existing tests and README expect a local `src/data/ccf_conferences.yaml` bundled catalog, but the file is currently missing.

## Assumptions

* Use a conservative high-quality systems set instead of broad low-quality expansion.
* Keep network-only conferences separate unless they are strongly systems-facing; include NSDI because it is core networked systems.
* Use CCF-style `DS` for systems/storage/distributed venues and keep focus tags explicit for project search.

## Requirements

* Add explicit local config entries for systems/cloud-native venues:
  * SOSP
  * OSDI
  * NSDI
  * EuroSys
  * USENIX ATC
  * FAST
  * SoCC
  * ASPLOS
  * Middleware
  * HPDC
  * ICDCS
* Use 2023, 2024, 2025, and 2026 as the configured collection years for the systems-focused set.
* Assign stable DBLP streams and aliases so old saved JSON filenames and DBLP venue filters continue to resolve.
* Mark relevant venues with `distributed_systems` and `cloud_native`; mark storage/architecture fields where useful through full names and category.
* Restore the bundled CCFDDL catalog file required by existing catalog tests.
* Add tests that validate the local config exposes the systems venues with the expected metadata.

## Acceptance Criteria

* [ ] `/api/options` can expose the new systems conferences through normalized catalog entries.
* [ ] Systems-focused conferences advertise 2023-2026 as their configured years.
* [ ] Collection requests can address each new conference by stable lowercase ID.
* [ ] Search can map saved data files such as `OSDI_2025.json` and `nsdi_2025.json` to configured conference metadata.
* [ ] Catalog unit tests pass.
* [ ] Full unit test suite passes, except explicitly skipped live network tests.

## Definition of Done

* Tests added/updated.
* Relevant unit tests run.
* No unrelated source changes.

## Out of Scope

* Adding official-source parsers for USENIX/ACM proceedings pages.
* Crawling all newly added venues immediately.
* Changing semantic search scoring.

## Technical Notes

* Relevant files: `config.yaml`, `src/core/conference_catalog.py`, `tests/test_conference_catalog.py`.
* Backend quality spec requires catalog fields to keep stable `id`, `display_name`, `dblp_stream`, `aliases`, `category`, `tier`, `enabled`, `years`, and `focus_tags`.
* Missing CCFDDL file causes existing `tests/test_conference_catalog.py` failures for bundled catalog expansion and rank merge behavior.
