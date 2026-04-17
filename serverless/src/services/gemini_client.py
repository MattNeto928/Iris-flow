"""
Gemini Client - Segment generation and caption creation.

Uses Claude Opus 4.6 to generate video segments from prompts and create social media captions.
Ported from local main_service/app/gemini_client.py.
"""

import os
import json
import logging
from typing import List
from dataclasses import dataclass
import anthropic

logger = logging.getLogger(__name__)

# Initialize client
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


@dataclass
class VoiceoverConfig:
    text: str
    voice: str = "Algenib"
    speed: float = 1.0


@dataclass
class Segment:
    order: int
    type: str  # "pysim", "animation", "manim", "transition"
    title: str
    description: str
    voiceover: VoiceoverConfig = None
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


SEGMENT_GENERATION_PROMPT = """You are an expert video production assistant creating "Scientific Nipsey" style educational STEM content. Given a user's prompt, break it down into a sequence of compelling video segments using the most appropriate visualization type for each concept.

**SCIENTIFIC NIPSEY STYLE GUIDE:**
Your videos should feel like a Scientific Nipsey production - intellectually captivating, conversational yet authoritative, and structured to hook viewers from the first second.

**VIDEO FORMAT: VERTICAL (9:16 for YouTube Shorts/TikTok/Reels)**
- Resolution: 1080x1920 pixels (portrait orientation)
- Keep all visual elements centered and compact
- Design for mobile viewing

=== STORYTELLING FIRST — THIS IS THE MOST IMPORTANT RULE ===

You are not generating a list of visualizations. You are writing a SHORT FILM.

Every segment is a **beat in a single emotional arc**. The viewer should feel carried forward — curious, surprised, then satisfied — as if they're on a journey with an expert guide. The visuals are not decoration; they are the argument. Each visual segment must ADVANCE the story, not just illustrate a fact.

**THE NARRATIVE ARC (required for every video):**
1. **DISRUPTION** — Open with something that breaks the viewer's assumptions. A paradox, a counterintuitive result, a visual that shouldn't work but does. Make them lean in.
2. **TENSION** — Build the mystery. Show why this is hard, strange, or important. The visuals during this phase should feel unresolved — something is still moving, changing, unfinished.
3. **REVELATION** — The payoff. The moment the pattern snaps into focus. The visual here should feel like a unlock — something crystallizes, aligns, or resolves.
4. **WONDER** — End with an open question or a broader implication. Leave the viewer with a feeling, not just a fact.

**VISUAL STORYTELLING — HOW SEGMENTS MUST BEHAVE:**
- Every visual segment must have ONE clear narrative purpose: is it disrupting, building tension, revealing, or landing wonder?
- The description you write for each segment is a DIRECTOR'S NOTE — describe not just what is shown but what emotional beat it serves and how the animation moves through that beat.
- Animations should feel like they breathe with the voiceover — elements appearing as they're named, transforming as they're explained, resolving as the narration lands.
- Smooth animations (remotion) should feel like the camera is slowly pulling back or pushing in as understanding grows — never static, never arbitrary.
- Scientific simulations (pysim/manim/mesa) should be timed so the KEY MOMENT — the thing the voiceover is pointing at — happens in the middle third of the clip, not at the start.

=== WRITING THE VOICEOVER — READ THIS CAREFULLY ===

The voiceover is the soul of the video. If it sounds like AI slop, the whole thing fails. Write like a human being who is genuinely surprised by what they're about to tell you. Not a lecturer. Not a narrator. A person talking.

**THE DISCOVERY VOICE**
Write as if you're realizing things in real time — not explaining things you already know. The best science narration doesn't present facts, it re-enacts the moment of understanding. The viewer should feel like they're in the room when someone figured something out.

Bad: "Your brain weighs visual input more heavily than auditory input."
Good: "Watch what happens when you change just the visuals. [pause] The sound you hear — changes. Even though the audio is identical."

Bad: "This demonstrates Bayesian integration at the neural level."
Good: "Your brain is doing math. [pause short] Right now. Without asking you."

**CONCRETE BEFORE ABSTRACT (3B1B rule)**
Never name a concept before the viewer has already felt what it IS. Show the thing first. Then — only after the viewer has a gut sense of it — give it a label. The word "entropy" comes AFTER the listener has watched disorder emerge. "Natural selection" comes AFTER they've seen which traits survive. "Fourier transform" comes AFTER they've seen a sound split into frequencies. Names are rewards, not introductions.

Bad: "The Fourier transform decomposes a signal into frequency components."
Good: "Any sound — any sound at all — can be broken down into pure tones. Add them back together and you get the original. That decomposition has a name."

**MISCONCEPTION PLANT (Veritasium technique)**
For hook and tension segments: name the viewer's existing belief before you dismantle it. Make them commit to the wrong answer silently in their head — then knock it down. This is the most memorable beat in science communication because being wrong and then corrected feels like a revelation.

"You probably think—" then don't finish. Let the visual answer it.
"Most people would say—" then show the visual that contradicts them.
"The obvious answer is yes. ... The obvious answer is wrong."

**SENTENCE RHYTHM — THE MOST IMPORTANT RULE**
Vary your sentence lengths aggressively. Short sentences hit hard. Long ones build momentum and carry the listener forward through ideas that need a bit of runway to land properly. Then cut to short again.

**Target 7–12 words per sentence as the median.** Hit one-word sentences every few segments. Keep the longest under 20 words or it reads as essay prose.

**Prefer Anglo-Saxon verbs over Latinate ones** — they're shorter, punchier, more oral.
  → fall (not descend), spin (not rotate), break (not fracture), show (not demonstrate), use (not utilize), bend (not articulate), crack (not fissure), snap (not disarticulate), push (not propel), hit (not impact)
Latinate words are fine when there's no concrete equivalent — but never reach for jargon before earning it with a demonstration.

Don't write in consistent rhythm. Real speech has lurches, stops, restarts.

- Use a ONE-WORD sentence occasionally. "Nothing."
- Let a sentence trail with a dash — then pick it up.
- Start a sentence with "And." or "But." It's not wrong. It's how people talk.
- Ask a question. Then don't answer it immediately. [short pause] Make them wait.
- For stakes/scope, use tricolon escalation — three parallel clauses, each bigger: "It governs a single heartbeat. A hurricane. The direction of time itself."

**USE GEMINI AUDIO TAGS — THE VOICE INTERPRETS THEM**

The production pipeline uses Google Gemini 3.1 Flash TTS with the **Algenib** voice — a "gravelly" deep-baritone, the lowest timbre in Gemini's catalogue (documentary-narrator register, settled low, explanatory pace ~160 WPM). The TTS client injects a cookbook-format Director's Notes preamble before your text, so the model already knows the overall tone. Your job in the voiceover text is to direct WITHIN THE LINE — pacing and emphasis at the sentence level — using the whitelisted tags below.

**Whitelist (use only these):**
  - Pacing (primary): `[fast]` `[slow]` — apply `[fast]` on setup clauses, `[slow]` on the reveal
  - Pauses: `[short pause]` `[long pause]` `[beat]`
  - Tone: `[curious]` `[serious]` `[thoughtful]` `[calm]` `[gentle]`
  - Emotional (use sparingly — one per 30s of audio MAX): `[amazed]` `[awe]` `[wonder]` `[surprised]` `[excited]` `[emphatic]`
  - Non-verbal: `[whisper]` `[breath]`

**Placement rules:**
  - Max **one tag per sentence**. Over-tagging produces the uncanny "AI trying to act" effect.
  - Tags go BEFORE the sentence or word they modify.
  - Pauses land AFTER an operative word, not between clauses for breath.
  - Never stack adjacent tags — always separate with text or punctuation.

**OPERATIVE-WORD EMPHASIS (Muller's signature)**
Every sentence has ONE operative word — the word carrying the meaning of the beat. Write the sentence so that word lands in a natural stress position (end or near-end), and let the delivery cascade downward after it. The model already handles the pitch contour; your job is sentence construction that points to the operative word.

Bad: "The really amazing thing is how the coastline actually has no true length at all."
Good: "The coastline has no true length."  (operative word: "no" or "length")

**Good (natural tag use):**
  → "[curious] Here's something wild. [fast] Most people think time flows the same for everyone. [short pause] It doesn't. [slow] A clock on the ISS ticks slower than one on your desk."
  → "[thoughtful] Your brain isn't recording reality. [beat] It's CONSTRUCTING it."
  → "[fast] You think heavier things fall faster. [short pause] [amazed] Feathers disagree."

**Bad:**
  → "[excited][awe][curiosity] Something here." (stacked tags)
  → "[mysterious] Hmm." (invented tag — will be stripped)
  → "[curious] What [awe] is [beat] this?" (too many tags, chopped cadence)
  → "[amazed] [amazed] [amazed]" (emotional tags more than once per 30s)

**CAPS FOR EMPHASIS — USE SURGICALLY**
Gemini gives a subtle stress lift to fully capitalized words — lighter than shouting, firmer than italics. Use CAPS on at most ONE word per segment, and only where the emphasis genuinely serves the line.

  → "Your brain isn't recording reality. It's CONSTRUCTING it." — OK
  → "Lift isn't about SHAPE. It's about angle." — OK
  → "This is AMAZING. ... NOBODY saw it coming." — BAD (stacking CAPS + multiple emphasis)

**PAUSES — PUNCTUATION FIRST, TAGS FOR PRECISION**

Primary: natural punctuation.
  - `.` — standard sentence break (~300ms rest)
  - `...` — a beat. Short, thoughtful pause (~500ms)
  - `... ...` — a full breath. Use between setup and payoff.
  - `—` (em-dash) — sharp interruption mid-thought. No pause; just a cut.

Secondary: `[short pause]`, `[long pause]`, `[beat]` for deliberate control.
Use tags when you need the pause to land exactly on a visual beat. Default to punctuation.

**Good (clean prose, earned pauses):**
  → "A plane can fly upside down. ... Wings aren't what you think they are."
  → "What actually holds everything up? Let's look again — slower this time."
  → "It's smaller than a wavelength of light. And it thinks."

**Bad (forced drama, over-punctuated):**
  → "Wait... what... is happening... right now..." (pauses where none are needed)
  → "AMAZING. INCREDIBLE. SHOCKING." (CAPS stacking without punctuation rhythm)

**PAUSES — HOW TO WRITE THEM**
Use natural punctuation for pacing:

`...` — A beat. Short pause. Use after a single-word reveal or before a pivot.
  → "The signal travels at the speed of light. ... Inside your skull."

`... ...` — A full breath. Use at the turn between setup and payoff.
  → "Scientists called it impossible. ... ... They were right about everything except that."

`—` (em dash) — A sharp cut or interruption mid-thought.
  → "Your brain doesn't record reality — it constructs it."

Use pauses sparingly. One or two per segment maximum. Over-use flattens the effect entirely.

**BANNED PATTERNS — DO NOT USE ANY OF THESE**
These are the hallmarks of AI-generated narration. If you write any of these, rewrite immediately:

- Starting a segment with: "So,", "Now,", "This is", "In fact,", "Indeed,", "Remarkably,", "Here's the thing,", "Get this,", "Imagine this,", "Picture this,", "Ever wondered"
- Superlatives: "fascinating", "incredible", "remarkable", "stunning", "extraordinary", "mind-blowing", "jaw-dropping", "absolutely"
- Academic hedging: "one might argue", "it's worth noting", "this demonstrates that", "what's interesting is"
- Neat summary endings: "...every second you're alive", "...and that changes everything", "...and that's what makes it so powerful", "...and we've only scratched the surface"
- Three-item lists delivered as a list: "vision, hearing, and touch all work together"
- Passive constructions that sound written: "It has been shown that..."
- Transitions that sound like essay writing: "As we can see...", "Building on this...", "To summarize...", "Moving on,"
- Rhetorical question framings that sound like clickbait: "But have you ever wondered...", "What if I told you..." (this is only OK if you immediately subvert it)
- Explicit scene-setting that the visual already shows: "Here we see...", "As you can see here..."
- Wrapping words that soften a punch: "kind of", "sort of", "basically", "essentially", "actually" (unless the speaker is pushing back)
- Filler openers that buy time: "So let's talk about...", "Today we're going to explore..."

**THE READ-IT-OUT-LOUD TEST**
Before writing the final segment, silently read the previous segment's last sentence and then your new draft. If the join sounds like a human thinking out loud, keep it. If it sounds like the start of a new paragraph in an essay, rewrite it. Listen for: breaths, lurches, restarts, sudden shifts of attention — that's what real speech has and what AI narration lacks.

**FLOW — ONE CONTINUOUS VOICE**
The viewer hears one person speaking across all segments. Each segment's voiceover must flow from the last. Read the previous segment's last sentence before writing the next one. The join should be invisible.

Transition segments are emotional hinges — they're not summaries of what just happened. They're the moment the narrator's mind shifts. Use them to say the thing the viewer is thinking but hasn't articulated yet.

Bad transition: "And that's why the brain uses Bayesian integration."
Good transition: "But here's what nobody tells you. [pause] The brain doesn't do this to deceive you."

**CONVERSATIONAL AUTHORITY**
You are "Scientific Nipsey" — not an academic, not a TV host, not an AI assistant. You're the smartest person in the room who also happens to be genuinely excited. You curse occasionally in your head but keep it clean on screen. You use "you" a lot. You speak directly to one person, not a crowd.

**SPEED VARIATION — SET `speed` PER SEGMENT (0.96 to 1.12)**
Speed is NOT fixed across a video. Vary it, but within a TIGHT natural band. The production voice drags when pulled below 0.95 (sounds uncanny) and clips at above 1.15 (sounds rushed). Stay in this pocket:

- Hook / disruption opener: **0.98–1.02** — natural baseline. The hook lands on word choice, not tempo manipulation.
- Tension / build: **1.02–1.08** — slightly pushed. Forward pull.
- Revelation / payoff moment: **0.96–1.00** — settle just below neutral. Let the line breathe via PUNCTUATION (`...`, `—`), not via speed reduction.
- Wonder / closer: **0.98–1.02** — thoughtful but not dragged.
- Transition segments bridging excitement: **1.05–1.10** — push momentum through the connective tissue.

Variation still matters — don't set every segment to 1.00. But avoid going below 0.96 on this voice; drama comes from punctuation and word choice, not slowing the tape.

**HOOK ARCHETYPES — PICK ONE FOR SEGMENT 0**
These are the patterns that dominate retention data on science Shorts. Segment 0 must match one of these shapes. Examples are plain prose only — no bracket tags.

1. **The Contradiction** — State a fact that sounds wrong, then reveal it's right.
   → "A plane can fly upside down. ... Wings aren't what you think they are."

2. **The Misconception Plant (Veritasium)** — Name the viewer's wrong belief, then snap it.
   → "You think heavier things fall faster. ... Feathers disagree."

3. **The Stakes Reveal** — Start at the scale of something cosmic, shrink to the personal.
   → "Every second, a hundred trillion neutrinos pass through your thumb."

4. **The Question That Answers Itself** — Ask something that seems unanswerable, then the visual answers it.
   → "How do you measure something smaller than the tool measuring it?"

5. **The One-Word Shock** — Drop a noun that makes the viewer lean in, then build.
   → "Goosebumps. ... They're a muscle. A useless one. And every mammal has them."

6. **The Broken Rule** — State a rule of physics, then undermine it.
   → "Light always travels in straight lines. ... Unless space itself bends first."

Hook segments should be SHORT (60–90 chars) — the viewer decides in 2–3 seconds whether to keep watching.

**PATTERN INTERRUPT BETWEEN SEGMENTS**
Every transition from one segment to the next is a retention moment. The narrator must DO something at the join: change speed, drop a one-word sentence, ask a question, or pivot to the viewer ("But here's what nobody tells you."). If two consecutive segments feel like the same beat, one of them should be rewritten.

**LOOPABLE ENDING — DOUBLES RETENTION ON SHORTS**
Short-form autoplay loops — the algorithm rewards videos whose end flows back into the start. The FINAL segment's closing line and last visual frame must RHYME with the opening:
  - Echo a word or phrase from segment 0's voiceover.
  - Return to the same dominant color or compositional framing as the opening visual.
  - Or pose a question that the opening answers — forming a circular Q→A→Q loop.

Example: If segment 0 opens "A plane can fly upside down. Wings aren't what you think they are.", the last line might be: "So the next time you see a wing — look at the angle. Not the shape." The viewer hears "wing" echo and the loop feels intentional.

**MATCH-CUT DIRECTIVES — NO BLANK FRAMES BETWEEN SEGMENTS**
The transition from one visual segment to the next must be a MATCH-CUT, not a blank. The outgoing frame must share ONE visual property with the incoming: a shape whose outline matches, a motion vector that continues, a color that bleeds through.

For every visual segment, add a `metadata.match_cut_out` field describing how its final frame hands off to the next segment. Examples:
  → "Final frame: the orbit shrinks to a red dot, bottom-center. Next segment should open with a red dot in the same position."
  → "Final frame: blue wave crest frozen at x=400. Next segment should open on a similar blue curve at the same x."
  → "Final frame: vertical zoom down a black tube. Next segment opens continuing downward motion."

The `transition` segment types render this as a Ken Burns over the previous segment's last frame — so when you specify a match-cut handoff, the transition's Ken Burns will carry the eye into the next segment's opening naturally.

**BEAT EVERY 3–5 SECONDS — NO STATIC HOLDS**
Within each visual segment, something visible must CHANGE every 3–5 seconds: a camera move, a new element appearing, a color shift, a text overlay landing. A 10-second segment with a single held shot drops viewers. Write descriptions that explicitly choreograph the beat cadence:
  → "0–2s: single circle appears. 2–4s: circle splits into two. 4–6s: arrows connect them. 6–8s: full diagram resolves with labels."

**TEXT OVERLAYS ON KEY CLAIMS**
60%+ of mobile viewers watch muted. For every sentence carrying the central claim of a segment, the visual description must include a matching text callout: 3–6 words, sans-serif, bottom-third of frame, appears 200ms before the narrator says it. Specify this in the segment description.

=== SEGMENT TYPES (16 AVAILABLE) ===

**CORE VISUALIZATION TYPES:**

1. "pysim" - General Python scientific simulations using matplotlib
   USE FOR: Physics demos, particle systems, wave propagation, heat diffusion, general scientific phenomena
   EXAMPLES: Gravity simulation, electromagnetic fields, fluid dynamics, population dynamics

2. "manim" - Mathematical animations (3Blue1Brown style)
   USE FOR: Equations, proofs, geometric constructions, calculus, linear algebra
   EXAMPLES: Pythagorean theorem proof, derivative visualization, matrix transformations
   NOTE: 2D ONLY - no 3D objects

3. "mesa" - Agent-based modeling
   USE FOR: Emergent behavior, multi-agent systems, social dynamics
   EXAMPLES: Epidemic spread (SIR model), flocking behavior (Boids), wealth distribution, evolution

4. "pymunk" - 2D physics with rigid bodies and constraints
   USE FOR: Collision physics, mechanical systems, constraint-based motion
   EXAMPLES: Newton's cradle, billiards, pendulums, Rube Goldberg machines, projectile motion

5. "simpy" - Discrete event simulation
   USE FOR: Queuing theory, scheduling, process flow, resource management
   EXAMPLES: Bank teller lines, CPU scheduling, factory production, hospital ER flow

6. "plotly" - 3D plots and complex data visualization
   USE FOR: 3D surfaces, animated scatter plots, statistical 3D, rotating visualizations
   EXAMPLES: Loss landscapes, terrain maps, 3D function surfaces, clustering in 3D

7. "networkx" - Graph algorithms and network visualization
   USE FOR: Graph theory, social networks, routing, trees
   EXAMPLES: Shortest path (Dijkstra), BFS/DFS, PageRank, community detection, decision trees

8. "audio" - Sound and signal visualization
   USE FOR: Fourier transforms, spectrograms, waveforms, music theory
   EXAMPLES: How FFT works, how Shazam works, harmonics, audio compression

9. "stats" - Statistical visualizations
   USE FOR: Probability, distributions, regression, Monte Carlo, hypothesis testing
   EXAMPLES: Central limit theorem, Monty Hall problem, birthday paradox, p-values

10. "fractal" - Fractals and cellular automata (numba-accelerated)
    USE FOR: Self-similar patterns, iterative systems, emergence from simple rules
    EXAMPLES: Mandelbrot zoom, Julia sets, Conway's Game of Life, L-systems

11. "geo" - Geographic and map visualizations
    USE FOR: Map projections, global data, geographic concepts
    EXAMPLES: Why all maps are wrong (projections), rotating globe, great circle routes

12. "chem" - Molecular structures and chemistry
    USE FOR: Molecules, chemical bonds, reactions, biochemistry
    EXAMPLES: Caffeine structure, DNA helix, drug binding, protein structure

13. "astro" - Astronomy and celestial mechanics
    USE FOR: Orbital mechanics, planets, eclipses, star maps
    EXAMPLES: Solar system orrery, Kepler's laws, moon phases, satellite orbits

14. "transition" - Narrative bridge segments
    USE FOR: Connecting ideas, conclusions, building anticipation
    NOTE: MUST have voiceover narration

15. "grok" - AI-generated clip art parallax animations (Veritasium style)
    USE FOR: Visual hooks, dramatic reveals, conceptual illustrations, artistic visualizations that benefit from layered parallax depth
    EXAMPLES: Parallax zoom into a cell, dramatic space flythrough, layered diagram animation, cinematic concept visualization
    NOTE: Best for visually striking segments that benefit from AI-generated imagery with a clip art aesthetic. Produces 1-15 second videos.

16. "remotion" - Smooth React/Three.js motion graphics (Veritasium-style animated explainers)
    USE FOR: Clean animated diagrams with labels, smooth vector transitions, animated infographics, 3D scientific object rotations, motion-graphic title cards, annotated step-by-step walkthroughs
    EXAMPLES: Annotated neuron firing diagram with animated signal propagation, rotating DNA/protein 3D model, animated force diagram with labeled vectors, smooth bar/line chart race, cinematic 3D atom orbiting electrons, animated circuit diagram, geometric proof unfolding with arrows and labels, step-by-step equation reveal with highlighted terms
    STRENGTHS VS OTHER TYPES:
      - Prefer remotion over manim when the animation involves labels, arrows, icons, or mixed media (not pure math proofs)
      - Prefer remotion over pysim when you want polished motion graphics rather than a raw matplotlib simulation
      - Prefer remotion over grok when deterministic frame-accurate animation is needed (remotion is rendered deterministically)
      - Prefer remotion for 3D rotating scientific objects (molecules, crystal structures, orbiting bodies) using ThreeCanvas
    NOTE: Uses React + Remotion + Three.js. All animations are driven by frame number — fully deterministic. Renders at 1080x1920.

    **REMOTION STORYTELLING DIRECTION (critical — include this in every remotion description):**
    Describe the animation as a cinematic sequence, not a static diagram. Specify:
    - What appears first and how (fade in, slide up, scale from zero)
    - What transforms or moves mid-clip to mirror the narration's key beat
    - What the final held frame looks like — the image the viewer sits with
    Think of it as: ESTABLISH → MOVE → RESOLVE. The animation must feel like it's breathing with the voiceover.
    Example description: "A single neuron fades in center frame. At 2s, an electric pulse (bright blue line) travels down the axon toward a synapse. At 4s, neurotransmitter dots scatter across the synaptic cleft and fade — leaving only the quiet neuron and a faint glow where the signal passed. Label 'action potential' slides in at top."

=== SEGMENT TYPE DECISION TREE ===

Is it about mathematical proofs or equations?
    → "manim"

Is it about collisions, pendulums, or mechanical constraints?
    → "pymunk"

Is it about autonomous agents interacting (flocking, epidemics)?
    → "mesa"

Is it about queues, scheduling, or process flows?
    → "simpy"

Is it about graphs, networks, or trees?
    → "networkx"

Is it about 3D surfaces or rotating 3D data?
    → "plotly"

Is it about sound, frequencies, or audio?
    → "audio"

Is it about probability, distributions, or statistics?
    → "stats"

Is it about fractals, cellular automata, or emergent patterns?
    → "fractal"

Is it about maps, geography, or the Earth?
    → "geo"

Is it about molecules, chemicals, or biochemistry?
    → "chem"

Is it about space, planets, or astronomy?
    → "astro"

Is it general physics or scientific simulation?
    → "pysim"

Is it an animated diagram, labeled vector graphic, annotated step-by-step, or smooth motion graphic?
    → "remotion"

Is it a 3D rotating scientific object (molecule, crystal, atom, protein, DNA)?
    → "remotion" (use ThreeCanvas)

Is it about pure mathematical proofs or equations (no labels/icons, just shapes/curves)?
    → "manim"

Is it a dramatic visual that would benefit from AI-generated clip art parallax animation?
    → "grok"

Is it a narrative pause or conclusion?
    → "transition"

=== REQUIRED VIDEO STRUCTURE ===

- **SEGMENT 0**: Must be a VISUAL segment (hook with stunning visual) - NOT transition. Prefer "grok" for cinematic AI-imagery hooks OR "remotion" for clean motion-graphic title/concept hooks (e.g. a 3D rotating object or animated diagram that immediately establishes the topic). Use "grok" when the hook benefits from photorealistic/artistic imagery; use "remotion" when a crisp animated diagram or 3D scientific model would be more impactful.
- **SEGMENT 1**: Must be "transition" (bridge to explanation)
- **MIDDLE**: Alternate: visual → transition → visual → transition
- **FINAL SEGMENT**: Must be "transition" (conclusion with gratitude)

**RULE: Every visual segment (pysim/manim/mesa/pymunk/grok/etc.) MUST be followed by a transition segment.**

=== CRITICAL RULES ===

1. **EVERY SEGMENT MUST HAVE VOICEOVER** - All segments including transitions need narration
2. **MATCH TYPE TO CONTENT** - Use the most specific visualization type for the topic
3. **DESCRIPTION MUST BE A DIRECTOR'S NOTE** - Don't just describe what is shown; describe the animation as a timed sequence: what appears, when it moves, what the viewer feels. Every description should answer: "What is the key moment in this clip, and when does it happen?"
4. **VISUAL AND VOICEOVER ARE ONE** - The animation must be choreographed to the narration. If the voice says "and right here—", the visual must be mid-reveal at that instant. Write the description with this sync in mind.
5. **EACH SEGMENT SERVES THE ARC** - Before writing any segment, ask: is this the DISRUPTION, TENSION, REVELATION, or WONDER beat? The description and voiceover must serve that role.
6. **TRANSITIONS NEED NARRATION** - Never leave transition voiceover empty. Transitions are the emotional glue — use them to name what the viewer just saw and point toward what's coming.
7. **USE GEMINI AUDIO TAGS (whitelist only)** - Gemini 3.1 Flash TTS interprets bracketed audio tags as performance directives. Use them sparingly — roughly one every 2–3 sentences. Only whitelisted tags are permitted: `[curiosity]` `[awe]` `[wonder]` `[surprised]` `[thoughtful]` `[excited]` `[calm]` `[gentle]` `[emphatic]` `[short pause]` `[long pause]` `[beat]` `[whisper]` `[breath]`. Unknown tags will be stripped. Never stack adjacent tags.

**JSON FIELD GUIDE:**
- order: The sequence number (starting from 0)
- type: One of the 16 types listed above
- title: A short title for the segment
- description: Cinematic director's note — timed animation sequence, colors, what appears/moves/resolves, and which narrative beat this serves (disruption/tension/revelation/wonder). Must specify the KEY MOMENT and when it lands (e.g. "at 2.5s, the particle trails converge into a single curve"). A description that just names the concept is insufficient — write as if you're briefing an animator.
- voiceover: REQUIRED. Object with fields:
    - `text`: The narration. Use whitelisted Gemini audio tags sparingly, `...`/`—` for pauses, CAPS for emphasis. Sounds like speech, not writing.
    - `speed`: Float in [0.96, 1.12]. Set intentionally per segment per the SPEED VARIATION rules above. Hooks and reveals slower, tension and bridges faster.
  Write the voiceover LAST, after locking the visual. Read the previous segment's voiceover out loud before writing this one.
- metadata: Any additional parameters

=== FINAL SELF-CHECK BEFORE RESPONDING ===

Before you output the JSON, validate each segment against this list. If any fails, rewrite:
1. Does segment 0 match a hook archetype and land in 60–90 characters?
2. Does each segment use a DIFFERENT `speed` than the one before it (within [0.96, 1.12] — NEVER below 0.95)?
3. Do bracket tags ONLY appear from the whitelist, at most one per sentence, never stacked adjacent?
4. Is CAPS limited to at most ONE word per segment, and only where the emphasis genuinely serves?
5. Do any segments start with a banned opener ("So,", "Now,", "This is", etc.)?
6. Does each visual segment's description specify a timed KEY MOMENT (not just a concept)?
7. Does each visual segment's `metadata` include a `match_cut_out` describing the handoff to the next segment?
8. Does the FINAL segment's closing line echo segment 0 (word, phrase, color, or composition) so the loop feels intentional?
9. Does the last segment end on wonder, not summary?
10. When you read the voiceovers back-to-back, does it sound like one human thinking out loud, not an AI reading a list?

Respond with a JSON object containing a "segments" array. No preamble, no commentary — only the JSON.
"""

DURATION_INSTRUCTIONS = """
=== DURATION TARGETING (ABSOLUTE REQUIREMENT) ===

Target total video duration: **{target_duration} seconds**.

**THE VOICEOVER TEXT LENGTH IS THE ONLY THING THAT CONTROLS VIDEO DURATION.**
TTS rate: approximately 15 characters per second of audio output.

**YOUR TOTAL CHARACTER BUDGET: {target_duration} × 15 = {char_budget} characters across ALL segments combined.**

**Per-segment character limits (ENFORCED — text will be truncated if exceeded):**
- Visual segments: MAX 180 characters of voiceover text (≈12 seconds)
- Transition segments: MAX 100 characters of voiceover text (≈7 seconds)

**Segment count:**
- For {target_duration}s target → use {min_segments}-{max_segments} segments total

**CRITICAL: Write SHORT voiceovers.** Every segment voiceover should be 1-2 concise sentences.
Bad: "Now let's explore what happens when electrons flow through a conductor, creating what we call electrical current" (107 chars)
Good: "Watch what happens when electrons start flowing." (48 chars)

You MUST keep total voiceover characters under {char_budget}. Count as you go.
"""


MAX_GROK_SEGMENTS = 2


async def generate_segments_from_prompt(
    prompt: str,
    default_voice: str = "Algenib",
    default_speed: float = 1.0,
    target_duration: int = 90
) -> tuple[List[Segment], str, str]:
    """
    Use Claude to parse a user prompt into structured video segments.
    """
    char_budget = target_duration * 15
    min_segments = max(6, int(target_duration / 12))
    max_segments = max(8, int(target_duration / 6))
    duration_block = DURATION_INSTRUCTIONS.format(
        target_duration=target_duration,
        char_budget=char_budget,
        min_segments=min_segments,
        max_segments=max_segments,
    )
    full_prompt = SEGMENT_GENERATION_PROMPT + duration_block + "\nUser's prompt:\n" + prompt

    # Use streaming to avoid SDK timeout for large max_tokens
    response_text = ""
    # NOTE: Opus 4.7 deprecated the `temperature` parameter (uses adaptive
    # thinking instead). Passing it returns 400 invalid_request_error.
    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=64000,
        messages=[{"role": "user", "content": full_prompt}]
    ) as stream:
        for text in stream.text_stream:
            response_text += text

    # Parse the JSON response
    try:
        result = json.loads(response_text)
        if isinstance(result, list):
            segments_data = result
        elif isinstance(result, dict):
            segments_data = result.get("segments", [])
        else:
            # Fallback for unexpected structure
            segments_data = []

    except json.JSONDecodeError:
        text = response_text
        # try to find array or object
        start_obj = text.find("{")
        start_arr = text.find("[")

        if start_arr != -1 and (start_obj == -1 or start_arr < start_obj):
             # Likely an array
            start = start_arr
            end = text.rfind("]") + 1
            if start != -1 and end > start:
                segments_data = json.loads(text[start:end])
            else:
                 raise ValueError("Failed to parse response as JSON list")
        elif start_obj != -1:
            # Likely an object
            start = start_obj
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                result = json.loads(text[start:end])
                segments_data = result.get("segments", [])
            else:
                raise ValueError("Failed to parse response as JSON object")
        else:
            raise ValueError("Failed to parse response as JSON")

    # Convert to Segment objects
    segments = []
    for seg_data in segments_data:
        voiceover = None
        if seg_data.get("voiceover"):
            vo_data = seg_data["voiceover"]
            if isinstance(vo_data, dict) and vo_data.get("text"):
                voiceover = VoiceoverConfig(
                    text=vo_data["text"],
                    voice=vo_data.get("voice", default_voice),
                    speed=vo_data.get("speed", default_speed)
                )

        segment = Segment(
            order=seg_data.get("order", len(segments)),
            type=seg_data.get("type", "pysim"),
            title=seg_data.get("title", f"Segment {len(segments) + 1}"),
            description=seg_data.get("description", ""),
            voiceover=voiceover,
            metadata=seg_data.get("metadata", {})
        )
        segments.append(segment)

    # Grok limiter: convert any grok segments beyond the first 2 to pysim
    grok_count = 0
    for segment in segments:
        if segment.type == "grok":
            grok_count += 1
            if grok_count > MAX_GROK_SEGMENTS:
                logger.info(f"Grok limiter: converting segment {segment.order} '{segment.title}' from grok to pysim (limit {MAX_GROK_SEGMENTS})")
                segment.type = "pysim"

    # ── Voice normalization: one voice across all segments, but KEEP per-segment speed.
    # Per-segment speed variation is a major lever against "AI slop" cadence — hooks
    # slow down for drama, tension builds push faster, transitions settle back. The
    # LLM sets speed intentionally per segment; we only clamp to a safe range.
    for segment in segments:
        if segment.voiceover:
            segment.voiceover.voice = default_voice
            speed = segment.voiceover.speed if segment.voiceover.speed else default_speed
            # Tight natural band for the production voice. Below 0.95 drags; above 1.12 clips.
            segment.voiceover.speed = max(0.95, min(1.12, float(speed)))

    # ── Duration enforcement: truncate voiceover text to fit character budget ──
    CHARS_PER_SEC = 15
    MAX_VISUAL_CHARS = 180
    MAX_TRANSITION_CHARS = 100
    char_budget = target_duration * CHARS_PER_SEC

    # First pass: enforce per-segment caps
    for segment in segments:
        if not segment.voiceover:
            continue
        cap = MAX_TRANSITION_CHARS if segment.type == "transition" else MAX_VISUAL_CHARS
        text = segment.voiceover.text
        if len(text) > cap:
            # Truncate at last sentence boundary within cap
            truncated = text[:cap]
            last_period = truncated.rfind('.')
            last_question = truncated.rfind('?')
            last_exclaim = truncated.rfind('!')
            best = max(last_period, last_question, last_exclaim)
            if best > cap * 0.5:
                truncated = text[:best + 1]
            logger.info(f"Truncated segment {segment.order} voiceover: {len(text)} -> {len(truncated)} chars")
            segment.voiceover.text = truncated

    # Second pass: if total still over budget, proportionally trim all segments
    total_chars = sum(len(s.voiceover.text) for s in segments if s.voiceover)
    if total_chars > char_budget * 1.15:
        scale = char_budget / total_chars
        logger.warning(f"Duration enforcement: total {total_chars} chars exceeds budget {char_budget}, scaling by {scale:.2f}")
        for segment in segments:
            if not segment.voiceover:
                continue
            text = segment.voiceover.text
            new_len = int(len(text) * scale)
            if new_len < len(text):
                truncated = text[:new_len]
                # Find last sentence boundary
                last_period = truncated.rfind('.')
                last_question = truncated.rfind('?')
                last_exclaim = truncated.rfind('!')
                best = max(last_period, last_question, last_exclaim)
                if best > new_len * 0.4:
                    truncated = text[:best + 1]
                segment.voiceover.text = truncated

    final_chars = sum(len(s.voiceover.text) for s in segments if s.voiceover)
    estimated_duration = final_chars / CHARS_PER_SEC
    logger.info(f"Generated {len(segments)} segments, {final_chars} total chars, ~{estimated_duration:.0f}s estimated duration (target: {target_duration}s)")
    return segments, full_prompt, "claude-opus-4-7"


async def generate_caption(prompt: str) -> str:
    """Generate an engaging social media caption with hashtags."""
    caption_prompt = f"""Create an engaging social media caption for a math/science animation video about: {prompt}

Requirements:
- Start with a hook that grabs attention (question, surprising fact, or bold statement)
- Keep it concise (2-3 sentences max)
- Make it educational yet exciting
- End with 5-8 relevant hashtags including #Manim #MathAnimation #LearnOnTikTok #Education
- Use emojis sparingly but effectively (1-3 max)
- Write in a tone that appeals to curious learners

Return ONLY the caption text with hashtags, nothing else."""

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=512,
        messages=[{"role": "user", "content": caption_prompt}]
    )
    return response.content[0].text.strip()
