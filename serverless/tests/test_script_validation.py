"""validate_script must reject empty/incomplete generations BEFORE execution —
the production failure was an empty script exiting 0 with zero frames written."""
import asyncio

import pytest

from src.services._llm import validate_script
import src.services.pysim_service as pysim


def test_rejects_empty_script():
    with pytest.raises(RuntimeError, match="empty or incomplete"):
        validate_script("", "savefig", "end_turn", "matplotlib")


def test_rejects_short_commentary():
    with pytest.raises(RuntimeError, match="empty or incomplete"):
        validate_script("# I cannot write this script", "savefig", "end_turn", "matplotlib")


def test_rejects_script_missing_required_call():
    code = "import numpy as np\n" + "x = 1\n" * 200  # long but never saves frames
    with pytest.raises(RuntimeError, match="savefig"):
        validate_script(code, "savefig", "end_turn", "matplotlib")


def test_accepts_complete_script():
    code = ("import matplotlib\n" + "y = 2\n" * 100 +
            "fig.savefig(f'{OUTPUT_DIR}/frame_0000.png')\n")
    assert validate_script(code, "savefig", "end_turn", "matplotlib") == code


def test_error_message_carries_stop_reason_for_retry_prompt():
    try:
        validate_script("", "write_image", "max_tokens", "plotly")
    except RuntimeError as e:
        assert "stop_reason=max_tokens" in str(e)
        assert "write_image" in str(e)
    else:
        pytest.fail("expected RuntimeError")


def test_pysim_generate_script_raises_on_empty_response(monkeypatch):
    """End-to-end through the service: an empty model response must raise, not
    return an empty script that 'runs successfully' with no frames."""
    monkeypatch.setattr(pysim, "generate_text",
                        lambda prompt, max_tokens=32000, use_thinking=True: ("", "end_turn"))
    svc = pysim.PysimService.__new__(pysim.PysimService)
    with pytest.raises(RuntimeError, match="empty or incomplete"):
        asyncio.run(svc._generate_script("orbit", 10.0, 300, None, None))


# ---- refusal handling (prepare_retry_context) ----
from src.services._llm import prepare_retry_context, REFUSAL_MARKER


def test_retry_context_normal_error_keeps_brief_and_appends_error():
    d, n, e = prepare_retry_context("a pendulum", "NARRATION TIMELINE...", "NameError: x")
    assert d == "a pendulum"
    assert n == "NARRATION TIMELINE..."
    assert "NameError: x" in e and "PREVIOUS ATTEMPT FAILED" in e


def test_retry_context_no_error_is_passthrough():
    d, n, e = prepare_retry_context("a pendulum", "block", None)
    assert (d, n, e) == ("a pendulum", "block", "")


def test_retry_context_refusal_recasts_to_geometry_and_drops_narration():
    err = f"{REFUSAL_MARKER}: the API refused this generation request."
    d, n, e = prepare_retry_context("DNA double helix with base-pair rungs", "NARRATION...", err)
    assert "Purely geometric" in d
    assert "DNA double helix" in d            # the geometry brief is preserved
    assert n == ""                            # narration dropped to cut trigger surface
    assert e == ""                            # no refusal text echoed into the prompt


def test_pysim_refusal_retry_builds_sanitized_prompt(monkeypatch):
    captured = {}

    def fake_generate_text(prompt, max_tokens=32000, use_thinking=True):
        captured["prompt"] = prompt
        return (("# ok\n" * 60) + "fig.savefig('f.png')\n", "end_turn")

    monkeypatch.setattr(pysim, "generate_text", fake_generate_text)
    svc = pysim.PysimService.__new__(pysim.PysimService)
    err = f"{REFUSAL_MARKER}: refused"
    asyncio.run(svc._generate_script("DNA helix", 9.0, 270, err, "the rungs carry the code"))
    p = captured["prompt"]
    assert "Purely geometric" in p
    assert "NARRATION TIMELINE" not in p      # dropped on refusal retry
    assert "PREVIOUS ATTEMPT FAILED" not in p # refusal text not echoed
