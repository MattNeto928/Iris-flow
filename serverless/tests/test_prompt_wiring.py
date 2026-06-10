"""Verify each generator builds a correct prompt: exact frame count, the real
duration, the narration timeline, the description, and NO leftover {placeholders}."""
import asyncio

import src.services.pysim_service as pysim
import src.services.plotly_service as plotly
import src.services.manim_service as manim


def _capture(monkeypatch, module):
    """Patch the module's generate_text to record the prompt and return canned code."""
    box = {}

    def fake_generate_text(prompt, max_tokens=32000, use_thinking=True):
        box["prompt"] = prompt
        box["max_tokens"] = max_tokens
        return ("print('frame')", "end_turn")

    monkeypatch.setattr(module, "generate_text", fake_generate_text)
    return box


def test_pysim_prompt_has_exact_frames_duration_and_narration(monkeypatch):
    box = _capture(monkeypatch, pysim)
    svc = pysim.PysimService.__new__(pysim.PysimService)  # skip dir-creating __init__
    asyncio.run(svc._generate_script("a falling ball bouncing", 26.3, 789, None, "It falls. It bounces."))
    p = box["prompt"]
    assert "789" in p                        # exact frame count present
    assert "26.3" in p                       # the real (measured) duration
    assert "a falling ball bouncing" in p    # the description
    assert "NARRATION TIMELINE" in p         # narration was injected
    assert "It falls." in p
    assert "frame_0788.png" in p             # {last:04d} computed = frames-1
    # No template tokens leaked through:
    for tok in ("{description}", "{duration}", "{frames}", "{narration_block}", "{last:04d}"):
        assert tok not in p, f"leftover token {tok}"
    # Physics-accuracy guidance is present (the user's core complaint):
    assert "Velocity Verlet" in p
    assert "PHYSICAL ACCURACY" in p


def test_plotly_prompt_wiring(monkeypatch):
    box = _capture(monkeypatch, plotly)
    svc = plotly.PlotlyService.__new__(plotly.PlotlyService)
    asyncio.run(svc._generate_script("a rotating dispersion surface", 17.0, 510, None, "Watch the surface."))
    p = box["prompt"]
    assert "510" in p
    assert "17.0" in p
    assert "a rotating dispersion surface" in p
    assert "NARRATION TIMELINE" in p
    assert "frame_0509.png" in p
    assert "engine='kaleido'" in p           # matches the pinned kaleido 0.2.1
    for tok in ("{description}", "{duration}", "{frames}", "{narration_block}", "{last:04d}"):
        assert tok not in p


def test_manim_prompt_wiring_and_robustness(monkeypatch):
    box = _capture(monkeypatch, manim)
    svc = manim.ManimService.__new__(manim.ManimService)
    asyncio.run(svc._generate_script("derive E=mc^2", 20.0, None, "Energy equals mass times c squared."))
    p = box["prompt"]
    assert "20.0" in p
    assert "derive E=mc^2" in p
    assert "NARRATION TIMELINE" in p
    assert "Energy equals mass" in p
    # Robustness guidance fixing the two top crashes from production logs:
    assert "VGroup" in p and "Group(" in p   # VGroup-type-error fix
    assert "Timing Budget" in p              # fill-the-duration guidance
    for tok in ("{description}", "{duration}", "{narration_block}"):
        assert tok not in p


def test_no_voiceover_still_builds(monkeypatch):
    """A silent segment (no narration) must still produce a valid prompt."""
    box = _capture(monkeypatch, pysim)
    svc = pysim.PysimService.__new__(pysim.PysimService)
    asyncio.run(svc._generate_script("orbit", 10.0, 300, None, None))
    p = box["prompt"]
    assert "NARRATION TIMELINE" not in p      # nothing to sync to
    assert "{narration_block}" not in p       # token still removed
    assert "300" in p
