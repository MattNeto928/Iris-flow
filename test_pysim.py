#!/usr/bin/env python3
"""
Standalone test for PySim service - tests script generation and execution.
Run this outside Docker to debug issues.

Usage: python test_pysim.py
"""
import os
import sys
import subprocess
import tempfile
import shutil

# Add pysim_service to path
sys.path.insert(0, os.path.dirname(__file__))


def test_simple_simulation():
    """Test a simple, known-working simulation script."""
    
    simple_script = '''
import sys
import os
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import numpy as np

def main(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    
    TOTAL_FRAMES = 90  # 3 seconds at 30fps
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    for frame_num in range(TOTAL_FRAMES):
        ax.clear()
        
        # Simple animated sine wave
        x = np.linspace(0, 4 * np.pi, 200)
        phase = frame_num * 0.1
        y = np.sin(x + phase)
        
        ax.plot(x, y, 'b-', linewidth=2)
        ax.set_xlim(0, 4 * np.pi)
        ax.set_ylim(-1.5, 1.5)
        ax.set_title(f'Simple Sine Wave (Frame {frame_num + 1}/{TOTAL_FRAMES})')
        ax.grid(True)
        
        plt.savefig(os.path.join(output_dir, f"frame_{frame_num:05d}.png"), dpi=100)
    
    plt.close()
    print(f"Generated {TOTAL_FRAMES} frames")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <output_dir>")
        sys.exit(1)
    main(sys.argv[1])
'''
    
    print("=" * 60)
    print("TEST 1: Simple known-working simulation")
    print("=" * 60)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, "test_sim.py")
        frames_dir = os.path.join(temp_dir, "frames")
        
        with open(script_path, "w") as f:
            f.write(simple_script)
        
        print(f"Running script at: {script_path}")
        print(f"Frames output to: {frames_dir}")
        
        try:
            result = subprocess.run(
                ["python", script_path, frames_dir],
                capture_output=True,
                text=True,
                timeout=60  # 1 minute timeout
            )
            
            print(f"\nReturn code: {result.returncode}")
            print(f"stdout: {result.stdout}")
            if result.stderr:
                print(f"stderr: {result.stderr}")
            
            # Check frames
            if os.path.exists(frames_dir):
                frames = [f for f in os.listdir(frames_dir) if f.endswith('.png')]
                print(f"\nGenerated {len(frames)} frames")
                
                if frames:
                    # Compile to video
                    output_video = os.path.join(temp_dir, "test_output.mp4")
                    ffmpeg_result = subprocess.run([
                        "ffmpeg", "-y",
                        "-framerate", "30",
                        "-i", os.path.join(frames_dir, "frame_%05d.png"),
                        "-c:v", "libx264",
                        "-pix_fmt", "yuv420p",
                        "-crf", "23",
                        output_video
                    ], capture_output=True, text=True)
                    
                    if ffmpeg_result.returncode == 0:
                        print(f"\n✅ Video compiled successfully!")
                        # Copy to current dir for viewing
                        shutil.copy(output_video, "./test_pysim_output.mp4")
                        print(f"Output saved to: ./test_pysim_output.mp4")
                    else:
                        print(f"❌ FFmpeg failed: {ffmpeg_result.stderr}")
            else:
                print("❌ No frames directory created!")
                
        except subprocess.TimeoutExpired:
            print("❌ Script timed out!")
        except Exception as e:
            print(f"❌ Error: {e}")


def test_claude_generated_script():
    """Test script generation via Claude (requires ANTHROPIC_API_KEY)."""
    
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\n" + "=" * 60)
        print("TEST 2: Claude script generation (SKIPPED)")
        print("Set ANTHROPIC_API_KEY to test")
        print("=" * 60)
        return
    
    print("\n" + "=" * 60)
    print("TEST 2: Claude script generation")
    print("=" * 60)
    
    try:
        # Import from pysim_service
        from pysim_service.app.claude_client import generate_simulation_script
        import asyncio
        
        description = "A simple bouncing ball animation"
        duration = 3.0  # 3 seconds
        
        print(f"Description: {description}")
        print(f"Duration: {duration}s")
        print("\nGenerating script...")
        
        script = asyncio.run(generate_simulation_script(description, duration))
        
        print("\n--- Generated Script ---")
        print(script[:2000] if len(script) > 2000 else script)
        print("--- End Script ---")
        
        # Save script for inspection
        with open("./test_generated_script.py", "w") as f:
            f.write(script)
        print("\nScript saved to: ./test_generated_script.py")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_simple_simulation()
    test_claude_generated_script()
