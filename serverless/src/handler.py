"""
Iris Flow Serverless - Main Handler

Triggered by EventBridge 4x daily (9am, 12pm, 3pm, 7pm EST).

Pipeline:
1. Check SQS queue for user-provided topic; if empty, generate one
2. Generate video segments using Gemini
3. Process each segment (TTS + visual generation)
4. Concatenate final video
5. Upload to S3
6. Schedule to Metricool for social media posting
"""

import os
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:
    class ZoneInfo:
        def __init__(self, key): pass
        def utcoffset(self, dt): return timedelta(hours=-5)
        def dst(self, dt): return timedelta(0)
        def tzname(self, dt): return "EST"

from src.topic_manager import TopicManager
from src.video_pipeline import VideoPipeline
from src.metricool_client import MetricoolClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Version
VERSION = "v1.0.0-iris-flow"


async def main():
    """
    Main entry point for the video generation pipeline.
    
    At 6am EST daily:
    1. Generate random number 2-5 for how many posts today
    2. Generate random schedule times between 8am-9pm EST
    3. For each post: generate video and schedule it
    """
    import random
    
    logger.info("=" * 60)
    logger.info(f"Starting Iris Flow Video Pipeline - Version: {VERSION}")
    logger.info("=" * 60)
    
    try:
        # Initialize components
        topic_manager = TopicManager()
        video_pipeline = VideoPipeline()
        metricool_client = MetricoolClient()
        
        # Get NY timezone
        try:
            ny_tz = ZoneInfo("America/New_York")
        except Exception:
            class ZoneInfoMock:
                def utcoffset(self, dt): return timedelta(hours=-5)
                def dst(self, dt): return timedelta(0)
                def tzname(self, dt): return "EST"
            ny_tz = ZoneInfoMock()
        
        # Get current time in NY
        try:
            now_ny = datetime.now(ny_tz)
        except Exception:
            now_ny = datetime.now(timezone.utc) - timedelta(hours=5)
        
        # Determine scheduling date
        # If invoked after 9pm, schedule for tomorrow (since 8am-9pm window is closed)
        if now_ny.hour >= 21:  # 9pm or later
            schedule_date = (now_ny + timedelta(days=1)).date()
            logger.info(f"⏰ Invoked after 9pm - scheduling for tomorrow ({schedule_date})")
        else:
            schedule_date = now_ny.date()
        
        # Step 1: Determine how many posts for today (2-5)
        if os.environ.get('NUM_POSTS'):
            num_posts = int(os.environ['NUM_POSTS'])
            logger.info(f"📊 Using override: Generating {num_posts} videos")
        else:
            num_posts = random.randint(2, 5)
            logger.info(f"📊 Generating {num_posts} videos for {schedule_date}")
        
        # Step 2: Generate random schedule times between 8am-9pm EST
        schedule_times = _generate_random_schedule_times(schedule_date, num_posts, ny_tz)
        logger.info(f"📅 Schedule times: {[t.strftime('%I:%M %p') for t in schedule_times]}")
        
        # Step 3: Generate and schedule each video
        successful = 0
        failed = 0
        
        for i, schedule_time in enumerate(schedule_times, 1):
            logger.info("=" * 60)
            logger.info(f"🎬 Video {i}/{num_posts} - Scheduled for {schedule_time.strftime('%I:%M %p EST')}")
            logger.info("=" * 60)
            
            try:
                # Get topic
                logger.info(f"[{i}/{num_posts}] Step 1: Getting topic...")
                topic = await topic_manager.get_topic()
                logger.info(f"[{i}/{num_posts}] Topic: {topic['prompt'][:80]}...")
                
                # Generate video
                logger.info(f"[{i}/{num_posts}] Step 2-4: Running video pipeline...")
                result = await video_pipeline.generate_video(
                    prompt=topic['prompt'],
                    topic_id=topic['topic_id'],
                    category=topic.get('category', 'general')
                )
                
                if not result['success']:
                    logger.error(f"[{i}/{num_posts}] Video generation failed: {result.get('error')}")
                    failed += 1
                    continue
                
                logger.info(f"[{i}/{num_posts}] Video generated: {result['video_url']}")
                
                # Schedule to Metricool (skip if DRY_RUN mode)
                dry_run = os.environ.get('DRY_RUN', 'false').lower() == 'true'
                
                if dry_run:
                    logger.info(f"[{i}/{num_posts}] 🧪 DRY RUN - Skipping Metricool scheduling")
                    logger.info(f"[{i}/{num_posts}] Would have scheduled for: {schedule_time.strftime('%I:%M %p EST')}")
                else:
                    logger.info(f"[{i}/{num_posts}] Step 5: Scheduling to Metricool for {schedule_time}...")
                    schedule_result = await metricool_client.schedule_post(
                        video_url=result['video_url'],
                        caption=result['caption'],
                        schedule_time=schedule_time,
                        youtube_title=result.get('youtube_title', topic['prompt'][:97] + '...')
                    )
                    
                    if schedule_result['success']:
                        logger.info(f"[{i}/{num_posts}] ✅ Scheduled successfully! Post ID: {schedule_result['post_id']}")
                        for provider in schedule_result.get('providers', []):\
                            logger.info(f"  - {provider['network']}: {provider['status']}")
                    else:
                        logger.error(f"[{i}/{num_posts}] ❌ Scheduling failed: {schedule_result.get('error')}")
                
                # Record topic
                logger.info(f"[{i}/{num_posts}] Step 6: Recording topic to DynamoDB...")
                await topic_manager.record_topic(
                    topic_id=topic['topic_id'],
                    category=topic.get('category', 'general'),
                    prompt=topic['prompt'],
                    video_url=result['video_url']
                )
                
                successful += 1
                logger.info(f"[{i}/{num_posts}] ✅ Video {i} complete!")
                
            except Exception as e:
                logger.exception(f"[{i}/{num_posts}] ❌ Failed to generate video {i}: {e}")
                failed += 1
                # Continue with remaining posts
                continue
        
        logger.info("=" * 60)
        logger.info(f"🎉 Pipeline completed! {successful}/{num_posts} videos generated")
        if failed > 0:
            logger.warning(f"⚠️  {failed} videos failed")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.exception(f"Pipeline failed with error: {e}")
        raise


def _generate_random_schedule_times(date, num_posts: int, tz) -> list:
    """
    Generate random schedule times between 8am-9pm for the given date.
    Ensures minimum 30 minute spacing between posts.
    Returns sorted list of datetime objects.
    """
    import random
    
    # 8am = 8*60 = 480 minutes from midnight
    # 9pm = 21*60 = 1260 minutes from midnight
    start_minutes = 8 * 60   # 8am
    end_minutes = 21 * 60    # 9pm
    
    # Generate random times
    times_minutes = []
    attempts = 0
    max_attempts = 100
    
    while len(times_minutes) < num_posts and attempts < max_attempts:
        attempts += 1
        candidate = random.randint(start_minutes, end_minutes)
        
        # Check minimum 30 minute spacing
        too_close = False
        for existing in times_minutes:
            if abs(candidate - existing) < 30:
                too_close = True
                break
        
        if not too_close:
            times_minutes.append(candidate)
    
    # Sort times
    times_minutes.sort()
    
    # Convert to datetime objects
    schedule_times = []
    for minutes in times_minutes:
        hour = minutes // 60
        minute = minutes % 60
        try:
            dt = datetime(date.year, date.month, date.day, hour, minute, tzinfo=tz)
        except Exception:
            # Fallback without tzinfo
            dt = datetime(date.year, date.month, date.day, hour, minute)
        schedule_times.append(dt)
    
    return schedule_times


if __name__ == "__main__":
    asyncio.run(main())
