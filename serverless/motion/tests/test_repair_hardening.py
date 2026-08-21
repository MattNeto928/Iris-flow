"""
Tests for the repair-loop hardening added after the 2026-08-20 log research.

Covers the two mechanical failure classes that cost 3 of 12 repair cycles:
  - an edit list that leaves piece.html unparseable (SyntaxError)
  - the skip-superseded path that predicts it

and the failure corpus writer, whose one hard requirement is that it can never
break a run.

Run:  ../../../.venv-iris/bin/python -m pytest serverless/motion/tests -q
"""

import os
import shutil
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))

os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("MOTION_BUCKET", "iris-motion-test")
# Must be unset for the no-op tests; set explicitly per-test where needed.
os.environ.pop("FAILURE_TABLE", None)

prep = pytest.importorskip("prep", reason="prep.py needs anthropic/boto3 present")
import failure_log  # noqa: E402


def _piece(body):
    return (
        "<html><head>\n"
        '<script type="importmap">{"imports":{}}</script>\n'
        '<script type="module">\n'
        f"{body}\n"
        "</script>\n</head><body></body></html>"
    )


# ---------------------------------------------------------------------------
# js_syntax_error — the new pre-gate
# ---------------------------------------------------------------------------
@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_valid_module_passes():
    assert prep.js_syntax_error(_piece("const a = 1;\nfunction f(){ return a; }")) is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_unbalanced_paren_is_caught():
    """The literal run1-cycle1 fault: a construct left open across two edits."""
    err = prep.js_syntax_error(_piece("foo(bar(1, 2;\n"))
    assert err is not None
    assert "SyntaxError" in err


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_error_does_not_leak_the_temp_path():
    err = prep.js_syntax_error(_piece("const = ;"))
    assert err is not None
    assert "/tmp" not in err and "/var/folders" not in err
    assert "piece.html" in err


def test_missing_module_script_is_not_a_failure():
    """Never invent a failure — probe_render is authoritative."""
    assert prep.js_syntax_error("<html><body>no script</body></html>") is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_tdz_is_NOT_caught_here():
    """
    Documents the boundary deliberately: `node --check` parses, it does not run,
    so the ReferenceError/temporal-dead-zone class passes this gate and is left
    to probe_render. If this ever starts failing, the gate got stronger and the
    comment in prep.py should be updated.
    """
    assert prep.js_syntax_error(_piece("f(starOrb);\nconst starOrb = 1;")) is None


# ---------------------------------------------------------------------------
# apply_edits — skipped_out reporting
# ---------------------------------------------------------------------------
def test_skipped_out_records_superseded_edit_indices():
    template = "AAA BBB CCC"
    edits = [
        {"find": "AAA BBB", "replace": "XXX"},   # rewrites the region...
        {"find": "BBB", "replace": "YYY"},       # ...that this one anchors on
    ]
    skipped = []
    out = prep.apply_edits(template, edits, skip_consumed=True, skipped_out=skipped)
    assert skipped == [1]
    assert out == "XXX CCC"


def test_skipped_out_empty_when_edits_are_clean():
    skipped = []
    out = prep.apply_edits("AAA BBB", [{"find": "AAA", "replace": "ZZZ"}],
                           skip_consumed=True, skipped_out=skipped)
    assert skipped == []
    assert out == "ZZZ BBB"


def test_invented_anchor_still_raises():
    """A skip must only ever downgrade the superseded case, never a bad anchor."""
    with pytest.raises(ValueError, match="invented the anchor"):
        prep.apply_edits("AAA", [{"find": "NOPE", "replace": "X"}],
                         skip_consumed=True, skipped_out=[])


def test_ambiguous_anchor_still_raises():
    with pytest.raises(ValueError, match="must be"):
        prep.apply_edits("AA AA", [{"find": "AA", "replace": "X"}],
                         skip_consumed=True, skipped_out=[])


# ---------------------------------------------------------------------------
# failure_log — must never break a run
# ---------------------------------------------------------------------------
def test_record_noops_without_a_table(monkeypatch):
    monkeypatch.setattr(failure_log, "TABLE", "")
    monkeypatch.setattr(failure_log, "_table", None)
    assert failure_log.record("EDIT_SYNTAX_ERROR", video_id="v1", cycle=0) is False


def test_record_swallows_a_broken_table(monkeypatch):
    class Boom:
        def put_item(self, **kw):
            raise RuntimeError("throughput exceeded")

    monkeypatch.setattr(failure_log, "_get_table", lambda: Boom())
    # The assertion is that this returns False rather than propagating.
    assert failure_log.record("GATE_FAILED", video_id="v1", cycle=2,
                              error="x") is False


def test_record_builds_the_expected_item(monkeypatch):
    captured = {}

    class Fake:
        def put_item(self, Item):
            captured.update(Item)

    monkeypatch.setattr(failure_log, "_get_table", lambda: Fake())
    ok = failure_log.record("EDIT_SYNTAX_ERROR", video_id="vid1", cycle=3,
                            error="SyntaxError: boom", skipped_edits=[1, 2],
                            n_edits=7, cost_usd=1.0567)
    assert ok is True
    assert captured["failure_class"] == "EDIT_SYNTAX_ERROR"
    assert captured["video_id"] == "vid1"
    assert captured["cycle"] == 3
    assert captured["skipped_edits"] == [1, 2]
    # Sort key must lead with the timestamp so a class reads back in time order.
    assert captured["occurred_at_video_cycle"].endswith("#vid1#3")
    assert captured["occurred_at_video_cycle"].startswith(captured["created_at"])
    # floats must not reach DynamoDB
    import decimal
    assert isinstance(captured["cost_usd"], decimal.Decimal)


def test_record_truncates_a_huge_error(monkeypatch):
    captured = {}

    class Fake:
        def put_item(self, Item):
            captured.update(Item)

    monkeypatch.setattr(failure_log, "_get_table", lambda: Fake())
    failure_log.record("GATE_FAILED", video_id="v", cycle=0, error="x" * 50000)
    assert len(captured["error"]) < 5000
    assert "truncated" in captured["error"]


def test_summarise_returns_empty_without_a_table(monkeypatch):
    monkeypatch.setattr(failure_log, "TABLE", "")
    monkeypatch.setattr(failure_log, "_table", None)
    assert failure_log.summarise() == {}
