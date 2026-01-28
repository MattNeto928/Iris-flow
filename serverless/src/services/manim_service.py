"""
Manim Service - Mathematical animation generation.

Uses Claude to generate Manim scripts, then renders them.
Ported from local manim_service.
"""

import os
import uuid
import logging
import asyncio
from pathlib import Path
import anthropic

logger = logging.getLogger(__name__)

# Initialize Anthropic client
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Output directories
OUTPUT_DIR = Path("/app/output")
SCRIPTS_DIR = OUTPUT_DIR / "manim_scripts"
VIDEOS_DIR = OUTPUT_DIR / "manim_videos"


MANIM_PROMPT = """You are an expert Manim Community v0.19.0 animator creating educational content in the style of 3Blue1Brown.

VIDEO FORMAT: VERTICAL (9:16 for YouTube Shorts/TikTok/Reels)
- Resolution: 1080x1920 pixels (portrait orientation)
- Coordinate range: Keep x in [-4,4] and y in [-7,7] (narrower width, taller height)
- LAYOUT: Stack elements VERTICALLY, not horizontally
- Text: Use smaller font_size (24-32 for body, 36-42 for titles) to fit narrow width
- Animations: Flow TOP-TO-BOTTOM instead of left-to-right
- Keep visual elements centered and compact

DURATION: {duration} seconds

EXACT TEMPLATE TO FOLLOW:
```python
from manim import *
import numpy as np

class ExplanationScene(Scene):
    def construct(self):
        # Your animation code here
        # Example:
        # title = Text("Title", font_size=42)
        # self.play(Write(title))
        # self.wait(1)
        pass
```

SAFE MOBJECTS TO USE:
- Shapes: Circle, Square, Rectangle, Triangle, Polygon, Line, Arrow, Dot, Ellipse, Arc
- Text: Text, MathTex, Tex, Title
- Groups: VGroup, Group
- Graphs: Axes, NumberPlane, NumberLine, FunctionGraph

SAFE ANIMATIONS TO USE:
- Create, Write, FadeIn, FadeOut, GrowFromCenter, DrawBorderThenFill
- Transform, ReplacementTransform
- Indicate, Circumscribe, Flash, Wiggle
- MoveToTarget, Rotate, Scale, Shift

**CRITICAL - LaTeX in MathTex:**
- Each substring in MathTex() MUST be valid, compilable LaTeX on its own.
- NEVER split in the middle of a LaTeX command like `\\frac{}{}`, `\\sqrt{}`, `\\sum_{}^{}`.
- BAD: `MathTex(r"\\frac{2", r"GM", r"}{", r"c^2", r"}")` - splits break LaTeX and cause crashes!
- GOOD: `MathTex(r"\\frac{2GM}{c^2}")` - complete expression
- GOOD: `MathTex(r"r_s", r"=", r"\\frac{2GM}{c^2}")` - each part is valid LaTeX
- If you need to animate parts separately, use TransformMatchingTex or ReplacementTransform, not invalid substring splits.

EXAMPLES (VERTICAL FORMAT):

# Example 1: Basic Shapes & Text
class ShapeScene(Scene):
    def construct(self):
        circle = Circle(color=BLUE, fill_opacity=0.5)
        square = Square(color=RED)
        square.next_to(circle, DOWN)  # Vertical layout
        
        text = Text("Hello Manim", font_size=32)
        text.next_to(circle, UP)
        
        self.play(Create(circle), Create(square))
        self.wait(1)
        self.play(Write(text))
        self.wait(2)

# Example 2: Math
class MathScene(Scene):
    def construct(self):
        axes = Axes(x_range=[-3, 3], y_range=[-3, 3], x_length=6, y_length=6)
        graph = axes.plot(lambda x: x**2, color=YELLOW)
        
        eq = MathTex(r"f(x) = x^2", font_size=36)
        eq.next_to(axes, UP)
        
        self.play(Create(axes), run_time=1.5)
        self.play(Create(graph), run_time=2)
        self.play(Write(eq))
        self.wait(2)

CRITICAL RULES:
1. Class MUST be named ExplanationScene
2. Always use self.play() for animations
3. Use .animate syntax: self.play(circle.animate.shift(UP))
4. Keep x in [-4,4] and y in [-7,7] for vertical format
5. Add self.wait() between sections
6. Return ONLY raw Python code, no markdown

**STRING FORMATTING RULES (CRITICAL):**
- NEVER use .format() with numbered placeholders like {{0}}, {{1}}
- BAD: `Text("Value: {{0}}".format())` - causes "Replacement index 0 out of range"!
- BAD: `Text("{{}}".format())` - empty format causes crash!
- GOOD: Use f-strings: `Text(f"Value: {{my_var}}")`
- GOOD: Direct string: `Text("Value: " + str(my_var))`
- GOOD: Simple strings: `Text("My Label")`

**CODE SYNTAX RULES:**
- ALWAYS close all parentheses, brackets, and braces
- DOUBLE-CHECK multi-line expressions have proper closing
- BAD: `self.play(Create(` (unclosed!)
- GOOD: Complete all statements properly

Description: {description}

GENERATE ONLY PYTHON CODE:
"""


class ManimService:
    def __init__(self):
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    
    async def generate(self, description: str, duration: float, previous_error: str = None) -> str:
        """
        Generate a Manim video from description.
        
        1. Generate Manim script with Claude
        2. Render with Manim
        
        Returns path to generated video.
        """
        video_id = str(uuid.uuid4())[:8]
        
        logger.info(f"[Manim] Generating script for {duration}s video")
        if previous_error:
            logger.info(f"[Manim] Retrying with error context: {previous_error}")
        
        # Step 1: Generate script
        script = await self._generate_script(description, duration, previous_error)
        logger.info(f"[Manim] Script generated ({len(script)} chars)")
        
        # Step 2: Render
        video_path = await self._render(script, video_id)
        
        return video_path
    
    async def generate_from_script(self, script: str, duration: float) -> str:
        """
        Render a Manim video from a pre-generated script.
        Used for soundwave transitions where the script is templated.
        
        Returns path to generated video.
        """
        video_id = str(uuid.uuid4())[:8]
        
        logger.info(f"[Manim] Rendering from provided script")
        
        # Skip script generation, go straight to render
        video_path = await self._render(script, video_id, scene_name="SoundWaveScene")
        
        return video_path
    
    async def _generate_script(self, description: str, duration: float, previous_error: str = None) -> str:
        """Generate Manim script using Claude."""
        
        # Add error context if retrying
        error_context = ""
        if previous_error:
            error_context = f"""
*** PREVIOUS ATTEMPT FAILED WITH ERROR: ***
{previous_error}
*** YOU MUST FIX THIS ERROR IN THE NEW SCRIPT ***
"""
        
        # Use replace() instead of format() to avoid conflicts with curly braces in the prompt examples
        prompt = MANIM_PROMPT.replace("{description}", description).replace("{duration}", str(duration)) + error_context
        
        message = client.messages.create(
            model="claude-opus-4-5-20251101",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text
        
        # Clean markdown if present
        if "```python" in response_text:
            start = response_text.find("```python") + 9
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
        elif "```" in response_text:
            start = response_text.find("```") + 3
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
        
        return response_text
    
    async def _render(self, script: str, video_id: str, scene_name: str = "ExplanationScene") -> str:
        """Render Manim scene."""
        script_path = SCRIPTS_DIR / f"{video_id}.py"
        
        with open(script_path, "w") as f:
            f.write(script)
        
        logger.info(f"[Manim] Rendering scene: {scene_name}...")
        
        # Vertical resolution: 1080x1920
        cmd = f"manim -r 1080,1920 --fps 30 -ql --media_dir {OUTPUT_DIR} {script_path} {scene_name}"
        
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(SCRIPTS_DIR)
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            logger.error(f"[Manim] Render failed: {error_msg}")
            raise RuntimeError(f"Manim render failed: {error_msg}")
        
        # Find output video
        video_files = list(OUTPUT_DIR.rglob("*.mp4"))
        if not video_files:
            raise RuntimeError("No video file found after rendering")
        
        video_path = max(video_files, key=lambda p: p.stat().st_mtime)
        
        # Move to final location
        final_path = VIDEOS_DIR / f"manim_{video_id}.mp4"
        video_path.rename(final_path)
        
        logger.info(f"[Manim] Rendered: {final_path}")
        return str(final_path)
