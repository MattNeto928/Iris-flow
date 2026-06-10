"""
Story Topic Manager — topic source for the origin-story pipeline.

Mirrors topic_manager.TopicManager but:
  - reads from the STORY SQS queue (STORY_QUEUE_URL),
  - generates "how X came to be" origin-story topics (not STEM paradoxes) when the
    queue is empty, and
  - records to the same DynamoDB topics table under story-flavored categories.

Topics are returned as { topic_id, prompt, category }, the same shape job_prep
expects, so the rest of the pipeline is unchanged.
"""

import os
import json
import uuid
import logging
from datetime import datetime, timedelta

import boto3
import anthropic

logger = logging.getLogger(__name__)

sqs = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "us-east-1"))
dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

STORY_QUEUE_URL = os.environ.get("STORY_QUEUE_URL")
TOPICS_TABLE = os.environ.get("TOPICS_TABLE", "iris-flow-topics")

# Angle tags the story_client understands. The generator is told to pick one and
# tag the prompt so the script step selects the right hook template.
ANGLES = (
    "[ACC] accidental discovery / happy accident",
    "[DARK] dark or strange origin of an innocent everyday thing",
    "[IMP] told it was impossible / everyone laughed, then vindication",
    "[HIDDEN] the forgotten inventor / wrong person got the credit",
    "[WHY] the everyday 'why' nobody questions",
    "[NEAR] near-miss / it almost never happened",
    "[RIVAL] a rivalry or race between two people",
    "[FORBID] something banned, forbidden, or suppressed",
)


class StoryTopicManager:
    def __init__(self):
        self.topics_table = dynamodb.Table(TOPICS_TABLE)

    async def get_topic(self) -> dict:
        """Pull a story topic from the story queue, or generate one."""
        queued = await self._get_from_queue()
        if queued:
            logger.info("Got story topic from SQS queue")
            return queued
        logger.info("Story queue empty, generating an origin-story topic with Claude...")
        return await self._generate_topic()

    async def _get_from_queue(self) -> dict | None:
        if not STORY_QUEUE_URL:
            logger.warning("STORY_QUEUE_URL not set, skipping queue check")
            return None
        try:
            resp = sqs.receive_message(
                QueueUrl=STORY_QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=5,
                VisibilityTimeout=1800,
            )
            messages = resp.get("Messages", [])
            if not messages:
                return None
            msg = messages[0]
            body = json.loads(msg["Body"])
            sqs.delete_message(QueueUrl=STORY_QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
            result = {
                "topic_id": body.get("topic_id", str(uuid.uuid4())[:8]),
                "prompt": body.get("prompt", body.get("topic", "")),
                "category": body.get("category", "origin_story"),
            }
            if "target_duration" in body:
                result["target_duration"] = int(body["target_duration"])
            return result
        except Exception as e:
            logger.error(f"Error reading from story SQS: {e}")
            return None

    async def _generate_topic(self) -> dict:
        recent = await self._get_recent_topics()
        recent_list = ", ".join(recent) if recent else "none"
        angles = "\n".join(f"- {a}" for a in ANGLES)

        prompt = f"""Generate ONE origin-story topic for a short-form vertical video — a "how X came
to be" story that would rack up views on TikTok / Reels / YouTube Shorts. These are
stories of how things came to be: scientific discoveries above all, but also
inventions, the dark/forgotten origins of everyday objects, ideas once called
impossible — anything genuinely thought-provoking and surprising.

AVOID anything close to these recently used topics: {recent_list}

Pick exactly ONE angle and tag the prompt with it:
{angles}

The winning lever is the ANGLE/framing, not just the subject. Lead with the
surprising contrast. Anchor it in a real, concrete detail (a name, a date, a number).

Return ONLY a JSON object (no markdown):
- "prompt": one or two sentences describing the specific story to tell, STARTING with
  the angle tag in brackets, e.g. "[ACC] How a messy lab and a summer vacation gave
  Alexander Fleming penicillin in 1928." Be specific — a concrete story, not a vague subject.
- "category": one of: scientific_discovery, invention_origin, dark_origin,
  impossible_idea, everyday_why, forgotten_inventor
- "short_title": a 3-5 word title for tracking."""

        try:
            response = anthropic_client.messages.create(
                model="claude-fable-5",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(_b.text for _b in response.content if getattr(_b,"type",None)=="text").strip()
            logger.info(f"Claude story-topic response (first 200): {text[:200]}")

            result = None
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                pass
            if not result and "```" in text:
                try:
                    block = text.split("```")[1]
                    if block.startswith("json"):
                        block = block[4:]
                    result = json.loads(block.strip())
                except (IndexError, json.JSONDecodeError):
                    pass
            if not result:
                start, end = text.find("{"), text.rfind("}") + 1
                if start != -1 and end > start:
                    try:
                        result = json.loads(text[start:end])
                    except json.JSONDecodeError:
                        pass
            if not result:
                result = {
                    "prompt": text if len(text) > 20 else
                    "[ACC] How a radar engineer's melting chocolate bar led to the microwave oven.",
                    "category": "scientific_discovery",
                    "short_title": "Generated Story",
                }

            return {
                "topic_id": str(uuid.uuid4())[:8],
                "prompt": result.get("prompt", text),
                "category": result.get("category", "origin_story"),
                "short_title": result.get("short_title", "Generated Story"),
            }
        except Exception as e:
            logger.error(f"Error generating story topic: {e}")
            return {
                "topic_id": str(uuid.uuid4())[:8],
                "prompt": "[ACC] How burrs stuck to a dog on a walk became Velcro.",
                "category": "invention_origin",
                "short_title": "Velcro Origin",
            }

    async def _get_recent_topics(self, days: int = 30) -> list[str]:
        try:
            response = self.topics_table.scan(
                Limit=50, ProjectionExpression="short_title, prompt"
            )
            topics = []
            for item in response.get("Items", []):
                if "short_title" in item:
                    topics.append(item["short_title"])
                elif "prompt" in item:
                    topics.append(item["prompt"][:50])
            return topics[:25]
        except Exception as e:
            logger.error(f"Error getting recent story topics: {e}")
            return []

    async def record_topic(self, topic_id: str, category: str, prompt: str, video_url: str):
        """Record to DynamoDB with 30-day TTL (shared topics table)."""
        try:
            now = datetime.utcnow()
            ttl = int((now + timedelta(days=30)).timestamp())
            self.topics_table.put_item(Item={
                "topic_id": topic_id,
                "created_at": now.isoformat(),
                "category": category,
                "prompt": prompt,
                "video_url": video_url,
                "short_title": prompt[:50] if len(prompt) > 50 else prompt,
                "ttl": ttl,
            })
            logger.info(f"Recorded story topic {topic_id} to DynamoDB")
        except Exception as e:
            logger.error(f"Error recording story topic: {e}")
            raise
