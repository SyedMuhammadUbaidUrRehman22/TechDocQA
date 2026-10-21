# Phase 3A implementation plan

Inspected 2026-10-21: Revision 3 requirements/ACs, roadmap, implemented Phase 2 contracts, LangChain loader plan, registry/CLI/settings/error schemas, dependency lock/tests and draft corpus manifest.

1. Add the single approved online catalog to the existing TOML settings. Kafka/Airflow are enabled; PostgreSQL/Spark/Redis/Docker are initially disabled. Only finite configured pages or the catalog entry point can be requested; redirects must remain in declared scopes.
2. Use existing urllib3 with verified public DNS answers, a connection pinned to a validated IP, original-host TLS verification/SNI, explicit redirects/time/size/retry limits and sequential pacing. A bounded isolated worker covers DNS, network and extraction. Do not use a loader's independent network client.
3. Use LangChain BSHTMLLoader on the fetched local representation, with a small BeautifulSoup structure/code preservation adapter. Keep whole-page extracted text, heading paths and raw HTML snapshots; do not implement FR-04 normalization or chunking.
4. Reuse SQLite runs/attempts/events/registrations. Add URL identity and typed online provenance through existing JSON columns and optional Python fields; keep schema version 1 and all local identity/eligibility contracts. Preserve each retrieval in its attempt, and preserve immutable content-addressed raw/text files.
5. Extend the existing ingest command with mutually exclusive local, catalog-source and explicit-URL modes. Export an unfrozen online-candidate section using the existing corpus-manifest shape under ignored runtime data, derived from the registry. Add offline network-denial/mock tests and a separately enabled live smoke test.
6. Run the complete offline suite, dependency/lock/build checks and documentation checks; document evidence and remaining course gates.

## Contract conflicts and boundaries

- URL ingestion is optional P2 in FR-01/FR-23 and roadmap Phase 12. The user explicitly selected this limited slice early as Phase 3A; this does not authorize the remaining P2 work or complete P0 parsing/versioning.
- Phase 2 binds local filename/logical-name identities to canonical paths and has no URL API. Online keys use the requirements' normalized URL identity; local keys and IDs stay unchanged. Raw byte differences still reserve provisional candidates; normalized hashes remain null and eligibility remains false. No full FR-05 finalization/supersession claim.
- There is no established migration runner. Existing metadata/result JSON fields accommodate online provenance and failed-fetch/extraction context without a schema migration or another registry. A failed extraction may retain its fetched snapshot on the attempt before a successful registration exists; complete FR-03 local parsing/status semantics remain later work.
- The committed manifest is a draft reference-corpus specification, not a live ingestion log. Runtime candidate manifests are registry projections using that shape; they cannot freeze the reference corpus or count URLs as local format coverage.
- Kafka's supplied `/documentation/` entry currently serves a redirect page. The catalog explicitly selects the official `/43/getting-started/introduction/` page as its one default fetch and retains the supplied entry. No runtime HTML/JavaScript redirect discovery is performed. Airflow selects only its supplied stable entry.
- License-policy references do not establish redistribution permission. All catalog usage statuses remain unverified pending corpus review.
