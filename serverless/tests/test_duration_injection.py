"""The smoking-gun fix: the sim runner MUST inject the real segment duration into
the subprocess env as DURATION, so generated scripts render the correct frame count
instead of defaulting to 8 seconds and getting time-stretched."""
import asyncio

import src.services.pysim_service as pysim
import src.services.plotly_service as plotly


class _FakeProc:
    returncode = 0

    async def communicate(self):
        return (b"", b"")


def _patch_exec(monkeypatch, module):
    box = {}

    async def fake_exec(*args, **kwargs):
        box["args"] = args
        box["env"] = kwargs.get("env")
        return _FakeProc()

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", fake_exec)
    return box


def test_pysim_injects_real_duration(monkeypatch, tmp_path):
    box = _patch_exec(monkeypatch, pysim)
    svc = pysim.PysimService.__new__(pysim.PysimService)
    asyncio.run(svc._run_simulation("print('x')", str(tmp_path), 23.4))
    assert box["env"]["DURATION"] == "23.4"
    assert box["env"]["OUTPUT_DIR"] == str(tmp_path)


def test_plotly_injects_real_duration(monkeypatch, tmp_path):
    box = _patch_exec(monkeypatch, plotly)
    svc = plotly.PlotlyService.__new__(plotly.PlotlyService)
    asyncio.run(svc._run_visualization("print('x')", str(tmp_path), 11.9))
    assert box["env"]["DURATION"] == "11.9"
    assert box["env"]["OUTPUT_DIR"] == str(tmp_path)


def test_duration_not_left_at_default_8(monkeypatch, tmp_path):
    """Regression guard: even if DURATION=8 is already in the ambient env, the
    runner must overwrite it with the real value."""
    monkeypatch.setenv("DURATION", "8")
    box = _patch_exec(monkeypatch, pysim)
    svc = pysim.PysimService.__new__(pysim.PysimService)
    asyncio.run(svc._run_simulation("print('x')", str(tmp_path), 19.0))
    assert box["env"]["DURATION"] == "19.0"
