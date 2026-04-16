"""
Remotion Service - React-based video generation.

Uses Claude to generate Remotion React components, creates a temporary Remotion project,
and compiles it into an MP4.
"""

import os
import uuid
import logging
import asyncio
from pathlib import Path
import anthropic
import shutil

logger = logging.getLogger(__name__)

# Initialize Anthropic client
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Output directories
OUTPUT_DIR = Path("/app/output")
REMOTION_DIR = OUTPUT_DIR / "remotion_projects"
VIDEOS_DIR = OUTPUT_DIR / "videos"

# Pre-cached base react template
BASE_APP_DIR = REMOTION_DIR / "base_app"


REMOTION_PROMPT = """{skill_content}"""


class RemotionService:
    def __init__(self):
        REMOTION_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    async def _ensure_base_app(self):
        """Scaffold a fresh Remotion blank app if it doesn't exist yet."""
        if not BASE_APP_DIR.exists():
            logger.info("[Remotion] Scaffolding base Remotion application... (this takes a moment)")
            # Create video using the blank template interactively via pexpect
            import pexpect
            # Need to install pexpect if not present, but let's assume it's added to docker or we can use a simpler approach.
            cmd = f"git config --global user.name 'Remotion' && git config --global user.email 'remotion@test.com' && cd {REMOTION_DIR} && npx create-video@latest {BASE_APP_DIR.name} --blank -y"
            try:
                child = pexpect.spawn("/bin/bash", ["-c", cmd], encoding='utf-8', timeout=300)
                # Wait for tailwind prompt
                child.expect(r"Add TailwindCSS\?", timeout=120)
                child.sendline("N")
                # Wait for next prompt (if any) or EOF
                try:
                    child.expect(r"Add agent skills\?", timeout=10)
                    child.sendline("N")
                except pexpect.TIMEOUT:
                    pass
                child.expect(pexpect.EOF)
                logger.info(f"[Remotion] Scaffolding pexpect output: {child.before}")
                
                # Check if package.json exists to verify success
                if not (BASE_APP_DIR / "package.json").exists():
                    raise RuntimeError("Scaffolding failed, package.json missing.")
                    
                # Run npm install + 3D deps
                npm_cmd = f"cd {BASE_APP_DIR} && npm install && npm install @remotion/three three @react-three/fiber @react-three/drei && npm install --save-dev @types/three"
                npm_proc = await asyncio.create_subprocess_shell(
                    npm_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                await npm_proc.communicate()
            except Exception as e:
                logger.error(f"Pexpect scaffolding failed: {str(e)}")
                raise RuntimeError(f"Remotion scaffold failed via pexpect: {str(e)}")
                
            # Overwrite the Root.tsx to dynamically load Scene.tsx as MyComp
            root_code = """import {Composition} from 'remotion';
import Scene from './Scene';

export const Root: React.FC = () => {
    // 30fps * requested duration or default to 8s
    const durFrames = parseInt(process.env.REMOTION_DURATION || "240");
    return (
        <>
            <Composition
                id="MyComp"
                component={Scene}
                durationInFrames={durFrames}
                width={1080}
                height={1920}
                fps={30}
            />
        </>
    );
};
"""
            root_path = BASE_APP_DIR / "src" / "Root.tsx"
            with open(root_path, "w") as f:
                f.write(root_code)

            logger.info("[Remotion] Base app scaffolded successfully.")

    async def generate(self, description: str, duration: float, metadata: dict = None, previous_error: str = None) -> str:
        """
        Generate a Remotion video from description.
        """
        video_id = str(uuid.uuid4())[:8]
        logger.info(f"[Remotion] Starting project generation for {video_id}")

        await self._ensure_base_app()

        # Load skill prompt
        skill_path = Path("/app/src/../iris-flow-plugin/skills/remotion-segments/SKILL.md")
        if skill_path.exists():
            with open(skill_path, "r") as f:
                skill_content = f.read()
            # Strip YAML frontmatter
            if skill_content.startswith("---"):
                parts = skill_content.split("---", 2)
                if len(parts) >= 3:
                    skill_content = parts[2].strip()
        else:
            raise FileNotFoundError("Remotion SKILL.md not found.")

        prompt = REMOTION_PROMPT.format(skill_content=skill_content).replace("{description}", description).replace("{duration}", str(duration))
        
        self._last_prompt = prompt
        self._last_model = 'claude-opus-4-7'

        logger.info(f"[Remotion] Requesting TSX from Claude...")
        message = client.messages.create(
            model=self._last_model,
            # TSX/JSX is verbose; 8k was hitting the ceiling on moderately complex
            # scenes (causing "Expected identifier but found end of file" esbuild
            # errors at ~line 815). 16k matches the other code-gen services.
            max_tokens=16000,
            messages=[{"role": "user", "content": prompt}]
        )

        # If Claude ran out of tokens mid-file the TSX is invalid — fail fast
        # with a clean error so the worker retry loop can feed this back to
        # Claude as `previous_error`, giving it signal to be more concise.
        if message.stop_reason == "max_tokens":
            raise RuntimeError(
                "Remotion TSX generation was truncated (hit max_tokens). "
                "The scene description may be too complex — simplify the "
                "animation or break it into multiple segments."
            )

        code = message.content[0].text
        if "```tsx" in code:
            code = code.split("```tsx")[1].split("```")[0].strip()
        elif "```typescript" in code:
            code = code.split("```typescript")[1].split("```")[0].strip()
        elif "```" in code:
            code = code.split("```")[1].split("```")[0].strip()

        # Inject the generated scene directly into the existing base app
        scene_name = f"Scene_{video_id}"
        root_name = f"Root_{video_id}"
        index_name = f"index_{video_id}"

        scene_path = BASE_APP_DIR / "src" / f"{scene_name}.tsx"
        root_path = BASE_APP_DIR / "src" / f"{root_name}.tsx"
        index_path = BASE_APP_DIR / "src" / f"{index_name}.ts"

        with open(scene_path, "w") as f:
            f.write(code)

        root_code = f"""import {{Composition}} from 'remotion';
import Scene from './{scene_name}';

export const Root: React.FC = () => {{
    const durFrames = parseInt(process.env.REMOTION_DURATION || "240");
    return (
        <>
            <Composition
                id="MyComp"
                component={{Scene}}
                durationInFrames={{durFrames}}
                width={{1080}}
                height={{1920}}
                fps={{30}}
            />
        </>
    );
}};
"""
        with open(root_path, "w") as f:
            f.write(root_code)

        index_code = f"""import {{registerRoot}} from 'remotion';
import {{Root}} from './{root_name}';
registerRoot(Root);
"""
        with open(index_path, "w") as f:
            f.write(index_code)

        logger.info(f"[Remotion] Rendering MP4 via Node.js...")
        output_mp4 = VIDEOS_DIR / f"remotion_{video_id}.mp4"
        
        # Calculate frames
        dur_frames = int(duration * 30)

        env = os.environ.copy()
        env["REMOTION_DURATION"] = str(dur_frames)
        
        # Use local binary directly to avoid npx "could not determine executable" errors
        cmd = f"node_modules/.bin/remotion render src/{index_name}.ts MyComp {output_mp4}"

        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(BASE_APP_DIR),
            env=env
        )

        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.error(f"[Remotion] Render failed: {stderr.decode()}")
            raise RuntimeError(f"Remotion compilation failed:\n{stderr.decode()}")
            
        logger.info(f"[Remotion] Render complete: {output_mp4}")
        
        # Clean up temp unique files
        scene_path.unlink(missing_ok=True)
        root_path.unlink(missing_ok=True)
        index_path.unlink(missing_ok=True)

        return str(output_mp4)
