"""
Boundary tests for check.py's lifted-blacks gate.

The gate was changed from "the worst frame decides" to "the fraction of affected
frames decides" after a 73-second piece was rejected for 0.23 s of bloom flash
(7 frames of 2205, 0.32%) while a genuinely empty render — a flat blue gradient
with captions and no subject — was 9.13%. See the rationale block on
--max-black-frac in check.py.

These tests synthesise frames so the boundary stays pinned once the two archived
MP4s that motivated it are gone.

Run:  ../../../.venv-iris/bin/python -m pytest serverless/motion/tests -q
"""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

CHECK_PY = Path(__file__).resolve().parents[1] / "app" / "check.py"
W, H = 1080, 1920


def _write_frames(d: Path, n: int, n_lifted: int, lifted_value: int = 44):
    """
    n frames of a plausible dark scene; the first n_lifted are washed out.

    A lit subject is required or the unrelated brightness-floor gate fires and
    the test stops measuring what it means to measure.
    """
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        base = np.full((H, W), 4, dtype=np.uint8)          # near-black background
        base[400:1400, 200:900] = 150                       # a lit subject
        if i < n_lifted:
            # Lift the floor so the 1st percentile clears the limit.
            base = np.maximum(base, lifted_value)
        Image.fromarray(base, mode="L").convert("RGB").save(d / f"f{i:04d}.png")


def _run_gate(frames: Path, *extra):
    r = subprocess.run(
        [sys.executable, str(CHECK_PY), "--frames", str(frames), "--fps", "30", *extra],
        capture_output=True, text=True,
    )
    return r.returncode, r.stdout + r.stderr


@pytest.fixture(scope="module")
def tmp_root(tmp_path_factory):
    return tmp_path_factory.mktemp("gate")


def test_transient_flash_passes(tmp_root):
    """0.4% lifted — the Aug 1 shape. Must publish."""
    d = tmp_root / "transient"
    _write_frames(d, n=250, n_lifted=1)          # 1/250 = 0.40%
    code, out = _run_gate(d)
    assert code == 0, out
    assert "blacks lifted" not in out


def test_sustained_lift_fails(tmp_root):
    """10% lifted — the Jul 31 shape. Must not publish."""
    d = tmp_root / "sustained"
    _write_frames(d, n=250, n_lifted=25)         # 25/250 = 10.00%
    code, out = _run_gate(d)
    assert code == 1, out
    assert "blacks lifted" in out
    assert "10.00%" in out
    assert "longest run 25 frames" in out


def test_fraction_boundary_is_the_configured_limit(tmp_root):
    """Just under and just over --max-black-frac 0.04 flip the verdict."""
    under = tmp_root / "under"
    _write_frames(under, n=100, n_lifted=4)      # 4.00%, not > 4.00%
    code, out = _run_gate(under, "--max-black-frac", "0.04")
    assert code == 0, out

    over = tmp_root / "over"
    _write_frames(over, n=100, n_lifted=5)       # 5.00% > 4.00%
    code, out = _run_gate(over, "--max-black-frac", "0.04")
    assert code == 1, out


def test_hard_ceiling_fails_even_one_frame(tmp_root):
    """
    A single catastrophically washed frame must still fail, so the fraction
    rule cannot swallow a broken render.
    """
    d = tmp_root / "blown"
    _write_frames(d, n=250, n_lifted=1, lifted_value=200)   # 0.40%, but p1 ~200
    code, out = _run_gate(d)
    assert code == 1, out
    assert "blacks blown" in out


def test_worst_frame_mode_still_available(tmp_root):
    """--max-black-frac 0 restores the old strict behaviour for a manual check."""
    d = tmp_root / "strict"
    _write_frames(d, n=250, n_lifted=1)
    assert _run_gate(d)[0] == 0
    code, out = _run_gate(d, "--max-black-frac", "0")
    assert code == 1, out
    assert "blacks lifted" in out
