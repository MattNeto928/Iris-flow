from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from veo_client import generate_animation


app = FastAPI(
    title="Iris Animation Service",
    description="Video generation using Gemini Veo 3.1",
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


class GenerateResponse(BaseModel):
    video_path: str
    duration: float


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "anim_service"}


@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest):
    """
    Generate an animation using Veo 3.1.
    
    The animation will be styled like Veritasium/3Blue1Brown educational content:
    - Clean, modern motion graphics
    - Dark background with vibrant colors
    - Smooth camera movements
    - Professional visual hierarchy
    """
    try:
        video_path = await generate_animation(
            description=request.description,
            duration_seconds=request.duration_seconds,
            metadata=request.metadata
        )
        return GenerateResponse(
            video_path=video_path,
            duration=request.duration_seconds
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
