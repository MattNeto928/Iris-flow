"""
TTS Client - Google Gemini 3.1 Flash TTS (Algenib voice).

Cross-segment consistency comes from three levers:
  1. STYLE_PREAMBLE — Google's cookbook-canonical AUDIO PROFILE / SCENE /
     DIRECTOR'S NOTES / SAMPLE CONTEXT / TRANSCRIPT format, byte-identical
     across every call. Names the narrator (IRIS) to anchor identity.
  2. temperature=0.6 — lowers prosody variance between parallel renders.
  3. Voice=Algenib — "Gravelly" deep-baritone, the lowest timbre in Gemini's
     catalogue. Closest to the "documentary narrator" register.
Inline bracket tags are passed through a whitelist; [fast]/[slow]/[short pause]
are the primary pace levers within a segment.

Post-hoc pacing: Gemini has no speed knob, so we apply `atempo` in ffmpeg.
BASE_ATEMPO=1.08 lands the default output at ~160 WPM (Muller's explanatory
rate). Per-segment `speed` multiplies on top; final atempo is clamped to
[0.85, 1.15] so we stay out of the pitch-artifact zone.

Public signature `generate_voiceover(text, voice, speed) -> (path, duration)`
is preserved so the worker's call sites do not change.
"""

import asyncio
import io
import os
import random
import re
import subprocess
import uuid
import wave
import logging
from pathlib import Path

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

AUDIO_OUTPUT_DIR = Path("/app/output/audio")

GEMINI_API_KEY = os.environ.get("GOOGLE_AI_API_KEY", "")
MODEL_ID = "gemini-3.1-flash-tts-preview"
DEFAULT_VOICE = "Algenib"  # "Gravelly" deep-baritone — lowest timbre available

# Gemini TTS returns 24 kHz mono s16le PCM.
SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2  # bytes — 16-bit
CHANNELS = 1

# Prosody variance control — lower temperature = more consistent voice across
# parallel segment renders. 0.6 is the community-reported sweet spot for TTS.
TTS_TEMPERATURE = 0.6

# Base pacing offset applied to every segment. MEASURED with Algenib voice +
# current "VERY BRISK" Pace directive: raw output spans ~145–200 WPM with
# significant call-to-call variance (prosody sampling even at temp=0.6).
# Muller's explanatory rate is ~160 WPM; Shorts favor slightly faster.
# Neutral 1.0× keeps the preamble in control; per-segment `speed` (0.96–1.12)
# provides hook/tension/reveal variation. If "too slow" bump to 1.1; if
# "too fast" drop to 0.9.
BASE_ATEMPO = 1.0

# Final atempo clamp. Single-filter atempo is cleanly pitch-preserved up to
# ~1.3 with modern ffmpeg; we cap at 1.3 to stay well clear of audible formant
# compression. Floor 0.85 — below that drags audibly.
ATEMPO_MIN = 0.85
ATEMPO_MAX = 1.3

# Per-call timeout. Preview TTS occasionally hangs on [slow]-tagged or very
# long inputs; this bounds the blast radius.
TTS_TIMEOUT_SEC = 90

# Style preamble — Google cookbook canonical format. Every TTS call gets this
# verbatim prepended. Names the character (IRIS) to anchor cross-call identity.
# Pace/Register/Accent blocks use natural-language prose (confirmed by Google
# docs to outperform keyword lists). The {transcript} token is replaced with
# the per-segment narration text before sending.
STYLE_PREAMBLE = """# AUDIO PROFILE: IRIS
## "The Science Explainer"

## THE SCENE: A quiet studio, late evening.
A baritone narrator sits at a desk in a darkened room, one warm lamp on.
They are not broadcasting — they are explaining one counter-intuitive idea
to one friend across the table. The mic is close. The energy is confident
calm. The friend already trusts them.

### DIRECTOR'S NOTES

Style:
* Warm, lived-in baritone. Conversational chest voice — never broadcast.
* One-on-one intimacy. Moderate volume, wide pitch contour: each sentence
  has ONE operative word that lifts in pitch, and the rest cascades down.
* The listener should feel the narrator has explained this a hundred times
  and still finds it genuinely cool. Understated wonder, never theatrical.
* Warmth over authority. Invite, never project.

Pace:
VERY BRISK — the tempo of a confident host on the second take, slightly
hurried, every syllable clipped short. Around 170 words per minute. Do NOT
drag. Do NOT linger on commas. Do NOT stretch vowels. Tight sentence
transitions. Sentences flow into each other with minimal breath. The only
pauses are the ones explicitly marked [short pause] or [long pause]; those
land AFTER the operative word, not between clauses for breathing room.
Use [fast] on setup clauses. Default energy: a fast-talking expert who is
excited to get to the point.

Accent:
Neutral North American English with a faint Canadian-Australian hybrid
warmth. Crisp consonants. Rounded vowels. No regional markers.

Register:
Settled into the LOWER THIRD of the voice's natural range. Gravitas
without heaviness. Zero vocal fry. Zero uptalk — every declarative
sentence ends with a downward pitch.

### SAMPLE CONTEXT
IRIS is the narrator of a short-form science explainer — the kind of
60-second counter-intuitive reveal you'd find on Veritasium or 3Blue1Brown.
Trustworthy, curious, never condescending. Treats the viewer as smart.

#### TRANSCRIPT
{transcript}
"""

# Whitelisted audio tags. Anything outside this set is dropped before sending
# so the model never reads an invented tag literally. Expanded per the Google
# cookbook's documented working set for anchor-style narration.
GEMINI_TAG_WHITELIST = {
    # Pacing (primary pace control, per Google Cloud docs)
    "fast", "slow", "very fast", "very slowly",
    # Pauses
    "short pause", "long pause", "pause", "pause short", "pause long", "beat",
    # Register / tone
    "serious", "curious", "curiosity", "thoughtful", "calm", "gentle",
    # Emotional (use sparingly — one per 30s max)
    "amazed", "awe", "wonder", "surprised", "excited", "emphatic",
    # Non-verbal
    "whisper", "whispers", "breath",
}

# Minimum valid audio duration in seconds. Under this we treat the response as
# degenerate and retry — catches the rare "model returned a near-empty PCM blob"
# failure mode documented for preview TTS models.
MIN_AUDIO_SEC = 0.2


class TTSTextResponseError(RuntimeError):
    """Model returned text parts instead of audio — distinct retry class."""


class TTSRateLimitError(RuntimeError):
    """429 / RESOURCE_EXHAUSTED — distinct backoff class."""


_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GOOGLE_AI_API_KEY environment variable not set")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _pcm_to_wav(pcm_bytes: bytes) -> bytes:
    """Wrap raw 24kHz mono s16le PCM in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm_bytes)
    return buf.getvalue()


def _validate_pcm(pcm_bytes: bytes) -> None:
    """Raise if audio is too short to be real speech."""
    min_bytes = int(SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS * MIN_AUDIO_SEC)
    if len(pcm_bytes) < min_bytes:
        raise TTSTextResponseError(
            f"Audio response under {MIN_AUDIO_SEC}s ({len(pcm_bytes)} bytes) — degenerate"
        )


def _sanitize_bracket_tags(text: str) -> str:
    """Keep whitelisted bracket tags; drop unknown ones (so they're not read literally)."""
    def keep_or_drop(match: re.Match) -> str:
        tag = match.group(1).strip().lower()
        if tag in GEMINI_TAG_WHITELIST:
            return match.group(0)
        logger.info(f"[TTS] Dropping unknown bracket tag: [{tag}]")
        return ""
    return re.sub(r"\[([^\[\]]{1,40})\]", keep_or_drop, text)


def _prepare_text(text: str) -> str:
    text = _sanitize_bracket_tags(text)
    text = re.sub(r" {2,}", " ", text).strip()
    return text


def _extract_pcm(response) -> bytes:
    """Walk the candidate parts and return the first inline_data blob, or raise."""
    try:
        candidates = response.candidates or []
        for cand in candidates:
            parts = (cand.content.parts if cand.content else None) or []
            for part in parts:
                inline = getattr(part, "inline_data", None)
                if inline and inline.data:
                    return inline.data
    except Exception as e:
        raise TTSTextResponseError(f"Malformed response: {e}")

    # No audio parts. Grab any text for the error message.
    text_preview = ""
    try:
        text_preview = (response.text or "")[:200]
    except Exception:
        pass
    # Observed: when the preview model throttles under parallel load, it
    # returns HTTP 200 with no content parts and empty text — NOT a 429.
    # Treat empty-text as a rate-limit so we get the longer backoff path.
    if not text_preview:
        raise TTSRateLimitError(
            "Model returned empty response (likely silent throttling)"
        )
    raise TTSTextResponseError(f"Model returned no audio parts. Text: {text_preview!r}")


async def _call_gemini_tts(text: str, voice: str) -> bytes:
    client = _get_client()
    # Cookbook canonical format: the preamble IS the contents, with the
    # transcript spliced into its {transcript} slot. Prepending-style drift
    # was the failure mode of the v1 implementation.
    contents = STYLE_PREAMBLE.format(transcript=text)

    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        temperature=TTS_TEMPERATURE,
        http_options=types.HttpOptions(timeout=TTS_TIMEOUT_SEC * 1000),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        ),
    )

    # SDK call is synchronous; offload so we don't block the worker event loop.
    def _sync_call():
        return client.models.generate_content(
            model=MODEL_ID,
            contents=contents,
            config=config,
        )

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(_sync_call),
            timeout=TTS_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError as e:
        raise TTSRateLimitError(
            f"Gemini TTS exceeded {TTS_TIMEOUT_SEC}s — retry with backoff"
        ) from e
    except Exception as e:
        # Classify transients as rate-limit (longer backoff):
        #   - 429 / RESOURCE_EXHAUSTED: quota
        #   - 5xx / DEADLINE_EXCEEDED / UNAVAILABLE: Google server-side hiccup
        # Anything else (4xx, malformed, auth) — re-raise immediately.
        msg = str(e).lower()
        transient_markers = (
            "429", "resource_exhausted", "rate",
            "500", "502", "503", "504",
            "deadline_exceeded", "deadline exceeded",
            "unavailable", "server error", "internal error",
        )
        if any(tok in msg for tok in transient_markers):
            raise TTSRateLimitError(str(e)) from e
        raise

    pcm = _extract_pcm(response)
    _validate_pcm(pcm)
    return pcm


async def generate_voiceover(
    text: str,
    voice: str = DEFAULT_VOICE,
    speed: float = 1.0,
    stability: float = None,       # ignored — kept for call-site compat
    similarity_boost: float = None,  # ignored — kept for call-site compat
    seed: int = None,               # ignored — kept for call-site compat
    output_filename: str = None,
) -> tuple[str, float]:
    """
    Generate voiceover audio using Gemini 3.1 Flash TTS.

    Args:
        text:            Narration text. May include whitelisted [tags].
        voice:           Prebuilt voice name (default: Algenib). Short legacy
                         voice names like "Fenrir" are treated as the default.
        speed:           Speaking rate (0.85–1.15 clamp). Applied via ffmpeg atempo.
        output_filename: Optional output filename (.wav).

    Returns:
        (audio_file_path, duration_seconds)
    """
    AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not output_filename:
        output_filename = f"voiceover_{uuid.uuid4().hex}.wav"
    output_path = AUDIO_OUTPUT_DIR / output_filename

    # Legacy voice IDs (24-char ElevenLabs-style) or aliases → default.
    resolved_voice = voice if (voice and not _looks_like_legacy_id(voice)) else DEFAULT_VOICE
    prepared = _prepare_text(text)

    logger.info(
        f"[TTS] Gemini {MODEL_ID} | voice={resolved_voice} | {len(prepared)} chars"
    )

    pcm = None
    last_err = None
    for attempt in range(5):
        try:
            pcm = await _call_gemini_tts(prepared, resolved_voice)
            break
        except TTSRateLimitError as e:
            last_err = e
            wait = min(60.0, (2 ** attempt) * 2 + random.uniform(0, 2))
            logger.warning(
                f"[TTS] 429/rate-limit (try {attempt + 1}/5) — retry in {wait:.1f}s"
            )
            await asyncio.sleep(wait)
        except TTSTextResponseError as e:
            last_err = e
            wait = min(30.0, (2 ** attempt) + random.uniform(0, 1.5))
            logger.warning(
                f"[TTS] text-instead-of-audio (try {attempt + 1}/5) — retry in {wait:.1f}s: {e}"
            )
            await asyncio.sleep(wait)

    if pcm is None:
        raise RuntimeError(f"TTS failed after 5 attempts: {last_err}")

    # Write raw WAV, then apply atempo + tail pad in a single ffmpeg pass.
    wav_bytes = _pcm_to_wav(pcm)
    raw_path = output_path.with_suffix(".raw.wav")
    raw_path.write_bytes(wav_bytes)

    # Multiply the incoming per-segment speed by the global BASE_ATEMPO, then
    # clamp to [ATEMPO_MIN, ATEMPO_MAX]. Example: segment speed=1.0 ⇒ 1.08;
    # speed=1.12 ⇒ 1.15 (clamped); speed=0.96 ⇒ 1.037. This bumps the floor
    # without losing per-segment variation.
    atempo = max(ATEMPO_MIN, min(ATEMPO_MAX, float(speed) * BASE_ATEMPO))
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(raw_path),
                "-af", f"atempo={atempo:.3f},apad=pad_dur=0.3",
                "-c:a", "pcm_s16le",
                "-ar", str(SAMPLE_RATE),
                "-ac", str(CHANNELS),
                str(output_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning(f"[TTS] ffmpeg post-process failed, using raw WAV: {result.stderr}")
            raw_path.replace(output_path)
        else:
            raw_path.unlink(missing_ok=True)
    except FileNotFoundError:
        logger.warning("[TTS] ffmpeg not found — using raw WAV without atempo/tail-pad")
        raw_path.replace(output_path)

    duration = await get_audio_duration(str(output_path))
    logger.info(f"[TTS] Done: {output_path} ({duration:.2f}s)")

    return str(output_path), duration


def _looks_like_legacy_id(voice: str) -> bool:
    """
    Heuristic: ElevenLabs voice IDs are ~20-char alphanumeric strings.
    Gemini prebuilt voices are short capitalized names (Algenib, Gacrux, …).
    Long alphanumeric IDs and legacy ElevenLabs aliases (Fenrir, Rachel, …)
    are routed to the current DEFAULT_VOICE for consistency.
    """
    if not voice:
        return True
    # Legacy ElevenLabs IDs — long alphanumeric strings
    if len(voice) > 15:
        return True
    # Legacy ElevenLabs aliases we want to replace with the current default
    if voice.lower() in {"fenrir", "rachel", "bella", "adam", "antoni"}:
        return True
    return False


async def get_audio_duration(audio_path: str) -> float:
    """Get duration of an audio file via ffprobe, with mutagen fallback."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
    except (FileNotFoundError, ValueError):
        pass

    try:
        from mutagen.wave import WAVE
        audio = WAVE(audio_path)
        return audio.info.length
    except Exception:
        pass

    try:
        from mutagen.mp3 import MP3
        audio = MP3(audio_path)
        return audio.info.length
    except Exception:
        return 10.0
