"""
Read Manifest Lambda — returns the visual segment list for the Step Functions Map.

Downloads manifest.json from S3 and returns:
  { "visualSegments": [{ "video_id": "...", "segment_index": 0 }, ...] }

All segment types (matplotlib, manim, plotly, title_card) are handled by
job_visual — title_cards use inline FFmpeg drawtext, no code generation.
There are no "transition" segments anymore.
"""

import os
import json
import logging
import boto3

logger = logging.getLogger(__name__)

s3 = boto3.client('s3')
VIDEO_BUCKET_NAME = os.environ['VIDEO_BUCKET_NAME']


def handler(event, context):
    """
    Input: { "video_id": "abc123", ... } (full Step Functions state)
    Output: { "visualSegments": [{ "video_id": "...", "segment_index": N }, ...] }
    """
    video_id = event['video_id']
    logger.info(f"Reading manifest for video_id={video_id}")

    obj = s3.get_object(
        Bucket=VIDEO_BUCKET_NAME,
        Key=f'jobs/{video_id}/manifest.json',
    )
    manifest = json.loads(obj['Body'].read())

    segments = manifest.get('segments', [])
    logger.info(f"Found {len(segments)} segments")

    # All segments route to job_visual regardless of type.
    # title_card is rendered inline (FFmpeg drawtext, no API call).
    visual_segments = [
        {'video_id': video_id, 'segment_index': seg['index']}
        for seg in segments
    ]

    return {'visualSegments': visual_segments}
