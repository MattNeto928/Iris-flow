"""
Shared Anthropic call helper for every code/script-generation service.

Why this exists: a non-streaming `client.messages.create(..., max_tokens=16384)`
on `claude-fable-5` raises

    ValueError: Streaming is required for operations that may take longer than
    10 minutes

because the SDK refuses long non-streaming requests (idle connections drop).
This was the single largest source of visual-segment failures in production
(~63% of failed visual jobs). Routing every generator through the STREAMING API
fixes that class of failure outright.

Streaming also lets us:
  * raise `max_tokens` well past the ~16K non-streaming ceiling (Fable 5 streams
    up to 128K), so long Manim/matplotlib scripts no longer truncate, and
  * enable ADAPTIVE THINKING — the model reasons about physics correctness,
    timing, and on-screen layout before it writes a single line of code.

Fable 5 request-surface rules (enforced here):
  * adaptive thinking only — `{"type": "adaptive"}`. Never send `budget_tokens`
    or an explicit `{"type": "disabled"}` block (both 400).
  * never send `temperature` / `top_p` / `top_k` (all 400).
"""

import os
import logging

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-fable-5"

# One module-level client shared by every importer (thread-safe, connection-pooled).
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def generate_text(
    prompt: str,
    *,
    max_tokens: int = 32000,
    use_thinking: bool = True,
) -> tuple[str, str]:
    """Run a single-prompt Claude call over the STREAMING API.

    Returns ``(text, stop_reason)``. Only text blocks are concatenated; adaptive
    thinking blocks (if any) are ignored. Callers should treat
    ``stop_reason == "max_tokens"`` as a truncation and retry / raise.
    """
    kwargs = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if use_thinking:
        kwargs["thinking"] = {"type": "adaptive"}

    with client.messages.stream(**kwargs) as stream:
        message = stream.get_final_message()

    text = "".join(
        b.text for b in message.content if getattr(b, "type", None) == "text"
    ).strip()
    return text, message.stop_reason


def strip_code_fences(text: str) -> str:
    """Return the body of a single ```python ...``` (or bare ```) fence, if present."""
    if "```python" in text:
        start = text.find("```python") + len("```python")
        end = text.find("```", start)
        if end != -1:
            return text[start:end].strip()
    if "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end != -1:
            return text[start:end].strip()
    return text.strip()


def build_narration_timeline(voiceover_text: str, duration: float, lead_in: float = 0.5) -> str:
    """Build a per-sentence NARRATION TIMELINE block for a visual-generation prompt.

    The visual generators otherwise never see the words being spoken, so on-screen
    events drift out of sync with the voiceover. We split the narration into
    sentences and assign each an approximate [start, end] window, distributing the
    real measured `duration` in proportion to character count and offsetting by the
    `lead_in` of silence the compositor adds before the first word.

    Returns an empty string when there is no narration (e.g. silent segments).
    """
    if not voiceover_text or not voiceover_text.strip():
        return ""

    import re

    # Split into sentence-ish chunks; keep terminator so timing reflects pauses.
    raw = re.split(r"(?<=[.!?])\s+", voiceover_text.strip())
    sentences = [s.strip() for s in raw if s.strip()]
    if not sentences:
        return ""

    total_chars = sum(len(s) for s in sentences) or 1
    speak_window = max(0.1, duration)  # seconds available for the words themselves

    lines = []
    t = float(lead_in)
    for s in sentences:
        share = len(s) / total_chars
        dt = share * speak_window
        lines.append(f"  [{t:5.1f}s - {t + dt:5.1f}s] {s}")
        t += dt

    return (
        "\n## NARRATION TIMELINE (the visual MUST stay in sync with these words)\n"
        f"The voiceover starts at ~{lead_in:.1f}s (a short lead-in of silence) and is spoken\n"
        "over this segment. Time each on-screen event so that whatever the narrator is\n"
        "describing is visible on screen during the window shown. Do not show a result\n"
        "before it is named, and do not still be setting up after it has been explained.\n"
        + "\n".join(lines)
        + "\n"
    )
