"""
Burned-in keyword captions for muted-autoplay viewers.

A majority of feed video is watched muted, and captions also reduce the
engagement penalty of AI narration — so every STEM segment gets short-phrase
captions burned in. Style follows the research notes in
docs/video-appeal-research.md: 3-5 word chunks (keyword-level, not verbatim
walls of text), bold white with a black outline, positioned inside the
platform-UI safe zone (clear of the bottom ~350px caption/progress area and
the right ~140px engagement rail).

Timing mirrors src/services/_llm.build_narration_timeline exactly: the
compositor delays narration by `lead_in` seconds (combine_audio_video's
narration_delay), and the measured audio `duration` is distributed across
sentences by character share; within a sentence, across word-chunks the same way.
"""

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("/app/output")
CAPTIONS_DIR = OUTPUT_DIR / "captions"

MAX_WORDS_PER_CHUNK = 4
MIN_CHUNK_SECONDS = 0.30

# 1080x1920 layout: Alignment=2 (bottom-center). MarginV=420 keeps the text
# block's bottom edge ~1500px, above the platform's bottom ~350px UI zone.
# MarginR > MarginL biases the centering box away from the right-side rail.
ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,2,90,160,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _strip_tags(text: str) -> str:
    """Remove [bracket] tone/pace tags — TTS strips them, so captions must too."""
    return re.sub(r"\[[^\[\]]{1,40}\]", "", text)


def _sentences(text: str) -> list[str]:
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in raw if s.strip()]


def _word_chunks(sentence: str) -> list[str]:
    """Split a sentence into chunks of <= MAX_WORDS_PER_CHUNK words, balanced so
    the last chunk is never a single orphan word when avoidable."""
    words = sentence.split()
    if not words:
        return []
    import math
    n_chunks = max(1, math.ceil(len(words) / MAX_WORDS_PER_CHUNK))
    base = len(words) // n_chunks
    extra = len(words) % n_chunks
    chunks, i = [], 0
    for c in range(n_chunks):
        take = base + (1 if c < extra else 0)
        chunks.append(" ".join(words[i:i + take]))
        i += take
    return chunks


def chunk_narration(
    voiceover_text: str,
    duration: float,
    lead_in: float = 0.5,
) -> list[tuple[float, float, str]]:
    """Return [(start, end, text), ...] caption chunks covering the narration."""
    if not voiceover_text or not voiceover_text.strip():
        return []
    text = re.sub(r" {2,}", " ", _strip_tags(voiceover_text)).strip()
    sentences = _sentences(text)
    if not sentences:
        return []

    total_chars = sum(len(s) for s in sentences) or 1
    speak_window = max(0.1, float(duration))

    out: list[tuple[float, float, str]] = []
    t = float(lead_in)
    for s in sentences:
        sent_dur = (len(s) / total_chars) * speak_window
        chunks = _word_chunks(s)
        chunk_chars = sum(len(c) for c in chunks) or 1
        ct = t
        for c in chunks:
            cd = max(MIN_CHUNK_SECONDS, (len(c) / chunk_chars) * sent_dur)
            out.append((ct, ct + cd, c))
            ct += cd
        t += sent_dur

    # Clamp: never let captions outlive the lead_in + narration window by much.
    limit = lead_in + speak_window + 0.25
    return [(s, min(e, limit), c) for s, e, c in out if s < limit]


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(chunks: list[tuple[float, float, str]]) -> str:
    lines = [ASS_HEADER]
    for start, end, text in chunks:
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,{_ass_escape(text)}\n"
        )
    return "".join(lines)


def burn_captions(
    video_path: str,
    voiceover_text: str,
    duration: float,
    video_id: str,
    segment_index: int,
    lead_in: float = 0.5,
) -> str:
    """Burn keyword captions into a combined (video+audio) segment.

    Gracefully degrades: on any failure the original video path is returned —
    a caption-less segment beats a failed pipeline.
    """
    chunks = chunk_narration(voiceover_text, duration, lead_in)
    if not chunks:
        return video_path

    try:
        CAPTIONS_DIR.mkdir(parents=True, exist_ok=True)
        ass_path = CAPTIONS_DIR / f"{video_id}_{segment_index:02d}.ass"
        ass_path.write_text(build_ass(chunks))

        output_path = str(Path(video_path).with_suffix(".captioned.mp4"))
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"ass={ass_path}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(f"[captions] burn failed, using uncaptioned video: {result.stderr[-400:]}")
            return video_path
        logger.info(f"[captions] burned {len(chunks)} caption chunks into seg {segment_index}")
        return output_path
    except Exception as e:
        logger.warning(f"[captions] unexpected failure, using uncaptioned video: {e}")
        return video_path
