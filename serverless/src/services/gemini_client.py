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

from src.services._llm import generate_text

logger = logging.getLogger(__name__)


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

This is educational content for someone who wants to genuinely understand the topic. The
viewer is studying — but on a feed, so the first seconds must EARN the watch. Do NOT use:
- Curiosity-bait archetypes ("Ever wonder why...", "What if I told you...", "You won't believe...")
- DISRUPTION → TENSION → REVELATION → WONDER narrative arcs
- Dramatic transitions or hype language

DO use:
- **Misconception-first cold opens (the signature move).** Open by naming and refuting a
  common wrong belief, or with a precise surprising claim: "Heavier objects don't fall
  faster." / "Every diagram of an atom you've seen is wrong." / "This orbit never repeats."
  Refuting a misconception first is the one hook that IS pedagogy: stating the wrong idea
  and correcting it roughly doubles learning versus a straight exposition. One sentence,
  ≤12 spoken words, then teach.
- Motivation-before-formula: each segment opens with WHY before the equation
- Concrete before abstract: show the phenomenon, then name it
- One focused idea per segment — no cramming
- Intuitive language: "the electron cloud shifts" before "the induced dipole moment"

=== THE FIRST 2 SECONDS (distribution gate — design segment 0 around this) ===

Viewers decide to keep or swipe in the first 1-3 seconds, mostly with sound OFF. Segment 0 MUST:
- COLD-OPEN ON THE PAYOFF: at t=0 the frame already shows the topic's most dramatic,
  fully-formed visual state (the completed orbit, the resonating bead at peak amplitude,
  the assembled molecule) — never an empty axes, a slow build-up, or a title screen.
  Write this into segment 0's description explicitly: "opens already showing ...".
- Put a ≤7-word on-screen hook line in segment 0's description (e.g. "Heavier does NOT
  mean faster") displayed immediately at the top of the frame.
- The voiceover's first sentence is the misconception/claim, ≤12 words.

=== VISUAL BEAT CADENCE ===

Something meaningful must CHANGE on screen every 3-5 seconds — a reveal, a camera move,
a label appearing, a parameter sweep, a color pulse on the key term. No static shot may
exceed 5 seconds. Write the beats into each description ("at ~4s the field reverses;
at ~9s the trace begins...") so the renderer paces them.

=== LOOP-FRIENDLY ENDING ===

The final segment should end on a frame that visually rhymes with the opening frame (same
object, same composed state) so the video loops cleanly on replay, and the last narration
sentence is ≤6 words ("That's why the sky is blue."). No trailing dead air, no fade to black.

Each segment serves a clear pedagogical role:
1. **SETUP** — establish the physical situation, what are we looking at?
2. **MECHANISM** — show how it works, what moves, what drives what
3. **EQUATION** — derive or state the governing relation (use manim)
4. **IMPLICATION** — show what the equation predicts or implies
5. **RESULT** — the key takeaway, what this means in practice

Not every video needs all five — pick the ones that matter for the topic.

=== SEGMENT TYPES (3 AVAILABLE) ===

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

Do NOT use title cards or static text-only segments — a static text screen mid-video is
where viewers swipe away. When the topic shifts, the NEXT segment opens with its own short
kinetic on-screen label over a live visual (put that in its description), and the narration
carries the transition in one clause.

=== ENGINE DECISION TREE ===

Is the core content an equation, derivation, or proof? → "manim"
Does the segment need 3D geometry + overlaid equations? → "manim" (ThreeDScene)
Is it a high-quality continuous 3D surface or isosurface? → "plotly"
Is it everything else (physical motion, fields, schematics, particles)? → "matplotlib"

=== VIDEO STRUCTURE ===

Target: 60-90 seconds total. Length must be EARNED: plan the idea, then cut to the minimum
that completes it. Only exceed 90s when the topic demonstrably needs it (hard cap 120s);
never pad to reach a length. Keep the total at or above ~61s when possible.
Segment count: 3-6 visual segments.

Typical structure:
  matplotlib (cold-open on the payoff visual + misconception hook) →
  manim (governing equation) →
  matplotlib (mechanism/behavior) →
  manim (result/implication) →
  matplotlib (loop-closing physical intuition, ending frame rhymes with the opening)

Content segment durations:
- Simple concept or single equation: 10-20s
- Physical simulation with explanation: 15-30s
- Full derivation: 25-40s

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

=== VISUAL / NARRATION SYNC — THIS IS WHAT MAKES IT FEEL POLISHED ===

The renderer receives BOTH the `description` and the segment's `voiceover` text, and it
times on-screen events to the words. So the two must agree, or the video will look like the
narration is describing something other than what is on screen:
- The `description` must introduce events in the SAME ORDER the voiceover mentions them.
  ("First the ball falls, then it bounces" -> describe the fall before the bounce.)
- Never name a result in the voiceover before the description shows it; never leave the
  description still setting up after the narration has moved on.
- Put the ONE key moment ("watch what happens when...") at roughly the same point in both.
- Keep them proportional: chars_in_voiceover / 15 should ~ the natural length of the visual
  you describe. A 30s visual with a 10s voiceover leaves dead air; a 10s visual under 30s of
  narration freezes on screen. Size them to match.
- In the `description`, when a beat is pinned to a moment, say so ("at the midpoint, the
  field reverses") — the renderer uses these cues to line the animation up to the words.

=== REQUIRED JSON FORMAT ===

For each segment provide:
- order: int, sequential from 0
- type: one of "matplotlib", "manim", "plotly"
- title: short human label (for logging only)
- description: for visual segments — a DIRECTOR'S NOTE. Describe exactly what is shown:
  what objects, what motion, what camera behavior, what key moment happens at the midpoint.
  Be specific. "3D nanoparticle with oscillating electron cloud, camera sweeps azimuth
  -55° → 35° with ease, electron scatter shifts ±0.3 units along z at 2Hz visual."
  Include the timed visual beats and, for segment 0, the cold-open state + on-screen hook line.
- voiceover: object with "text" (narration), "speed" (float 0.97-1.03)
- metadata: {} (empty for now)

Respond with JSON: {"segments": [...]}

User's prompt:
"""


CAPTION_PROMPT = """You are writing the title and caption for a TikTok / Instagram Reel / YouTube Short about this topic:

{topic}

Write the way a smart human creator writes, not the way an AI writes.

HARD RULES (violating any one of these makes the post unusable):
- NO em dashes ( — ) anywhere. Use commas or periods.
- NO en dashes ( – ). Use a regular hyphen ( - ) only when joining words like "well-known".
- NO "dive into", "fascinating", "let's explore", "uncover", "unpack", "delve", "journey", "buckle up", "mind-blowing", "wild".
- NO "did you know" / "ever wondered" openers.
- NO meta references to the video itself ("in this video", "today we look at").
- NO mention of "Iris Flow", "AI", or any tool/brand name.
- NO ellipses ( ... ).
- NO emojis anywhere in the title or caption text. Hashtags only.

TITLE (used as YouTube + TikTok title):
- Under 40 characters, and the payoff keyword must appear in the FIRST 3 words (feeds
  truncate titles around 40 visible characters).
- Concrete, specific noun phrase. Name the phenomenon, person, or number.
- No clickbait fluff like "you wont believe" or "shocking".
- Examples of the right tone: "Why bees make hexagons", "Bayes rule, decoded in 60 seconds", "Lorenz attractor: order from a butterfly".

CAPTION:
- 1-2 short sentences, under 220 chars total before hashtags.
- Open with a concrete claim or surprising fact about the actual topic. Mention a number, a name, or a specific phenomenon. Be SPECIFIC.
- The second sentence (if any) is the "but here's the twist" line, the part that makes a viewer want to watch.
- Tone: a sharp graduate student texting a friend who is curious about science. Confident, no filler.
- Then a blank line, then 3-5 hashtags (more dilutes relevance). Hashtags should be specific to the topic (not just generic #science #stem). Include a couple broad ones at the end.

OUTPUT FORMAT (must parse as JSON, no markdown fences, no commentary):
{{"title": "...", "caption": "...\\n\\n#tag1 #tag2 #tag3 #tag4"}}"""


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
        f"\nUpper bound for total duration: {target_duration} seconds. "
        f"Prefer 60–90 seconds total — use the minimum that completes the idea."
    )
    full_prompt = SEGMENT_GENERATION_PROMPT + prompt + duration_hint

    model = "claude-fable-5"
    # Streaming + adaptive thinking: the model plans the timed segment breakdown
    # (and avoids the non-streaming "Streaming is required" failure on long outputs).
    response_text, _stop = generate_text(full_prompt, max_tokens=20000, use_thinking=True)

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


def _strip_em_dashes(text: str) -> str:
    """Belt-and-braces: remove em/en dashes even if the model slips."""
    return (
        text.replace("—", ", ")
            .replace("–", ", ")
            .replace("...", ".")
            .replace("…", ".")
    )


async def generate_caption(topic: str) -> dict:
    """Generate {title, caption} for the video as a dict.

    Backwards-compat shim: callers that expected a plain string can still
    use `(await generate_caption(...))['caption']`.
    """
    import json as _json
    prompt = CAPTION_PROMPT.format(topic=topic)
    model = "claude-fable-5"
    raw, _stop = generate_text(prompt, max_tokens=2048, use_thinking=False)
    raw = raw.strip()
    # Sometimes Claude wraps in markdown fences; strip them.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json\n"):
            raw = raw[5:]
        raw = raw.strip()
    try:
        data = _json.loads(raw)
        title = _strip_em_dashes(data.get("title", "").strip())
        caption = _strip_em_dashes(data.get("caption", "").strip())
    except Exception:
        # Fallback: treat entire response as caption, derive title heuristically.
        cleaned = _strip_em_dashes(raw)
        caption = cleaned
        # Take first sentence (up to 80 chars) as title.
        title = cleaned.split(".")[0].strip()[:80]
    return {"title": title, "caption": caption}
