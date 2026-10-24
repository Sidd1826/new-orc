"""Test harness.

The app's modules live in *.txt files (repo convention), so a finder maps
`import processor` etc. onto them. SQLite stands in for Postgres: the few
Postgres-only column types are compiled to SQLite equivalents, and every
transaction is BEGIN IMMEDIATE so concurrent writers serialise instead of
deadlocking. UNIQUE constraints — what the idempotency relies on — are real.
"""
from __future__ import annotations

import base64
import importlib.machinery
import importlib.util
import os
import sys
from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import BigInteger, Computed, DefaultClause, create_engine, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

ROOT = Path(__file__).resolve().parents[1]
_APP_MODULES = {"config", "logger", "db", "models", "classifier", "gateway_client",
                "encryption", "bank_codes", "processor", "schemas", "main"}

sys.dont_write_bytecode = True                  # don't litter the repo with .pyc
os.environ.pop("GOOGLE_CLOUD_PROJECT", None)    # never reach Secret Manager
os.environ.pop("DATABASE_URL", None)


class _TxtModules:
    @staticmethod
    def find_spec(name, path=None, target=None):
        src = ROOT / f"{name}.txt"
        if path is None and name in _APP_MODULES and src.is_file():
            return importlib.util.spec_from_loader(
                name, importlib.machinery.SourceFileLoader(name, str(src)))
        return None


sys.meta_path.insert(0, _TxtModules)


@compiles(JSONB, "sqlite")
def _jsonb(type_, compiler, **kw):
    return "JSON"


@compiles(BigInteger, "sqlite")
def _bigint(type_, compiler, **kw):
    return "INTEGER"            # so BIGINT primary keys autoincrement


@compiles(Computed, "sqlite")
def _computed(element, compiler, **kw):
    sql = str(element.sqltext)
    if "AT TIME ZONE" in sql:   # incidents.transaction_at: IST wall clock -> UTC
        sql = "datetime(transaction_date || ' ' || transaction_time, '-330 minutes')"
    return f"GENERATED ALWAYS AS ({sql}) STORED"


import config       # noqa: E402
import db           # noqa: E402
import encryption   # noqa: E402
import models       # noqa: E402
import processor    # noqa: E402
from gateway_client import GatewayError  # noqa: E402

# Upstream rows may omit the date (MHA "account + amount only"); the shared
# schema says NOT NULL today, so relax it only for the test DDL.
models.Incident.__table__.c.transaction_date.nullable = True
models.Incident.__table__.c.transaction_time.nullable = True
models.Incident.__table__.c.transaction_at.nullable = True     # computed from the two above
# The real DDL (models/orc_tables.txt) has DB-side DEFAULT 0, which the raw
# bootstrap INSERT relies on; the ORM models only carry Python defaults.
for _col in ("attempt_count", "defer_count"):
    models.ComplaintProcessing.__table__.c[_col].server_default = DefaultClause(text("0"))

ACCOUNT = "006361141001"    # 12 digits with leading zeros
UPI_RRN = "244444440001"
UTR = "HSBCN52026060900034931"   # NEFT UTR, embedded date 2026-06-09


@pytest.fixture
def engine(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path / 'test.db'}",
                        connect_args={"timeout": 30, "check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _connect(dbapi_conn, _):
        dbapi_conn.isolation_level = None       # SQLAlchemy drives BEGIN/SAVEPOINT

    @event.listens_for(eng, "begin")
    def _begin(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    models.Base.metadata.create_all(eng)
    monkeypatch.setattr(db, "_engine", eng)
    monkeypatch.setattr(db, "_SessionLocal", None)
    yield eng
    eng.dispose()


class FakeGateway:
    """Records every upstream call. Configure the attributes per test."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.sent: list[dict] = []          # decrypted MHA responses
        self.history: list[dict] = []       # DD transaction-history txns
        self.balance = "100000.00"
        self.cbdoc_rows: list[dict] = []
        self.errors: dict[str, Exception] = {}   # method name -> exception to raise once
        self.before_send = None              # hook run inside mha_response

    def _call(self, name, **kw):
        self.calls.append((name, kw))
        if name in self.errors:
            raise self.errors.pop(name)

    def transaction_history(self, account, from_date=None, to_date=None):
        self._call("transaction_history", account=account)
        return {"data": {"accountInformation": {"transactionDetails": self.history}}}

    def demand_deposit(self, account):
        self._call("demand_deposit", account=account)
        return {"data": {"accounts": [{"availableBalance": {"amount": self.balance}}]}}

    def apply_hold(self, **kw):
        self._call("apply_hold", **kw)
        return {"data": {"status": "SUCCESS"}}

    def upi_bene_lookup(self, **kw):
        self._call("upi_bene_lookup", **kw)
        return {"data": {"pyAccNo": "50100200300", "pyIfscCode": "HDFC0000001",
                         "bankName": "HDFC Bank", "txnDate": "2026/06/09 10:00:00"}}

    def bigquery_search(self, filters, limit=100):
        self._call("bigquery_search", filters=filters)
        return {"rows": self.cbdoc_rows}

    def mha_response(self, encrypted):
        self._call("mha_response")
        if self.before_send:
            self.before_send()
        payload = encryption.decrypt_payload(encrypted)
        self.sent.append(payload)
        ack = encryption.encrypt_payload(
            {"message": f"Response has been successfully added. {payload.get('job_id')}",
             "statuscode": "00"})
        return {"requestId": "r1", "data": {"raw": ack}}

    def names(self):
        return [n for n, _ in self.calls]


@pytest.fixture
def gw(engine, monkeypatch):
    fake = FakeGateway()
    monkeypatch.setattr(processor, "gateway", lambda: fake)
    monkeypatch.setattr(config, "MHA_RESPONSE_KEY_B64", base64.b64encode(b"k" * 32).decode())
    return fake


def incident(merchant_id=UTR, amount="1000.00", disputed="1000.00", layer=0,
             d: date | None = date(2026, 6, 9), t: time | None = time(10, 0)):
    return dict(merchant_id=merchant_id, amount=Decimal(amount),
                disputed_amount=Decimal(disputed), layer=layer,
                transaction_date=d, transaction_time=t)


def seed(ack="ACK0000000001", account=ACCOUNT, mode="Debit", incidents=None) -> int:
    """Insert a complaint the way the upstream service does; returns its id."""
    with db.session_scope() as s:
        c = models.Complaint(acknowledgement_no=ack, sub_category="Fraud", status="OPEN")
        inst = models.Instrument(requestor="I4C-MHA", payer_bank="HSBC", payer_bank_code="10",
                                 mode_of_payment=mode, transaction_type="P2P",
                                 payer_mobile_number="919000000001",
                                 payer_account_number=account)
        inst.incidents = [models.Incident(**i) for i in (incidents or [incident()])]
        c.instrument = inst
        s.add(c)
        s.commit()
        return c.id


def run(times: int = 1):
    """Run processing ticks, ignoring leases (as a retry after expiry would)."""
    for _ in range(times):
        with db.session_scope() as s:
            s.query(models.ComplaintProcessing).update({"lease_expires_at": None})
            s.commit()
        processor.process_batch()


def state(ack="ACK0000000001"):
    with db.session_scope() as s:
        p = s.query(models.ComplaintProcessing).filter_by(acknowledgement_no=ack).one()
        log = s.query(models.ApiResponseLog).filter_by(acknowledgement_no=ack).all()
        steps = s.query(models.ProcessingStep).filter_by(
            acknowledgement_no=ack, step="MHA_RESPONSE").all()
        return p, log, steps


def txn(narratives, amount, ts):
    return {"transactionAmount": {"amount": amount},
            "transactionId": {"executionTimestamp": ts},
            "transactionDescription": [{"transactionNarrative": n} for n in narratives]}


def cbdoc_row(ogtmz1, utr=UTR, bene="/50100999888", name="RAVI KUMAR"):
    return {"LPUTRN": utr, "OGTMZ1": ogtmz1, "OGBEAC": bene, "OGBEA1": name,
            "OGPYCY": "INR", "OGNAR1": "neft"}


__all__ = ["ACCOUNT", "UPI_RRN", "UTR", "FakeGateway", "GatewayError", "incident",
           "seed", "run", "state", "txn", "cbdoc_row"]
