"""
Orchestrator Lambda — starts a Step Functions execution per video.

Triggered by EventBridge (4x daily). Reads one topic from SQS if available;
otherwise passes an empty topic string and lets the Batch prep job pick one
from TopicManager.
"""

import os
import json
import uuid
import logging
import boto3

logger = logging.getLogger(__name__)

sqs = boto3.client('sqs')
sfn = boto3.client('stepfunctions')

TOPIC_QUEUE_URL = os.environ['TOPIC_QUEUE_URL']
STATE_MACHINE_ARN = os.environ['STATE_MACHINE_ARN']


def handler(event, context):
    """
    1. Try to pull one topic JSON from SQS.
    2. Generate a video_id.
    3. Start a Step Functions execution with { video_id, topic, target_duration }.
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

    execution_input = {
        'video_id': video_id,
        'topic': topic,           # empty string → prep job uses TopicManager
        'target_duration': 90,    # seconds
    }

    sfn.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=f'iris-flow-{video_id}',
        input=json.dumps(execution_input),
    )

    logger.info(f"Started execution for video_id={video_id}")
    return {'video_id': video_id, 'started': True}
