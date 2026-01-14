import os
import anthropic


# Initialize Anthropic client
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


MANIM_PROMPT = """You are an expert Manim programmer using Manim Community v0.19.0.
Generate a complete, self-contained Manim script that creates the requested animation.

IMPORTANT RULES & BEST PRACTICES:
1. Use `from manim import *` at the top.
2. Use Manim Community syntax (NOT manimlib/3b1b).
3. Create exactly ONE Scene class (or VoiceoverScene if strictly necessary, but prefer Scene).
4. **Camera:** Use `self.camera.frame.animate` (e.g. `self.play(self.camera.frame.animate.scale(0.5))`) NOT `self.camera.animate`.
5. **Grouping:** Use `VGroup` to group mobjects for collective animation.
6. **Positioning:** Use `UP`, `DOWN`, `LEFT`, `RIGHT` constants (e.g. `obj.next_to(other, DOWN)`).
7. **Math:** Use `MathTex` for equations (LaTeX). Use raw strings `r"..."`.
8. **Timing:** Use `self.wait(seconds)` for pacing.
9. **Output:** Output ONLY the Python code, no markdown backticks, no explanations.

**CRITICAL - LaTeX in MathTex:**
- Each substring in MathTex() MUST be valid, compilable LaTeX on its own.
- NEVER split in the middle of a LaTeX command like `\\frac{}{}`, `\\sqrt{}`, `\\sum_{}^{}`.
- BAD: `MathTex(r"\\frac{2", r"GM", r"}{", r"c^2", r"}")` - splits break LaTeX!
- GOOD: `MathTex(r"\\frac{2GM}{c^2}")` - complete expression
- GOOD: `MathTex(r"r_s", r"=", r"\\frac{2GM}{c^2}")` - each part is valid LaTeX
- If you need to animate parts separately, use TransformMatchingTex or ReplacementTransform, not invalid substring splits.

**CRITICAL - DURATION CONTROL:**
- Target duration: {duration} seconds
- Each `self.play()` call typically takes ~1 second by default (or use run_time=X)
- Use `self.wait(X)` to add pauses and reach the target duration
- CALCULATE: If you have N play() calls at ~1s each, add wait() calls totaling ({duration} - N) seconds
- Distribute waits naturally throughout the animation for good pacing
- Add a final `self.wait(1)` at the end to ensure the animation doesn't end abruptly

EXAMPLES:

# Example 1: Basic Shapes & Text (target: 5 seconds)
class ShapeScene(Scene):
    def construct(self):
        circle = Circle(color=BLUE, fill_opacity=0.5)
        square = Square(color=RED)
        square.next_to(circle, RIGHT)
        
        text = Text("Hello Manim", font_size=42)
        text.next_to(circle, UP)
        
        self.play(Create(circle), Create(square))  # ~1s
        self.wait(1)  # +1s = 2s
        self.play(Write(text))  # ~1s = 3s
        self.wait(2)  # +2s = 5s total

# Example 2: Math & Graphing (target: 8 seconds)
class MathScene(Scene):
    def construct(self):
        axes = Axes(x_range=[-3, 3], y_range=[-3, 3])
        graph = axes.plot(lambda x: x**2, color=YELLOW)
        label = axes.get_graph_label(graph, label="x^2")
        
        eq = MathTex(r"f(x) = x^2")
        eq.to_corner(UL)
        
        self.play(Create(axes), run_time=1.5)  # 1.5s
        self.wait(0.5)  # 2s
        self.play(Create(graph), Write(label), run_time=2)  # 4s
        self.wait(1)  # 5s
        self.play(Write(eq))  # 6s
        self.wait(2)  # 8s total

Description of animation to create:
{description}

Target Duration: {duration} seconds (MUST be approximately this length - calculate your waits!)

Generate the complete Manim Python script:
"""


async def generate_manim_script(description: str, duration_seconds: float) -> str:
    """
    Use Claude 4.5 Opus to generate a Manim script based on the description.
    
    Args:
        description: What the animation should show
        duration_seconds: Target duration in seconds
        
    Returns:
        Python code for the Manim script
    """
    # Use replace() instead of format() to avoid conflicts with curly braces in the prompt examples
    prompt = MANIM_PROMPT.replace("{description}", description).replace("{duration}", str(duration_seconds))
    
    message = client.messages.create(
        model="claude-opus-4-5-20251101",
        max_tokens=4096,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    # Extract the code from the response
    response_text = message.content[0].text
    
    # If the response contains markdown code blocks, extract just the code
    if "```python" in response_text:
        start = response_text.find("```python") + 9
        end = response_text.find("```", start)
        response_text = response_text[start:end].strip()
    elif "```" in response_text:
        start = response_text.find("```") + 3
        end = response_text.find("```", start)
        response_text = response_text[start:end].strip()
    
    return response_text
