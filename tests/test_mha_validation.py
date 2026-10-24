"""MHA input validation and response codes, end to end through process_batch."""
from __future__ import annotations

import pytest

import processor
from conftest import (ACCOUNT, UPI_RRN, UTR, GatewayError, incident, run,
                      seed, state, txn)

FAILURE_KEYS = {"root_rrn_transaction_id", "root_bankid", "root_account_number", "amount",
                "transaction_datetime", "disputed_amount", "remarks", "status_code"}


def _only_response(gw):
    assert len(gw.sent) == 1, gw.sent
    return gw.sent[0]


# --- code 12: invalid account / input ----------------------------------------------

@pytest.mark.parametrize("account", [
    "12345",                    # too short
    "0063611410012",            # 13 digits
    "00636114100A",             # non-numeric
    "INHSBC006361141001",       # HSBC-prefixed form
    " 006361141001",            # padded
    "",                         # empty
    "٠٠٦٣٦١١٤١٠٠١",             # 12 non-ASCII (Arabic-Indic) digits
])
def test_invalid_account_returns_12_without_upstream_calls(gw, account):
    seed(account=account)
    run()
    p, logs, _ = state()
    resp = _only_response(gw)
    assert gw.names() == ["mha_response"]              # nothing before the callback
    assert p.processing_state == "NEEDS_REVIEW"
    assert p.last_error == "Invalid account number"
    assert logs[0].response_code == "12"
    assert resp["acknowledgement_no"] == "ACK0000000001" and resp["job_id"] == p.job_id
    [obj] = resp["transactions"]
    assert set(obj) == FAILURE_KEYS
    assert (obj["status_code"], obj["remarks"]) == ("12", "Invalid account number")


def test_invalid_input_missing_utr_returns_12(gw):
    seed(incidents=[incident(merchant_id="")])          # date present, UTR missing
    run()
    [obj] = _only_response(gw)["transactions"]
    assert (obj["status_code"], obj["remarks"]) == ("12", "Invalid input")
    assert gw.names() == ["mha_response"]


def test_leading_zeros_are_kept_end_to_end(gw):
    seed(account="000000000012", incidents=[incident(merchant_id=UPI_RRN)])
    run()
    p, _, _ = state()
    assert p.processing_state == "RESOLVED"
    [(_, upi)] = [c for c in gw.calls if c[0] == "upi_bene_lookup"]
    assert upi["account_number"] == "000000000012"
    assert _only_response(gw)["transactions"][0]["root_account_number"] == "000000000012"


# --- account + amount, no date, no UTR: ack only, no callback -------------------------

@pytest.mark.parametrize("account", [ACCOUNT, "12345"])
def test_missing_date_and_utr_acknowledges_only_and_never_calls_back(gw, account):
    pid = seed(account=account, incidents=[incident(merchant_id="", d=None, t=None)])
    run(3)
    processor._process_one(pid)                         # the manual trigger too
    p, logs, steps = state()
    assert gw.calls == []                               # no upstream call, no callback
    assert steps == []
    assert p.processing_state == "NEEDS_REVIEW"
    [log] = logs
    assert log.response_payload == {"acknowledgement_no": "ACK0000000001"}


# --- 01 / 20 / 31 ------------------------------------------------------------------

def test_account_not_found_returns_01(gw):
    gw.errors["transaction_history"] = GatewayError("not found", status_code=404)
    seed()
    run()
    p, logs, _ = state()
    [obj] = _only_response(gw)["transactions"]
    assert (obj["status_code"], obj["remarks"]) == ("01", "Record not found")
    assert logs[0].response_code == "01"
    assert p.processing_state == "NEEDS_REVIEW"


def test_other_gateway_errors_are_still_retried_not_reported(gw):
    gw.errors["transaction_history"] = GatewayError("upstream down", status_code=503)
    seed()
    run()
    p, logs, _ = state()
    assert logs == [] and gw.sent == []
    assert p.attempt_count == 1 and p.processing_state not in ("RESOLVED", "NEEDS_REVIEW")


def test_utr_not_found_returns_20(gw):
    gw.history = [txn(["SOMETHING ELSE"], "-10.00", "2026-06-09T10:00:00+05:30")]
    seed()
    run()
    [obj] = _only_response(gw)["transactions"]
    assert (obj["status_code"], obj["remarks"]) == ("20", "Invalid RRN")
    assert state()[1][0].response_code == "20"


def test_imps_and_atm_legs_return_31_pending(gw):
    gw.balance = "0"                                     # nothing to hold -> reconcile all
    gw.history = [
        txn([UPI_RRN], "1000.00", "2026-06-09T10:00:00+05:30"),             # the fraud credit
        txn(["IMPS", "123456789012"], "-600.00", "2026-06-09T11:00:00+05:30"),
        txn(["ATM", "223456789012"], "-400.00", "2026-06-09T12:00:00+05:30"),
    ]
    seed(mode="Credit", incidents=[incident(merchant_id=UPI_RRN, layer=1)])
    run()
    legs = _only_response(gw)["transactions"]
    assert [(t["rrn_transaction_id"], t["status_code"], t["remarks"]) for t in legs] == [
        ("123456789012", "31", "Pending"), ("223456789012", "31", "Pending")]
    assert "upi_bene_lookup" not in gw.names()           # IMPS/ATM are never looked up
    assert state()[0].processing_state == "RESOLVED"


def test_atm_needs_an_exact_token():
    assert processor._scheme_from_narratives(
        {"transactionDescription": [{"transactionNarrative": "ATMARAM/UPI"}]}) == "UPI"
    assert processor._scheme_from_narratives(
        {"transactionDescription": [{"transactionNarrative": "ATM/WDL"}]}) == "ATM"


# --- existing behaviour stays compatible -------------------------------------------

MONEY_TRANSFER_KEYS = {
    "rrn_transaction_id", "payee_bank", "payee_bank_code", "payee_account_number", "amount",
    "transaction_datetime", "disputed_amount", "ifsc_code", "txn_type", "txn_type_id",
    "phone_number", "email", "pan_number", "root_account_number", "root_rrn_transaction_id",
    "root_bankid", "status_code", "remarks", "root_effective_balance", "root_ifsc_code"}


def test_upi_debit_with_small_incident_keeps_contract(gw):
    seed(incidents=[incident(merchant_id=UPI_RRN),
                    incident(merchant_id="244444440009", amount="300.00", disputed="300.00")])
    run()
    p, logs, steps = state()
    resp = _only_response(gw)
    assert set(resp) == {"acknowledgement_no", "job_id", "transactions"}
    assert resp["job_id"] == p.job_id and p.job_id.startswith("BANKS-")
    money, small = resp["transactions"]
    assert set(money) == MONEY_TRANSFER_KEYS and money["status_code"] == "00"
    assert money["payee_account_number"] == "50100200300"
    assert small["txn_type_id"] == "17"
    assert p.processing_state == "RESOLVED"
    assert [s.status for s in steps] == ["SUCCESS"]
    assert logs[0].acknowledgement_mha["statuscode"] == "00"   # MHA ack stored


def test_ib_debit_with_empty_cbdoc_keeps_blank_bene(gw):
    gw.history = [txn([UTR], "-1000.00", "2026-06-09T10:00:00+05:30")]
    gw.cbdoc_rows = []                                   # not in CBDOC yet: unchanged behaviour
    seed()
    run()
    [obj] = _only_response(gw)["transactions"]
    assert obj["status_code"] == "00" and obj["payee_account_number"] == ""
