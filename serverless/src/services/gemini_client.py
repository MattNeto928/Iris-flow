"""
Gemini Client - Segment generation and caption creation.

Uses Gemini to generate video segments from prompts and create social media captions.
Ported from local main_service/app/gemini_client.py.
"""

import os
import json
import logging
from typing import List
from dataclasses import dataclass
from google import genai

logger = logging.getLogger(__name__)

# Initialize client
client = genai.Client(api_key=os.environ.get("GOOGLE_AI_API_KEY"))


@dataclass
class VoiceoverConfig:
    text: str
    voice: str = "Fenrir"
    speed: float = 1.15


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


SEGMENT_GENERATION_PROMPT = """You are an expert video production assistant creating Veritasium-style educational STEM content. Given a user's prompt, break it down into a sequence of compelling video segments using the most appropriate visualization type for each concept.

**VERITASIUM STYLE GUIDE:**
Your videos should feel like a Veritasium documentary - intellectually captivating, conversational yet authoritative, and structured to hook viewers from the first second.

**VIDEO FORMAT: VERTICAL (9:16 for YouTube Shorts/TikTok/Reels)**
- Resolution: 1080x1920 pixels (portrait orientation)
- Keep all visual elements centered and compact
- Design for mobile viewing

**KEY PRINCIPLES:**
1. **HOOK FIRST** - Open with a mind-bending question, paradox, or visually stunning simulation
2. **CONVERSATIONAL AUTHORITY** - Write like you're explaining to a curious friend
3. **BUILD MYSTERY** - Each section should raise questions before answering them
4. **END WITH WONDER** - Conclude with gratitude and a lingering thought

=== SEGMENT TYPES (14 AVAILABLE) ===

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

Is it a narrative pause or conclusion?
    → "transition"

=== REQUIRED VIDEO STRUCTURE ===

- **SEGMENT 0**: Must be a VISUAL segment (hook with stunning visual) - NOT transition
- **SEGMENT 1**: Must be "transition" (bridge to explanation)
- **MIDDLE**: Alternate: visual → transition → visual → transition
- **FINAL SEGMENT**: Must be "transition" (conclusion with gratitude)

**RULE: Every visual segment (pysim/manim/mesa/pymunk/etc.) MUST be followed by a transition segment.**

=== CRITICAL RULES ===

1. **EVERY SEGMENT MUST HAVE VOICEOVER** - All segments including transitions need narration
2. **MATCH TYPE TO CONTENT** - Use the most specific visualization type for the topic
3. **DESCRIPTION MUST BE DETAILED** - Include specific parameters, colors, animations
4. **TRANSITIONS NEED NARRATION** - Never leave transition voiceover empty

For each segment, provide:
- order: The sequence number (starting from 0)
- type: One of the 14 types listed above
- title: A short title for the segment
- description: Detailed description of what should be shown visually
- voiceover: REQUIRED - Object with "text" field containing Veritasium-style narration
- metadata: Any additional parameters

Respond with a JSON object containing a "segments" array.

User's prompt:
"""


async def generate_segments_from_prompt(
    prompt: str, 
    default_voice: str = "Fenrir", 
    default_speed: float = 1.15
) -> List[Segment]:
    """
    Use Gemini to parse a user prompt into structured video segments.
    """
    full_prompt = SEGMENT_GENERATION_PROMPT + prompt

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=full_prompt,
        config={
            "temperature": 0.7,
            "top_p": 0.95,
            "max_output_tokens": 16384,
            "response_mime_type": "application/json",
        }
    )
    
    # Parse the JSON response
    try:
        result = json.loads(response.text)
        if isinstance(result, list):
            segments_data = result
        elif isinstance(result, dict):
            segments_data = result.get("segments", [])
        else:
            # Fallback for unexpected structure
            segments_data = []
            
    except json.JSONDecodeError:
        text = response.text
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
                 raise ValueError("Failed to parse Gemini response as JSON list")
        elif start_obj != -1:
            # Likely an object
            start = start_obj
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                result = json.loads(text[start:end])
                segments_data = result.get("segments", [])
            else:
                raise ValueError("Failed to parse Gemini response as JSON object")
        else:
            raise ValueError("Failed to parse Gemini response as JSON")

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

    logger.info(f"Generated {len(segments)} segments from prompt")
    return segments


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

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=caption_prompt
    )
    return response.text.strip()
