"""
Batch Worker Entrypoint for iris-motion - Routes by JOB_TYPE env var.

JOB_TYPE values: prep, render, stitch, postprocess

One container image, four job definitions (see CONTRACT.md):
  prep         2 vCPU / 4096 MiB   topic -> narration + scene -> probe render -> S3
  render       4 vCPU / 8192 MiB   frames [FRAME_FROM, FRAME_TO] -> S3
  stitch       2 vCPU / 8192 MiB   frames -> gates -> encode + mux -> S3
  postprocess  1 vCPU / 2048 MiB   public copy -> caption -> Metricool -> plan.json

Every job exits non-zero on a real failure so Step Functions catches it.
"""

import asyncio
import inspect
import os
import sys
from pathlib import Path

# So `import common` / `import prep` resolve however the container invokes this
# (python app/worker.py, python -m worker, or an absolute path from any cwd).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import logger  # noqa: E402


# Each entry imports its module on call, not at module import time: prep.py is
# owned separately and pulls in the LLM/TTS clients, so an image that ships
# without it -- or with its dependencies broken -- must still run render and
# stitch.
def _prep():
    from prep import run as prep_run
    return prep_run()


def _render():
    from render_shard import run as render_run
    return render_run()


def _stitch():
    from stitch import run as stitch_run
    return stitch_run()


# Returns a COROUTINE, not a result: MetricoolClient is async, so postprocess.run
# is too. main() below awaits whatever comes back, which is why this needs no
# special case.
def _postprocess():
    from postprocess import run as postprocess_run
    return postprocess_run()


# Also a coroutine, and also on its own weekly schedule rather than in the
# per-video state machine: it consumes pieces that are already finished.
def _compile():
    from compile_video import run as compile_run
    return compile_run()


JOB_DISPATCH = {
    "prep": _prep,
    "render": _render,
    "stitch": _stitch,
    "postprocess": _postprocess,
    "compile": _compile,
}


def main():
    job_type = os.environ.get('JOB_TYPE')
    if not job_type:
        logger.error("JOB_TYPE environment variable not set")
        sys.exit(1)

    handler = JOB_DISPATCH.get(job_type)
    if not handler:
        logger.error(f"Unknown JOB_TYPE: {job_type}. Must be one of: {list(JOB_DISPATCH.keys())}")
        sys.exit(1)

    logger.info(f"Starting motion worker: JOB_TYPE={job_type}")
    logger.info(f"VIDEO_ID={os.environ.get('VIDEO_ID', 'N/A')}")

    try:
        result = handler()
        # render and stitch are synchronous; postprocess is a coroutine (the
        # Metricool client is async) and prep is not ours, so if its run() turns
        # out to be async too, await it here rather than exiting 0 on a coroutine
        # that never ran.
        if inspect.isawaitable(result):
            asyncio.run(result)
    except Exception as e:
        logger.exception(f"Worker {job_type} failed: {e}")
        sys.exit(1)

    logger.info(f"Worker {job_type} completed successfully")


if __name__ == "__main__":
    main()
