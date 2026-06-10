---
name: manim-segments
description: This skill should be used when generating Manim animation code for Iris-flow video segments, when writing manim scenes, when the user asks about manim mathematical animations, MovingCameraScene, vector fields in manim, LaTeX rendering in manim, or when working on any "manim" segment type in the pipeline.
version: 1.0.0
---

# Manim Segment Generation

Manim segments produce 3Blue1Brown-style mathematical and scientific animations. The output is a rendered MP4 at 1080x1920 (9:16 vertical). Every generated script must be cinematic, fluid, and educational — no snapping, no jitter, no overcrowding.

## Scene Configuration (Always Required)

```python
from manim import *
import numpy as np

config.pixel_width = 1080
config.pixel_height = 1920
config.frame_rate = 30
# Coordinate space: x ∈ [-4.5, 4.5], y ∈ [-8, 8]
# Safe content zone: x ∈ [-3.8, 3.8], y ∈ [-7.2, 7.2]
```

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

# Primary palette
ELECTRIC_BLUE = "#4FC3F7"
SOFT_GOLD     = "#FFD54F"
CORAL         = "#FF7043"
MINT          = "#80CBC4"
LAVENDER      = "#CE93D8"
WARM_WHITE    = "#F5F5F5"
DIM_GREY      = "#424242"
```

Use vibrant but not garish colors. Equations in `ELECTRIC_BLUE` or `WARM_WHITE`. Highlighted terms in `SOFT_GOLD`. Secondary elements in `DIM_GREY`. Avoid pure `WHITE` (too harsh on dark backgrounds).

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
Every `self.play()` call MUST specify a rate_func appropriate to the motion:

```python
# Standard smooth motion — use for most animations
self.play(Create(curve), rate_func=smooth, run_time=2)

# Settle into position — great for equations appearing
self.play(FadeIn(eq, shift=UP*0.3), rate_func=ease_out_cubic, run_time=1.5)

# Organic, breathing feel — for emphasis
self.play(eq.animate.scale(1.1), rate_func=there_and_back_with_pause, run_time=2)

# Building up — for sequential reveals
self.play(Write(formula), rate_func=linear, run_time=2.5)

# Departing / exiting
self.play(FadeOut(group), rate_func=ease_in_cubic, run_time=1.0)
```

Rate function reference:
| Motion type | rate_func |
|---|---|
| Default smooth | `smooth` |
| Ease in | `rush_into` / `ease_in_cubic` |
| Ease out | `rush_from` / `ease_out_cubic` |
| Ease in-out | `smooth` |
| Oscillate/pulse | `there_and_back` |
| Constant speed | `linear` |

**Never use `rate_func=linear` for object creation or transformation** — it looks mechanical. Reserve `linear` only for things meant to feel continuous (scrolling, rotation).

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

## Reference Files

- `references/camera-easing.md` — MovingCameraScene patterns, zoom sequences, pan choreography
- `references/text-latex.md` — MathTex, TransformMatchingTex, Roboto setup, substring indexing
- `references/vector-fields.md` — VectorField, StreamLines, AnimatedStreamLines, phase portraits
- `references/threed.md` — ThreeDScene, Surface, ParametricSurface, 3D camera rotation
