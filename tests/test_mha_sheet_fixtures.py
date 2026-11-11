"""The six I4C-MHA sheet payloads (3160823000011-16) plus the corrected invalid-RRN
fixture, and the failure modes around them: receipt rows, mixed outcomes,
direct-DB ingestion, gateway failures, holds, callbacks and concurrency.

The fake gateway's DD transaction history is the authoritative bank record for
each case. Receipt rows written by the ingest service are a separate concept
and never count as a result. test_pg_integration re-runs this module on
PostgreSQL."""
from __future__ import annotations

import threading
from datetime import date, datetime, time, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

import config
import db
import encryption
import models
import processor
from conftest import GatewayError, cbdoc_row, incident, run, seed, state, txn

DAY = date(2026, 11, 4)
WHEN = "2026-11-04T{}:00+05:30"
KNOWN = "003240868006"                 # known-existing account, leading zeros
FROZEN = datetime(2026, 11, 10, 12, 55, 50, tzinfo=timezone.utc)   # the export's clock

# ack -> (account, rrn, amount, HH:MM, transaction_type)
SHEET = {
    "3160823000011": (KNOWN, "630818826981", "50000.00", "18:44", ""),
    "3160823000012": ("999999999999", "630815826975", "1000.00", "15:52", ""),
    "3160823000013": ("3240868006", "630815826952", "900.00", "15:16", ""),
    "3160823000014": ("3240A68006", "630815826952", "900.00", "15:16", ""),
    "3160823000015": ("999999999999", "999999999999", "1000.00", "15:12", ""),
    "3160823000016": (KNOWN, "630815826944", "900.00", "15:11", "IMPS"),
}
FAILURE_KEYS = {"root_rrn_transaction_id", "root_bankid", "root_account_number", "amount",
                "transaction_datetime", "disputed_amount", "remarks", "status_code"}


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(processor, "_now", lambda: FROZEN)


def seed_sheet(ack, account=None, rrn=None, transaction_type=None):
    acct, r, amount, hhmm, tt = SHEET[ack]
    h, m = map(int, hhmm.split(":"))
    return seed(ack=ack, account=account or acct, sub_category="UPI Related Frauds",
                transaction_type=tt if transaction_type is None else transaction_type,
                wallet="Phonepe",
                incidents=[incident(merchant_id=rrn or r, amount=amount, disputed=amount,
                                    layer=0, d=DAY, t=time(h, m))])


def sheet_txn(narratives, ack, sign="-"):
    _, _, amount, hhmm, _ = SHEET[ack]
    return txn(narratives, f"{sign}{amount}", WHEN.format(hhmm))


def outcome(gw, ack):
    p, logs, steps = state(ack)
    [log] = [row for row in logs if row.job_id == p.job_id]
    [resp] = [r for r in gw.sent if r["acknowledgement_no"] == ack]
    assert resp == log.response_payload                  # callback == stored response
    return p, log, resp["transactions"]


def step_rows(ack, name):
    with db.session_scope() as s:
        return s.query(models.ProcessingStep).filter_by(acknowledgement_no=ack, step=name).all()


# --- the six sheet cases ----------------------------------------------------------

def test_0011_valid_upi_transaction_returns_00(gw):
    gw.history = [sheet_txn(["UPI", "630818826981", "P2A"], "3160823000011")]
    seed_sheet("3160823000011")
    run()
    p, log, [obj] = outcome(gw, "3160823000011")
    assert (obj["txn_type"], obj["status_code"], obj["remarks"]) == ("Money Transfer To", "00", "")
    assert obj["payee_account_number"] == "50100200300"
    assert obj["root_account_number"] == KNOWN and obj["amount"] == "50000.00"
    assert (log.response_code, log.response_message, log.is_success) == ("00", "SUCCESS", True)
    assert p.processing_state == "RESOLVED"
    assert "apply_hold" not in gw.names()                # UPI debit: no hold
    [ack] = step_rows("3160823000011", "MHA_ACK")
    assert ack.status == "SUCCESS" and log.acknowledgement_mha["statuscode"] == "00"


@pytest.mark.parametrize("absence", ["http_404", "documented_empty_history"])
def test_0012_account_absent_returns_01(gw, absence):
    if absence == "http_404":
        gw.errors["transaction_history"] = GatewayError("account not found", status_code=404,
                                                        body={"errors": [{"code": "NF"}]})
    seed_sheet("3160823000012")
    run()
    p, log, [obj] = outcome(gw, "3160823000012")
    assert (obj["status_code"], obj["remarks"]) == ("01", "Record not found")
    assert set(obj) == FAILURE_KEYS
    assert (log.response_code, log.response_message, log.is_success) == ("01", "FAILURE", False)
    assert gw.names() == ["transaction_history", "mha_response"]
    assert p.processing_state == "NEEDS_REVIEW"


@pytest.mark.parametrize("ack", ["3160823000013", "3160823000014"])
def test_0013_0014_invalid_account_returns_12_before_any_gateway_call(gw, ack):
    seed_sheet(ack)
    run()
    p, log, [obj] = outcome(gw, ack)
    assert (obj["status_code"], obj["remarks"]) == ("12", "Invalid account number")
    assert obj["root_account_number"] == SHEET[ack][0]   # echoed exactly as received
    assert obj["transaction_datetime"] == "2026-11-04 15:16:00"
    assert (log.response_code, log.response_message, log.is_success) == ("12", "FAILURE", False)
    assert gw.names() == ["mha_response"]                # no lookup, no hold
    assert step_rows(ack, "HOLD") == [] and p.processing_state == "NEEDS_REVIEW"


@pytest.mark.parametrize("absence", ["http_404", "documented_empty_history"])
def test_0015_original_fixture_account_absence_wins_over_rrn(gw, absence):
    """The sheet changed BOTH fields; the account check runs first, so 01 — never 02."""
    if absence == "http_404":
        gw.errors["transaction_history"] = GatewayError("account not found", status_code=404)
    seed_sheet("3160823000015")
    run()
    _, log, [obj] = outcome(gw, "3160823000015")
    assert (log.response_code, obj["status_code"]) == ("01", "01")


def test_0015_corrected_known_account_without_that_rrn_returns_02(gw):
    gw.history = [txn(["UPI", "630815826900"], "-120.00", WHEN.format("09:00")),
                  sheet_txn(["UPI", "630818826981"], "3160823000011")]
    seed_sheet("3160823000015", account=KNOWN)
    run()
    p, log, [obj] = outcome(gw, "3160823000015")
    assert (obj["status_code"], obj["remarks"]) == ("02", "Invalid RRN")
    assert obj["root_rrn_transaction_id"] == "999999999999"
    assert (log.response_code, log.is_success) == ("02", False)
    assert "upi_bene_lookup" not in gw.names() and p.processing_state == "NEEDS_REVIEW"


def test_0016_imps_record_returns_31_and_keeps_transaction_type(gw):
    gw.history = [sheet_txn(["IMPS", "630815826944", "HDFC/500021522001"], "3160823000016")]
    seed_sheet("3160823000016")
    run()
    p, log, [obj] = outcome(gw, "3160823000016")
    assert (obj["status_code"], obj["remarks"]) == ("31", "Pending")
    assert (log.response_code, log.response_message, log.is_success) == ("31", "PENDING", False)
    assert "upi_bene_lookup" not in gw.names()
    with db.session_scope() as s:
        assert s.query(models.Instrument).one().transaction_type == "IMPS"


def test_imps_label_alone_does_not_route_without_the_bank_record(gw):
    """transaction_type is metadata; with an untagged record the UPI lookup decides."""
    gw.history = [sheet_txn(["630815826944"], "3160823000016")]
    seed_sheet("3160823000016")
    run()
    assert "upi_bene_lookup" in gw.names()
    assert outcome(gw, "3160823000016")[2][0]["status_code"] == "00"


def test_all_six_in_one_batch(gw):
    gw.history = [sheet_txn(["UPI", "630818826981"], "3160823000011"),
                  sheet_txn(["IMPS", "630815826944"], "3160823000016")]
    real = gw.transaction_history

    def history(account, from_date=None, to_date=None):
        if account == "999999999999":
            gw.calls.append(("transaction_history", {"account": account}))
            raise GatewayError("account not found", status_code=404)
        return real(account, from_date)
    gw.transaction_history = history
    for ack in SHEET:
        seed_sheet(ack)
    run()
    got = {ack: outcome(gw, ack)[1].response_code for ack in SHEET}
    assert got == {"3160823000011": "00", "3160823000012": "01", "3160823000013": "12",
                   "3160823000014": "12", "3160823000015": "01", "3160823000016": "31"}


# --- receipt rows / initial-ack-only observations -----------------------------------

def _receipt(ack, job_id):
    """What the ingest service writes on receipt: 00, no complaint_id, no payload."""
    with db.session_scope() as s:
        s.add(models.ApiResponseLog(acknowledgement_no=ack, job_id=job_id,
                                    response_code="00", response_message="SUCCESS"))
        s.commit()


def test_receipt_rows_are_not_results_and_are_never_overwritten(gw):
    seed_sheet("3160823000013")
    _receipt("3160823000013", "BANKS-370fbaf8-c191-40f4-8885-c9c2e71ab0db")
    with db.session_scope() as s:      # before processing: only the receipt exists
        assert s.query(models.ComplaintProcessing).count() == 0
    run()
    with db.session_scope() as s:
        rows = {r.job_id: r for r in s.query(models.ApiResponseLog).all()}
        p = s.query(models.ComplaintProcessing).one()
    receipt = rows.pop("BANKS-370fbaf8-c191-40f4-8885-c9c2e71ab0db")
    assert (receipt.response_code, receipt.response_payload, receipt.complaint_id,
            receipt.responded_at, receipt.acknowledgement_mha) == ("00", None, None, None, None)
    [final] = rows.values()
    assert final.job_id == p.job_id != receipt.job_id
    assert (final.response_code, final.is_success) == ("12", False)


def test_ack_naming_another_job_is_not_stored_on_that_row(gw, monkeypatch):
    receipt_job = "BANKS-63466ae6-799a-40bd-bda4-ca0eab1e4d0b"
    _receipt("3160823000014", receipt_job)

    def mha_response(encrypted):
        gw.calls.append(("mha_response", {}))
        gw.sent.append(encryption.decrypt_payload(encrypted))
        return {"data": {"raw": encryption.encrypt_payload(
            {"message": f"Response has been successfully added. {receipt_job}",
             "statuscode": "00"})}}
    monkeypatch.setattr(gw, "mha_response", mha_response)
    seed_sheet("3160823000014")
    run()
    with db.session_scope() as s:
        logs = {r.job_id: r for r in s.query(models.ApiResponseLog).all()}
    assert logs[receipt_job].acknowledgement_mha is None
    [ack] = step_rows("3160823000014", "MHA_ACK")
    assert ack.status == "PENDING" and "not BANKS-" in ack.response_payload["problem"]


# --- the special missing-date-and-RRN workflow (separate from receipts) ----------

def test_missing_date_and_rrn_is_ack_only_and_distinct_from_a_receipt(gw):
    seed(ack="ACKONLY000001", account=KNOWN,
         incidents=[incident(merchant_id="", amount="900.00", disputed="900.00", d=None, t=None)])
    run()
    p, [log], steps = state("ACKONLY000001")
    assert gw.calls == [] and steps == []
    assert log.response_payload == {"acknowledgement_no": "ACKONLY000001"}
    assert (log.response_code, log.complaint_id) == ("12", p.complaint_id)


def test_ingest_schema_cannot_carry_the_missing_date_workflow():
    """Documented constraint: the Pydantic contract (and the shared DDL's NOT NULL
    date/time) reject this payload, so it can only arrive via direct DB writes."""
    import pydantic
    import schemas
    with pytest.raises(pydantic.ValidationError):
        schemas.IncidentIn.model_validate({"amount": "900.00", "disputed_amount": "900.00",
                                           "rrn": ""})


# --- aggregation -------------------------------------------------------------------

@pytest.mark.parametrize("codes,complete,want", [
    (["00"], True, ("00", "SUCCESS")),
    (["00", "00"], True, ("00", "SUCCESS")),
    (["00", "31"], True, ("31", "PENDING")),
    (["31"], True, ("31", "PENDING")),
    (["00", "02"], True, ("02", "FAILURE")),
    (["31", "02", "01"], True, ("01", "FAILURE")),
    (["02", "01", "12"], True, ("12", "FAILURE")),
    ([], True, ("31", "PENDING")),
    (["00"], False, ("31", "PENDING")),
    (["02"], False, ("02", "FAILURE")),
])
def test_business_result_precedence(codes, complete, want):
    assert processor._business_result([{"status_code": c} for c in codes], complete) == want


@pytest.mark.parametrize("bad", [[{"status_code": "99"}], [{}], [{"status_code": "00"}, {}]])
def test_business_result_rejects_unsupported_codes(bad):
    with pytest.raises(ValueError):
        processor._business_result(bad)


def test_small_appended_object_cannot_make_a_failure_look_successful(gw):
    gw.history = [txn(["UPI", "630815826900"], "-120.00", WHEN.format("09:00"))]
    seed(account=KNOWN, incidents=[
        incident(merchant_id="999999999999", amount="900.00", disputed="900.00", d=DAY),
        incident(merchant_id="630815826901", amount="300.00", disputed="300.00", d=DAY)])
    run()
    p, [log], _ = state()
    objs = gw.sent[0]["transactions"]
    assert [(o["status_code"], o.get("txn_type_id")) for o in objs] == [("02", None), ("00", "17")]
    assert (log.response_code, log.is_success) == ("02", False)


def test_account_absence_with_small_incident_is_01(gw):
    gw.errors["transaction_history"] = GatewayError("nf", status_code=404)
    seed(account="999999999999", incidents=[
        incident(merchant_id="630815826975", amount="1000.00", disputed="1000.00", d=DAY),
        incident(merchant_id="630815826976", amount="200.00", disputed="200.00", d=DAY)])
    run()
    assert [o["status_code"] for o in gw.sent[0]["transactions"]] == ["01", "00"]
    assert state()[1][0].response_code == "01"


# --- leading zeros / direct-DB ingestion --------------------------------------------

def test_direct_db_ingestion_keeps_string_account_and_validates_in_worker(gw):
    """Production ingestion writes rows directly, bypassing Pydantic."""
    gw.history = [sheet_txn(["UPI", "630818826981"], "3160823000011")]
    with db.session_scope() as s:
        conn = s.connection()
        for ack, acct in (("DIRECT0000001", "'003240868006'"),     # string: zeros kept
                          ("DIRECT0000002", "003240868006")):      # numeric literal: lost
            cid = conn.execute(text(
                "INSERT INTO complaints (acknowledgement_no, sub_category, status) "
                f"VALUES ('{ack}', 'UPI Related Frauds', 'OPEN') RETURNING id")).scalar()
            iid = conn.execute(text(
                "INSERT INTO instruments (complaint_id, requestor, payer_bank, payer_bank_code, "
                "mode_of_payment, transaction_type, payer_mobile_number, payer_account_number) "
                f"VALUES ({cid}, 'I4C-MHA', 'HSBC', '10', 'Debit', 'Unknown', '919798868768', "
                f"{acct}) RETURNING id")).scalar()
            conn.execute(text(
                "INSERT INTO incidents (instrument_id, merchant_id, amount, disputed_amount, "
                f"layer, transaction_date, transaction_time) VALUES ({iid}, '630818826981', "
                "50000.00, 50000.00, 0, '2026-11-04', '18:44:00')"))
        s.commit()
    run()
    by_ack = {r["acknowledgement_no"]: r["transactions"][0] for r in gw.sent}
    assert by_ack["DIRECT0000001"]["status_code"] == "00"
    assert by_ack["DIRECT0000001"]["root_account_number"] == "003240868006"
    assert (by_ack["DIRECT0000002"]["status_code"],
            by_ack["DIRECT0000002"]["root_account_number"]) == ("12", "3240868006")
    assert [kw["account"] for n, kw in gw.calls if n == "transaction_history"] == [KNOWN]


def test_pydantic_ingest_keeps_account_string_and_scheme_metadata(gw):
    import main
    import schemas
    payload = {"acknowledgement_no": "3160823000016", "sub_category": "UPI Related Frauds",
               "instrument": {"requestor": "I4C-MHA", "payer_bank": "HSBC",
                              "payer_bank_code": "10", "mode_of_payment": "Debit",
                              "payer_mobile_number": "919798868768",
                              "payer_account_number": KNOWN, "transaction_type": "IMPS",
                              "wallet": "Phonepe", "incidents": [
                                  {"amount": "900.00", "rrn": "630815826944",
                                   "transaction_date": "2026-11-04", "transaction time": "15:11",
                                   "disputed_amount": "900.00", "layer": "0"}]}}
    main._ingest(schemas.ComplaintIn.model_validate(payload))
    with db.session_scope() as s:
        inst = s.query(models.Instrument).one()
        assert (inst.payer_account_number, inst.transaction_type) == (KNOWN, "IMPS")
    numeric = dict(payload, instrument=dict(payload["instrument"], payer_account_number=3240868006))
    import pydantic
    with pytest.raises(pydantic.ValidationError):       # never silently drop the zeros
        schemas.ComplaintIn.model_validate(numeric)


# --- gateway failures are retried, never mapped to 01/02/31 -------------------------

ROUTE_404 = GatewayError("no route", status_code=404, body={"detail": "Not Found"})


@pytest.mark.parametrize("failure", [
    GatewayError("upstream down", status_code=503),
    GatewayError("Gateway network error: ReadTimeout"),            # 502 default
    GatewayError("unauthorised", status_code=401),
    ROUTE_404,
    {"errors": [{"code": "E500"}]},                                # HTTP-200 app error
    {"raw": "<html>bad gateway</html>"},                           # malformed body
    {},
])
def test_dd_enquiry_failures_are_retried_then_parked_without_a_response(gw, failure):
    if isinstance(failure, GatewayError):
        gw.transaction_history = lambda *a, **k: (_ for _ in ()).throw(failure)
    else:
        gw.history_resp = failure
    seed_sheet("3160823000011")
    run(config.MAX_ATTEMPTS + 1)
    p, logs, steps = state("3160823000011")
    assert logs == [] and gw.sent == [] and steps == []
    assert p.processing_state == "NEEDS_REVIEW" and p.attempt_count == config.MAX_ATTEMPTS
    assert p.last_error                                  # the cause stays visible


def test_upi_outage_in_debit_path_is_retried_not_pending(gw):
    gw.history = [sheet_txn(["UPI", "630818826981"], "3160823000011")]
    gw.errors["upi_bene_lookup"] = GatewayError("UPI switch down", status_code=503)
    seed_sheet("3160823000011")
    run()
    p, logs, _ = state("3160823000011")
    assert logs == [] and gw.sent == [] and p.attempt_count == 1
    run()
    assert outcome(gw, "3160823000011")[2][0]["status_code"] == "00"


def _credit(gw, leg_narratives, amount="1000.00"):
    gw.balance = "0"
    gw.history = [txn(["630818826981"], amount, WHEN.format("10:00")),
                  txn(leg_narratives, f"-{amount}", WHEN.format("11:00"))]
    seed(account=KNOWN, mode="Credit", incidents=[
        incident(merchant_id="630818826981", amount=amount, disputed=amount, layer=1, d=DAY)])


def test_reconcile_upi_outage_is_retried_not_reported_as_imps(gw):
    _credit(gw, ["UPI", "630818826982"])
    gw.errors["upi_bene_lookup"] = GatewayError("UPI switch down", status_code=503)
    run()
    assert gw.sent == [] and state()[0].attempt_count == 1
    run()
    [leg] = gw.sent[0]["transactions"]
    assert (leg["status_code"], leg["payee_account_number"]) == ("00", "50100200300")


def test_reconcile_upi_rejection_is_pending(gw):
    _credit(gw, ["UPI", "630818826982"])
    gw.errors["upi_bene_lookup"] = GatewayError("unknown rrn", status_code=400)
    run()
    [leg] = gw.sent[0]["transactions"]
    assert (leg["status_code"], leg["remarks"]) == ("31", "Pending")
    assert state()[1][0].response_code == "31"


def test_reconcile_cbdoc_outage_is_retried_not_a_blank_success(gw):
    _credit(gw, ["NEFT", "HSBCN52026110400034931"])
    gw.errors["bigquery_search"] = GatewayError("BQ down", status_code=500)
    run()
    assert gw.sent == [] and state()[0].attempt_count == 1


def test_reconcile_shortfall_is_never_stored_as_success(gw):
    gw.balance = "0"
    gw.history = [txn(["630818826981"], "1000.00", WHEN.format("10:00")),
                  txn(["UPI", "630818826982"], "-100.00", WHEN.format("11:00"))]
    seed(account=KNOWN, mode="Credit", incidents=[
        incident(merchant_id="630818826981", amount="1000.00", disputed="1000.00",
                 layer=1, d=DAY)])
    run()
    p, [log], _ = state()
    assert [t["status_code"] for t in gw.sent[0]["transactions"]] == ["00"]
    assert p.processing_state == "NEEDS_REVIEW"
    assert (log.response_code, log.is_success) == ("31", False)


# --- the other finalizers ------------------------------------------------------------

def test_dd_probe_finalizer_unknown_rrn_returns_02_summary(gw):
    gw.history = [txn(["SOMETHING"], "-10.00", WHEN.format("09:00"))]
    seed(account=KNOWN, incidents=[incident(merchant_id="REF1234567", d=DAY)])
    run()
    [obj] = gw.sent[0]["transactions"]
    assert (obj["status_code"], state()[1][0].response_code) == ("02", "02")


def test_dd_probe_finalizer_found_returns_00(gw):
    gw.history = [txn(["REF1234567"], "-1000.00", WHEN.format("09:00"))]
    seed(account=KNOWN, incidents=[incident(merchant_id="REF1234567", d=DAY)])
    run()
    assert state()[1][0].response_code == "00"


def test_dd_probe_finalizer_outage_is_retried_not_01(gw):
    gw.errors["transaction_history"] = GatewayError("down", status_code=503)
    seed(account=KNOWN, incidents=[incident(merchant_id="REF1234567", d=DAY)])
    run()
    p, logs, _ = state()
    assert logs == [] and gw.sent == [] and p.attempt_count == 1


UTR = "HSBCN52026110400034931"


@pytest.mark.parametrize("rows,code", [
    ([cbdoc_row("2026-11-04-10.11.12.000000", utr=UTR)], "00"),
    ([cbdoc_row("2026-11-05-10.11.12.000000", utr=UTR)], "02"),   # no dated row
    ([], "31"),                                                    # not in CBDOC yet
])
def test_cbdoc_finalizer_summary_matches_its_object(gw, rows, code):
    gw.history = [txn([UTR], "-1000.00", WHEN.format("10:00"))]
    gw.cbdoc_rows = rows
    seed(account=KNOWN, incidents=[incident(merchant_id=UTR, d=DAY)])
    run()
    [obj] = gw.sent[0]["transactions"]
    assert obj["status_code"] == code == state()[1][0].response_code


# --- holds: never duplicated, uncertain outcomes never replayed ----------------------

def _hold_case(gw):
    gw.balance = "5000.00"
    gw.history = [txn(["630818826981"], "1000.00", WHEN.format("10:00"))]
    seed(account=KNOWN, mode="Credit", incidents=[
        incident(merchant_id="630818826981", amount="1000.00", disputed="1000.00",
                 layer=1, d=DAY)])


def test_hold_timeout_is_uncertain_and_never_replayed(gw):
    _hold_case(gw)
    gw.errors["apply_hold"] = GatewayError("Gateway network error: ReadTimeout")
    run(config.MAX_ATTEMPTS + 1)
    p, logs, _ = state()
    assert gw.names().count("apply_hold") == 1
    [hold] = step_rows("ACK0000000001", "HOLD")
    assert hold.status == "PENDING" and "ReadTimeout" in hold.response_payload["error"]
    assert p.processing_state == "NEEDS_REVIEW" and "outcome is unknown" in p.last_error
    assert logs == [] and gw.sent == []


def test_hold_crash_after_bank_applied_it_is_not_replayed(gw):
    _hold_case(gw)
    real = gw.apply_hold

    def apply_then_die(**kw):
        real(**kw)
        raise RuntimeError("process killed after the bank applied the hold")
    gw.apply_hold = apply_then_die
    run(3)
    assert gw.names().count("apply_hold") == 1
    assert [h.status for h in step_rows("ACK0000000001", "HOLD")] == ["PENDING"]


def test_hold_200_not_success_is_uncertain(gw, monkeypatch):
    _hold_case(gw)
    monkeypatch.setattr(gw, "apply_hold", lambda **kw: gw.calls.append(("apply_hold", kw))
                        or {"data": {"status": "QUEUED"}})
    run(3)
    assert gw.names().count("apply_hold") == 1
    assert step_rows("ACK0000000001", "HOLD")[0].status == "PENDING"


def test_hold_rejection_is_definite_and_retaken_once(gw):
    _hold_case(gw)
    gw.errors["apply_hold"] = GatewayError("invalid hold", status_code=422)
    run(3)
    [hold] = step_rows("ACK0000000001", "HOLD")
    assert (hold.status, hold.attempt) == ("SUCCESS", 2)
    assert gw.names().count("apply_hold") == 2
    [obj] = gw.sent[0]["transactions"]
    assert (obj["txn_type_id"], obj["amount"]) == ("1", "1000.00")


def test_hold_is_not_duplicated_when_the_balance_moves_between_retries(gw):
    _hold_case(gw)
    gw.errors["mha_response"] = GatewayError("MHA down", status_code=503)
    run()                                               # hold applied, send failed
    with db.session_scope() as s:                       # lose cached balance + state
        s.query(models.ProcessingStep).filter_by(step="DD_ENQUIRY").delete()
        s.query(models.ComplaintProcessing).update({"processing_state": "BALANCE_CHECKED"})
        s.commit()
    gw.balance = "700.00"                               # would key a different hold
    run()
    assert gw.names().count("apply_hold") == 1
    assert [h.status for h in step_rows("ACK0000000001", "HOLD")] == ["SUCCESS"]
    assert [o["amount"] for o in gw.sent[0]["transactions"]] == ["1000.00"]


# --- callback delivery vs MHA acceptance ---------------------------------------------

def test_missing_encryption_key_outside_dev_mode_is_visible(gw, monkeypatch):
    monkeypatch.setattr(config, "MHA_RESPONSE_KEY_B64", "")
    seed_sheet("3160823000013")
    run(config.MAX_ATTEMPTS + 1)
    p, logs, steps = state("3160823000013")
    assert gw.sent == [] and steps == []
    assert p.processing_state == "NEEDS_REVIEW" and "MHA_RESPONSE_KEY_B64" in p.last_error


def test_dev_mode_skips_the_send_explicitly(gw, monkeypatch):
    monkeypatch.setattr(config, "MHA_RESPONSE_KEY_B64", "")
    monkeypatch.setattr(config, "MHA_DEV_MODE", True)
    seed_sheet("3160823000013")
    run()
    p, [log], steps = state("3160823000013")
    assert gw.sent == [] and steps == [] and log.response_code == "12"


@pytest.mark.parametrize("reply,status", [
    ({"data": {"raw": "@@not-base64@@"}}, "PENDING"),
    ({"data": {}}, "PENDING"),
    ("ENC:01", "FAILURE"),
])
def test_http_200_is_delivery_not_acceptance(gw, monkeypatch, reply, status):
    if reply == "ENC:01":
        reply = {"data": {"raw": encryption.encrypt_payload(
            {"message": "rejected", "statuscode": "01"})}}
    monkeypatch.setattr(gw, "mha_response",
                        lambda enc: gw.sent.append(encryption.decrypt_payload(enc)) or reply)
    seed_sheet("3160823000013")
    run(2)
    p, [log], [sent] = state("3160823000013")
    [ack] = step_rows("3160823000013", "MHA_ACK")
    assert sent.status == "SUCCESS"                      # delivered over HTTP ...
    assert ack.status == status and ack.response_payload["problem"]   # ... not accepted
    assert (log.acknowledgement_mha is None) == (status == "PENDING")
    assert len(gw.sent) == 1                             # a rejection is never auto-resent


def test_callback_retry_exhaustion_stays_diagnosable(gw, monkeypatch):
    def down(encrypted):
        gw.calls.append(("mha_response", {}))
        raise GatewayError("MHA down", status_code=503)
    monkeypatch.setattr(gw, "mha_response", down)
    seed_sheet("3160823000013")
    run(config.MAX_ATTEMPTS + 2)
    p, [log], [sent] = state("3160823000013")
    assert gw.names().count("mha_response") == config.MAX_ATTEMPTS
    assert (sent.status, sent.attempt) == ("FAILURE", config.MAX_ATTEMPTS)
    assert p.processing_state == "NEEDS_REVIEW" and "MHA down" in p.last_error
    assert log.response_code == "12" and log.acknowledgement_mha is None


# --- batch / manual concurrency ------------------------------------------------------

def test_manual_trigger_cannot_run_alongside_a_leased_batch_worker(gw):
    from fastapi.testclient import TestClient

    import main
    seed_sheet("3160823000013")
    [pid] = processor.claim_batch(10)                    # a batch worker holds the lease
    r = TestClient(main.app).post("/process/3160823000013")
    assert r.status_code == 200 and r.json()["claimed"] is False
    assert gw.calls == []
    assert processor._process_one(pid) == "NEEDS_REVIEW"  # the lease holder finishes
    assert len(gw.sent) == 1
    assert TestClient(main.app).post("/process/3160823000013").json() == {
        "acknowledgement_no": "3160823000013", "state": "NEEDS_REVIEW", "claimed": False}


def test_manual_trigger_claims_and_assigns_a_job_id(gw):
    from fastapi.testclient import TestClient

    import main
    seed_sheet("3160823000014")
    r = TestClient(main.app).post("/process/3160823000014")
    assert r.json() == {"acknowledgement_no": "3160823000014", "state": "NEEDS_REVIEW",
                        "claimed": True}
    p, [log], _ = state("3160823000014")
    assert p.job_id and log.job_id == p.job_id


def test_concurrent_claims_never_share_a_complaint(gw):
    for ack in SHEET:
        seed_sheet(ack)
    got, start = [], threading.Barrier(3)

    def worker():
        start.wait(10)
        got.append(processor.claim_batch(4))
    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    claimed = [pid for ids in got for pid in ids]
    assert len(claimed) == len(set(claimed)) == len(SHEET)
