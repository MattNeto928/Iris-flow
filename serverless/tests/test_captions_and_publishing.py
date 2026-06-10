"""Tests for burned-in captions (chunking/timing/ASS) and the YouTube volume cap."""
import re

from src.services.captions import chunk_narration, build_ass, _ass_escape, _ass_time
from src.metricool_client import MetricoolClient
from src.worker import _youtube_included


# ---------- caption chunking ----------

def test_chunks_empty_text():
    assert chunk_narration("", 10.0) == []
    assert chunk_narration(None, 10.0) == []


def test_chunks_max_four_words_and_monotonic():
    vo = "Heavier objects do not fall faster than light ones. Galileo proved this four centuries ago."
    chunks = chunk_narration(vo, 12.0, lead_in=0.5)
    assert chunks, "expected chunks"
    for start, end, text in chunks:
        assert len(text.split()) <= 4
        assert end > start
    starts = [c[0] for c in chunks]
    assert starts == sorted(starts)
    assert abs(chunks[0][0] - 0.5) < 1e-6           # first caption at the lead-in
    assert chunks[-1][1] <= 0.5 + 12.0 + 0.25 + 1e-6  # never outlives the narration window


def test_chunks_strip_bracket_tags():
    vo = "[curious] Water is bent. [slow] That bend makes it polar."
    chunks = chunk_narration(vo, 8.0)
    joined = " ".join(c[2] for c in chunks)
    assert "[" not in joined and "]" not in joined
    assert "Water is bent." in joined


def test_chunks_cover_all_words():
    vo = "Sodium and chloride alternate in a perfect repeating cube."
    chunks = chunk_narration(vo, 6.0)
    assert " ".join(c[2] for c in chunks) == vo


# ---------- ASS rendering ----------

def test_ass_time_format():
    assert _ass_time(0) == "0:00:00.00"
    assert _ass_time(65.37) == "0:01:05.37"
    assert _ass_time(3700.5) == "1:01:40.50"


def test_ass_escape_removes_override_syntax():
    assert _ass_escape(r"a{\b1}c \ d") == "a(b1)c  d".replace("b1", "b1")  # braces->parens, backslashes dropped
    assert "{" not in _ass_escape("{x}") and "\\" not in _ass_escape("a\\b")


def test_build_ass_structure_and_safe_zone_margins():
    doc = build_ass([(0.5, 1.4, "Water is bent"), (1.4, 2.2, "and that matters")])
    assert "PlayResX: 1080" in doc and "PlayResY: 1920" in doc
    assert doc.count("Dialogue:") == 2
    assert "Water is bent" in doc
    # Style line carries the safe-zone margins (Alignment=2, MarginV=420)
    style = next(l for l in doc.splitlines() if l.startswith("Style: Caption"))
    fields = style.split(",")
    assert fields[-2].strip() == "420"   # MarginV — clear of bottom platform UI
    assert fields[-5].strip() == "2"     # Alignment bottom-center


# ---------- YouTube volume cap ----------

def test_youtube_included_inside_window():
    assert _youtube_included(11, "11,12,20,21") is True
    assert _youtube_included(21, "11,12,20,21") is True


def test_youtube_excluded_outside_window():
    assert _youtube_included(0, "11,12,20,21") is False
    assert _youtube_included(16, "11,12,20,21") is False


def test_youtube_included_env_default(monkeypatch):
    monkeypatch.delenv("YOUTUBE_POSTING_HOURS", raising=False)
    assert _youtube_included(12) is True
    assert _youtube_included(3) is False


# ---------- Metricool network exclusion ----------

def _client(monkeypatch) -> MetricoolClient:
    monkeypatch.setenv("METRICOOL_API_KEY", "k")
    monkeypatch.setenv("METRICOOL_USER_ID", "u")
    monkeypatch.setenv("METRICOOL_BLOG_ID", "111")
    monkeypatch.delenv("METRICOOL_PRIMARY_NETWORKS", raising=False)
    return MetricoolClient()


def test_effective_networks_excludes_youtube(monkeypatch):
    c = _client(monkeypatch)
    nets = c._effective_networks("111", {"youtube"})
    assert "youtube" not in nets
    assert {"instagram", "tiktok", "facebook"} <= set(nets)


def test_effective_networks_no_exclusion(monkeypatch):
    c = _client(monkeypatch)
    assert c._effective_networks("111", None) == c._networks_for_blog("111")
