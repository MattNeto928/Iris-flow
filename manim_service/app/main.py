from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from claude_client import generate_manim_script
from renderer import render_manim_script


app = FastAPI(
    title="Iris Manim Service",
    description="Mathematical animation generation using Manim",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    description: str
    title: Optional[str] = None
    duration_seconds: float = 10.0
    metadata: Optional[dict] = None
    script: Optional[str] = None  # Optional pre-written script to bypass LLM


class GenerateResponse(BaseModel):
    video_path: str
    duration: float
    script: Optional[str] = None


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "manim_service"}


@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest):
    """
    Generate a Manim animation.
    
    1. Use Claude to generate the Manim script
    2. Render the script to video
    3. Return the video path
    """
    try:
        # Step 1: Generate script with Claude (if not provided)
        if request.script:
            script = request.script
            print(f"[Generate] Using provided script (length: {len(script)})")
        else:
            script = await generate_manim_script(
                description=request.description,
                duration_seconds=request.duration_seconds
            )
        
        # Step 2: Render the script
        video_path = await render_manim_script(script)
        
        return GenerateResponse(
            video_path=video_path,
            duration=request.duration_seconds,
            script=script
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/preview-script")
async def preview_script(request: GenerateRequest):
    """
    Generate only the Manim script without rendering.
    Useful for previewing/editing before render.
    """
    try:
        script = await generate_manim_script(
            description=request.description,
            duration_seconds=request.duration_seconds
        )
        return {"script": script}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
