"""The I4C-MHA UPI test sheet (TC02-TC08) plus edge cases, against controlled
records: the fake gateway's DD transaction history *is* the account's record."""
from __future__ import annotations

from datetime import date

import pytest

from conftest import GatewayError, incident, run, seed, state, txn

RRN = "630815826975"
OTHER_RRN = "630815826900"
WHEN = "2026-11-04T10:00:00+05:30"


def _fraud(rrn=RRN):
    return incident(merchant_id=rrn, amount="1500.00", disputed="1500.00", d=date(2026, 11, 4))


def _result(gw):
    p, [log], _ = state()
    [resp] = gw.sent
    assert resp == log.response_payload                  # callback == API_response log
    return p, log, resp["transactions"]


# --- TC02: valid-format account that has no records ---------------------------------

def test_tc02_account_unknown_to_bank_returns_01(gw):
    gw.errors["transaction_history"] = GatewayError("account not found", status_code=404)
    seed(account="999999999999", incidents=[_fraud()])
    run()
    p, log, [obj] = _result(gw)
    assert (log.response_code, log.response_message) == ("01", "FAILURE")
    assert (obj["status_code"], obj["remarks"]) == ("01", "Record not found")
    assert "upi_bene_lookup" not in gw.names()
    assert p.processing_state == "NEEDS_REVIEW"


def test_tc02_account_with_no_transactions_returns_01(gw):
    gw.history = []                                      # bank knows no record for it
    seed(account="999999999999", incidents=[_fraud()])
    run()
    _, log, [obj] = _result(gw)
    assert (obj["status_code"], obj["remarks"]) == ("01", "Record not found")
    assert "upi_bene_lookup" not in gw.names()


# --- TC03 / TC04 live in test_mha_validation (parametrised, incl. both values) ------


# --- TC05: valid account, RRN not among its transactions ------------------------------

def test_tc05_valid_account_unknown_rrn_returns_02(gw):
    gw.history = [txn([OTHER_RRN], "-200.00", WHEN)]     # account exists, other txn only
    seed(incidents=[_fraud(rrn="999999999999")])
    run()
    p, log, [obj] = _result(gw)
    assert (log.response_code, obj["status_code"], obj["remarks"]) == ("02", "02", "Invalid RRN")
    assert obj["root_rrn_transaction_id"] == "999999999999"   # echoed only in the failure
    assert "txn_type" not in obj                         # no Money Transfer To
    assert "upi_bene_lookup" not in gw.names()


def test_tc05_sheet_payload_is_rejected_by_the_account_first(gw):
    """The sheet's TC05 changed BOTH fields: the account check wins (01), by design."""
    gw.history = []
    seed(account="999999999999", incidents=[_fraud(rrn="999999999999")])
    run()
    assert _result(gw)[2][0]["status_code"] == "01"


# --- TC06 / TC07: the bank record is IMPS / ATM ------------------------------------------

@pytest.mark.parametrize("scheme", ["IMPS", "ATM"])
def test_tc06_tc07_imps_or_atm_record_returns_31_pending(gw, scheme):
    gw.history = [txn([scheme, RRN, "HDFC/500021522001"], "-1500.00", WHEN)]
    seed(account="003240868006", incidents=[_fraud()])
    run()
    p, log, [obj] = _result(gw)
    assert (log.response_code, log.response_message) == ("31", "PENDING")
    assert (obj["status_code"], obj["remarks"]) == ("31", "Pending")
    assert "txn_type" not in obj
    assert "upi_bene_lookup" not in gw.names()           # IMPS/ATM are never looked up
    assert obj["root_account_number"] == "003240868006"


def test_incoming_transaction_type_does_not_override_the_record(gw):
    """instrument.transaction_type is never read: a UPI record stays UPI."""
    gw.history = [txn(["UPI", RRN], "-1500.00", WHEN)]
    seed(incidents=[_fraud()])            # seed() uses transaction_type 'P2P'; 'IMPS'
    run()                                 # is coerced to 'Unknown' at ingest anyway
    assert _result(gw)[2][0]["status_code"] == "00"


def test_upi_reply_without_beneficiary_is_pending_not_success(gw, monkeypatch):
    gw.history = [txn([RRN], "-1500.00", WHEN)]
    monkeypatch.setattr(gw, "upi_bene_lookup",
                        lambda **kw: gw.calls.append(("upi_bene_lookup", kw)) or {"data": {}})
    seed(incidents=[_fraud()])
    run()
    _, log, [obj] = _result(gw)
    assert (log.response_code, obj["status_code"]) == ("31", "31")


def test_mixed_incidents_keep_per_incident_codes(gw):
    gw.history = [txn([RRN], "-1500.00", WHEN), txn(["IMPS", OTHER_RRN], "-900.00", WHEN)]
    seed(incidents=[_fraud(), _fraud(rrn=OTHER_RRN)])
    run()
    _, log, objs = _result(gw)
    assert [o["status_code"] for o in objs] == ["00", "31"]
    assert (log.response_code, log.response_message) == ("00", "SUCCESS")


# --- TC08: valid account + valid RRN + normal UPI transaction ---------------------------

def test_tc08_normal_upi_transaction_succeeds(gw):
    gw.history = [txn(["UPI", RRN], "-1500.00", WHEN)]
    seed(account="003240868006", incidents=[_fraud()])
    run()
    p, log, [obj] = _result(gw)
    assert (log.response_code, log.response_message) == ("00", "SUCCESS")
    assert (obj["txn_type"], obj["txn_type_id"], obj["status_code"]) == (
        "Money Transfer To", "3", "00")
    assert obj["payee_account_number"] == "50100200300"
    assert obj["root_account_number"] == "003240868006"
    assert p.processing_state == "RESOLVED"
    [(_, upi)] = [c for c in gw.calls if c[0] == "upi_bene_lookup"]
    assert (upi["rrn"], upi["account_number"]) == (RRN, "003240868006")


# --- only one field wrong / dates / malformed records -------------------------------------

def test_valid_rrn_on_wrong_date_is_not_found(gw):
    """The RRN exists, but before the reported date: the enquiry from that date
    can't see it, so it is not treated as a match."""
    gw.history = [txn([RRN], "-1500.00", "2026-11-03T10:00:00+05:30"),
                  txn([OTHER_RRN], "-10.00", WHEN)]
    seed(incidents=[_fraud()])
    run()
    assert _result(gw)[2][0]["status_code"] == "02"


def test_wrong_account_with_real_rrn_returns_01(gw):
    """Only the account is wrong: the bank has no records for it."""
    gw.errors["transaction_history"] = GatewayError("no such account", status_code=404)
    seed(account="111111111111", incidents=[_fraud()])
    run()
    assert _result(gw)[2][0]["status_code"] == "01"


def test_malformed_records_never_match(gw):
    gw.history = [
        {"transactionAmount": {"amount": None}, "transactionId": {"executionTimestamp": WHEN},
         "transactionDescription": None},
        {"transactionAmount": {}, "transactionId": {"executionTimestamp": WHEN},
         "transactionDescription": [{"transactionNarrative": None}, {}, "", 5]},
        txn([RRN[:-1]], "-1.00", WHEN),                  # near miss: 11 of 12 digits
    ]
    seed(incidents=[_fraud()])
    run()
    assert _result(gw)[2][0]["status_code"] == "02"


def test_all_flows_check_the_record_before_any_lookup(gw):
    gw.history = [txn([OTHER_RRN], "-10.00", WHEN)]
    seed(incidents=[_fraud()])
    run()
    assert gw.names() == ["transaction_history", "mha_response"]


@pytest.mark.parametrize("narrative,hit", [
    (RRN, True),
    (f"UPI/{RRN}/P2A", True),
    (f"UPI{RRN}", True),                 # glued to a scheme tag
    (f"upi {RRN} ref", True),
    (RRN[:-1], False),                   # truncated
    ("9", False), ("26", False),         # short narratives are not "inside" the RRN
    (f"1{RRN}", False),                  # part of a longer number
    (f"{RRN}0", False),
    ("", False),
])
def test_rrn_matching_is_whole_reference_only(narrative, hit):
    import processor
    t = txn([narrative], "-1.00", WHEN)
    assert (processor._find_txn_by_rrn([t], RRN) is t) is hit


def test_nonexistent_rrn_cannot_ride_on_short_narratives(gw):
    """'999999999999' used to match any narrative like '9' or '99'."""
    gw.history = [txn(["9", "99", "IMPS"], "-10.00", WHEN)]
    seed(incidents=[_fraud(rrn="999999999999")])
    run()
    assert _result(gw)[2][0]["status_code"] == "02"
