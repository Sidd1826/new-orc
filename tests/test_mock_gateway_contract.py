"""The real GatewayClient against mock_gateway, end to end: method, parameter and
response-shape mismatches between them fail here instead of in a demo."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config
import gateway_client
import mock_gateway as mock
import processor
from conftest import run, state
from test_mha_sheet_fixtures import KNOWN, frozen_clock, outcome, seed_sheet, step_rows  # noqa: F401


class Recording(gateway_client.GatewayClient):
    def __init__(self):
        super().__init__()
        self._http = TestClient(mock.app, base_url="http://mock")
        self.sent: list[dict] = []
        self.calls: list[str] = []

    def _request(self, method, path, **kw):
        self.calls.append(path)
        return super()._request(method, path, **kw)

    def mha_response(self, encrypted):
        import encryption
        self.sent.append(encryption.decrypt_payload(encrypted))
        return super().mha_response(encrypted)


@pytest.fixture
def real_gw(gw, monkeypatch):           # gw: DB + encryption key; then swap the client
    client = Recording()
    monkeypatch.setattr(processor, "gateway", lambda: client)
    return client


@pytest.mark.parametrize("ack,account,code", [
    ("3160823000011", None, "00"),
    ("3160823000012", None, "01"),                       # ABSENT_ACCOUNT -> HTTP 404
    ("3160823000013", None, "12"),
    ("3160823000014", None, "12"),
    ("3160823000015", None, "01"),                       # original fixture
    ("3160823000015", KNOWN, "02"),                      # corrected fixture
    ("3160823000016", None, "31"),
    ("3160823000012", mock.EMPTY_ACCOUNT, "01"),         # documented empty history
])
def test_sheet_cases_through_the_real_client(real_gw, ack, account, code):
    seed_sheet(ack, account=account)
    run()
    p, log, [obj] = outcome(real_gw, ack)
    assert obj["status_code"] == log.response_code == code
    [accepted] = step_rows(ack, "MHA_ACK")              # mock MHA echoes our job_id
    assert accepted.status == "SUCCESS" and log.acknowledgement_mha["statuscode"] == "00"


def test_upi_request_and_bene_shapes_line_up(real_gw):
    seed_sheet("3160823000011")
    run()
    _, _, [obj] = outcome(real_gw, "3160823000011")
    assert (obj["payee_account_number"], obj["ifsc_code"], obj["payee_bank"]) == (
        "50100200300", "HDFC0000001", "HDFC Bank")
    assert obj["transaction_datetime"] == "2026-11-04 18:44:00"
    assert "/api/v1/upi/secure" in real_gw.calls


def test_history_honours_the_start_date_parameter(real_gw):
    out = real_gw.transaction_history(KNOWN, from_date="2026-11-05")
    assert out["data"]["accountInformation"]["transactionDetails"] == []
    out = real_gw.transaction_history(KNOWN, from_date="2026-11-04")
    assert len(out["data"]["accountInformation"]["transactionDetails"]) == 3


def test_balance_is_at_the_configured_path(real_gw):
    resp = real_gw.demand_deposit(KNOWN)
    assert processor._dig(resp, config.BALANCE_PATH) == "76000.00"


@pytest.mark.parametrize("account", [mock.FAILING_ACCOUNT, mock.MALFORMED_ACCOUNT])
def test_gateway_failures_are_retried_never_a_business_code(real_gw, account):
    seed_sheet("3160823000011", account=account)
    run()
    p, logs, _ = state("3160823000011")
    assert logs == [] and real_gw.sent == [] and p.attempt_count == 1


def test_a_rejected_request_says_why_without_the_account(real_gw):
    import httpx
    real_gw._http = httpx.Client(base_url="http://gw", transport=httpx.MockTransport(
        lambda r: httpx.Response(400, json={"detail": "fromDate not allowed", "acct": KNOWN})))
    with pytest.raises(gateway_client.GatewayError) as e:
        real_gw.transaction_history(KNOWN, from_date="2026-11-04")
    assert e.value.status_code == 400 and "fromDate not allowed" in str(e.value)
    assert KNOWN not in str(e.value) and "GET /api/v1/transactions/history" in str(e.value)
