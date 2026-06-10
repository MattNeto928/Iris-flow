# Manim Text & LaTeX Reference

## Text vs MathTex vs Tex

| Class | Use for | Font control |
|-------|---------|-------------|
| `Text` | Plain prose, labels, titles | `font="Roboto"` — full control |
| `MathTex` | Pure math expressions | LaTeX rendering, limited font |
| `Tex` | Mixed text + math in LaTeX | LaTeX rendering |

**Rule:** Always use `Text(..., font="Roboto")` for all non-math content. Use `MathTex` only for equations.

## Text — Roboto Setup

```python
# Single object
label = Text("Convergence", font="Roboto", font_size=36, color=WHITE)

# With weight
bold = Text("Key Insight", font="Roboto", font_size=40, color=YELLOW, weight=BOLD)
light = Text("where n → ∞", font="Roboto", font_size=24, color=GREY_B)

# Multi-line — use \n or VGroup
multiline = Text("Line one\nLine two", font="Roboto", font_size=28, line_spacing=1.4)
```

Font size guidelines for 9:16 vertical (1080×1920):
- Main title: 44–52
- Section label: 32–40
- Body text: 24–30
- Annotation/footnote: 18–22
- **Never below 16** (unreadable on mobile)

## MathTex — Equations

```python
# Basic equation
eq = MathTex(r"e^{i\pi} + 1 = 0", font_size=52, color=BLUE_C)

# Multi-part (each string becomes a submobject)
eq = MathTex(r"f(x)", "=", r"\int_0^x", r"g(t)\,dt", font_size=40)
# Access parts: eq[0] = f(x), eq[1] = =, eq[2] = integral, eq[3] = g(t)dt

# Coloring parts
eq[0].set_color(YELLOW)
eq[2].set_color(BLUE)

# Aligned equations
aligned = MathTex(
    r"x &= r\cos\theta \\",
    r"y &= r\sin\theta",
    font_size=38,
)
```

## TransformMatchingTex — Morphing Equations

The most powerful tool for showing algebraic manipulation:

```python
eq1 = MathTex(r"x^2 + 2x + 1", font_size=46)
eq2 = MathTex(r"(x + 1)^2", font_size=46)

eq1.move_to(ORIGIN)
self.play(Write(eq1), run_time=2.0)
self.wait(1.0)

self.play(TransformMatchingTex(eq1, eq2), rate_func=smooth, run_time=2.5)
self.wait(1.5)
```

For `TransformMatchingTex` to work correctly, shared substrings must match exactly. Label the parts explicitly if matching fails:

```python
eq1 = MathTex(r"{{ x^2 }} + {{ 2x }} + {{ 1 }}", font_size=46)
eq2 = MathTex(r"{{ (x + 1) }}^2", font_size=46)
# Double braces {{ }} create explicit submobject boundaries
```

## Highlighting — Indicate and SurroundingRectangle

```python
# Pulse highlight
self.play(Indicate(eq[2], color=YELLOW, scale_factor=1.3), run_time=1.0)

# Box around a term
box = SurroundingRectangle(eq[2], color=YELLOW, buff=0.15, corner_radius=0.05)
self.play(Create(box), run_time=0.8)
self.wait(1.0)
self.play(FadeOut(box), run_time=0.5)

# Underline
ul = Underline(eq[0], color=YELLOW)
self.play(Create(ul), run_time=0.6)
```

## Positioning — Layout Rules for 9:16

```python
# Vertical stack (most common for 9:16)
title = Text("Bayes' Theorem", font="Roboto", font_size=44, color=WHITE)
eq    = MathTex(r"P(A|B) = \frac{P(B|A)P(A)}{P(B)}", font_size=40)
note  = Text("where all probabilities are non-zero", font="Roboto", font_size=22, color=GREY_B)

# Stack with consistent spacing
group = VGroup(title, eq, note).arrange(DOWN, buff=0.6)
group.move_to(ORIGIN)

# Verify bounds
assert group.get_top()[1] <= 7.0, "Title too high"
assert group.get_bottom()[1] >= -7.0, "Note too low"

# Title pinned to top
title.move_to(UP * 6.8)

# Content in middle
eq.move_to(ORIGIN)

# Annotation below
note.next_to(eq, DOWN, buff=0.5)
```

## Subscripts and Greek Letters (Quick Reference)

```python
MathTex(r"\alpha, \beta, \gamma, \delta, \epsilon, \theta, \lambda, \mu, \pi, \sigma, \omega")
MathTex(r"x_i, x_{n-1}, \sum_{i=0}^{n}, \prod_{k=1}^{K}")
MathTex(r"\frac{d}{dx}, \partial_t, \nabla f, \nabla^2")
MathTex(r"\lim_{x \to \infty}, \int_0^\infty, \oint_C")
MathTex(r"\mathbb{R}, \mathbb{C}, \mathbb{Z}, \mathbb{N}")
MathTex(r"\vec{v}, \hat{n}, \|v\|, \langle u, v \rangle")
```

## Write vs FadeIn for Equations

```python
# Write — draws stroke by stroke, good for "building" a formula
self.play(Write(eq), run_time=2.5, rate_func=linear)

# FadeIn with shift — appears with subtle drift, good for "revealing"
self.play(FadeIn(eq, shift=UP*0.2), rate_func=ease_out_cubic, run_time=1.2)

# FadeIn is faster — use for secondary labels/annotations
# Write is more dramatic — use for the main equation of the scene
```

## Numbered Steps Pattern

```python
steps = [
    (r"1.", "Start with the definition"),
    (r"2.", r"Apply \nabla \cdot \vec{E} = \rho / \varepsilon_0"),
    (r"3.", "Integrate over volume"),
]

step_group = VGroup()
for num, content in steps:
    n = MathTex(num, font_size=30, color=YELLOW)
    if content.startswith("\\") or "{" in content:
        c = MathTex(content, font_size=28, color=WHITE)
    else:
        c = Text(content, font="Roboto", font_size=28, color=WHITE)
    row = VGroup(n, c).arrange(RIGHT, buff=0.3, aligned_edge=UP)
    step_group.add(row)

step_group.arrange(DOWN, buff=0.5, aligned_edge=LEFT)
step_group.move_to(ORIGIN)

# Reveal one at a time
for step in step_group:
    self.play(FadeIn(step, shift=RIGHT*0.2), rate_func=ease_out_cubic, run_time=0.8)
    self.wait(1.2)
```
