"""
Topic Manager - Handle topic queue and generation.

Checks SQS queue for user-provided topics.
If queue is empty, generates a topic like gemini_manim does.
Records all topics to DynamoDB with TTL for deduplication.
"""

import os
import json
import uuid
import logging
from datetime import datetime, timedelta
import boto3
from google import genai

logger = logging.getLogger(__name__)

# Initialize AWS clients
sqs = boto3.client('sqs', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Initialize Gemini client
gemini_client = genai.Client(api_key=os.environ.get('GOOGLE_AI_API_KEY'))

# Table and queue names from environment
TOPIC_QUEUE_URL = os.environ.get('TOPIC_QUEUE_URL')
TOPICS_TABLE = os.environ.get('TOPICS_TABLE', 'iris-flow-topics')


class TopicManager:
    def __init__(self):
        self.topics_table = dynamodb.Table(TOPICS_TABLE)
    
    async def get_topic(self) -> dict:
        """
        Get a topic for video generation.
        
        First checks SQS queue for user-provided topics.
        If queue is empty, generates a unique topic using Gemini.
        
        Returns:
            dict with keys: topic_id, prompt, category
        """
        # Try to get from queue first
        queue_topic = await self._get_from_queue()
        if queue_topic:
            logger.info("Got topic from SQS queue")
            return queue_topic
        
        # Queue empty - generate a topic
        logger.info("Queue empty, generating topic with Gemini...")
        return await self._generate_topic()
    
    async def _get_from_queue(self) -> dict | None:
        """Try to receive a message from SQS queue."""
        if not TOPIC_QUEUE_URL:
            logger.warning("TOPIC_QUEUE_URL not set, skipping queue check")
            return None
        
        try:
            response = sqs.receive_message(
                QueueUrl=TOPIC_QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=5,  # Long polling
                VisibilityTimeout=1800  # 30 minutes (video gen takes a while)
            )
            
            messages = response.get('Messages', [])
            if not messages:
                return None
            
            message = messages[0]
            body = json.loads(message['Body'])
            
            # Delete message from queue (we're processing it)
            sqs.delete_message(
                QueueUrl=TOPIC_QUEUE_URL,
                ReceiptHandle=message['ReceiptHandle']
            )
            
            return {
                'topic_id': body.get('topic_id', str(uuid.uuid4())[:8]),
                'prompt': body.get('prompt', body.get('topic', '')),
                'category': body.get('category', 'general')
            }
            
        except Exception as e:
            logger.error(f"Error reading from SQS: {e}")
            return None
    
    async def _generate_topic(self) -> dict:
        """Generate a unique topic using Gemini, avoiding recent topics."""
        # Get recent topics from DynamoDB to avoid repeats
        recent_topics = await self._get_recent_topics()
        recent_list = ', '.join(recent_topics) if recent_topics else 'none'
        
        prompt = f"""Generate a unique, engaging topic prompt for an educational STEM video that would go viral on social media (TikTok, Instagram Reels, YouTube Shorts).

AVOID these recently used topics: {recent_list}

Choose ONE of these categories (vary your choices):
1. PARADOXES: Mind-bending logical or mathematical paradoxes
2. COUNTERINTUITIVE PHENOMENA: Results that defy intuition
3. ELEGANT THEOREMS: Beautiful mathematical results with visual proofs
4. REAL-WORLD APPLICATIONS: How abstract math applies to everyday life
5. MATHEMATICAL PATTERNS: Fascinating patterns in nature and numbers
6. PHYSICS PHENOMENA: Surprising physics concepts

Provide:
- A specific topic with depth (not just "explain X" but "show how X leads to Y and its applications in Z")
- Emphasis on visual demonstration possibilities
- A hook that would grab a viewer's attention in the first 3 seconds

Return a JSON object with:
- "prompt": The full detailed prompt for video generation
- "category": One of the categories above (lowercase, underscore-separated)
- "short_title": A 3-5 word title for tracking

Return ONLY the JSON object, no markdown."""

        try:
            response = gemini_client.models.generate_content(
                model="gemini-3-flash-preview",
                contents=prompt,
                config={
                    "temperature": 0.9,
                    "top_p": 0.95,
                    "max_output_tokens": 2048,  # Increased from 1024 to prevent truncation
                    "response_mime_type": "application/json",
                }
            )
            
            text = response.text.strip()
            logger.info(f"Gemini topic response (first 200 chars): {text[:200]}")
            
            result = None
            
            # Try direct JSON parsing
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                pass
            
            # Try extracting JSON from markdown code blocks
            if not result and "```" in text:
                try:
                    code_block = text.split("```")[1]
                    if code_block.startswith("json"):
                        code_block = code_block[4:]
                    result = json.loads(code_block.strip())
                except (IndexError, json.JSONDecodeError):
                    pass
            
            # Try finding JSON object in text
            if not result:
                try:
                    start = text.find("{")
                    end = text.rfind("}") + 1
                    if start != -1 and end > start:
                        result = json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            
            # If all parsing fails, use the raw text as the prompt
            if not result:
                logger.warning("Could not parse JSON from Gemini, using raw text as prompt")
                result = {
                    "prompt": text if len(text) > 20 else "Demonstrate a fascinating mathematical pattern that appears in nature",
                    "category": "general",
                    "short_title": "Generated Topic"
                }
            
            return {
                'topic_id': str(uuid.uuid4())[:8],
                'prompt': result.get('prompt', text),
                'category': result.get('category', 'general'),
                'short_title': result.get('short_title', 'Generated Topic')
            }
            
        except Exception as e:
            logger.error(f"Error generating topic: {e}")
            # Fallback to a default topic
            return {
                'topic_id': str(uuid.uuid4())[:8],
                'prompt': "Demonstrate the Fibonacci sequence and its appearance in nature, from sunflower spirals to galaxy formations",
                'category': 'mathematical_patterns',
                'short_title': 'Fibonacci in Nature'
            }
    
    async def _get_recent_topics(self, days: int = 30) -> list[str]:
        """Get list of recently used topic titles from DynamoDB."""
        try:
            # Scan for recent topics (not ideal for large tables, but works for now)
            response = self.topics_table.scan(
                Limit=50,
                ProjectionExpression='short_title, prompt'
            )
            
            topics = []
            for item in response.get('Items', []):
                if 'short_title' in item:
                    topics.append(item['short_title'])
                elif 'prompt' in item:
                    # Use first 50 chars of prompt as identifier
                    topics.append(item['prompt'][:50])
            
            return topics[:20]  # Return at most 20 recent topics
            
        except Exception as e:
            logger.error(f"Error getting recent topics: {e}")
            return []
    
    async def record_topic(
        self,
        topic_id: str,
        category: str,
        prompt: str,
        video_url: str
    ):
        """Record a generated topic to DynamoDB with 30-day TTL."""
        try:
            now = datetime.utcnow()
            ttl = int((now + timedelta(days=30)).timestamp())
            
            self.topics_table.put_item(Item={
                'topic_id': topic_id,
                'created_at': now.isoformat(),
                'category': category,
                'prompt': prompt,
                'video_url': video_url,
                'short_title': prompt[:50] if len(prompt) > 50 else prompt,
                'ttl': ttl
            })
            
            logger.info(f"Recorded topic {topic_id} to DynamoDB")
            
        except Exception as e:
            logger.error(f"Error recording topic: {e}")
            raise
