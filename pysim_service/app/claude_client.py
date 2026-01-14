import os
import anthropic


# Initialize Anthropic client
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


PYSIM_PROMPT = """You are an expert Python scientific computing programmer. Generate a complete, self-contained Python script that creates a simulation and outputs frames for video creation.

CRITICAL DURATION REQUIREMENTS:
- Target video duration: {duration} seconds
- Frame rate: 30 FPS
- EXACT frame count required: {frames} frames
- You MUST generate EXACTLY {frames} PNG files, no more, no less
- Frame naming: frame_00000.png, frame_00001.png, etc. (5-digit zero-padded)

**CRITICAL - MUST FOLLOW THESE RULES:**
1. **USE MATPLOTLIB ONLY** - Do NOT use pygame, tkinter, or any GUI libraries
2. **SET BACKEND FIRST** - Start with: `import matplotlib; matplotlib.use('Agg')`
3. **NO EVENT LOOPS** - No while True, no pygame.event loop, no blocking calls
4. **FINITE LOOP ONLY** - Use exactly: `for frame_num in range({frames}):`
5. **NO USER INPUT** - Script must run completely autonomously
6. Output ONLY the Python code - no explanations, no markdown backticks

**AVOID THESE COMMON ERRORS:**
- NO plt.colorbar() - causes layout errors
- NO plt.tight_layout() inside the loop - causes issues
- NO complex gridspec - keep it simple with single ax
- Use ax.clear() at start of each frame
- Use fixed axis limits (ax.set_xlim, ax.set_ylim)

**PARAMETER VALIDATION RULES (CRITICAL - VIOLATIONS CAUSE CRASHES):**
- ALWAYS clamp alpha values to [0, 1] range: `alpha = np.clip(alpha, 0, 1)`
- ALWAYS clamp any normalized values (0-1 range) using np.clip BEFORE passing to matplotlib
- ALWAYS ensure marker sizes are positive: `s = np.maximum(s, 1)` for arrays or `s = max(1, s)` for scalars
- NEVER compute values that could go negative for positive-only params (alpha, size, linewidth)
- When using mathematical functions that could produce out-of-range values, ALWAYS wrap with np.clip
- Example of safe alpha: `alpha = np.clip(0.5 + 0.5 * np.sin(t), 0, 1)`

**PERFORMANCE RULES (PREVENT TIMEOUTS - CRITICAL):**
- **VECTORIZATION IS MANDATORY**: NEVER loop over particles/agents to draw them individually.
    - BAD: `for p in particles: ax.scatter(p.x, p.y, ...)` (This causes timeouts!)
    - GOOD: `ax.scatter(particles_x, particles_y, s=sizes, c=colors, ...)` (One call per frame)
- Keep particle/agent counts reasonable (< 500 per frame)
- Avoid expensive operations (scipy.optimize, heavy matrix ops) inside frame loop
- Pre-compute static data BEFORE the frame loop
- If adding glow/effects, use layers (e.g. 3 scatter calls total), DO NOT iterate points.

REQUIRED TEMPLATE (USE THIS EXACT STRUCTURE):
```
import sys
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

def main(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    TOTAL_FRAMES = {frames}
    
    fig, ax = plt.subplots(figsize=(10, 8))
    
    for frame_num in range(TOTAL_FRAMES):
        ax.clear()
        
        # === YOUR SIMULATION CODE HERE ===
        # Example: animated scatter
        t = frame_num / TOTAL_FRAMES
        x = np.sin(t * 2 * np.pi) 
        y = np.cos(t * 2 * np.pi)
        ax.scatter(x, y, s=100, c='blue')
        # === END SIMULATION CODE ===
        
        ax.set_xlim(-2, 2)
        ax.set_ylim(-2, 2)
        ax.set_title(f'Frame {{frame_num + 1}}/{{TOTAL_FRAMES}}')
        
        plt.savefig(os.path.join(output_dir, f"frame_{{frame_num:05d}}.png"), dpi=100)
    
    plt.close()
    print(f"Generated {{TOTAL_FRAMES}} frames")

if __name__ == "__main__":
    main(sys.argv[1])
```

Available: numpy, scipy, matplotlib (NO colorbar, NO tight_layout)

Description: {description}

GENERATE ONLY PYTHON CODE (no markdown, no explanation):
"""


async def generate_simulation_script(description: str, duration_seconds: float) -> str:
    """
    Use Claude 4.5 Opus to generate a Python simulation script.
    
    Args:
        description: What the simulation should show
        duration_seconds: Target duration in seconds
        
    Returns:
        Python code for the simulation script
    """
    fps = 30
    frames = int(duration_seconds * fps)
    
    prompt = PYSIM_PROMPT.format(
        description=description,
        duration=duration_seconds,
        frames=frames
    )
    
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
