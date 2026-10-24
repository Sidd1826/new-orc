"""At most one MHA callback per (acknowledgement_no, job_id): retries, races, failures."""
from __future__ import annotations

import threading

import pytest

import config
import db
import models
import processor
from conftest import UPI_RRN, GatewayError, incident, run, seed, state


@pytest.fixture
def upi_debit(gw):
    seed(incidents=[incident(merchant_id=UPI_RRN)])
    return gw


def test_failed_callback_is_retried_then_delivered_once(upi_debit):
    gw = upi_debit
    gw.errors["mha_response"] = GatewayError("MHA down", status_code=503)
    run()
    p, logs, [step] = state()
    assert step.status == "FAILURE" and p.attempt_count == 1
    assert p.processing_state != "RESOLVED" and "MHA down" in p.last_error
    assert len(logs) == 1                                # response row kept for the retry

    run()                                                # recovery
    p, logs, [step] = state()
    assert (step.status, step.attempt) == ("SUCCESS", 2)
    assert p.processing_state == "RESOLVED"
    assert gw.names().count("mha_response") == 2 and len(gw.sent) == 1
    assert len(logs) == 1 and logs[0].acknowledgement_mha is not None

    run(2)                                               # terminal: nothing more
    assert gw.names().count("mha_response") == 2


def test_reprocessing_after_delivery_never_resends(upi_debit):
    run()
    with db.session_scope() as s:                        # e.g. crash before state commit
        s.query(models.ComplaintProcessing).update(
            {"processing_state": "ENRICHED", "lease_expires_at": None})
        s.commit()
    run()
    assert len(upi_debit.sent) == 1
    assert state()[0].processing_state == "RESOLVED"


def test_crash_mid_send_is_never_resent_and_parks_for_review(upi_debit):
    upi_debit.errors["mha_response"] = RuntimeError("process died during send")
    run(config.MAX_ATTEMPTS + 1)
    p, _, [step] = state()
    assert step.status == "PENDING"                      # outcome unknown
    assert upi_debit.names().count("mha_response") == 1  # at most once
    assert p.processing_state == "NEEDS_REVIEW"


def _load(s):
    p = s.query(models.ComplaintProcessing).one()
    return p, s.query(models.ApiResponseLog).one().response_payload


@pytest.fixture
def response_ready(upi_debit, monkeypatch):
    """A finalized complaint whose callback has not been sent yet."""
    key = config.MHA_RESPONSE_KEY_B64
    monkeypatch.setattr(config, "MHA_RESPONSE_KEY_B64", "")   # dev mode: no send
    run()
    monkeypatch.setattr(config, "MHA_RESPONSE_KEY_B64", key)
    assert upi_debit.sent == [] and state()[2] == []
    return upi_debit


def test_concurrent_send_while_first_is_in_flight(response_ready):
    gw = response_ready
    in_flight, release = threading.Event(), threading.Event()

    def slow_send():
        in_flight.set()
        assert release.wait(10)
    gw.before_send = slow_send
    errors = {}

    def worker(name):
        try:
            with db.session_scope() as s:
                p, payload = _load(s)
                processor._send_mha_response(s, p, payload)
                s.commit()
        except Exception as e:                           # noqa: BLE001
            errors[name] = e

    a = threading.Thread(target=worker, args=("a",))
    a.start()
    assert in_flight.wait(10)                            # A owns the claim, is sending
    gw.before_send = None
    b = threading.Thread(target=worker, args=("b",))
    b.start()
    b.join(10)
    release.set()
    a.join(10)

    assert "a" not in errors
    assert isinstance(errors["b"], RuntimeError)         # B saw PENDING and backed off
    assert len(gw.sent) == 1
    worker("c")                                          # a later retry: already delivered
    assert "c" not in errors and len(gw.sent) == 1
    assert state()[2][0].status == "SUCCESS"


def test_simultaneous_sends_deliver_exactly_once(response_ready):
    gw = response_ready
    start = threading.Barrier(4)
    outcomes = []

    def worker():
        with db.session_scope() as s:
            p, payload = _load(s)
            s.commit()                                   # don't hold the DB while waiting
            start.wait(10)
            try:
                processor._send_mha_response(s, p, payload)
                s.commit()
                outcomes.append("ok")
            except RuntimeError:
                outcomes.append("backed off")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(gw.sent) == 1
    assert len(outcomes) == 4
    assert state()[2][0].status == "SUCCESS"
