"""CBDOC row selection: date match between OGTMZ1 and the UTR, dedupe, conflicts."""
from __future__ import annotations

import pytest

import processor
from conftest import UTR, cbdoc_row, run, seed, state, txn

DAY = "2026-06-09-10.11.12.000000"      # OGTMZ1 on the UTR's date
OTHER_DAY = "2026-06-10-10.11.12.000000"


# --- unit: parsing ------------------------------------------------------------------

@pytest.mark.parametrize("utr,want", [
    (UTR, "20260609"),
    ("HSBCR52026060900034931", "20260609"),     # RTGS
    ("hsbcn52026060900034931", "20260609"),     # case-insensitive
    ("HSBCN16000034931", None),                 # 16-char internal ref: no date
    ("HSBCN5abcdefgh00034931", None),           # not digits
    ("HSBCN52026023000034931", None),           # 30 Feb
    ("XXXXN52026060900034931", None),           # wrong prefix
    ("", None), (None, None),
])
def test_utr_date(utr, want):
    assert processor._utr_date(utr) == want


@pytest.mark.parametrize("bad", [None, "", "garbage", 20260609, "2026-02-30-10.00.00",
                                 "2026-06-09 10:11:12", {"x": 1}])
def test_malformed_ogtmz1_never_matches_or_raises(bad):
    assert processor._cbdoc_row([cbdoc_row(bad)], UTR) is None


def test_one_valid_record_among_many():
    good = cbdoc_row(DAY, bene="/111111111111")
    rows = [cbdoc_row(OTHER_DAY, bene="/222"), cbdoc_row(None, bene="/333"), good,
            cbdoc_row("junk", bene="/444")]
    assert processor._cbdoc_row(rows, UTR) is good


def test_no_match_returns_none():
    assert processor._cbdoc_row([cbdoc_row(OTHER_DAY)], UTR) is None


def test_identical_records_are_deduplicated():
    row = cbdoc_row(DAY)
    assert processor._cbdoc_row([row, dict(row), cbdoc_row(OTHER_DAY)], UTR) == row


def test_distinct_matching_records_raise():
    with pytest.raises(processor.CbdocConflict):
        processor._cbdoc_row([cbdoc_row(DAY, bene="/1"), cbdoc_row(DAY, bene="/2")], UTR)


def test_utr_without_embedded_date_keeps_single_row_and_rejects_ambiguity():
    short = "HSBCN16000034931"
    row = cbdoc_row(None, utr=short)
    assert processor._cbdoc_row([row], short) is row
    with pytest.raises(processor.CbdocConflict):
        processor._cbdoc_row([row, cbdoc_row(None, utr=short, bene="/9")], short)


def test_rows_drops_junk_entries():
    assert processor._rows({"rows": [None, {}, "x", {"a": 1}]}) == [{"a": 1}]


# --- end to end through the IB-debit path ------------------------------------------

@pytest.fixture
def ib_debit(gw):
    gw.history = [txn([UTR], "-1000.00", "2026-06-09T10:00:00+05:30")]
    seed()
    return gw


def test_flow_picks_the_dated_record(ib_debit):
    ib_debit.cbdoc_rows = [cbdoc_row(OTHER_DAY, bene="/999999999999", name="WRONG"),
                           cbdoc_row(DAY, bene="/111111111111", name="RIGHT")]
    run()
    [obj] = ib_debit.sent[0]["transactions"]
    assert obj["payee_account_number"] == "111111111111"
    assert obj["payee_bank"] == "RIGHT"
    assert obj["transaction_datetime"] == "2026-06-09 10:11:12"


def test_flow_no_dated_record_returns_20(ib_debit):
    ib_debit.cbdoc_rows = [cbdoc_row(OTHER_DAY), cbdoc_row("garbage")]
    run()
    [obj] = ib_debit.sent[0]["transactions"]
    assert (obj["status_code"], obj["remarks"]) == ("20", "Invalid RRN")


def test_flow_duplicates_give_one_response_object(ib_debit):
    ib_debit.cbdoc_rows = [cbdoc_row(DAY), cbdoc_row(DAY)]
    run()
    assert len(ib_debit.sent) == 1 and len(ib_debit.sent[0]["transactions"]) == 1


def test_flow_conflict_goes_to_review_without_callback(ib_debit):
    ib_debit.cbdoc_rows = [cbdoc_row(DAY, bene="/1"), cbdoc_row(DAY, bene="/2")]
    run(2)
    p, logs, steps = state()
    assert p.processing_state == "NEEDS_REVIEW"
    assert "different rows" in p.last_error
    assert ib_debit.sent == [] and logs == [] and steps == []
