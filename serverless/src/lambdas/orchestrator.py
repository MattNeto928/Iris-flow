"""
Orchestrator Lambda — starts a Step Functions execution per video.

Triggered by EventBridge (4x daily). Reads one topic from SQS if available;
otherwise passes an empty topic string and lets the Batch prep job pick one
from TopicManager.
"""

import os
import json
import uuid
import random
import logging
from datetime import datetime, timedelta, timezone
import boto3

logger = logging.getLogger(__name__)

sqs = boto3.client('sqs')
sfn = boto3.client('stepfunctions')

# QUEUE_URL / TARGET_DURATION / EXEC_PREFIX generalize this Lambda so the SAME
# code drives both the STEM pipeline and the story pipeline — only the env differs.
# TOPIC_QUEUE_URL is kept as a fallback so the original STEM deployment is unchanged.
TOPIC_QUEUE_URL = os.environ.get('QUEUE_URL') or os.environ['TOPIC_QUEUE_URL']
STATE_MACHINE_ARN = os.environ['STATE_MACHINE_ARN']
TARGET_DURATION = int(os.environ.get('TARGET_DURATION', '90'))
EXEC_PREFIX = os.environ.get('EXEC_PREFIX', 'iris-flow')

# Random scheduling window: post anywhere from MIN_DELAY_MIN to MAX_DELAY_MIN
# minutes from now. With EventBridge firing 4× daily, this spreads posts
# organically across each ~6-hour window rather than clustering at trigger time.
MIN_DELAY_MIN = 30        # don't post before the pipeline has finished (~15 min runtime)
MAX_DELAY_MIN = 6 * 60    # 6 hours — matches the EventBridge interval


def _random_schedule_time() -> str:
    """Pick a random time between MIN_DELAY_MIN and MAX_DELAY_MIN from now, ISO-8601 UTC."""
    delay = random.randint(MIN_DELAY_MIN, MAX_DELAY_MIN)
    ts = datetime.now(timezone.utc) + timedelta(minutes=delay)
    return ts.isoformat()


def handler(event, context):
    """
    1. Try to pull one topic JSON from SQS.
    2. Generate a video_id and a random schedule_time in the next 6 hours.
    3. Start a Step Functions execution.
    """
    topic = ''

    # Pull one queued topic if available
    resp = sqs.receive_message(
        QueueUrl=TOPIC_QUEUE_URL,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=0,
    )
    messages = resp.get('Messages', [])
    if messages:
        msg = messages[0]
        topic = msg['Body']
        sqs.delete_message(
            QueueUrl=TOPIC_QUEUE_URL,
            ReceiptHandle=msg['ReceiptHandle'],
        )
        logger.info(f"Using queued topic: {topic[:80]}")
    else:
        logger.info("No queued topic — prep job will generate one from TopicManager")

    video_id = str(uuid.uuid4())[:8]
    schedule_time = _random_schedule_time()

    execution_input = {
        'video_id': video_id,
        'topic': topic,                  # empty string → prep job uses its TopicManager
        'target_duration': TARGET_DURATION,
        'schedule_time': schedule_time,  # ISO-8601 UTC, passed to postprocess
    }

    sfn.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=f'{EXEC_PREFIX}-{video_id}',
        input=json.dumps(execution_input),
    )

    logger.info(f"Started execution video_id={video_id} schedule_time={schedule_time}")
    return {'video_id': video_id, 'schedule_time': schedule_time, 'started': True}
