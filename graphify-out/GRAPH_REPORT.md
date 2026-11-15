# Graph Report - orc  (2026-11-15)

## Corpus Check
- 13 files · ~35,863 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 1 file(s) not represented in the graph (top: (none) 1)

## Summary
- 552 nodes · 1282 edges · 20 communities (18 shown, 2 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 128 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `77092ea6`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Complaint Processing Engine
- classify
- bank_codes.py
- _load_secrets_from_gcp
- Local Schema & Migration
- Gateway Client & Processing Settings
- run
- test_cbdoc_rows.py
- run
- conftest.py
- Recording
- FakeGateway
- ComplaintProcessing
- test_pg_integration.py
- test_response_idempotency.py
- Complaint
- _create_conn_pool
- Fraud-Ops Orchestrator
- ProcessingStep

## God Nodes (most connected - your core abstractions)
1. `run()` - 84 edges
2. `seed()` - 45 edges
3. `state()` - 45 edges
4. `txn()` - 36 edges
5. `seed_sheet()` - 34 edges
6. `incident()` - 26 edges
7. `_run_state_machine()` - 23 edges
8. `_enrich()` - 18 edges
9. `seed_tests.sql (10 labelled test complaints)` - 18 edges
10. `outcome()` - 17 edges

## Surprising Connections (you probably didn't know these)
- `MOCK HSBC MHA Gateway app` --semantically_similar_to--> `FastAPI app (Fraud-Ops Orchestrator)`  [AMBIGUOUS] [semantically similar]
  mock_gateway.txt → main.txt
- `Channel by RRN Shape` --conceptually_related_to--> `Resumable Processing State Machine`  [AMBIGUOUS]
  classifier.txt → README.md
- `_leg_bank_code()` --calls--> `resolve_from_narratives()`  [EXTRACTED]
  processor.txt → bank_codes.py
- `graphify Usage Rules` --references--> `Fraud-Ops Orchestrator`  [AMBIGUOUS]
  CLAUDE.md → README.md
- `resolve_from_narratives()` --references--> `MHA_DEFAULT_BANK_CODE`  [EXTRACTED]
  bank_codes.py → config.txt

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

## Communities (20 total, 2 thin omitted)

### Community 0 - "Complaint Processing Engine"
Cohesion: 0.05
Nodes (75): resolve_bank_code(), _apply_holds(), _available_balance(), _bene_for_rrn(), _bq_locate(), _cbdoc_account_debits(), _cbdoc_probe(), _cbdoc_wake_time() (+67 more)

### Community 1 - "classify"
Cohesion: 0.21
Nodes (10): channel_for_rrn(), Classification, classify(), direction_for_layer(), _earliest_txn_at(), Base, Incident, Instrument (+2 more)

### Community 2 - "bank_codes.py"
Cohesion: 0.05
Nodes (24): BankCodeRegistry, BankMatch, IFSC_PREFIX_TO_BANK, NAME_ALIASES, _norm(), _parenthetical_names(), registry(), resolve_from_narratives() (+16 more)

### Community 3 - "_load_secrets_from_gcp"
Cohesion: 0.18
Nodes (6): Gateway settings (GATEWAY_BASE_URL/USE_OIDC_AUTH/GATEWAY_AUDIENCE), GatewayClient, get_logger(), FastAPI app (Fraud-Ops Orchestrator), lifespan(), HSBC MHA Gateway

### Community 4 - "Local Schema & Migration"
Cohesion: 0.07
Nodes (63): api_response_logs table, api_response_status enum, complaints table, fraud_sub_category enum, incidents table, instruments table, local_setup.sql (fresh local Postgres base tables), payment_mode enum (+55 more)

### Community 5 - "Gateway Client & Processing Settings"
Cohesion: 0.07
Nodes (25): _env_int(), FRAUD_AGE_THRESHOLD_HOURS, Processing settings (BATCH_SIZE/LEASE_SECONDS/MAX_ATTEMPTS), UPI_SYSTEM_ID, GatewayClient.apply_hold(), GatewayClient.bigquery_search(), GatewayClient.demand_deposit(), GatewayClient._request() (+17 more)

### Community 6 - "run"
Cohesion: 0.09
Nodes (56): incident(), run(), seed(), state(), txn(), ib_debit(), _credit(), _hold_case() (+48 more)

### Community 7 - "test_cbdoc_rows.py"
Cohesion: 0.23
Nodes (14): cbdoc_row(), test_distinct_matching_records_raise(), test_flow_conflict_goes_to_review_without_callback(), test_flow_duplicates_give_one_response_object(), test_flow_no_dated_record_returns_02(), test_flow_picks_the_dated_record(), test_identical_records_are_deduplicated(), test_malformed_ogtmz1_never_matches_or_raises() (+6 more)

### Community 8 - "run"
Cohesion: 0.07
Nodes (37): frozen_clock(), outcome(), _receipt(), seed_sheet(), sheet_txn(), step_rows(), test_0011_valid_upi_transaction_returns_00(), test_0012_account_absent_returns_01() (+29 more)

### Community 9 - "conftest.py"
Cohesion: 0.12
Nodes (4): _bigint(), _computed(), _jsonb(), _TxtModules

### Community 12 - "FakeGateway"
Cohesion: 0.19
Nodes (3): engine(), FakeGateway, gw()

### Community 13 - "ComplaintProcessing"
Cohesion: 0.21
Nodes (10): session_scope(), process_batch() POST /process-batch, process_one() POST /process/{ack_no}, ComplaintProcessing, TERMINAL_STATES / processing states, _bootstrap_processing_rows(), claim_batch(), process_batch() (+2 more)

### Community 14 - "test_pg_integration.py"
Cohesion: 0.15
Nodes (7): engine(), pg_url(), _run_sql_file(), test_concurrent_batch_ticks_process_each_complaint_once(), test_real_ddl_rejects_the_missing_date_workflow(), test_seed_sql_is_rerunnable_and_matches_its_expectations(), test_skip_locked_skips_a_row_another_transaction_holds()

### Community 15 - "test_response_idempotency.py"
Cohesion: 0.18
Nodes (8): _load(), test_concurrent_send_while_first_is_in_flight(), worker(), test_crash_mid_send_is_never_resent_and_parks_for_review(), test_failed_callback_is_retried_then_delivered_once(), test_reprocessing_after_delivery_never_resends(), test_simultaneous_sends_deliver_exactly_once(), worker()

### Community 16 - "Complaint"
Cohesion: 0.27
Nodes (9): get_complaint() GET /api/v1/complaints/{ack_no}, _ingest(), ingest_complaint() POST /api/v1/complaints, ApiResponseLog, ApiResponseStatus enum, Complaint, STATUS_OPEN, ComplaintIn (+1 more)

### Community 17 - "_create_conn_pool"
Cohesion: 0.09
Nodes (19): _load_secrets_from_gcp(), MHA_RESPONSE_KEY_B64, Postgres settings (PG_*), SECRETS_TO_LOAD, get_secret(), _load_secrets_from_gcp(), _SECRET_FILES, _SECRET_STRINGS (+11 more)

### Community 18 - "Fraud-Ops Orchestrator"
Cohesion: 0.25
Nodes (3): graphify Usage Rules, Cloud Run + Cloud Scheduler Deploy, Fraud-Ops Orchestrator

### Community 19 - "ProcessingStep"
Cohesion: 0.47
Nodes (4): ProcessingStep, complaint_processing table, orchestrator_tables.sql, processing_steps table

## Ambiguous Edges - Review These
- `_run_state_machine()` → `_trace_and_collect()`  [AMBIGUOUS]
  processor.txt · relation: conceptually_related_to
- `Channel by RRN Shape` → `Resumable Processing State Machine`  [AMBIGUOUS]
  classifier.txt · relation: conceptually_related_to
- `graphify Usage Rules` → `Fraud-Ops Orchestrator`  [AMBIGUOUS]
  CLAUDE.md · relation: references
- `FastAPI app (Fraud-Ops Orchestrator)` → `MOCK HSBC MHA Gateway app`  [AMBIGUOUS]
  mock_gateway.txt · relation: semantically_similar_to

## Knowledge Gaps
- **31 isolated node(s):** `_LEG_STATUS`, `Miscellaneous Response to MHA`, `Classification`, `TERMINAL_STATES / processing states`, `ApiResponseStatus enum` (+26 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 151 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `resolve_bank_code()` connect `Complaint Processing Engine` to `bank_codes.py`?**
  _High betweenness centrality (0.300) - this node is a cross-community bridge._
- **What connects `_LEG_STATUS`, `Miscellaneous Response to MHA`, `Classification` to the rest of the system?**
  _31 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Complaint Processing Engine` be split into smaller, more focused modules?**
  _Cohesion score 0.05293383270911361 - nodes in this community are weakly interconnected._
- **Why does `_run_state_machine()` connect `Complaint Processing Engine` to `classify`, `ComplaintProcessing`?**
  _High betweenness centrality (0.173) - this node is a cross-community bridge._
- **Should `bank_codes.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05203619909502263 - nodes in this community are weakly interconnected._

### Low-confidence Hints
_AMBIGUOUS edges — the extractor was unsure. Verify before acting on these._

- **What is the exact relationship between `_run_state_machine()` and `_trace_and_collect()`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `Channel by RRN Shape` and `Resumable Processing State Machine`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._