import os
import re
import uuid
import subprocess
import tempfile
import shutil
import glob


VIDEO_OUTPUT_DIR = "/videos/manim"


async def render_manim_script(script: str) -> str:
    """
    Render a Manim script to video.
    
    Args:
        script: Python code containing a Manim Scene
        
    Returns:
        Path to the rendered video file
    """
    os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
    
    # Create a temporary directory for rendering
    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, "scene.py")
        
        # Write the script to a file
        with open(script_path, "w") as f:
            f.write(script)
        
        print(f"[Manim] Script written to: {script_path}")
        print(f"[Manim] Script content:\n{script[:500]}...")
        
        # Extract the Scene class name from the script
        scene_name = extract_scene_name(script)
        if not scene_name:
            raise ValueError("Could not find Scene class in script")
        
        print(f"[Manim] Detected scene name: {scene_name}")
        
        # Render the scene at 1080p, 30fps
        cmd = [
            "manim", "render",
            "-qh",  # High quality (1080p @ 30fps)
            "--format", "mp4",
            "--media_dir", temp_dir,
            script_path,
            scene_name
        ]
        
        print(f"[Manim] Running: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=temp_dir,
            timeout=300  # 5 minute timeout
        )
        
        print(f"[Manim] Return code: {result.returncode}")
        print(f"[Manim] stdout: {result.stdout[-1000:] if result.stdout else 'empty'}")
        print(f"[Manim] stderr: {result.stderr[-1000:] if result.stderr else 'empty'}")
        
        if result.returncode != 0:
            raise RuntimeError(f"Manim render failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")
        
        # Find all mp4 files in the temp directory (recursive)
        mp4_files = glob.glob(os.path.join(temp_dir, "**", "*.mp4"), recursive=True)
        print(f"[Manim] Found MP4 files: {mp4_files}")
        
        if not mp4_files:
            # List directory structure for debugging
            for root, dirs, files in os.walk(temp_dir):
                print(f"[Manim] Dir: {root}")
                for f in files:
                    print(f"[Manim]   File: {f}")
            raise RuntimeError("No MP4 files found after rendering")
        
        # Use the first MP4 file found
        video_file = mp4_files[0]
        print(f"[Manim] Using video file: {video_file}")
        
        # Copy to output directory with unique name
        output_filename = f"manim_{uuid.uuid4().hex}.mp4"
        output_path = os.path.join(VIDEO_OUTPUT_DIR, output_filename)
        shutil.copy2(video_file, output_path)
        
        print(f"[Manim] Output copied to: {output_path}")
        
        return output_path


def extract_scene_name(script: str) -> str:
    """
    Extract the Scene class name from a Manim script.
    """
    # Look for class definitions that inherit from Scene
    pattern = r"class\s+(\w+)\s*\([^)]*Scene[^)]*\)"
    matches = re.findall(pattern, script)
    
    if matches:
        return matches[0]
    
    # Fallback: look for any class that might be a scene
    pattern = r"class\s+(\w+)\s*\("
    matches = re.findall(pattern, script)
    
    return matches[0] if matches else None
