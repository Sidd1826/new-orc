"""Isolated PostgreSQL integration run (opt-in).

    ORC_TEST_PG_URL=postgresql+pg8000://USER:PASS@HOST:5432/postgres pytest tests

Creates a throwaway database `orc_it_<random>` through that admin URL, loads the
REAL DDL (local_setup -> orc_tables -> migration), re-runs the sheet,
validation and idempotency suites on it — real FOR UPDATE SKIP LOCKED, real
UNIQUE/NOT NULL, real generated is_success — then drops it. It never touches
any existing database. Skipped when ORC_TEST_PG_URL is unset."""
from __future__ import annotations

import os
import threading
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

import db
import models
import processor
from conftest import ROOT, GatewayError, run, txn
from test_mha_sheet_fixtures import *        # noqa: F401,F403 - re-run on PostgreSQL
from test_mha_sheet_fixtures import KNOWN, SHEET, _receipt, seed_sheet
from test_mha_validation import *            # noqa: F401,F403
from test_response_idempotency import *      # noqa: F401,F403
from test_upi_tc_sheet import *              # noqa: F401,F403

ADMIN_URL = os.getenv("ORC_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="set ORC_TEST_PG_URL to run")
DDL = ("models/local_setup.txt", "models/orc_tables.txt", "models/migration.txt")
TABLES = ("complaints, instruments, incidents, api_response_logs, "
          "complaint_processing, processing_steps")

# The real DDL keeps incidents.transaction_date/time NOT NULL, so these two
# can't be seeded here; test_real_ddl_rejects_the_missing_date_workflow covers it.
del test_missing_date_and_utr_acknowledges_only_and_never_calls_back      # noqa: F821
del test_missing_date_and_rrn_is_ack_only_and_distinct_from_a_receipt     # noqa: F821


@pytest.fixture(scope="module")
def pg_url():
    admin = sa.create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    name = f"orc_it_{uuid.uuid4().hex[:10]}"
    with admin.connect() as c:
        c.exec_driver_sql(f'CREATE DATABASE "{name}"')
    url = sa.engine.make_url(ADMIN_URL).set(database=name)
    try:
        eng = sa.create_engine(url, isolation_level="AUTOCOMMIT")
        with eng.connect() as c:
            for f in DDL:
                c.exec_driver_sql((ROOT / f).read_text())
        eng.dispose()
        yield url
    finally:
        with admin.connect() as c:
            c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.dispose()


@pytest.fixture
def engine(pg_url, monkeypatch):            # overrides conftest's SQLite engine
    assert pg_url.database.startswith("orc_it_")       # only ever our throwaway DB
    eng = sa.create_engine(pg_url)
    with eng.begin() as c:
        c.exec_driver_sql(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
    monkeypatch.setattr(db, "_engine", eng)
    monkeypatch.setattr(db, "_SessionLocal", None)
    yield eng
    eng.dispose()


# --- PostgreSQL-only checks --------------------------------------------------------

def test_real_ddl_rejects_the_missing_date_workflow(engine):
    """Documented constraint: shared DDL makes transaction_date/time NOT NULL, so
    the account+amount-only MHA payload cannot be stored until the ingest
    service's owners relax it (a shared-table migration to coordinate)."""
    with engine.connect() as c, pytest.raises(DBAPIError, match="not-null"):
        cid = c.exec_driver_sql("INSERT INTO complaints (acknowledgement_no, sub_category) "
                                "VALUES ('NODATE', 'Other') RETURNING id").scalar()
        iid = c.exec_driver_sql(
            "INSERT INTO instruments (complaint_id, requestor, payer_bank, payer_bank_code, "
            "mode_of_payment, payer_mobile_number, payer_account_number) VALUES "
            f"({cid}, 'I4C-MHA', 'HSBC', '10', 'Debit', '9', '{KNOWN}') RETURNING id").scalar()
        c.exec_driver_sql("INSERT INTO incidents (instrument_id, merchant_id, amount, "
                          f"disputed_amount) VALUES ({iid}, '', 900, 900)")


def test_generated_is_success_reflects_only_the_summary_code(gw):
    _receipt("3160823000013", "BANKS-receipt-0013")
    for ack in ("3160823000013", "3160823000016"):
        seed_sheet(ack)
    gw.history = [txn(["IMPS", "630815826944"], "-900.00", "2026-11-04T15:11:00+05:30")]
    run()
    with db.session_scope() as s:
        rows = s.execute(sa.text("SELECT job_id, response_code, is_success "
                                 "FROM api_response_logs ORDER BY id")).all()
    assert [(r.response_code, r.is_success) for r in rows] == [
        ("00", True),          # the receipt: "received", not a business success
        ("12", False), ("31", False)]


def test_skip_locked_skips_a_row_another_transaction_holds(gw):
    for ack in ("3160823000013", "3160823000014"):
        seed_sheet(ack)
    processor.claim_batch(0)                          # bootstrap sidecar rows only
    with db.get_engine().connect() as holder:
        locked = holder.exec_driver_sql(
            "SELECT id FROM complaint_processing WHERE acknowledgement_no = '3160823000013' "
            "FOR UPDATE").scalar()
        ids = processor.claim_batch(10)               # must not block, must skip
        assert locked not in ids and len(ids) == 1
        holder.rollback()


def test_concurrent_batch_ticks_process_each_complaint_once(gw):
    for ack in SHEET:
        seed_sheet(ack)
    start = threading.Barrier(3)

    def tick():
        start.wait(10)
        processor.process_batch()
    threads = [threading.Thread(target=tick) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    acks = sorted(r["acknowledgement_no"] for r in gw.sent)
    assert acks == sorted(SHEET) and len(gw.sent) == len(SHEET)


def _run_sql_file(engine, name):
    with engine.connect() as c:
        c.exec_driver_sql((ROOT / name).read_text())
        c.commit()


def test_seed_sql_is_rerunnable_and_matches_its_expectations(gw, engine, monkeypatch):
    from test_mock_gateway_contract import Recording
    client = Recording()
    monkeypatch.setattr(processor, "gateway", lambda: client)
    _run_sql_file(engine, "models/new_seed.txt")
    _run_sql_file(engine, "models/new_seed.txt")      # second run: no error, no duplicates
    with db.session_scope() as s:
        assert s.execute(sa.text("SELECT count(*) FROM complaints")).scalar() == 17
    run(2)                                            # BATCH_SIZE 10 -> two ticks
    with db.session_scope() as s:
        got = dict(s.execute(sa.text(
            "SELECT p.acknowledgement_no, l.response_code FROM complaint_processing p "
            "LEFT JOIN api_response_logs l ON l.job_id = p.job_id")).all())
    assert {k: v for k, v in got.items() if k.startswith("316")} == {
        "3160823000011": "00", "3160823000012": "01", "3160823000013": "12",
        "3160823000014": "12", "3160823000015": "01", "3160823000015C": "02",
        "3160823000016": "31"}
    assert {got[f"TC0{n}"] for n in range(1, 10)} == {"12"} and got["TC10"] is None


def test_diagnostics_sql_runs_read_only_and_separates_receipts(gw, engine):
    gw.history = [txn(["UPI", "630818826981"], "-50000.00", "2026-11-04T18:44:00+05:30")]
    for ack in SHEET:
        seed_sheet(ack)
        _receipt(ack, f"BANKS-receipt-{ack}")
    gw.errors["transaction_history"] = GatewayError("down", status_code=503)
    run()                                             # 0011 retries: no final row yet
    sql = "\n".join(ln for ln in (ROOT / "models/diagnostics.txt").read_text().splitlines()
                    if not ln.strip().startswith("--"))
    stmts = [st for st in sql.split(";") if st.strip()]
    with engine.connect() as c:
        c.exec_driver_sql("SET TRANSACTION READ ONLY")   # any write would error
        results = [c.exec_driver_sql(st).mappings().all() for st in stmts]
        c.rollback()
    assert len(results) == 7
    kinds = {(r["ack"], r["row_kind"].split(" ")[0]) for r in results[4]}
    assert ("3160823000013", "FINAL") in kinds and ("3160823000013", "RECEIPT") in kinds
    assert ("3160823000011", "FINAL") not in kinds
    verdicts = {r["ack"]: r["verdict"] for r in results[6]}
    assert verdicts["3160823000013"] == "ACCEPTED BY MHA"
    assert verdicts["3160823000011"].startswith("IN PROGRESS")
    [row] = [r for r in results[2] if r["ack"] == "3160823000011"]
    assert row["attempt_count"] == 1 and "down" in row["last_error"]
