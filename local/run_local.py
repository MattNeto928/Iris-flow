#!/usr/bin/env python3
"""
Local Runner - Test the serverless video pipeline locally.

This script directly invokes the same code that runs in production,
allowing you to iterate on changes without deploying.

Usage (from inside the container):
    # Full pipeline with a specific topic
    python -m local.run_local --topic "Visualize the Fibonacci sequence" --duration 60

    # Full pipeline with auto-generated topic
    python -m local.run_local

    # Run a specific worker job type
    python -m local.run_local --job-type prep
    python -m local.run_local --job-type visual --segment-index 0

    # Run the full handler (mimics EventBridge trigger)
    python -m local.run_local --handler

Usage (via docker compose):
    docker compose -f docker-compose.local.yml run --rm iris-flow \
        python -m local.run_local --topic "Your topic" --duration 60
"""

import os
import sys
import uuid
import json
import asyncio
import argparse
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("local-runner")


async def run_pipeline(topic: str, duration: int, dry_run: bool):
    """Run the full video generation pipeline with a direct topic."""
    from src.video_pipeline import VideoPipeline

    video_id = f"local_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    logger.info(f"Starting local pipeline run: {video_id}")
    logger.info(f"Topic: {topic}")
    logger.info(f"Target duration: {duration}s")
    logger.info(f"Dry run: {dry_run}")

    pipeline = VideoPipeline()

    result = await pipeline.generate_video(
        prompt=topic,
        topic_id=video_id,
        category="local_test",
        target_duration=duration,
    )

    print("\n" + "=" * 60)
    if result["success"]:
        print(f"✅ Video generated successfully!")
        print(f"   Video URL: {result.get('video_url', 'N/A')}")
        print(f"   Caption:   {result.get('caption', 'N/A')[:100]}...")
    else:
        print(f"❌ Video generation failed: {result.get('error')}")
    print("=" * 60)

    return result


async def run_handler():
    """Run the full handler (mimics what EventBridge triggers)."""
    from src.handler import main
    await main()


def run_worker(job_type: str, video_id: str, segment_index: int | None):
    """Run a specific worker job type (mimics Batch job)."""
    os.environ["JOB_TYPE"] = job_type
    os.environ["VIDEO_ID"] = video_id
    if segment_index is not None:
        os.environ["SEGMENT_INDEX"] = str(segment_index)

    from src.worker import main as worker_main
    worker_main()


def main():
    parser = argparse.ArgumentParser(
        description="Iris Flow - Local Pipeline Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate a video with a specific topic
  python -m local.run_local --topic "Visualize chaos theory" --duration 60

  # Run the full handler (mimics the daily EventBridge trigger)
  python -m local.run_local --handler

  # Run only the prep worker job
  python -m local.run_local --job-type prep --video-id my_test_001

  # Run a visual worker job for segment 2
  python -m local.run_local --job-type visual --video-id my_test_001 --segment-index 2
        """,
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--handler",
        action="store_true",
        help="Run the full handler (mimics EventBridge trigger)",
    )
    mode.add_argument(
        "--job-type",
        choices=["prep", "visual", "transition", "concatenate", "postprocess"],
        help="Run a specific worker job type",
    )

    parser.add_argument(
        "--topic",
        default="Demonstrate the Fibonacci sequence appearing in nature, "
                "from sunflower spirals to galaxy formations",
        help="Topic prompt for video generation (default: Fibonacci)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=int(os.environ.get("TARGET_DURATION", "90")),
        help="Target video duration in seconds (default: 90)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.environ.get("DRY_RUN", "true").lower() == "true",
        help="Skip Metricool scheduling (default: true)",
    )

    # Worker-specific args
    parser.add_argument("--video-id", help="Video ID for worker jobs")
    parser.add_argument("--segment-index", type=int, help="Segment index for visual/transition jobs")

    args = parser.parse_args()

    # Set DRY_RUN in env so downstream code respects it
    os.environ["DRY_RUN"] = "true" if args.dry_run else "false"

    if args.handler:
        logger.info("Running full handler (EventBridge simulation)...")
        asyncio.run(run_handler())

    elif args.job_type:
        video_id = args.video_id or f"local_{uuid.uuid4().hex[:8]}"
        logger.info(f"Running worker job: {args.job_type} (video_id={video_id})")
        run_worker(args.job_type, video_id, args.segment_index)

    else:
        # Default: run the pipeline with a topic
        logger.info("Running pipeline with direct topic...")
        result = asyncio.run(run_pipeline(args.topic, args.duration, args.dry_run))
        sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
