# Graph Report - orc  (2026-11-06)

## Corpus Check
- 10 files · ~29,135 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 1 file(s) not represented in the graph (top: (none) 1)

## Summary
- 449 nodes · 934 edges · 12 communities (11 shown, 1 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 109 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `1611b5bb`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Complaint Processing Engine
- API Ingest & Classification
- Bank Code Registry
- Secrets & Gateway Config
- Local Schema & Migration
- Gateway Client & Processing Settings
- run
- HSBC/UPI/BigQuery Config
- RRN Parsing Helpers
- conftest.py
- FakeGateway

## God Nodes (most connected - your core abstractions)
1. `run()` - 38 edges
2. `seed()` - 33 edges
3. `txn()` - 23 edges
4. `_run_state_machine()` - 23 edges
5. `state()` - 21 edges
6. `_enrich()` - 18 edges
7. `seed_tests.sql (10 labelled test complaints)` - 18 edges
8. `_step_get()` - 17 edges
9. `_fraud()` - 16 edges
10. `_reconcile_credit_from_dd()` - 16 edges

## Surprising Connections (you probably didn't know these)
- `MOCK HSBC MHA Gateway app` --semantically_similar_to--> `FastAPI app (Fraud-Ops Orchestrator)`  [AMBIGUOUS] [semantically similar]
  mock_gateway.txt → main.txt
- `_finalize_bene_only()` --calls--> `resolve_bank_code()`  [EXTRACTED]
  processor.txt → bank_codes.py
- `_finalize_cbdoc_bene()` --calls--> `resolve_bank_code()`  [EXTRACTED]
  processor.txt → bank_codes.py
- `Channel by RRN Shape` --conceptually_related_to--> `Resumable Processing State Machine`  [AMBIGUOUS]
  classifier.txt → README.md
- `graphify Usage Rules` --references--> `Fraud-Ops Orchestrator`  [AMBIGUOUS]
  CLAUDE.md → README.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Bank code resolution chain** — bank_codes_resolve_bank_code, bank_codes_resolve_from_narratives, bank_codes_bankcoderegistry_resolve, bank_codes_bankcoderegistry_lookup_name, bank_codes_ifsc_prefix_to_bank [EXTRACTED 1.00]
- **Complaint ingestion (schemas -> models -> db)** — main_ingest, schemas_complaintin, models_complaint, models_instrument, models_incident, db_session_scope [EXTRACTED 1.00]
- **Local DB bootstrap: local_setup -> migrations -> seed** — models_local_setup_local_setup_sql, models_migration_migration_sql, models_seed_seed_sql [EXTRACTED 1.00]
- **Credit fraud balance -> hold -> DD reconcile flow** — processor_available_balance, processor_apply_holds, processor_reconcile_credit_from_dd, processor_extract_rrns, processor_bene_for_rrn, processor_mha_debit_obj [EXTRACTED 1.00]
- **MHA contract object builders** — processor_mha_money_transfer_to, processor_mha_put_on_hold, processor_mha_failure, processor_mha_others_le_500 [EXTRACTED 1.00]
- **MHA response finalize -> log -> encrypt/send -> ack pipeline** — processor_finalize, processor_finalize_bene_only, processor_finalize_cbdoc_bene, processor_finalize_miscellaneous, processor_finalize_dd_probe, processor_finalize_small_only, processor_write_response_log, processor_send_mha_response, processor_store_mha_ack [EXTRACTED 1.00]
- **Enum to VARCHAR schema evolution** — models_schema_final_schema_sql, models_migration_enum_to_varchar, models_updated_schema_embedded_migration, models_updated_schema_schema_sql, models_migration_drop_enum_types [INFERRED 0.85]
- **Encrypted MHA response delivery** — encryption_encrypt_payload, gateway_client_gatewayclient_mha_response, test_mha_response, configv2_mha_response_url [INFERRED 0.85]
- **Orchestrator sidecar processing pattern** — models_orc_tables_complaint_processing, models_orc_tables_processing_steps, models_orc_tables_idx_cp_poll, models_orc_tables_idempotency_key [INFERRED 0.85]

## Communities (12 total, 1 thin omitted)

### Community 0 - "Complaint Processing Engine"
Cohesion: 0.06
Nodes (67): _apply_holds(), _available_balance(), _bene_for_rrn(), _bq_locate(), _cbdoc_account_debits(), _cbdoc_probe(), _cbdoc_wake_time(), Credit Fraud Flow (DD validate -> balance -> hold -> reconcile) (+59 more)

### Community 1 - "API Ingest & Classification"
Cohesion: 0.07
Nodes (33): channel_for_rrn(), Classification, classify(), direction_for_layer(), _earliest_txn_at(), session_scope(), get_complaint() GET /api/v1/complaints/{ack_no}, _ingest() (+25 more)

### Community 2 - "Bank Code Registry"
Cohesion: 0.07
Nodes (16): BankCodeRegistry, BankMatch, IFSC_PREFIX_TO_BANK, NAME_ALIASES, _norm(), _parenthetical_names(), registry(), resolve_bank_code() (+8 more)

### Community 3 - "Secrets & Gateway Config"
Cohesion: 0.06
Nodes (28): graphify Usage Rules, Gateway settings (GATEWAY_BASE_URL/USE_OIDC_AUTH/GATEWAY_AUDIENCE), _load_secrets_from_gcp(), MHA_RESPONSE_KEY_B64, Postgres settings (PG_*), SECRETS_TO_LOAD, get_secret(), _load_secrets_from_gcp() (+20 more)

### Community 4 - "Local Schema & Migration"
Cohesion: 0.07
Nodes (63): api_response_logs table, api_response_status enum, complaints table, fraud_sub_category enum, incidents table, instruments table, local_setup.sql (fresh local Postgres base tables), payment_mode enum (+55 more)

### Community 5 - "Gateway Client & Processing Settings"
Cohesion: 0.07
Nodes (25): _env_int(), FRAUD_AGE_THRESHOLD_HOURS, Processing settings (BATCH_SIZE/LEASE_SECONDS/MAX_ATTEMPTS), UPI_SYSTEM_ID, GatewayClient.apply_hold(), GatewayClient.bigquery_search(), GatewayClient.demand_deposit(), GatewayClient._request() (+17 more)

### Community 6 - "run"
Cohesion: 0.09
Nodes (44): incident(), run(), seed(), state(), txn(), ib_debit(), _only_response(), test_account_not_found_returns_01() (+36 more)

### Community 7 - "HSBC/UPI/BigQuery Config"
Cohesion: 0.18
Nodes (10): MHA_RESPONSE_PATH, BigQuery settings (BQ_PROJECT/DATASET/TABLE), _env(), HSBC Hub endpoint URLs, HSBC E2E Trust Token settings, MHA_RESPONSE_URL / MHA_RESPONSE_TIMEOUT, UPI settings (UPI_BASE_URL/paths/creds), validate() (+2 more)

### Community 8 - "RRN Parsing Helpers"
Cohesion: 0.33
Nodes (6): _classify_rrn(), _extract_rrns(), _log_rrn_miss(), _narratives(), _norm_ref(), _scheme_from_narratives()

### Community 9 - "conftest.py"
Cohesion: 0.09
Nodes (18): _bigint(), cbdoc_row(), _computed(), _jsonb(), _TxtModules, test_distinct_matching_records_raise(), test_flow_conflict_goes_to_review_without_callback(), test_flow_duplicates_give_one_response_object() (+10 more)

### Community 11 - "FakeGateway"
Cohesion: 0.19
Nodes (3): engine(), FakeGateway, gw()

## Ambiguous Edges - Review These
- `_run_state_machine()` → `_trace_and_collect()`  [AMBIGUOUS]
  processor.txt · relation: conceptually_related_to
- `Channel by RRN Shape` → `Resumable Processing State Machine`  [AMBIGUOUS]
  classifier.txt · relation: conceptually_related_to
- `FastAPI app (Fraud-Ops Orchestrator)` → `MOCK HSBC MHA Gateway app`  [AMBIGUOUS]
  mock_gateway.txt · relation: semantically_similar_to
- `graphify Usage Rules` → `Fraud-Ops Orchestrator`  [AMBIGUOUS]
  CLAUDE.md · relation: references

## Knowledge Gaps
- **31 isolated node(s):** `_LEG_STATUS`, `Miscellaneous Response to MHA`, `Classification`, `ApiResponseStatus enum`, `STATUS_OPEN` (+26 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 125 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `resolve_bank_code()` connect `Bank Code Registry` to `Complaint Processing Engine`?**
  _High betweenness centrality (0.275) - this node is a cross-community bridge._
- **What connects `_LEG_STATUS`, `Miscellaneous Response to MHA`, `Classification` to the rest of the system?**
  _31 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Complaint Processing Engine` be split into smaller, more focused modules?**
  _Cohesion score 0.061708860759493674 - nodes in this community are weakly interconnected._
- **Why does `_run_state_machine()` connect `Complaint Processing Engine` to `API Ingest & Classification`?**
  _High betweenness centrality (0.187) - this node is a cross-community bridge._
- **Should `API Ingest & Classification` be split into smaller, more focused modules?**
  _Cohesion score 0.06753006475485661 - nodes in this community are weakly interconnected._

### Low-confidence Hints
_AMBIGUOUS edges — the extractor was unsure. Verify before acting on these._

- **What is the exact relationship between `_run_state_machine()` and `_trace_and_collect()`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `Channel by RRN Shape` and `Resumable Processing State Machine`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._