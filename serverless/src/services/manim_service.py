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


MANIM_PROMPT = """# Manim Segment Generation

Manim segments produce 3Blue1Brown-style mathematical and scientific animations. The output is a rendered MP4 at 1080x1920 (9:16 vertical). Every generated script must be cinematic, fluid, and educational — no snapping, no jitter, no overcrowding.

## Scene Configuration (Always Required)

```python
from manim import *
from manim.utils.rate_functions import (
    ease_in_sine, ease_out_sine, ease_in_out_sine,
    ease_in_quad, ease_out_quad, ease_in_out_quad,
    ease_in_cubic, ease_out_cubic, ease_in_out_cubic,
    ease_in_quart, ease_out_quart, ease_in_out_quart,
    ease_in_expo, ease_out_expo,
    ease_out_back, ease_in_back,
    ease_out_elastic,
)
import numpy as np

config.pixel_width = 1080
config.pixel_height = 1920
config.frame_rate = 30
# Coordinate space: x ∈ [-4.5, 4.5], y ∈ [-8, 8]
# Safe content zone: x ∈ [-3.8, 3.8], y ∈ [-7.2, 7.2]
```

**CRITICAL**: The `ease_*` functions are NOT exported by `from manim import *`. You MUST include the `from manim.utils.rate_functions import ...` block above in every script, or any `ease_*` usage will raise a `NameError`.

Always use `MovingCameraScene` as the base class — it enables cinematic camera control even when no camera movement is planned.

```python
class MyScene(MovingCameraScene):
    def construct(self):
        ...
```

## Coordinate System Rules

The rendered frame is 1080×1920. In Manim's coordinate units:
- **Full frame**: x ∈ [−4.5, 4.5], y ∈ [−8, 8]
- **Safe zone** (always stay inside): x ∈ [−3.8, 3.8], y ∈ [−7.2, 7.2]
- **Never** place text or labels outside the safe zone
- **Never** use absolute coordinates without verifying they fit
- Prefer `next_to`, `align_to`, `move_to` over raw coordinate placement

When using `NumberPlane` or `Axes`, always set explicit ranges that keep the grid within safe bounds:
```python
plane = NumberPlane(
    x_range=[-3.5, 3.5, 1],
    y_range=[-6.5, 6.5, 1],
    background_line_style={"stroke_color": GREY_D, "stroke_width": 1, "stroke_opacity": 0.4},
)
```

## Aesthetic Standards

### Background and Colors
```python
# Scene background — set in config or manually
config.background_color = "#0D0D0D"

# Primary palette — defined as ManimColor so they work with interpolate_color()
# CRITICAL: always define custom colors as ManimColor(...), not bare strings.
# Bare hex strings (#4FC3F7) will raise AttributeError inside interpolate_color().
ELECTRIC_BLUE = ManimColor("#4FC3F7")
SOFT_GOLD     = ManimColor("#FFD54F")
CORAL         = ManimColor("#FF7043")
MINT          = ManimColor("#80CBC4")
LAVENDER      = ManimColor("#CE93D8")
WARM_WHITE    = ManimColor("#F5F5F5")
DIM_GREY      = ManimColor("#424242")
```

Use vibrant but not garish colors. Equations in `ELECTRIC_BLUE` or `WARM_WHITE`. Highlighted terms in `SOFT_GOLD`. Secondary elements in `DIM_GREY`. Avoid pure `WHITE` (too harsh on dark backgrounds).

**Color rule:** Any color constant you define must be `ManimColor("#...")`. Never assign a bare hex string to a variable you'll pass to Manim color functions (`interpolate_color`, `set_color`, etc.) — it will raise `AttributeError: 'str' object has no attribute 'interpolate'`.

### Typography — Roboto Throughout
```python
# Always specify font for all Text objects
label = Text("Euler's Formula", font="Roboto", font_size=36, color=WARM_WHITE)
small = Text("where n → ∞", font="Roboto", font_size=24, color=DIM_GREY)

# For mathematical expressions, use MathTex
eq = MathTex(r"e^{i\pi} + 1 = 0", font_size=48, color=ELECTRIC_BLUE)

# Mixed text+math — use Tex with explicit font in preamble
# Or combine Text + MathTex with VGroup
```

Never use default font — always specify `font="Roboto"`. If Roboto unavailable, fallback: `font="Helvetica Neue"`, then `font="DejaVu Sans"`.

Font size guidelines:
- Main title: 42–52px
- Section headers: 32–40px
- Body labels: 24–30px
- Footnotes / annotations: 18–22px
- Avoid anything below 16px (unreadable on mobile)

## Animation Principles

### Easing — Always Use rate_func
Every `self.play()` call MUST specify a rate_func appropriate to the motion.

**Two categories of rate functions — know the difference:**

**Category A — exported by `from manim import *` (use directly):**
| Function | Behavior |
|---|---|
| `linear` | Constant speed — only for continuous motion (rotation, scrolling) |
| `smooth` | Sigmoid ease-in-out — default for most animations |
| `smoothstep` | Polynomial ease-in-out, snappier than smooth |
| `rush_into` | Strong ease-in (accelerates hard) |
| `rush_from` | Strong ease-out (decelerates hard) |
| `slow_into` | Starts fast, ends slow (circular arc) |
| `there_and_back` | Goes to 1 then returns to 0 — for pulses/emphasis |
| `there_and_back_with_pause` | Same but holds at peak — for sustained emphasis |
| `wiggle` | Oscillates — for attention/shake effects |
| `lingering` | Moves fast then lingers — good for reveals |
| `exponential_decay` | Explosive start, asymptotic approach |

**Category B — from `manim.utils.rate_functions` (already imported in the boilerplate above):**
| Function | Behavior |
|---|---|
| `ease_in_sine` / `ease_out_sine` / `ease_in_out_sine` | Gentle, cosine-based |
| `ease_in_cubic` / `ease_out_cubic` / `ease_in_out_cubic` | Moderate (t³) — great general purpose |
| `ease_in_quart` / `ease_out_quart` | Strong (t⁴) |
| `ease_in_expo` / `ease_out_expo` | Extreme — explosive start or finish |
| `ease_out_back` | Overshoots then settles — satisfying for reveals |
| `ease_in_back` | Slight windup before launching |
| `ease_out_elastic` | Spring oscillation at end — use sparingly |

```python
# Standard smooth motion
self.play(Create(curve), rate_func=smooth, run_time=2)

# Equation settling into position
self.play(FadeIn(eq, shift=UP*0.3), rate_func=ease_out_cubic, run_time=1.5)

# Satisfying reveal with slight overshoot
self.play(FadeIn(result, shift=UP*0.2), rate_func=ease_out_back, run_time=1.2)

# Sustained emphasis (pulse)
self.play(eq.animate.scale(1.1), rate_func=there_and_back_with_pause, run_time=2)

# Writing equations — linear only here
self.play(Write(formula), rate_func=linear, run_time=2.5)

# Exiting
self.play(FadeOut(group), rate_func=ease_in_cubic, run_time=1.0)
```

**Never use `rate_func=linear` for object creation or transformation** — it looks mechanical. Reserve `linear` only for `Write()` and things meant to feel continuous (rotation, scrolling).

### Timing — Let It Breathe
Educational content must be comprehensible. Pacing rules:
- Minimum `run_time=1.0` for any meaningful animation
- Complex equations: `run_time=2.0–3.0`
- Camera moves: `run_time=2.5–4.0`
- After every major reveal: `self.wait(1.5)` minimum
- Between sections: `self.wait(2.0)`
- Final hold before scene ends: `self.wait(2.0)`

### Sequencing — LaggedStart and AnimationGroup
```python
# Staggered appearance — feels natural, not mechanical
self.play(
    LaggedStart(
        FadeIn(label1, shift=UP*0.2),
        FadeIn(label2, shift=UP*0.2),
        FadeIn(label3, shift=UP*0.2),
        lag_ratio=0.25,
    ),
    rate_func=smooth,
    run_time=2.5,
)

# Simultaneous animations with different durations
self.play(
    AnimationGroup(
        Create(circle, run_time=2),
        Write(eq, run_time=3),
    )
)
```

### Smooth Transforms
```python
# Morphing one expression into another
self.play(TransformMatchingTex(old_eq, new_eq), run_time=2.0)

# Replacing cleanly
self.play(ReplacementTransform(old_obj, new_obj), rate_func=smooth, run_time=1.5)

# Highlighting a subexpression
self.play(Indicate(eq[0][3:6], color=SOFT_GOLD, scale_factor=1.3), run_time=1.0)
```

## Camera — Cinematic Movement

```python
class MyScene(MovingCameraScene):
    def construct(self):
        # Zoom in to a detail
        self.play(
            self.camera.animate.set(frame_width=4),
            rate_func=smooth,
            run_time=3.0,
        )
        self.wait(1.5)

        # Pan to a new location
        self.play(
            self.camera.animate.move_to(RIGHT * 2 + UP * 1),
            rate_func=smooth,
            run_time=2.5,
        )

        # Zoom back out
        self.play(
            self.camera.animate.set(frame_width=9),
            rate_func=smooth,
            run_time=2.5,
        )
```

Camera rules:
- Default `frame_width=9` for 9:16 vertical (matches pixel ratio)
- Minimum `frame_width=2` (extremely zoomed), maximum `frame_width=12`
- Always ease in and out of camera moves (`rate_func=smooth`)
- Never cut camera abruptly — always animate
- After a zoom, wait at least 1.5s before the next camera move

## Preventing Common Failures

### Overlap Prevention
```python
# Use VGroup with arrange for automatic spacing
group = VGroup(label1, eq1, label2, eq2).arrange(DOWN, buff=0.6, aligned_edge=LEFT)
group.move_to(ORIGIN)

# Check bounds after positioning
# If group.get_top()[1] > 7.0: shift down
# If group.get_bottom()[1] < -7.0: shift up or reduce font

# next_to with generous buff
subtitle.next_to(title, DOWN, buff=0.5)
```

### No Off-Screen Elements
Before any `self.play()` that creates an element:
1. Compute its position
2. Verify it's within safe zone
3. If not, reduce `font_size` or adjust position

### No Jitter in Continuous Animation
```python
# WRONG — recreating object every frame causes jitter
# DO NOT do: for t in range(n): self.remove(dot); dot = Dot(f(t)); self.add(dot)

# RIGHT — use ValueTracker + always_redraw
t_val = ValueTracker(0)
dot = always_redraw(lambda: Dot(
    ax.c2p(t_val.get_value(), np.sin(t_val.get_value())),
    color=ELECTRIC_BLUE,
))
self.add(dot)
self.play(t_val.animate.set_value(TAU), rate_func=linear, run_time=4.0)
```

### ValueTracker Pattern (Smooth Parameter Animation)
```python
# Animate any parameter smoothly
k = ValueTracker(1.0)

# Object that continuously redraws as k changes
curve = always_redraw(lambda: ax.plot(
    lambda x: np.sin(k.get_value() * x),
    x_range=[-3, 3],
    color=ELECTRIC_BLUE,
    stroke_width=3,
))
self.add(curve)

# Smoothly vary k
self.play(k.animate.set_value(3.0), rate_func=smooth, run_time=4.0)
```

## Standard Scene Structure

```python
class EducationalScene(MovingCameraScene):
    def construct(self):
        # 1. Configure
        self.camera.frame.set(frame_width=9)

        # 2. Title reveal
        title = Text("Topic Title", font="Roboto", font_size=44, color=WARM_WHITE)
        title.move_to(UP * 6.5)
        self.play(FadeIn(title, shift=DOWN*0.3), rate_func=ease_out_cubic, run_time=1.5)
        self.wait(1.0)

        # 3. Main visual (one clear focal element at a time)
        ...

        # 4. Build up with LaggedStart
        ...

        # 5. Cinematic camera move to emphasize
        ...

        # 6. Hold final state
        self.wait(2.0)

        # 7. Fade everything out (optional, for clean transitions)
        self.play(FadeOut(VGroup(*self.mobjects)), run_time=1.5)
```

CRITICAL DYNAMIC REQUIREMENTS:
- Target Duration: {duration} seconds
- Description: {description}

GENERATE ONLY PYTHON CODE. Be concise — use loops, helper functions, and avoid repeating similar code blocks. No markdown, no explanation:
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
        
        self._last_prompt = prompt
        
        self._last_model = 'claude-opus-4-7'
        
        message = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=16384,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text
        if message.stop_reason == "max_tokens":
            raise RuntimeError("Code generation was truncated (hit max_tokens). The description may be too complex for a single segment.")
        
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
        cmd = f"manim -r 1080,1920 --fps 30 -qm --media_dir {OUTPUT_DIR} {script_path} {scene_name}"
        
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
