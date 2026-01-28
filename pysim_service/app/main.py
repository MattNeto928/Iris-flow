from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from claude_client import generate_simulation_script
from simulator import run_simulation_and_compile

# Import new services
from simpy_service import SimpyService
from plotly_service import PlotlyService
from networkx_service import NetworkxService
from audio_service import AudioService
from stats_service import StatsService
from fractal_service import FractalService
from geo_service import GeoService
from chem_service import ChemService
from astro_service import AstroService


app = FastAPI(
    title="Iris PySim Service",
    description="Scientific simulation and visualization",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize new services
simpy_service = SimpyService()
plotly_service = PlotlyService()
networkx_service = NetworkxService()
audio_service = AudioService()
stats_service = StatsService()
fractal_service = FractalService()
geo_service = GeoService()
chem_service = ChemService()
astro_service = AstroService()


class GenerateRequest(BaseModel):
    description: str
    title: Optional[str] = None
    duration_seconds: float = 10.0
    metadata: Optional[dict] = None
    simulation_type: Optional[str] = None
    script: Optional[str] = None  # Allow passing pre-generated script


class GenerateResponse(BaseModel):
    video_path: str
    duration: float
    script: Optional[str] = None


@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest):
    """
    Generate a Python simulation video.
    
    If 'script' is provided in request, skips generation and runs it directly.
    Otherwise:
    1. Use Claude to generate the simulation script
    2. Run the simulation to generate frames
    3. Compile frames to video
    4. Return the video path
    """
    try:
        # Step 1: Get script (either provided or generated)
        if request.script:
            script = request.script
            print("[PySim] Using provided script, skipping generation")
        else:
            # Enhance description with simulation type if provided
            description = request.description
            if request.simulation_type:
                description = f"[{request.simulation_type.upper()} simulation] {description}"
            
            # Generate script with Claude
            script = await generate_simulation_script(
                description=description,
                duration_seconds=request.duration_seconds
            )
        
        # Step 2 & 3: Run simulation and compile video
        video_path = await run_simulation_and_compile(
            script=script,
            duration_seconds=request.duration_seconds
        )
        
        return GenerateResponse(
            video_path=video_path,
            duration=request.duration_seconds,
            script=script
        )
    except Exception as e:
        import traceback
        error_msg = str(e)
        print(f"[PySim] ERROR: {error_msg}")
        print(f"[PySim] Traceback:\n{traceback.format_exc()}")
        
        # If we have a script, return it with the error so it can be debugged
        if 'script' in locals() and script:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=422,  # Unprocessable Entity (valid request, but simulation failed)
                content={
                    "detail": error_msg,
                    "script": script,
                    "error_type": "simulation_error"
                }
            )
            
        raise HTTPException(status_code=500, detail=error_msg)


@app.post("/preview-script")
async def preview_script(request: GenerateRequest):
    """
    Generate only the simulation script without running.
    Useful for previewing/editing before execution.
    """
    try:
        description = request.description
        if request.simulation_type:
            description = f"[{request.simulation_type.upper()} simulation] {description}"
            
        script = await generate_simulation_script(
            description=description,
            duration_seconds=request.duration_seconds
        )
        return {"script": script}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== NEW SERVICE ENDPOINTS ==========

@app.post("/generate/simpy", response_model=GenerateResponse)
async def generate_simpy(request: GenerateRequest):
    """Generate discrete event simulation visualization."""
    try:
        video_path = await simpy_service.generate(
            description=request.description,
            duration=request.duration_seconds
        )
        return GenerateResponse(video_path=video_path, duration=request.duration_seconds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate/plotly", response_model=GenerateResponse)
async def generate_plotly(request: GenerateRequest):
    """Generate 3D plot visualization."""
    try:
        video_path = await plotly_service.generate(
            description=request.description,
            duration=request.duration_seconds
        )
        return GenerateResponse(video_path=video_path, duration=request.duration_seconds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate/networkx", response_model=GenerateResponse)
async def generate_networkx(request: GenerateRequest):
    """Generate graph algorithm visualization."""
    try:
        video_path = await networkx_service.generate(
            description=request.description,
            duration=request.duration_seconds
        )
        return GenerateResponse(video_path=video_path, duration=request.duration_seconds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate/audio", response_model=GenerateResponse)
async def generate_audio(request: GenerateRequest):
    """Generate audio/signal visualization."""
    try:
        video_path = await audio_service.generate(
            description=request.description,
            duration=request.duration_seconds
        )
        return GenerateResponse(video_path=video_path, duration=request.duration_seconds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate/stats", response_model=GenerateResponse)
async def generate_stats(request: GenerateRequest):
    """Generate statistical visualization."""
    try:
        video_path = await stats_service.generate(
            description=request.description,
            duration=request.duration_seconds
        )
        return GenerateResponse(video_path=video_path, duration=request.duration_seconds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate/fractal", response_model=GenerateResponse)
async def generate_fractal(request: GenerateRequest):
    """Generate fractal/cellular automata visualization."""
    try:
        video_path = await fractal_service.generate(
            description=request.description,
            duration=request.duration_seconds
        )
        return GenerateResponse(video_path=video_path, duration=request.duration_seconds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate/geo", response_model=GenerateResponse)
async def generate_geo(request: GenerateRequest):
    """Generate geographic visualization."""
    try:
        video_path = await geo_service.generate(
            description=request.description,
            duration=request.duration_seconds
        )
        return GenerateResponse(video_path=video_path, duration=request.duration_seconds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate/chem", response_model=GenerateResponse)
async def generate_chem(request: GenerateRequest):
    """Generate molecular structure visualization."""
    try:
        video_path = await chem_service.generate(
            description=request.description,
            duration=request.duration_seconds
        )
        return GenerateResponse(video_path=video_path, duration=request.duration_seconds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate/astro", response_model=GenerateResponse)
async def generate_astro(request: GenerateRequest):
    """Generate astronomy visualization."""
    try:
        video_path = await astro_service.generate(
            description=request.description,
            duration=request.duration_seconds
        )
        return GenerateResponse(video_path=video_path, duration=request.duration_seconds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

