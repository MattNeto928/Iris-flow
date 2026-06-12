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
    _DEFAULT_PRIMARY_NETWORKS = ("instagram", "tiktok", "youtube", "facebook")
    _DEFAULT_ADDITIONAL_NETWORKS = ("tiktok",)
    _SUPPORTED_NETWORKS = {"instagram", "tiktok", "youtube", "facebook"}

    def __init__(self):
        self.api_key = os.getenv("METRICOOL_API_KEY")
        self.user_id = os.getenv("METRICOOL_USER_ID")
        # Backward compatible:
        # - METRICOOL_BLOG_ID=5572925
        # - METRICOOL_BLOG_ID=5572925,5786828
        # - METRICOOL_BLOG_IDS=5572925,5786828
        blog_ids_raw = os.getenv("METRICOOL_BLOG_IDS") or os.getenv("METRICOOL_BLOG_ID", "")
        self.blog_ids = self._parse_csv(blog_ids_raw)
        self.blog_id = self.blog_ids[0] if self.blog_ids else None  # primary brand id

        # Trending-audio configuration.
        #
        # TikTok: `tiktokData.autoAddMusic` is REJECTED by Metricool for video
        # posts (HTTP 400: "Cannot enable autoAddMusic in posts with videos.
        # Only applies for images and carousels."). Since our pipeline only
        # publishes videos, the field is omitted unless explicitly forced via
        # env. The default is therefore False / unset.
        self.tiktok_auto_add_music = os.getenv(
            "METRICOOL_TIKTOK_AUTO_ADD_MUSIC", "false"
        ).strip().lower() in ("1", "true", "yes", "on")

        # Instagram: Meta's Graph API has NO field for selecting a trending
        # track on Reels. Meta's `audio_name` (Metricool's `instagramData.audioName`)
        # is only a *label* for Original Audio — it doesn't attach a song.
        # Two paths exist to actually attach audio to a scheduled Reel:
        #   (a) Set autoPublish=False so Metricool pushes a notification at
        #       publish time and you finish in the IG app (true native
        #       trending-audio access).
        #   (b) Use Metricool's UI to pick from their licensed library —
        #       Metricool then mixes the track into the video server-side
        #       before publishing. The trigger field for (b) via the public
        #       /v2/scheduler/posts endpoint isn't documented; inspect the
        #       browser network tab on a successful UI submit to discover
        #       it, then add it to instagramData below.
        self.instagram_manual_for_audio = os.getenv(
            "METRICOOL_INSTAGRAM_MANUAL_FOR_AUDIO", "false"
        ).strip().lower() in ("1", "true", "yes", "on")
        # Optional default label that lands on the Reel's audio entry.
        self.default_audio_name = os.getenv("METRICOOL_DEFAULT_AUDIO_NAME", "").strip()
        # Whether to also cross-share the Reel into the main feed.
        self.show_reel_on_feed = os.getenv(
            "METRICOOL_SHOW_REEL_ON_FEED", "true"
        ).strip().lower() in ("1", "true", "yes", "on")

        primary_networks_raw = os.getenv("METRICOOL_PRIMARY_NETWORKS")
        additional_networks_raw = os.getenv("METRICOOL_ADDITIONAL_NETWORKS")
        self.primary_networks = (
            self._parse_csv(primary_networks_raw, valid_values=self._SUPPORTED_NETWORKS)
            if primary_networks_raw
            else list(self._DEFAULT_PRIMARY_NETWORKS)
        )
        self.additional_networks = (
            self._parse_csv(additional_networks_raw, valid_values=self._SUPPORTED_NETWORKS)
            if additional_networks_raw
            else list(self._DEFAULT_ADDITIONAL_NETWORKS)
        )

        # Ensure there's always at least one network target.
        if not self.primary_networks:
            self.primary_networks = list(self._DEFAULT_PRIMARY_NETWORKS)
        if not self.additional_networks:
            self.additional_networks = list(self._DEFAULT_ADDITIONAL_NETWORKS)

        self.base_url = "https://app.metricool.com/api"

        if not all([self.api_key, self.user_id, self.blog_id]):
            logger.warning("Metricool credentials not fully configured")

    @staticmethod
    def _parse_csv(raw: str, valid_values: Optional[set] = None) -> list[str]:
        if not raw:
            return []
        values = []
        for value in raw.split(","):
            normalized = value.strip()
            if not normalized:
                continue
            if valid_values is not None and normalized not in valid_values:
                continue
            values.append(normalized)
        # Stable de-duplication
        deduped = []
        seen = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped

    def _networks_for_blog(self, blog_id: str) -> list[str]:
        if blog_id == self.blog_id:
            return self.primary_networks
        return self.additional_networks

    def _build_post_data(
        self,
        blog_id: str,
        networks: list[str],
        video_url: str,
        caption: str,
        date_str: str,
        youtube_title: str,
        tiktok_title: str,
        audio_name: Optional[str] = None,
    ) -> dict:
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
            "providers": [{"network": network, "id": blog_id} for network in networks],
        }

        if "instagram" in networks:
            # autoPublish=False makes Metricool send a push notification at
            # scheduled time so the user finishes the Reel in the IG app and
            # can pick trending audio natively. autoPublish=True is fully
            # automatic but the post will have NO audio (we no longer bake
            # music in) unless the source video already has any.
            ig_data: dict = {
                "autoPublish": not self.instagram_manual_for_audio,
                "type": "REEL",
                "showReelOnFeed": self.show_reel_on_feed,
            }
            # `audioName` is Meta's `audio_name` — a *label* on the Reel's
            # Original Audio. It does not attach a track. Useful for naming
            # the audio entry consistently across posts.
            effective_audio_name = audio_name or self.default_audio_name
            if effective_audio_name:
                ig_data["audioName"] = effective_audio_name
            post_data["instagramData"] = ig_data
            if self.instagram_manual_for_audio:
                # Top-level autoPublish must also be false for IG manual flow.
                post_data["autoPublish"] = False
        if "tiktok" in networks:
            tiktok_data: dict = {
                "disableComment": False,
                "disableDuet": False,
                "disableStitch": False,
                "privacyOption": "PUBLIC_TO_EVERYONE",
                "title": tiktok_title,
            }
            # `autoAddMusic`: Metricool's API only accepts this for IMAGE and
            # CAROUSEL posts. For VIDEO posts (our entire pipeline) Metricool
            # rejects the payload with HTTP 400. Only include the field if
            # the operator explicitly enables it via env (intended for future
            # image/carousel support).
            if self.tiktok_auto_add_music:
                tiktok_data["autoAddMusic"] = True
            post_data["tiktokData"] = tiktok_data
        if "youtube" in networks:
            post_data["youtubeData"] = {
                "title": youtube_title,
                "type": "SHORT",
                "privacy": "PUBLIC",
                "madeForKids": False
            }
        if "facebook" in networks:
            post_data["facebookData"] = {
                "type": "REEL"
            }

        return post_data

    async def _schedule_post_for_blog(
        self,
        client: httpx.AsyncClient,
        blog_id: str,
        networks: list[str],
        video_url: str,
        caption: str,
        date_str: str,
        youtube_title: str,
        tiktok_title: str,
        audio_name: Optional[str] = None,
    ) -> dict:
        post_data = self._build_post_data(
            blog_id=blog_id,
            networks=networks,
            video_url=video_url,
            caption=caption,
            date_str=date_str,
            youtube_title=youtube_title,
            tiktok_title=tiktok_title,
            audio_name=audio_name,
        )

        url = f"{self.base_url}/v2/scheduler/posts?userId={self.user_id}&blogId={blog_id}"
        response = await client.post(
            url,
            json=post_data,
            headers={
                "X-Mc-Auth": self.api_key,
                "Content-Type": "application/json"
            },
            timeout=30.0
        )

        if response.status_code in (200, 201):
            data = response.json()
            return {
                "blog_id": blog_id,
                "networks": networks,
                "success": True,
                "post_id": data.get("data", {}).get("id"),
                "providers": data.get("data", {}).get("providers", []),
                "scheduled_time": date_str
            }

        error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
        logger.error(f"Metricool API error {response.status_code} for blog {blog_id}: {error_data}")
        return {
            "blog_id": blog_id,
            "networks": networks,
            "success": False,
            "error": f"API error {response.status_code}: {error_data}"
        }

    async def schedule_post(
        self,
        video_url: str,
        caption: str,
        schedule_time: datetime,
        youtube_title: str,
        include_youtube: bool = True,
        tiktok_title: Optional[str] = None,
        audio_name: Optional[str] = None,
    ) -> dict:
        """
        Schedule a video post to Instagram, TikTok, and YouTube.

        Args:
            video_url: Public URL to the video file
            caption: Social media caption with hashtags
            schedule_time: When to publish (should be 24h from now)
            youtube_title: Title for YouTube (must be < 100 chars)
            include_youtube: When False, the youtube network is dropped from
                every blog's network list (used to cap YouTube at 2 posts/day).
                Other networks (IG/TikTok/Facebook) are unaffected.
            tiktok_title: Optional separate title for TikTok

        Returns:
            dict with keys: success, post_id, providers, error
        """
        if not all([self.api_key, self.user_id]):
            logger.warning("Metricool API key not set, skipping scheduling")
            return {
                'success': False,
                'error': 'Metricool credentials not configured'
            }

        if not self.blog_ids:
            logger.warning("Metricool blog IDs not configured, skipping scheduling")
            return {
                "success": False,
                "error": "Metricool blog IDs not configured"
            }

        if tiktok_title is None:
            tiktok_title = youtube_title

        # Ensure YouTube title is under 100 chars
        if len(youtube_title) > 100:
            youtube_title = youtube_title[:97] + "..."

        # Format datetime for Metricool API
        date_str = schedule_time.strftime("%Y-%m-%dT%H:%M:%S")

        results = []
        try:
            async with httpx.AsyncClient() as client:
                for blog_id in self.blog_ids:
                    # Temporarily disabled: posting for blogId=5786828 (userId=4323879)
                    # if blog_id == "5786828":
                    #     logger.info(f"Skipping blog {blog_id}: temporarily disabled")
                    #     continue
                    if blog_id == "5786828":
                        logger.info(f"Skipping blog {blog_id}: temporarily disabled")
                        continue
                    networks = self._networks_for_blog(blog_id)
                    if not include_youtube:
                        networks = [n for n in networks if n != "youtube"]
                    if not networks:
                        logger.warning(f"Skipping blog {blog_id}: no networks configured")
                        results.append({
                            "blog_id": blog_id,
                            "success": False,
                            "error": "No networks configured for blog",
                            "networks": []
                        })
                        continue

                    logger.info(f"Scheduling to Metricool blog {blog_id} with networks={networks}")
                    blog_result = await self._schedule_post_for_blog(
                        client=client,
                        blog_id=blog_id,
                        networks=networks,
                        video_url=video_url,
                        caption=caption,
                        date_str=date_str,
                        youtube_title=youtube_title,
                        tiktok_title=tiktok_title,
                        audio_name=audio_name,
                    )
                    results.append(blog_result)

        except Exception as e:
            logger.error(f"Metricool scheduling failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }

        successful = [r for r in results if r.get("success")]
        failed = [r for r in results if not r.get("success")]

        response = {
            "success": len(failed) == 0 and len(successful) > 0,
            "results": results,
            "post_id": successful[0].get("post_id") if successful else None,
            "providers": successful[0].get("providers", []) if successful else [],
            "scheduled_time": date_str
        }
        if failed:
            response["error"] = "; ".join(
                f"blog {r.get('blog_id')}: {r.get('error', 'unknown error')}" for r in failed
            )
        return response

    async def get_scheduled_posts(self) -> list:
        """Get list of currently scheduled posts."""
        if not self.api_key or not self.user_id or not self.blog_ids:
            return []

        posts = []
        try:
            async with httpx.AsyncClient() as client:
                for blog_id in self.blog_ids:
                    url = f"{self.base_url}/v2/scheduler/posts?userId={self.user_id}&blogId={blog_id}"
                    response = await client.get(
                        url,
                        headers={
                            "X-Mc-Auth": self.api_key,
                            "Content-Type": "application/json"
                        },
                        timeout=30.0
                    )
                    if response.status_code == 200:
                        blog_posts = response.json().get("data", [])
                        for post in blog_posts:
                            post["_blog_id"] = blog_id
                        posts.extend(blog_posts)
            return posts
        except Exception:
            return []
