"""
Gemini TTS, synchronous and self-contained.

Deliberately a trimmed sibling of serverless/src/services/tts_client.py rather
than an import: that module is async, is wired to the STEM worker's paths, and
carries Metricool-era pacing logic this pipeline does not want. The parts that
matter are copied verbatim and marked — the voice, the style preamble format,
and the pause-tag strip, because those three are what keep the narrator sounding
like the same person across parallel segment renders.
"""

import io
import logging
import os
import re
import subprocess
import time
import wave
from pathlib import Path

log = logging.getLogger("motion.tts")

MODEL_ID = "gemini-3.1-flash-tts-preview"
VOICE = "Algenib"          # "Gravelly" deep baritone — the documentary register
TEMPERATURE = 0.6          # lower = less prosody drift between parallel calls
SAMPLE_RATE, SAMPLE_WIDTH, CHANNELS = 24000, 2, 1
TIMEOUT_S = 180
RETRIES = 4

# Byte-identical across every call so the narrator identity is anchored. Copied
# from tts_client.py — do not paraphrase it, the format is load-bearing.
STYLE_PREAMBLE = """AUDIO PROFILE: A single narrator, IRIS.
SCENE: A quiet studio. One voice, close-mic'd, unhurried.
DIRECTOR'S NOTES: Deep, warm, gravelly. BRISK explanatory pace — keep it moving,
no dwelling between sentences. Confident, never breathless. Land the final word.
TRANSCRIPT:
{transcript}"""

# Gemini TTS has no speed control, so pacing is post-hoc ffmpeg atempo, the same
# lever serverless/src/services/tts_client.py pulls. MEASURED here: with the
# preamble above, Algenib reads at ~1.25 words/s raw (75 WPM) — far slower than
# the ~2.2 w/s of documentary narration, and slow enough that a 60 s picture
# only fits ~75 words. Outside [0.85, 1.15] atempo lands in the pitch-artifact
# zone, so this is a nudge, not a rescue: if a segment needs more than 1.15 to
# fit its slot, the script is too long and has to lose words.
ATEMPO_MIN, ATEMPO_MAX = 0.85, 1.15


def retime(src, dest, factor):
    """Apply an atempo factor, clamped. Returns (path, new_duration)."""
    f = max(ATEMPO_MIN, min(ATEMPO_MAX, factor))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                    "-filter:a", f"atempo={f:.4f}", str(dest)], check=True)
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", str(dest)],
                         capture_output=True, text=True, check=True)
    return str(dest), float(out.stdout.strip()), f

# Pause-class tags produce literal dead air in Algenib's output. Use punctuation.
_PAUSE_TAGS = re.compile(
    r"\[(short pause|long pause|beat|breath|silence|pause)\]", re.I)


def _clean(text):
    return _PAUSE_TAGS.sub("", text).strip()


def _pcm_to_wav(pcm, path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS)


def generate_voiceover(text, out_path):
    """Synthesise one segment. Returns (path, duration_seconds)."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GOOGLE_AI_API_KEY"])
    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        temperature=TEMPERATURE,
        http_options=types.HttpOptions(timeout=TIMEOUT_S * 1000),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE))),
    )
    last = None
    for attempt in range(RETRIES):
        try:
            r = client.models.generate_content(
                model=MODEL_ID,
                contents=STYLE_PREAMBLE.format(transcript=_clean(text)),
                config=cfg)
            pcm = None
            for cand in (r.candidates or []):
                for part in (cand.content.parts or []):
                    if getattr(part, "inline_data", None) and part.inline_data.data:
                        pcm = part.inline_data.data
                        break
            if not pcm:
                raise RuntimeError("no audio part in response (silent throttle?)")
            if len(pcm) < SAMPLE_RATE * SAMPLE_WIDTH * 0.2:
                raise RuntimeError(f"suspiciously short audio: {len(pcm)} bytes")
            return str(out_path), _pcm_to_wav(pcm, out_path)
        except Exception as e:                              # noqa: BLE001
            last = e
            # 429/5xx are the common transients; back off rather than fail the job.
            wait = 2 ** attempt * 3
            log.warning("tts attempt %d failed (%s) — retrying in %ds",
                        attempt + 1, str(e)[:160], wait)
            time.sleep(wait)
    raise RuntimeError(f"TTS failed after {RETRIES} attempts: {last}")


def mix_track_to_slots(paths, starts, total_s, dest):
    """
    Place each segment at an absolute time on one silent bed of `total_s`.

    This is the PICTURE-LOCKED direction: the scene's pose() is keyed to fixed
    frame numbers, so the beats cannot move and the audio has to land on them.
    `adelay` positions each segment and `amix` sums them over an anullsrc bed;
    a segment that overruns its slot simply overlaps the next, which sounds far
    better than time-stretching it. `dropout_transition=0` and `normalize=0`
    stop amix from ducking the level every time a segment starts or ends —
    without them the narration audibly pumps.
    """
    inputs, filt, chain = [], [], ""
    filt.append(f"anullsrc=r={SAMPLE_RATE}:cl=mono,atrim=0:{total_s}[bed]")
    chain += "[bed]"
    for i, p in enumerate(paths):
        inputs += ["-i", str(p)]
    for i, st in enumerate(starts):
        filt.append(f"[{i}:a]aresample={SAMPLE_RATE},"
                    f"aformat=sample_fmts=s16:channel_layouts=mono,"
                    f"adelay={int(round(st * 1000))}[d{i}]")
        chain += f"[d{i}]"
    n = chain.count("[")
    graph = ";".join(filt) + (f";{chain}amix=inputs={n}:duration=first"
                              f":dropout_transition=0:normalize=0[out]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
                    "-filter_complex", graph, "-map", "[out]", str(dest)],
                   check=True)
    return str(dest)


def mix_track(paths, dest, lead=0.4, gap=0.25):
    """
    Concatenate the segments with silence padding, matching exactly the offsets
    narrate.beats_from_durations assumes: `lead` before the first word, `gap`
    between segments. If these two ever disagree the picture drifts off the
    voice, so they are passed the same values from one call site.
    """
    inputs, filt, chain = [], [], ""
    for p in paths:
        inputs += ["-i", str(p)]
    if lead > 0:
        filt.append(f"aevalsrc=0:d={lead}:s={SAMPLE_RATE}:c=mono[lead]")
        chain += "[lead]"
    for i in range(len(paths)):
        filt.append(f"[{i}:a]aresample={SAMPLE_RATE},"
                    f"aformat=sample_fmts=s16:channel_layouts=mono[a{i}]")
        chain += f"[a{i}]"
        if gap > 0 and i < len(paths) - 1:
            filt.append(f"aevalsrc=0:d={gap}:s={SAMPLE_RATE}:c=mono[g{i}]")
            chain += f"[g{i}]"
    n = chain.count("[")
    graph = ";".join(filt) + f";{chain}concat=n={n}:v=0:a=1[out]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
                    "-filter_complex", graph, "-map", "[out]", str(dest)],
                   check=True)
    return str(dest)
