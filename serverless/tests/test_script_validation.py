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
