"""
Regression tests for app/lambdas/notify.py.

WHY THIS FILE EXISTS. On 2026-08-02..08-10 fifteen scheduled runs failed in
`prep`, before plan.json was written. notify's `_post_lines` then did a bare
`plan.get('post')` on a None plan and raised AttributeError, so instead of the
failure report — status, gate output, cost — the only mail sent was a bare
"notifier failed" note naming a tooling error. The pipeline outage read as a
notifier bug and went unnoticed for 20 days.

The tests below pin the two shapes that produced a None plan:
  - a run that died before writing plan.json  (prep failure)
  - a compile run whose video_id is 'unknown'

Run:  ../../../.venv-iris/bin/python -m pytest serverless/motion/tests -q
(from the repo root, or point PYTHONPATH at app/lambdas)
"""

import os
import sys
import types
from pathlib import Path

import pytest

# notify.py builds boto3 clients at import time. Give it a region and a bucket
# so import succeeds offline; every client call is monkeypatched out below.
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("MOTION_BUCKET", "iris-motion-test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "lambdas"))

import notify  # noqa: E402


@pytest.fixture
def sent(monkeypatch):
    """Capture SES sends instead of performing them. Returns the list of calls."""
    calls = []

    def _send_email(**kw):
        calls.append(kw)
        return {"MessageId": "test-message-id"}

    monkeypatch.setattr(notify.ses, "send_email", _send_email)
    return calls


@pytest.fixture
def no_s3(monkeypatch):
    """Every S3 read misses, as it does when prep died before writing anything."""

    def _get_object(**kw):
        raise RuntimeError("NoSuchKey")

    monkeypatch.setattr(notify.s3, "get_object", _get_object)
    monkeypatch.setattr(
        notify.s3, "generate_presigned_url", lambda *a, **k: "https://example/x.mp4"
    )
    # head_object is used by the video probe; make it miss too.
    monkeypatch.setattr(notify.s3, "head_object", _get_object, raising=False)


# ---------------------------------------------------------------------------
# the exact regression
# ---------------------------------------------------------------------------
def test_post_lines_tolerates_none_plan():
    """The literal 2026-08 crash: _post_lines(None) must not raise."""
    assert notify._post_lines(None) is None


def test_post_lines_tolerates_empty_and_missing_post():
    assert notify._post_lines({}) is None
    assert notify._post_lines({"post": None}) is None


def test_post_lines_still_reports_a_real_post():
    """Guard against 'fixing' the crash by returning None unconditionally."""
    lines = notify._post_lines({"post": {"status": "scheduled", "dry_run": False}})
    assert lines is not None
    assert any("scheduled" in ln for ln in lines)


def test_post_lines_explains_a_gate_block():
    lines = notify._post_lines({"post": {"status": "blocked_gates_failed"}})
    assert any("NOTHING WAS PUBLISHED" in ln for ln in lines)


# ---------------------------------------------------------------------------
# end to end: a prep failure must still produce the real report
# ---------------------------------------------------------------------------
def test_prep_failure_sends_the_real_report_not_a_notifier_error(sent, no_s3):
    """
    A run that died in prep: plan.json absent, so plan is None.

    Must send ONE mail whose subject reports FAILED — not the handler's
    'notifier failed' fallback.
    """
    out = notify.handler(
        {
            "video_id": "20260810T190032Z-a90436ab",
            "topic": "Volcanic lightning",
            "error": {"Error": "States.TaskFailed", "Cause": "prep exited 1"},
        },
        None,
    )

    assert out["sent"] is True
    assert out["status"] == "FAILED", out
    assert out["status"] != "NOTIFIER_ERROR"
    assert len(sent) == 1
    subject = sent[0]["Message"]["Subject"]["Data"]
    assert "notifier failed" not in subject
    assert "FAILED" in subject
    body = sent[0]["Message"]["Body"]["Text"]["Data"]
    assert "Volcanic lightning" in body
    assert "prep exited 1" in body


def test_compile_run_with_unknown_video_id_still_reports(sent, no_s3):
    """video_id 'unknown' pins plan to None by design (notify.py:380)."""
    out = notify.handler({"video_id": "unknown"}, None)

    assert out["sent"] is True
    assert out["status"] != "NOTIFIER_ERROR"
    assert len(sent) == 1
    assert "notifier failed" not in sent[0]["Message"]["Subject"]["Data"]


def test_gate_failure_is_reported_as_gates_failed(sent, monkeypatch):
    """
    A gate-blocked run — the Jul 31/Aug 1 shape. plan.json exists and records
    gates_passed False, and postprocess recorded that it published nothing.
    """
    plan = {
        "topic": "hummingbird hover",
        "output": {"gates_passed": False},
        "post": {"status": "blocked_gates_failed"},
    }
    monkeypatch.setattr(notify, "_s3_json", lambda key: plan)
    monkeypatch.setattr(
        notify, "_s3_text", lambda key, limit=None: "FAIL: blacks lifted: p1 luma 44.4"
    )
    monkeypatch.setattr(notify, "_video_lines", lambda vid: (["  ok"], True))

    out = notify.handler({"video_id": "20260801T130033Z-57e79ac8"}, None)

    assert out["status"] == "GATES FAILED", out
    body = sent[0]["Message"]["Body"]["Text"]["Data"]
    assert "NOTHING WAS PUBLISHED" in body
    assert "blacks lifted" in body
