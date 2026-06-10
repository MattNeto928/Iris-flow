"""
Story Client — origin-story script generation for the image-sequence pipeline.

Uses Claude Opus to turn a single "how X came to be" topic into a sequence of
narrated BEATS. Each beat is 1-2 sentences of voiceover plus a director's-note
image prompt. A single global STYLE ANCHOR is returned alongside the beats and
is prepended to every image prompt so the whole video reads as one consistent
illustrated world (same characters, palette, line weight, framing).

This is the storytelling counterpart to gemini_client.generate_segments_from_prompt:
same return-shape philosophy (list of beats + the prompt + model), but the output
targets a flat clip-art image sequence rather than manim/matplotlib segments.
"""

import os
import json
import logging
from typing import List
from dataclasses import dataclass

from src.services._llm import generate_text

logger = logging.getLogger(__name__)

MODEL = "claude-fable-5"


@dataclass
class VoiceoverConfig:
    text: str
    voice: str = "Algenib"
    speed: float = 1.0


@dataclass
class StoryBeat:
    order: int
    image_prompt: str          # director's note for one illustration (without style anchor)
    title: str                 # short human label (logging only)
    voiceover: VoiceoverConfig
    speed: float = 1.0


# The style anchor is generated PER VIDEO by Claude (so each story gets its own
# world) but every image prompt in that video is prefixed with it verbatim. This
# is the single biggest lever for cross-frame continuity, on top of feeding the
# previous rendered image back as a reference (see image_service.py).
STYLE_ANCHOR_RULES = """A reusable STYLE ANCHOR is a single paragraph that locks the visual identity of
the whole video. It MUST specify, concretely:
- Medium: "minimalist flat clip-art cartoon illustration, thin clean outlines,
  hand-drawn simplicity" (this is the channel's signature — do not deviate from
  the minimalist flat clip-art look).
- Background: clean off-white / white background, lots of negative space.
- Palette: a SMALL fixed palette named explicitly — electric blue (#4FC3F7),
  warm gold (#FFD54F), coral (#FF7043), charcoal line work on near-white.
- Characters: describe the recurring character(s) as simple, consistent shapes
  (e.g. "a round-headed stick-figure scientist in a blue shirt", "simple
  round-bodied creatures"). Name them so they recur identically.
- Strictly NO text, NO words, NO letters, NO numbers anywhere in the images.
- Mood: friendly, curious, clean, calm."""


STORY_GENERATION_PROMPT = """You are the writer + art director for a short-form vertical video channel that
tells ORIGIN STORIES — "how X came to be." Scientific discoveries, inventions,
the dark/forgotten origins of everyday things, ideas that were called impossible.
The format is a narrated sequence of minimalist clip-art illustrations: ONE
illustration per beat (a beat is 1-2 sentences of narration), shown full-screen
9:16 for mobile.

The single most important metric is COMPLETION RATE (how many viewers watch to
the end). Everything below serves that.

=== STORY STRUCTURE (three acts, ~60-90 seconds total) ===

ACT I — HOOK + OPEN LOOP (first beat, 0-8s):
- Open on the most JARRING CONTRAST or surprise. Never start with chronology
  ("In 1817..." is banned). Lead with the reveal-tease, then withhold the payoff.
- The first sentence must be under ~14 spoken words.
- Hook patterns that work for this genre:
  * "The [wholesome everyday thing] you use every day began as [grim/strange thing]."
  * "This was a complete accident, and now billions of people rely on it."
  * "Everyone told him it was impossible. He failed thousands of times."
  * "A movie star invented the technology in your phone."
  * "[Familiar thing] exists because of one tiny mistake."

ACT II — BUILD / COMPLICATION (middle beats, ~8-60s):
- Tell the actual story: the setup, the accident, the obstacle, the failure, the
  rivalry, the near-miss. Escalate the stakes beat by beat. Do NOT info-dump.
- Surface ONE concrete credibility anchor: a real number, name, or date
  ("5,127 prototypes", "1928", "Alexander Fleming"). Weave it into the narration.
- Each beat advances the story by one clear step — one new image per beat.

ACT III — PAYOFF + ZOOM-OUT (last 1-2 beats, ~60-90s):
- Deliver the resolution/reveal the hook promised.
- End with a one-line "zoom out" that reframes the viewer's everyday world
  ("...and that's why every gym has one"). Optionally a final line that makes the
  opening hit differently on a re-watch (loop close). Do NOT end with a generic
  call-to-action or "thanks for watching".

=== THE STYLE ANCHOR (continuity) ===

{style_anchor_rules}

You will return ONE style_anchor string for the whole video. Then every beat's
image_prompt describes only WHAT HAPPENS in that frame, in the same world the
style anchor establishes. Keep characters/objects consistent across beats — refer
to them the same way every time ("the round-headed scientist", "the gold beaker").

=== WRITING THE IMAGE PROMPTS ===

For each beat, image_prompt is a director's note for a SINGLE still illustration:
- Describe the subject, their action/pose, the simple props, and the composition.
- One clear focal action per frame. Leave negative space.
- Reinforce continuity: name the recurring characters/objects exactly as before.
- NEVER request text, captions, labels, speech bubbles, or numbers in the image.
- Example: "The round-headed scientist in the blue shirt leans over a wooden
  workbench, surprised, as a single petri dish glows faintly gold; simple round
  creatures peek from the edge of the frame."

=== WRITING THE VOICEOVER ===

Voice: a warm deep baritone narrator (~14-15 characters/second at speed 1.0). To
estimate a beat's duration: characters_in_text / 14.5 ≈ seconds.

Style: a sharp, curious friend telling you something genuinely surprising. Confident,
concrete, no filler, no "did you know", no "let's dive in", no meta references to
"this video". Short punchy sentences. Specific nouns and numbers over vague claims.

Pacing tags — use SPARINGLY (the narrator already has natural pacing):
- Allowed, at most ~2 per whole video: [curious], [thoughtful], [slow] for the
  key reveal; [fast] on a setup clause.
- NEVER use [pause], [short pause], [long pause], [beat], [breath], [silence] —
  they produce literal dead air and are stripped. Use commas and periods instead.
- speed: default 1.0; use 0.97 for the big reveal beat, 1.03 for brisk setup.

=== LENGTH BUDGET (hard target) ===

Total narration across ALL beats must land between 60 and 90 seconds — aim for ~72s.
That is roughly 150-200 spoken words total. Produce 8 to 13 beats. Each beat is
1-2 sentences. Do the arithmetic: sum of (characters / 14.5) across beats should be
~62-88 seconds. Keep it tight; over-long videos lose completion.

=== REQUIRED JSON OUTPUT ===

Return ONLY a JSON object, no markdown fences, no commentary:
{{
  "title": "short human title for the story (logging only)",
  "style_anchor": "the one-paragraph style anchor described above",
  "beats": [
    {{
      "order": 0,
      "title": "short label",
      "image_prompt": "director's note for this single illustration (no style anchor, no text-in-image)",
      "voiceover": {{ "text": "1-2 sentences of narration", "speed": 1.0 }}
    }}
  ]
}}

The topic to tell (it may include an angle tag like [ACC]/[DARK]/[IMP]/[HIDDEN]/[WHY]/[NEAR]/[RIVAL]/[FORBID] — use it to pick the hook template):
"""


async def generate_story(
    prompt: str,
    default_voice: str = "Algenib",
    target_duration: int = 75,
) -> tuple[str, List[StoryBeat], str]:
    """
    Use Claude to turn an origin-story topic into (style_anchor, beats, model).

    Returns:
        style_anchor: paragraph prepended to every image prompt for continuity.
        beats: ordered list of StoryBeat (voiceover + image prompt per illustration).
        model: model id used.
    """
    duration_hint = (
        f"\n\nTarget total spoken duration: ~{target_duration} seconds "
        f"(must stay within 60-90s). Size the number of beats accordingly."
    )
    full_prompt = (
        STORY_GENERATION_PROMPT.format(style_anchor_rules=STYLE_ANCHOR_RULES)
        + prompt
        + duration_hint
    )

    # Streaming + adaptive thinking (avoids the non-streaming "Streaming is required"
    # failure and lets the model plan the three-act structure before writing).
    response_text, _stop = generate_text(full_prompt, max_tokens=20000, use_thinking=True)

    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start != -1 and end > start:
            result = json.loads(response_text[start:end])
        else:
            raise ValueError(
                f"Failed to parse story JSON from Claude: {response_text[:500]}"
            )

    style_anchor = (result.get("style_anchor") or "").strip()
    if not style_anchor:
        # Defensive default — keep the channel look even if Claude omits it.
        style_anchor = (
            "Minimalist flat clip-art cartoon illustration, thin clean outlines, "
            "clean off-white background with lots of negative space. Small fixed "
            "palette: electric blue (#4FC3F7), warm gold (#FFD54F), coral (#FF7043), "
            "charcoal line work. Friendly simple round-bodied characters. No text, "
            "no words, no numbers anywhere."
        )

    beats: List[StoryBeat] = []
    for i, b in enumerate(result.get("beats", [])):
        vo = b.get("voiceover") or {}
        text = vo.get("text") if isinstance(vo, dict) else None
        if not text:
            # Skip beats with no narration — every frame needs a voiceover.
            logger.warning(f"Story beat {i} has no voiceover text; skipping")
            continue
        speed = float(vo.get("speed", 1.0)) if isinstance(vo, dict) else 1.0
        beats.append(
            StoryBeat(
                order=b.get("order", len(beats)),
                image_prompt=b.get("image_prompt", "").strip(),
                title=b.get("title", f"Beat {len(beats) + 1}"),
                voiceover=VoiceoverConfig(text=text, voice=default_voice, speed=speed),
                speed=speed,
            )
        )

    if not beats:
        raise ValueError("Story generation produced no usable beats")

    logger.info(f"Story '{result.get('title','?')}' → {len(beats)} beats")
    return style_anchor, beats, MODEL
