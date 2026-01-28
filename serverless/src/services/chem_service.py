"""
Chem Service - Molecular structure visualization using RDKit.

Uses Claude to generate RDKit scripts for 2D molecular structures,
reaction mechanisms, and chemical concept visualization.
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
FRAMES_DIR = OUTPUT_DIR / "frames"
VIDEOS_DIR = OUTPUT_DIR / "videos"


CHEM_PROMPT = """You are an expert Python programmer specializing in chemistry visualization using RDKit.
Generate a complete, self-contained Python script that creates molecular structure animations.

CRITICAL DURATION REQUIREMENTS:
- Target video duration: {duration} seconds
- Frame rate: 30 FPS
- EXACT frame count required: {frames} frames
- You MUST generate EXACTLY {frames} PNG files, no more, no less
- Frame naming: frame_00000.png, frame_00001.png, etc. (5-digit zero-padded)

VIDEO FORMAT: VERTICAL (9:16 for Shorts/Reels/TikTok)
- Output resolution: 1080x1920 pixels (portrait)
- Use image size (1080, 1920) in RDKit drawing options

**RDKIT BEST PRACTICES:**
```python
from rdkit import Chem
from rdkit.Chem import Draw, AllChem
from rdkit.Chem.Draw import rdMolDraw2D
from PIL import Image
import io

# Create molecule from SMILES
mol = Chem.MolFromSmiles('CCO')  # Ethanol

# Generate 2D coordinates
AllChem.Compute2DCoords(mol)

# Draw to image
drawer = rdMolDraw2D.MolDraw2DCairo(1080, 1920)
drawer.drawOptions().setBackgroundColour((0.1, 0.1, 0.18, 1))  # Dark background
drawer.DrawMolecule(mol)
drawer.FinishDrawing()

# Save PNG
png_data = drawer.GetDrawingText()
with open('molecule.png', 'wb') as f:
    f.write(png_data)
```

**COMMON SMILES STRINGS:**
- Water: 'O'
- Ethanol: 'CCO'
- Caffeine: 'CN1C=NC2=C1C(=O)N(C(=O)N2C)C'
- Aspirin: 'CC(=O)OC1=CC=CC=C1C(=O)O'
- Benzene: 'c1ccccc1'
- Glucose: 'OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O'
- ATP: 'c1nc(c2c(n1)n(cn2)[C@H]3[C@@H]([C@@H]([C@H](O3)COP(=O)(O)OP(=O)(O)OP(=O)(O)O)O)O)N'
- DNA base (Adenine): 'Nc1ncnc2[nH]cnc12'
- Dopamine: 'NCCc1ccc(O)c(O)c1'
- Serotonin: 'NCCc1c[nH]c2ccc(O)cc12'

**ANIMATION IDEAS:**

1. **Building a molecule atom by atom:**
```python
full_smiles = 'CCO'  # Ethanol
for frame_num in range(TOTAL_FRAMES):
    t = frame_num / TOTAL_FRAMES
    # Reveal atoms progressively (simplified: fade in whole molecule)
```

2. **Highlighting functional groups:**
```python
from rdkit.Chem import AllChem

mol = Chem.MolFromSmiles('CCO')
# Highlight the OH group
highlightAtoms = [1, 2]  # Indices of O and H
drawer.DrawMolecule(mol, highlightAtoms=highlightAtoms)
```

3. **Reaction animation (reactants → products):**
Show transition between two molecules.

4. **3D rotation (using coordinates):**
```python
from rdkit.Chem import AllChem
AllChem.EmbedMolecule(mol, AllChem.ETKDG())  # 3D coordinates
conf = mol.GetConformer()
# Rotate and project to 2D for each frame
```

**DRAWING OPTIONS:**
```python
drawer = rdMolDraw2D.MolDraw2DCairo(1080, 1920)
opts = drawer.drawOptions()
opts.setBackgroundColour((0.1, 0.1, 0.18, 1))  # Dark blue
opts.bondLineWidth = 3
opts.atomLabelFontSize = 24
opts.addAtomIndices = False
opts.addStereoAnnotation = True
```

**STYLE GUIDE:**
- Dark background: RGB (0.1, 0.1, 0.18) or hex #1a1a2e
- Bright atoms: use default RDKit colors (C=gray, O=red, N=blue)
- Large, clear bonds
- Add labels and annotations

**REQUIRED TEMPLATE:**
```python
import sys
import os
from rdkit import Chem
from rdkit.Chem import AllChem, Draw
from rdkit.Chem.Draw import rdMolDraw2D
import numpy as np

def main(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    TOTAL_FRAMES = {frames}
    
    # Create molecule
    smiles = 'CCO'  # Example: ethanol
    mol = Chem.MolFromSmiles(smiles)
    AllChem.Compute2DCoords(mol)
    
    for frame_num in range(TOTAL_FRAMES):
        t = frame_num / TOTAL_FRAMES
        
        # Create drawer
        drawer = rdMolDraw2D.MolDraw2DCairo(1080, 1920)
        opts = drawer.drawOptions()
        opts.setBackgroundColour((0.1, 0.1, 0.18, 1))
        opts.bondLineWidth = 4
        
        # Animation logic (e.g., highlighting, opacity)
        # ...
        
        drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        
        # Save frame
        png_data = drawer.GetDrawingText()
        with open(os.path.join(output_dir, f"frame_{{frame_num:05d}}.png"), 'wb') as f:
            f.write(png_data)
    
    print(f"Generated {{TOTAL_FRAMES}} frames")

if __name__ == "__main__":
    main(sys.argv[1])
```

Description: {description}

GENERATE ONLY PYTHON CODE (no markdown, no explanation):
"""


class ChemService:
    def __init__(self):
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    
    async def generate(self, description: str, duration: float, previous_error: str = None) -> str:
        """
        Generate a chemistry visualization video from description.
        
        1. Generate RDKit script with Claude
        2. Run script to generate frames
        3. Compile frames to video
        
        Returns path to generated video.
        """
        video_id = str(uuid.uuid4())[:8]
        fps = 30
        frames = int(duration * fps)
        
        logger.info(f"[Chem] Generating {frames} frames for {duration}s video")
        if previous_error:
            logger.info(f"[Chem] Retrying with error context: {previous_error}")
        
        # Step 1: Generate script
        script = await self._generate_script(description, duration, frames, previous_error)
        logger.info(f"[Chem] Script generated ({len(script)} chars)")
        
        # Step 2: Run visualization
        frames_path = FRAMES_DIR / f"chem_{video_id}"
        frames_path.mkdir(exist_ok=True)
        
        await self._run_visualization(script, str(frames_path))
        
        # Step 3: Compile to video
        video_path = VIDEOS_DIR / f"chem_{video_id}.mp4"
        await self._compile_video(str(frames_path), str(video_path), fps)
        
        return str(video_path)
    
    async def _generate_script(self, description: str, duration: float, frames: int, previous_error: str = None) -> str:
        """Generate chem script using Claude."""
        
        error_context = ""
        if previous_error:
            error_context = f"""
*** PREVIOUS ATTEMPT FAILED WITH ERROR: ***
{previous_error}
*** YOU MUST FIX THIS ERROR IN THE NEW SCRIPT ***
"""
        
        final_prompt = CHEM_PROMPT.replace("{description}", description).replace("{duration}", str(duration)).replace("{frames}", str(frames)) + error_context
        
        message = client.messages.create(
            model="claude-opus-4-5-20251101",
            max_tokens=4096,
            messages=[{"role": "user", "content": final_prompt}]
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
    
    async def _run_visualization(self, script: str, output_dir: str):
        """Run the chem visualization script."""
        script_path = Path(output_dir) / "visualization.py"
        
        with open(script_path, "w") as f:
            f.write(script)
        
        logger.info(f"[Chem] Running visualization...")
        
        process = await asyncio.create_subprocess_exec(
            "python", str(script_path), output_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Chem visualization failed: {error_msg}")
        
        logger.info(f"[Chem] Visualization complete")
    
    async def _compile_video(self, frames_dir: str, output_path: str, fps: int = 30):
        """Compile frames to video using FFmpeg."""
        from pathlib import Path
        frames_path = Path(frames_dir)
        frame_files = sorted(frames_path.glob("frame_*.png"))
        
        if not frame_files:
            raise RuntimeError(f"No frames found in {frames_dir}")
        
        logger.info(f"[Chem] Compiling {len(frame_files)} frames to video")
        
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", f"{frames_dir}/frame_%05d.png",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "23",
            output_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            stderr_text = stderr.decode() if stderr else "Unknown error"
            logger.error(f"[Chem] FFmpeg failed: {stderr_text}")
            raise RuntimeError(f"FFmpeg compilation failed: {stderr_text}")
        
        logger.info(f"[Chem] Video compiled: {output_path}")
