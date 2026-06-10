"""match_duration must be a no-op when already close, and must CLAMP the retime
factor so extreme mismatches never warp the physics into slow-mo / fast-forward."""
import src.video_utils as vu


class _OK:
    returncode = 0
    stderr = ""


def _grab_setpts(monkeypatch, video_dur, target_dur):
    monkeypatch.setattr(vu, "get_duration", lambda p: video_dur)
    box = {}

    def fake_run(cmd, **kw):
        box["cmd"] = cmd
        return _OK()

    monkeypatch.setattr(vu.subprocess, "run", fake_run)
    out = vu.match_duration("/x/v.mp4", target_dur)
    box["out"] = out
    if "cmd" in box:
        cmd = box["cmd"]
        box["filter"] = cmd[cmd.index("-filter:v") + 1]
    return box


def test_noop_when_within_tolerance(monkeypatch):
    monkeypatch.setattr(vu, "get_duration", lambda p: 20.0)
    # No subprocess should run; returns the input path unchanged.
    assert vu.match_duration("/x/v.mp4", 20.02) == "/x/v.mp4"


def test_clamps_extreme_slowdown(monkeypatch):
    # video 8s vs target 26s => raw factor 0.31, clamped UP to 0.7 => pts 1/0.7 ~= 1.4286
    box = _grab_setpts(monkeypatch, 8.0, 26.0)
    assert "setpts=1.428" in box["filter"], box["filter"]


def test_clamps_extreme_speedup(monkeypatch):
    # video 30s vs target 10s => raw factor 3.0, clamped DOWN to 1.4 => pts 1/1.4 ~= 0.714
    box = _grab_setpts(monkeypatch, 30.0, 10.0)
    assert "setpts=0.714" in box["filter"], box["filter"]


def test_gentle_mismatch_not_clamped(monkeypatch):
    # video 22s vs target 20s => factor 1.1 (inside band) => pts 1/1.1 ~= 0.909
    box = _grab_setpts(monkeypatch, 22.0, 20.0)
    assert "setpts=0.909" in box["filter"], box["filter"]
