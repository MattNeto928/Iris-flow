from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from claude_client import generate_simulation_script
from simulator import run_simulation_and_compile


app = FastAPI(
    title="Iris PySim Service",
    description="Scientific simulation and visualization",
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
