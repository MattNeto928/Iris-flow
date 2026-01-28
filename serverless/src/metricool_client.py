"""
Metricool Client - Social media scheduling.

Schedules posts to Instagram Reels, TikTok, YouTube Shorts, and Facebook Reels via Metricool API.
Direct port from gemini_manim working implementation.
"""

import os
import logging
from datetime import datetime
from typing import Optional
import httpx

logger = logging.getLogger(__name__)


class MetricoolClient:
    def __init__(self):
        self.api_key = os.getenv("METRICOOL_API_KEY")
        self.user_id = os.getenv("METRICOOL_USER_ID")
        self.blog_id = os.getenv("METRICOOL_BLOG_ID")
        self.base_url = "https://app.metricool.com/api"
        
        if not all([self.api_key, self.user_id, self.blog_id]):
            logger.warning("Metricool credentials not fully configured")
    
    async def schedule_post(
        self,
        video_url: str,
        caption: str,
        schedule_time: datetime,
        youtube_title: str,
        tiktok_title: Optional[str] = None
    ) -> dict:
        """
        Schedule a video post to Instagram, TikTok, and YouTube.
        
        Args:
            video_url: Public URL to the video file
            caption: Social media caption with hashtags
            schedule_time: When to publish (should be 24h from now)
            youtube_title: Title for YouTube (must be < 100 chars)
            tiktok_title: Optional separate title for TikTok
        
        Returns:
            dict with keys: success, post_id, providers, error
        """
        if not self.api_key:
            logger.warning("Metricool API key not set, skipping scheduling")
            return {
                'success': False,
                'error': 'Metricool API key not configured'
            }
        
        if tiktok_title is None:
            tiktok_title = youtube_title
        
        # Ensure YouTube title is under 100 chars
        if len(youtube_title) > 100:
            youtube_title = youtube_title[:97] + "..."
        
        # Format datetime for Metricool API
        date_str = schedule_time.strftime("%Y-%m-%dT%H:%M:%S")
        
        post_data = {
            "publicationDate": {
                "dateTime": date_str,
                "timezone": "America/New_York"
            },
            "text": caption,
            "autoPublish": True,
            "draft": False,
            "media": [video_url],
            "saveExternalMediaFiles": True,
            "providers": [
                {
                    "network": "instagram",
                    "id": self.blog_id
                },
                {
                    "network": "tiktok",
                    "id": self.blog_id
                },
                {
                    "network": "youtube",
                    "id": self.blog_id
                },
                {
                    "network": "facebook",
                    "id": self.blog_id
                }
            ],
            "instagramData": {
                "autoPublish": True,
                "type": "REEL"
            },
            "tiktokData": {
                "disableComment": False,
                "disableDuet": False,
                "disableStitch": False,
                "privacyOption": "PUBLIC_TO_EVERYONE",
                "title": tiktok_title
            },
            "youtubeData": {
                "title": youtube_title,
                "type": "SHORT",
                "privacy": "PUBLIC",
                "madeForKids": False
            },
            "facebookData": {
                "type": "REEL"
            }
        }
        
        url = f"{self.base_url}/v2/scheduler/posts?userId={self.user_id}&blogId={self.blog_id}"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=post_data,
                    headers={
                        "X-Mc-Auth": self.api_key,
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if response.status_code == 201:
                    data = response.json()
                    return {
                        "success": True,
                        "post_id": data.get("data", {}).get("id"),
                        "providers": data.get("data", {}).get("providers", []),
                        "scheduled_time": date_str
                    }
                else:
                    error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
                    logger.error(f"Metricool API error {response.status_code}: {error_data}")
                    return {
                        "success": False,
                        "error": f"API error {response.status_code}: {error_data}"
                    }
                    
        except Exception as e:
            logger.error(f"Metricool scheduling failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_scheduled_posts(self) -> list:
        """Get list of currently scheduled posts."""
        if not self.api_key:
            return []
        
        url = f"{self.base_url}/v2/scheduler/posts?userId={self.user_id}&blogId={self.blog_id}"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={
                        "X-Mc-Auth": self.api_key,
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    return response.json().get("data", [])
                return []
                
        except Exception:
            return []
