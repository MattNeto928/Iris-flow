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
import json
import logging
import os
import re
import subprocess
import time
import urllib.request
import wave
from pathlib import Path

log = logging.getLogger("motion.tts")

# ---------------------------------------------------------------- ElevenLabs
# Primary. Chosen over Gemini on MEASURED evidence, not preference:
#   latency        3.8 s   vs 60-203 s (a 504 on the first call is routine)
#   silence pad    none    vs 43% of a real track, incl. one 8.25 s dead gap
#   duration spread 2%     vs unbounded (11 s of speech padded to 68.9 s)
#   timestamps     character-level ground truth   vs none
#
# eleven_multilingual_v2, NOT v3. v3 is newer and worse here: the live model
# list reports NO capability flags for it, it is the slowest to generate AND
# the slowest speaker, caps at 5000 chars, and the docs disable speed,
# similarity, speaker boost and request stitching on it. It is built for
# expressive dialogue, not deterministic narration.
# eleven_flash_v2_5 is faster still (0.9 s) but was DISQUALIFIED by test: it
# read "1,384,000 km" as "1084 thousand kilometerly". On a pipeline whose
# premise is defensible on-screen numbers, that is fatal.
EL_MODEL = "eleven_multilingual_v2"
EL_VOICE_ID = os.environ.get("EL_VOICE_ID", "iiidtqDt9FBdT1vfBluA")   # Bill Oxley
EL_VOICE_NAME = "Bill Oxley - Documentary Commentator"
# Settings D, chosen by listening. MEASURED against the alternatives: 3.30 w/s
# (vs 2.89 at defaults) with a +-0.81 s spread over 3 runs. The wider spread is
# harmless HERE because the beat table is derived from each run's own measured
# audio -- it would only matter on the picture-locked path, which fits audio
# into fixed slots.
EL_SETTINGS = {"stability": 0.30, "similarity_boost": 0.70, "style": 0.50,
               "speed": 1.15, "use_speaker_boost": True}
# pcm_24000 lands in the sample rate this module already uses, so the bytes go
# straight into _pcm_to_wav with no transcode.
EL_FORMAT = "pcm_24000"

# ------------------------------------------------------------ Gemini fallback
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


# Trim the silence Gemini pads around every segment, and cap the pauses inside
# it. MEASURED on a real 53.8 s narration track: 43% of it was silence, with a
# single 8.25 s dead gap three seconds in. Two things went wrong at once —
# the piece sounded full of holes, AND the beat table is derived from each
# segment's DURATION, so the picture was being timed to the padding rather than
# to the speech.
#   - both ends trimmed to nothing (leading silence also shifts every later beat)
#   - internal pauses capped at 0.30 s, which keeps natural sentence prosody and
#     removes the caesuras Algenib leaves between clauses
TRIM_DB = "-45dB"
MAX_INTERNAL_PAUSE = 0.30

# Trimming alone is NOT enough, and the sibling STEM pipeline learned this the
# expensive way (serverless/src/services/tts_client.py, commit b603f1b):
# Algenib sometimes speaks only PART of the line and pads the rest, and a
# truncated clip trims to a clean-but-incomplete clip -- which is worse than a
# noisy one, because nothing downstream can tell it is wrong. So the length is
# judged on the RAW clip, before trimming, and the whole call is re-rolled when
# it is wildly long. 14.5 chars/s is their measured rate for this voice.
CHARS_PER_SEC = 14.5
ANOMALY_SLACK, ANOMALY_PAD = 1.8, 4.0
GEN_ATTEMPTS = 4


def _trim_silence(path):
    """Trim head/tail silence and cap internal pauses. Returns new duration."""
    out = str(path) + ".trim.wav"
    chain = (
        f"silenceremove=start_periods=1:start_threshold={TRIM_DB}:start_silence=0,"
        f"areverse,"
        f"silenceremove=start_periods=1:start_threshold={TRIM_DB}:start_silence=0,"
        f"areverse,"
        f"silenceremove=stop_periods=-1:stop_threshold={TRIM_DB}"
        f":stop_silence={MAX_INTERNAL_PAUSE}"
    )
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
                        "-af", chain, out], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 4096:
        log.warning("silence trim failed for %s, keeping original: %s",
                    path, r.stderr[:200])
        return _duration(path)
    os.replace(out, path)
    return _duration(path)


def _duration(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())


def _pcm_to_wav(pcm, path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS)


def _elevenlabs(text, out_path):
    """
    One segment via ElevenLabs /with-timestamps. Returns (path, duration).

    Duration comes from the ALIGNMENT, not the file length: the last character's
    end time is exactly when speech stops, so there is no silence to detect or
    trim and no heuristic in the loop. The audio is cut to that point, which
    makes the returned duration ground truth rather than an estimate -- and the
    beat table downstream is only ever as good as this number.

    The full alignment is written alongside as <out>.align.json. Nothing reads
    it yet; it is what a future pass needs to key captions to individual WORDS
    instead of to a whole segment.
    """
    import base64
    key = os.environ["ELEVENLABS_API_KEY"]
    body = json.dumps({"text": text, "model_id": EL_MODEL,
                       "voice_settings": EL_SETTINGS}).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{EL_VOICE_ID}"
        f"/with-timestamps?output_format={EL_FORMAT}",
        data=body, headers={"xi-api-key": key, "content-type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT_S).read())

    pcm = base64.b64decode(d["audio_base64"])
    align = d.get("alignment") or {}
    ends = align.get("character_end_times_seconds") or []
    raw = _pcm_to_wav(pcm, out_path)
    if not ends:
        log.warning("no alignment returned — falling back to file length")
        return str(out_path), raw

    speech_end = float(ends[-1])
    Path(str(out_path) + ".align.json").write_text(json.dumps(align))
    # Cut to the last character. ElevenLabs does not pad, but a few hundred ms
    # of room tone at the end is still dead air in a 50 s piece.
    if raw - speech_end > 0.05:
        trimmed = str(out_path) + ".cut.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out_path),
                        "-t", f"{speech_end:.3f}", trimmed], check=True)
        os.replace(trimmed, out_path)
    return str(out_path), speech_end


def generate_voiceover(text, out_path):
    """
    Synthesise one segment. Returns (path, duration_seconds).

    ElevenLabs primary, Gemini fallback. The fallback is not decoration: this
    runs unattended 5x/day and a single-vendor outage would otherwise skip the
    slot entirely. The anomaly re-roll below guards BOTH paths, because both are
    generative and both can decide to stop early and pad.
    """
    clean_text = _clean(text)
    if os.environ.get("ELEVENLABS_API_KEY"):
        expected = max(1.0, len(clean_text) / CHARS_PER_SEC)
        ceiling = expected * ANOMALY_SLACK + ANOMALY_PAD
        for attempt in range(GEN_ATTEMPTS):
            try:
                path, dur = _elevenlabs(clean_text, out_path)
                if dur > ceiling:
                    raise RuntimeError(
                        f"{dur:.1f}s >> expected ~{expected:.1f}s "
                        f"(ceiling {ceiling:.1f}s)")
                if dur < 0.35:
                    raise RuntimeError(f"only {dur:.2f}s of speech")
                return path, dur
            except Exception as e:                          # noqa: BLE001
                log.warning("elevenlabs attempt %d/%d failed: %s",
                            attempt + 1, GEN_ATTEMPTS, str(e)[:180])
                time.sleep(2 ** attempt)
        log.error("ElevenLabs failed %d times — falling back to Gemini",
                  GEN_ATTEMPTS)
    return _gemini_voiceover(text, out_path)


def _gemini_voiceover(text, out_path):
    """Fallback. Returns (path, duration_seconds)."""
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
    clean = _clean(text)
    last = None
    for attempt in range(max(RETRIES, GEN_ATTEMPTS)):
        try:
            r = client.models.generate_content(
                model=MODEL_ID,
                contents=STYLE_PREAMBLE.format(transcript=clean),
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
            raw = _pcm_to_wav(pcm, out_path)
            expected = max(1.0, len(clean) / CHARS_PER_SEC)
            ceiling = expected * ANOMALY_SLACK + ANOMALY_PAD
            if raw > ceiling and attempt < GEN_ATTEMPTS - 1:
                # Judged on RAW, deliberately: a truncated clip trims to
                # something clean and short, and then silently desynchronises
                # the whole beat table.
                raise RuntimeError(
                    f"raw clip {raw:.1f}s >> expected ~{expected:.1f}s "
                    f"(ceiling {ceiling:.1f}s) -- partial script + dead air")
            dur = _trim_silence(out_path)
            if dur < 0.35:
                raise RuntimeError(
                    f"segment is {dur:.2f}s after trimming ({raw:.2f}s raw) "
                    f"-- the model returned padding, not speech")
            if raw - dur > 0.5:
                log.info("  trimmed %.2fs of silence (%.2f -> %.2f, expected ~%.1f)",
                         raw - dur, raw, dur, expected)
            return str(out_path), dur
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
