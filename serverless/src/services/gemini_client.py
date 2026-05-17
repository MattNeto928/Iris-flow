"""
Gemini Client - Segment generation and caption creation.

Uses Claude Opus to generate video segments from prompts and create social media captions.
Iris-local style: pedagogical, 3D-first, manim for equations, matplotlib for physics.
"""

import os
import json
import logging
from typing import List
from dataclasses import dataclass
import anthropic

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


@dataclass
class VoiceoverConfig:
    text: str
    voice: str = "Algenib"
    speed: float = 1.0


@dataclass
class Segment:
    order: int
    type: str  # "matplotlib", "manim", "plotly", "title_card"
    title: str
    description: str
    voiceover: VoiceoverConfig = None
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


SEGMENT_GENERATION_PROMPT = """You are an expert video production assistant creating pedagogical STEM educational content — short-form study videos in the style of 3Blue1Brown. Given a user's prompt, break it down into a sequence of focused, intuitive video segments.

**VIDEO FORMAT: VERTICAL (9:16 for YouTube Shorts/TikTok/Reels)**
- Resolution: 1080x1920 pixels (portrait orientation)
- Design for mobile viewing, but content depth for actual learning

=== THE PEDAGOGICAL APPROACH — THIS IS THE MOST IMPORTANT RULE ===

This is educational content for someone who wants to genuinely understand the topic. Not entertainment. The viewer is studying. Do NOT use:
- Hook archetypes ("Ever wonder why...", "What if I told you...")
- DISRUPTION → TENSION → REVELATION → WONDER narrative arcs
- Loopable endings
- Dramatic transitions

DO use:
- Motivation-before-formula: each segment opens with WHY before the equation
- Concrete before abstract: show the phenomenon, then name it
- One focused idea per segment — no cramming
- Intuitive language: "the electron cloud shifts" before "the induced dipole moment"

Each segment serves a clear pedagogical role:
1. **SETUP** — establish the physical situation, what are we looking at?
2. **MECHANISM** — show how it works, what moves, what drives what
3. **EQUATION** — derive or state the governing relation (use manim)
4. **IMPLICATION** — show what the equation predicts or implies
5. **RESULT** — the key takeaway, what this means in practice

Not every video needs all five — pick the ones that matter for the topic.

=== SEGMENT TYPES (4 AVAILABLE) ===

**1. "matplotlib" — Physics simulations and scientific visualizations**
USE FOR: Any segment involving motion, particles, waves, fields, trajectories, schematics,
cross-sections, process diagrams, orbital mechanics, electron behavior, physical geometry.

**DEFAULT TO 3D.** When the topic has any spatial geometry — surfaces, fields, volumes,
particle clouds, crystal structures, wavefunctions — use mpl_toolkits.mplot3d. 3D is the
default; 2D is the exception.

Key 3D patterns to request in description:
- "driven oscillator sweeping through resonance" — bead on spring, Verlet integration
- "electron sea sloshing in nanoparticle" — two point clouds, one oscillating
- "surface plot of dispersion relation" — rotating 3D surface with camera sweep
- "vector field in 3D" — quiver arrows showing E or B field
- "orbital trajectory" — parametric 3D curve with fading trail

**2. "manim" — Mathematical derivations and equations**
USE FOR: Any segment whose core content is an equation, derivation, formula step-through,
or symbolic manipulation. Manim renders real LaTeX via MathTex. If a segment needs BOTH
3D geometry AND overlaid equations, use manim ThreeDScene.

RULE: If the viewer needs to READ an equation to understand the segment, it must be manim.
matplotlib text rendering of math is unreadable.

**3. "plotly" — Continuous 3D surfaces and isosurfaces**
USE FOR: Only when you need Plotly's continuous surface shading quality: dispersion surfaces,
potential energy landscapes, isosurfaces of scalar fields, or surfaces that need to be
animated while a camera orbits. When matplotlib 3D would look blocky or insufficient.

**4. "title_card" — 2-3 second text card naming the next concept**
USE FOR: Brief structural markers between major topic shifts. A short voiceover sentence
("Now, the dispersion relation.") and a title. Duration: 2-3 seconds.
Do NOT use title_cards between every segment — only at major topic boundaries.

=== ENGINE DECISION TREE ===

Is the core content an equation, derivation, or proof? → "manim"
Does the segment need 3D geometry + overlaid equations? → "manim" (ThreeDScene)
Is it a high-quality continuous 3D surface or isosurface? → "plotly"
Is it everything else (physical motion, fields, schematics, particles)? → "matplotlib"
Is it a brief 2-3s label between major topic sections? → "title_card"

=== VIDEO STRUCTURE ===

Target: 60-180 seconds total. Aim for 90-120 seconds.
Segment count: 4-10 visual segments (plus 0-3 title_cards at major boundaries).

Typical structure:
  matplotlib (setup/situation) →
  manim (governing equation) →
  title_card (optional, if switching to a new sub-topic) →
  matplotlib (mechanism/behavior) →
  manim (result/implication) →
  matplotlib (final physical intuition)

Content segment durations:
- Simple concept or single equation: 15-25s
- Physical simulation with explanation: 25-40s
- Full derivation: 35-50s
Title cards: always 2-3s.

=== WRITING THE VOICEOVER ===

Voice: Gemini Algenib, deep baritone, ~15 characters per second at speed 1.0.
To estimate segment duration: chars_in_text / 15 ≈ seconds.

Style: Conversational, unhurried, intuitive. The narrator has explained this before and
still finds it interesting. Not a lecturer reading slides — a person explaining at a desk.

Opening each visual segment: one sentence that frames WHY before the WHAT.
  Good: "The key question is what happens to the electron cloud when the field oscillates."
  Bad: "We will now examine the induced dipole moment."

Motivation before labels:
  Good: "Watch how the cloud shifts back and forth — lagging behind the field. That lag is
        what we call the imaginary part of the permittivity."
  Bad: "The imaginary part of the permittivity Im(ε) represents absorption losses."

Bracket tags — USE SPARINGLY (Algenib at 1.0x already has natural pacing):
- [curious], [thoughtful], [slow] — at most 2 per whole video
- DO NOT use: [short pause], [long pause], [beat], [breath], [silence] — these produce
  literal dead air in the WAV and are stripped before synthesis. Use commas and periods
  for prosody.
- Tone tags go BEFORE the sentence, not mid-sentence.

Speed: default 1.0. Use 0.97 for equation-heavy segments, 1.02 for summary segments.

Title card voiceover: one short sentence only. "Now, the dispersion relation." or
"The Drude model explains this." Keep under 40 characters.

=== REQUIRED JSON FORMAT ===

For each segment provide:
- order: int, sequential from 0
- type: one of "matplotlib", "manim", "plotly", "title_card"
- title: short human label (for logging only)
- description: for visual segments — a DIRECTOR'S NOTE. Describe exactly what is shown:
  what objects, what motion, what camera behavior, what key moment happens at the midpoint.
  Be specific. "3D nanoparticle with oscillating electron cloud, camera sweeps azimuth
  -55° → 35° with ease, electron scatter shifts ±0.3 units along z at 2Hz visual."
  For title_cards: just the concept name being labeled.
- voiceover: object with "text" (narration), "speed" (float 0.97-1.03)
- metadata: {} (empty for now)

Respond with JSON: {"segments": [...]}

User's prompt:
"""


CAPTION_PROMPT = """Write a social media caption for a short-form STEM educational video about: {topic}

Requirements:
- 2-3 sentences max
- Conversational but substantive — treat the viewer as intelligent
- End with 3-5 relevant hashtags
- No emojis beyond the hashtags section
- Focus on the surprising or counterintuitive aspect of the topic

Return only the caption text."""


async def generate_segments_from_prompt(
    prompt: str,
    default_voice: str = "Algenib",
    default_speed: float = 1.0,
    target_duration: int = 90
) -> tuple[List[Segment], str, str]:
    """
    Use Claude to parse a user prompt into structured video segments.
    Returns (segments, llm_prompt, model_used).
    """
    duration_hint = (
        f"\nTarget total video duration: {target_duration} seconds "
        f"({target_duration // 60}–{(target_duration + 30) // 60} minutes). "
        f"Size segments accordingly."
    )
    full_prompt = SEGMENT_GENERATION_PROMPT + prompt + duration_hint

    model = "claude-opus-4-7"
    message = client.messages.create(
        model=model,
        max_tokens=8192,
        messages=[{"role": "user", "content": full_prompt}]
    )

    response_text = message.content[0].text

    # Extract JSON
    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start != -1 and end > start:
            result = json.loads(response_text[start:end])
        else:
            raise ValueError(f"Failed to parse Claude response as JSON: {response_text[:500]}")

    segments_data = result.get("segments", [])

    segments = []
    for seg_data in segments_data:
        voiceover = None
        if seg_data.get("voiceover"):
            vo_data = seg_data["voiceover"]
            if isinstance(vo_data, dict) and vo_data.get("text"):
                voiceover = VoiceoverConfig(
                    text=vo_data["text"],
                    voice=vo_data.get("voice", default_voice),
                    speed=float(vo_data.get("speed", default_speed)),
                )

        segment = Segment(
            order=seg_data.get("order", len(segments)),
            type=seg_data["type"],
            title=seg_data.get("title", f"Segment {len(segments) + 1}"),
            description=seg_data.get("description", ""),
            voiceover=voiceover,
            metadata=seg_data.get("metadata", {}),
        )
        segments.append(segment)

    return segments, full_prompt, model


async def generate_caption(topic: str) -> str:
    """Generate a social media caption for the video."""
    prompt = CAPTION_PROMPT.format(topic=topic)
    model = "claude-opus-4-7"
    message = client.messages.create(
        model=model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()
