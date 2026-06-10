"""Unit tests for the shared LLM helpers (narration timeline + fence stripping)."""
import re

from src.services._llm import build_narration_timeline, strip_code_fences


def test_narration_empty_returns_blank():
    assert build_narration_timeline("", 10.0) == ""
    assert build_narration_timeline(None, 10.0) == ""
    assert build_narration_timeline("   ", 10.0) == ""


def test_narration_contains_header_and_words():
    vo = "The ball falls. Then it bounces. Finally it stops."
    out = build_narration_timeline(vo, 12.0, lead_in=0.5)
    assert "NARRATION TIMELINE" in out
    assert "The ball falls." in out
    assert "bounces" in out
    assert "stops" in out


def test_narration_times_are_monotonic_and_bounded():
    vo = "One sentence. Two sentence. Three sentence. Four sentence."
    dur, lead = 8.0, 0.5
    out = build_narration_timeline(vo, dur, lead_in=lead)
    starts = [float(m) for m in re.findall(r"\[\s*([\d.]+)s", out)]
    assert len(starts) == 4
    assert starts[0] >= lead - 0.01            # first word starts after the lead-in
    assert starts == sorted(starts)            # monotonically increasing
    assert starts[-1] <= lead + dur + 0.01     # nothing scheduled past the segment


def test_narration_proportional_to_length():
    # A long sentence followed by a short one: the long one gets more time.
    vo = "This is a considerably longer opening sentence with many words. Short."
    out = build_narration_timeline(vo, 10.0, lead_in=0.0)
    rows = [ln for ln in out.splitlines() if ln.strip().startswith("[")]
    def span(row):
        a, b = re.findall(r"([\d.]+)s", row)[:2]
        return float(b) - float(a)
    assert span(rows[0]) > span(rows[1])


def test_strip_python_fence():
    assert strip_code_fences("```python\nx = 1\nprint(x)\n```") == "x = 1\nprint(x)"


def test_strip_bare_fence():
    assert strip_code_fences("```\ny = 2\n```") == "y = 2"


def test_strip_no_fence():
    assert strip_code_fences("z = 3") == "z = 3"


def test_strip_text_before_fence():
    assert strip_code_fences("Here you go:\n```python\nfoo()\n```") == "foo()"
