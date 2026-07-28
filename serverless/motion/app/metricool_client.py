"""
Metricool client — every post type and every field this account can reach.

Was: one function that put ONE caption and ONE title on four networks. Now each
network gets copy written for it (app/postcopy.py) and the fields that network
actually has, and the pipeline can publish four FORMATS rather than one:

  reel      the 1080x1920 video      IG Reel / TikTok / YT Short / FB Reel
  carousel  4-6 1080x1350 slides     IG Carousel / TikTok photo post
  image     one 1080x1350 still      IG + FB
  story     a 15s teaser cut         IG Story

FIELDS THAT WERE ON THE TABLE AND ARE NOW SET, all from the published OpenAPI
spec (https://app.metricool.com/api/swagger.json), all previously unused:
  youtubeData.tags / .category      YouTube is a search engine and we were
                                    handing it no keywords at all
  firstCommentText                  hashtags out of the caption
  videoCoverMilliseconds            the thumbnail frame, chosen by slides.py
                                    rather than whatever frame 0 happens to be
  mediaAltText                      accessibility, and IG reads it for context
  instagramData.audioConfiguration  see INSTAGRAM AUDIO below
  tiktokData.isAigc                 disclosure; every piece here is synthetic
  tiktokData.autoAddMusic           REJECTED on video (HTTP 400) but VALID on
                                    photo posts, so the carousel can carry it

INSTAGRAM AUDIO. GET /v2/scheduler/catalogs/instagram/audio returns Metricool's
licensed catalogue and it WORKS on this account (verified, HTTP 200 with real
audioIds). instagramData.audioConfiguration then attaches a track to a scheduled
Reel with independent audioVolume/videoVolume, so a track can sit under the
narration instead of replacing it. The previous comment in this file said the
trigger field "isn't documented" and suggested reading it out of a browser
network tab; it is documented, and this is it.

Metricool auto-publishes a Reel with attached audio ONLY when the audio comes
from its own library, which is exactly what that endpoint returns. Anything else
falls back to a push notification, i.e. a post that silently never publishes.

WHAT IS NOT REACHABLE FROM HERE: TikTok trending tracks. The endpoint answers
403 "TikTok Business account is required" and this brand is
tiktokAccountType=PERSONAL. Converting trades the viral sound library for the
Commercial Music Library, which is a bad trade for a channel that grows on the
For You page.
"""

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

# Metricool interprets a post's `dateTime` as wall-clock in this timezone. The
# pipeline computes schedule_time in UTC, so it MUST be converted to this zone's
# wall clock before formatting — otherwise UTC digits get read as Eastern and
# every post lands ~4h late (midnight-UTC triggers posted after midnight ET).
POST_TIMEZONE = "America/New_York"
_POST_TZ = ZoneInfo(POST_TIMEZONE)

# Which networks can carry which format. A network absent from a format's set is
# dropped from that post rather than sent and rejected.
FORMAT_NETWORKS = {
    'reel': {'instagram', 'tiktok', 'youtube', 'facebook'},
    # No YouTube: it has no carousel. Facebook is in, as a plain multi-photo
    # post with no facebookData block (its `type` enum for photo posts is not
    # in the spec, and guessing an enum is how you get a 400 at publish time).
    'carousel': {'instagram', 'tiktok', 'facebook'},
    'image': {'instagram', 'facebook'},
    # Instagram only, deliberately. Facebook Stories for a PAGE reach almost
    # nobody, and facebookData.type has no documented STORY value.
    'story': {'instagram'},
    # The weekly compilation. YouTube ONLY, and this is why it is its own kind
    # rather than a 'reel' with include_tiktok=False: the include_* flags gate
    # YouTube and TikTok, so a 'reel' restricted that way still carries
    # Instagram and Facebook, and an 8-minute landscape video would have gone
    # out as an IG Reel.
    'longform': {'youtube'},
}

# Instagram's own API cap, for reference in review: 50 posts/24h across feed
# posts, Reels and Stories combined. This pipeline schedules 9.
IG_DAILY_API_LIMIT = 50


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

        # --- Instagram audio -------------------------------------------------
        # Off by default so enabling it is a deliberate, revertible act: it is
        # the one change here that alters what a Reel SOUNDS like.
        self.instagram_audio = os.getenv(
            "METRICOOL_INSTAGRAM_AUDIO", "false"
        ).strip().lower() in ("1", "true", "yes", "on")
        # Under the narration, not over it. The pieces already carry a voice
        # track and a music bed mixed at 0.20 by stitch.py, so an attached
        # Instagram track is a third layer and has to sit well below both.
        self.audio_volume = int(os.getenv("METRICOOL_AUDIO_VOLUME", "12"))
        self.video_volume = int(os.getenv("METRICOOL_VIDEO_VOLUME", "100"))

        # TikTok trending audio via tiktokData.music is unreachable on a
        # PERSONAL account (403 from the trending-tracks catalogue), so this
        # stays a flag rather than a hardcoded false: if the account ever
        # converts to Business, this is the switch.
        self.tiktok_auto_add_music = os.getenv(
            "METRICOOL_TIKTOK_AUTO_ADD_MUSIC", "false"
        ).strip().lower() in ("1", "true", "yes", "on")

        self.instagram_manual_for_audio = os.getenv(
            "METRICOOL_INSTAGRAM_MANUAL_FOR_AUDIO", "false"
        ).strip().lower() in ("1", "true", "yes", "on")
        self.default_audio_name = os.getenv("METRICOOL_DEFAULT_AUDIO_NAME", "").strip()
        self.show_reel_on_feed = os.getenv(
            "METRICOOL_SHOW_REEL_ON_FEED", "true"
        ).strip().lower() in ("1", "true", "yes", "on")

        # Every piece is a synthetic 3D render with a synthetic voice. TikTok
        # asks publishers to declare that, and declaring it is both cheap and
        # the honest answer.
        self.tiktok_is_aigc = os.getenv(
            "METRICOOL_TIKTOK_IS_AIGC", "true"
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
        if not self.primary_networks:
            self.primary_networks = list(self._DEFAULT_PRIMARY_NETWORKS)
        if not self.additional_networks:
            self.additional_networks = list(self._DEFAULT_ADDITIONAL_NETWORKS)

        self.base_url = "https://app.metricool.com/api"

        if not all([self.api_key, self.user_id, self.blog_id]):
            logger.warning("Metricool credentials not fully configured")

    # ============================================================
    # helpers
    # ============================================================
    @staticmethod
    def _parse_csv(raw: str, valid_values: Optional[set] = None) -> list:
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
        deduped, seen = [], set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped

    def _headers(self) -> dict:
        return {"X-Mc-Auth": self.api_key, "Content-Type": "application/json"}

    def _networks_for_blog(self, blog_id: str) -> list:
        if blog_id == self.blog_id:
            return self.primary_networks
        return self.additional_networks

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.user_id and self.blog_ids)

    # ============================================================
    # read-only catalogues
    # ============================================================
    async def suggest_hashtags(self, seed: str, limit: int = 8) -> list:
        """
        Instagram's own hashtag suggestions for a seed word, most-used first.

        Metricool returns {"#physics": 167, "#quantumphysics": 18, ...} where the
        value is a usage weight. Used to VALIDATE and top up the model's tags
        with ones Instagram actually recognises, never to replace them: the
        model's are topical, these are popular, and a caption wants both.

        Never raises. A hashtag list is a nice-to-have and this is called on the
        publish path.
        """
        if not self.configured or not seed:
            return []
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{self.base_url}/actions/instagram/suggestions/hashtags",
                    params={"userId": self.user_id, "blogId": self.blog_id, "q": seed},
                    headers=self._headers(), timeout=20.0)
                if r.status_code != 200:
                    logger.warning("hashtag suggestions %s: %s", r.status_code, r.text[:160])
                    return []
                data = r.json()
        except Exception as e:  # noqa: BLE001 - advisory data, never fatal
            logger.warning("hashtag suggestions failed: %s", e)
            return []

        if not isinstance(data, dict):
            return []
        ranked = sorted(data.items(), key=lambda kv: -(kv[1] or 0))
        return [tag for tag, _ in ranked[:limit] if tag.startswith('#')]

    async def find_instagram_audio(self, query: str, min_ms: int = 0) -> Optional[dict]:
        """
        One track from Metricool's licensed Instagram catalogue, or None.

        min_ms drops tracks shorter than the video: a 20s loop under a 75s reel
        ends in 55s of silence where the music was.

        Selection is DETERMINISTIC on the query (sha256 -> index), not random.
        Two runs of the same piece pick the same track, which is what makes a
        re-run after a failure produce the same post rather than a different one.
        """
        if not self.configured or not query:
            return None

        # CASCADE. The catalogue matches literally against track metadata, not
        # semantically against a mood, so a phrase usually matches nothing at
        # all: MEASURED, "curious minimal ambient" returns zero tracks while
        # "ambient" alone returns plenty. Try the whole phrase first (if it hits,
        # it is the closest thing to the mood asked for), then each word on its
        # own, longest first because the longest word is the most distinctive.
        words = [w for w in query.split() if len(w) > 2]
        attempts = [query] + sorted(words, key=len, reverse=True)

        tracks = []
        used = query
        try:
            async with httpx.AsyncClient() as client:
                for attempt in attempts:
                    r = await client.get(
                        f"{self.base_url}/v2/scheduler/catalogs/instagram/audio",
                        params={"userId": self.user_id, "blogId": self.blog_id,
                                "searchQuery": attempt, "limit": 20},
                        headers=self._headers(), timeout=25.0)
                    if r.status_code != 200:
                        logger.warning("instagram audio search %s: %s",
                                       r.status_code, r.text[:200])
                        continue
                    data = (r.json() or {}).get("data") or {}
                    found = [t for t in (data.get("music") or []) if t.get("audioId")]
                    if found:
                        tracks, used = found, attempt
                        break
        except Exception as e:  # noqa: BLE001 - degrades to a reel with no track
            logger.warning("instagram audio search failed: %s", e)
            return None

        if min_ms:
            long_enough = [t for t in tracks if (t.get("durationMs") or 0) >= min_ms]
            tracks = long_enough or tracks
        if not tracks:
            logger.info("instagram audio: nothing for %r or any word in it", query)
            return None

        idx = int(hashlib.sha256(query.encode()).hexdigest(), 16) % len(tracks)
        t = tracks[idx]
        logger.info("instagram audio: %r (matched on %r) -> %r by %r (%dms, id=%s)",
                    query, used, t.get("title"), t.get("displayArtist"),
                    t.get("durationMs") or 0, t.get("audioId"))
        return t

    # ============================================================
    # payload
    # ============================================================
    def _build_post_data(self, *, blog_id, networks, kind, media, copy,
                         date_str, alt_text=None, first_comment=None,
                         cover_ms=None, audio=None) -> dict:
        """
        The whole payload for one blog. `copy` is postcopy.generate()'s bundle.

        The per-network sub-objects are added only for networks actually in
        `networks`: Metricool validates a sub-object even when its network is
        absent from providers, so a stray youtubeData on an IG-only carousel is
        a 400, not a no-op.
        """
        is_video = kind in ('reel', 'story', 'longform')
        ig = copy.get('instagram') or {}
        tt = copy.get('tiktok') or {}
        yt = copy.get('youtube') or {}
        fb = copy.get('facebook') or {}

        # Per-network caption. This is the point of the whole exercise: four
        # feeds that reward different things stop getting the same paragraph.
        if 'instagram' in networks:
            text = ig.get('caption') or ''
        elif 'tiktok' in networks:
            text = tt.get('caption') or ''
        elif 'facebook' in networks:
            text = fb.get('caption') or ''
        else:
            text = yt.get('description') or ''

        post_data = {
            "publicationDate": {"dateTime": date_str, "timezone": POST_TIMEZONE},
            "text": text,
            "autoPublish": True,
            "draft": False,
            "media": list(media),
            "saveExternalMediaFiles": True,
            "providers": [{"network": n, "id": blog_id} for n in networks],
        }

        if alt_text:
            # One entry per media item; Metricool matches them by index.
            post_data["mediaAltText"] = [alt_text] * len(media)
        if first_comment:
            post_data["firstCommentText"] = first_comment
        if is_video and cover_ms:
            post_data["videoCoverMilliseconds"] = int(cover_ms)

        # --- Instagram -------------------------------------------------------
        if 'instagram' in networks:
            # VERIFIED against the live API, not read off the spec. Metricool
            # rejects anything else with:
            #   "Invalid value 'CAROUSEL'. Valid types are:
            #    'POST, REEL, TRIAL_REEL, STORY'"
            # There is no CAROUSEL and no IMAGE. A carousel is a POST with
            # several media and a still is a POST with one -- the count of
            # `media` is what makes the difference, not the type. The OpenAPI
            # spec's own prose says "IMAGE, REEL, CAROUSEL, STORY", which is
            # where the wrong values came from; the spec describes the
            # ANALYTICS vocabulary, not the scheduler's.
            ig_type = {'reel': 'REEL', 'carousel': 'POST',
                       'image': 'POST', 'story': 'STORY'}[kind]
            ig_data = {
                "autoPublish": not self.instagram_manual_for_audio,
                "type": ig_type,
            }
            if kind == 'reel':
                ig_data["showReelOnFeed"] = self.show_reel_on_feed
                name = ig.get('audio_name') or self.default_audio_name
                if name:
                    # Meta's `audio_name`: a LABEL on the Reel's Original Audio.
                    # It does not attach a track — audioConfiguration does.
                    ig_data["audioName"] = name
                if audio:
                    ig_data["audioConfiguration"] = {
                        "audioId": audio["audioId"],
                        "audioType": audio.get("audioType") or "music",
                        "title": audio.get("title") or "",
                        "displayArtist": audio.get("displayArtist") or "",
                        "durationMs": audio.get("durationMs") or 0,
                        "audioVolume": self.audio_volume,
                        "videoVolume": self.video_volume,
                    }
            post_data["instagramData"] = ig_data
            if self.instagram_manual_for_audio:
                post_data["autoPublish"] = False

        # --- TikTok ----------------------------------------------------------
        if 'tiktok' in networks:
            tiktok_data = {
                "disableComment": False,
                "disableDuet": False,
                "disableStitch": False,
                "privacyOption": "PUBLIC_TO_EVERYONE",
                "title": (tt.get('title') or '')[:80],
                "isAigc": self.tiktok_is_aigc,
            }
            if kind == 'carousel':
                # Photo post. autoAddMusic is REJECTED on video posts with
                # "Only applies for images and carousels" — which means it is
                # accepted HERE, and it is the only route to a trending TikTok
                # sound available to a personal account.
                tiktok_data["photoCoverIndex"] = 0
                tiktok_data["autoAddMusic"] = True
            elif self.tiktok_auto_add_music:
                tiktok_data["autoAddMusic"] = True
            post_data["tiktokData"] = tiktok_data

        # --- YouTube ---------------------------------------------------------
        if 'youtube' in networks:
            yt_data = {
                "title": (yt.get('title') or '')[:100],
                # SHORT for the vertical pieces, VIDEO for the weekly landscape
                # compilation. Getting this wrong does not error, it just files
                # an 8-minute video in the Shorts shelf.
                "type": yt.get('type') or ('VIDEO' if kind == 'longform' else 'SHORT'),
                "privacy": "PUBLIC",
                "madeForKids": False,
            }
            if yt.get('tags'):
                yt_data["tags"] = yt['tags']
            if yt.get('category'):
                yt_data["category"] = yt['category']
            if yt.get('playlist_id'):
                yt_data["playlistId"] = yt['playlist_id']
            post_data["youtubeData"] = yt_data
            # Metricool has no separate YouTube description field: the post text
            # IS the description. When YouTube is the only network that text can
            # be the long form, chapter timestamps and all.
            if yt.get('description') and set(networks) == {'youtube'}:
                post_data["text"] = yt['description']

        # --- Facebook --------------------------------------------------------
        if 'facebook' in networks and kind == 'reel':
            post_data["facebookData"] = {
                "type": "REEL",
                "title": (fb.get('title') or yt.get('title') or '')[:100],
            }

        return post_data

    # ============================================================
    # send
    # ============================================================
    async def _post_once(self, client, blog_id, payload) -> tuple:
        url = f"{self.base_url}/v2/scheduler/posts?userId={self.user_id}&blogId={blog_id}"
        r = await client.post(url, json=payload, headers=self._headers(), timeout=45.0)
        if r.status_code in (200, 201):
            return True, r.json()
        body = (r.json() if r.headers.get("content-type", "").startswith("application/json")
                else r.text)
        return False, {"status": r.status_code, "body": body}

    async def _schedule_for_blog(self, client, blog_id, **kw) -> dict:
        payload = self._build_post_data(blog_id=blog_id, **kw)
        ok, data = await self._post_once(client, blog_id, payload)

        # DEGRADE, DO NOT DIE. The optional enrichments are the fields most
        # likely to be rejected — audioConfiguration is newly used here, and
        # Metricool validates enums server-side. A post that goes out without
        # its music track is a small loss; a slot that publishes nothing
        # because of one optional field is a whole missing post.
        if not ok and str(data.get('status')) == '400':
            for field, where in (('audioConfiguration', 'instagramData'),
                                 ('videoCoverMilliseconds', None),
                                 ('mediaAltText', None),
                                 ('firstCommentText', None)):
                container = payload.get(where) if where else payload
                if not isinstance(container, dict) or field not in container:
                    continue
                dropped = container.pop(field)
                logger.warning(
                    "blog %s rejected the post with %s (%s); retrying without it",
                    blog_id, field, str(data.get('body'))[:200])
                ok, data = await self._post_once(client, blog_id, payload)
                if ok:
                    logger.warning("blog %s: posted WITHOUT %s (dropped %s)",
                                   blog_id, field,
                                   str(dropped)[:80] if not isinstance(dropped, dict)
                                   else sorted(dropped))
                    break

        if ok:
            d = data.get("data", {})
            return {"blog_id": blog_id, "networks": kw['networks'], "success": True,
                    "post_id": d.get("id"), "providers": d.get("providers", []),
                    "scheduled_time": kw['date_str'], "kind": kw['kind']}

        logger.error("Metricool error for blog %s (%s): %s",
                     blog_id, kw['kind'], str(data)[:400])
        return {"blog_id": blog_id, "networks": kw['networks'], "success": False,
                "kind": kw['kind'],
                "error": f"API error {data.get('status')}: {str(data.get('body'))[:300]}"}

    async def schedule(self, *, kind: str, media: list, copy: dict,
                       schedule_time: datetime, include_youtube: bool = True,
                       include_tiktok: bool = True, alt_text: str = None,
                       first_comment: str = None, cover_ms: int = None,
                       audio: dict = None) -> dict:
        """
        Schedule ONE post of one format across every eligible network.

        kind is one of FORMAT_NETWORKS. Networks are the intersection of the
        blog's configured list, the per-slot include_* caps, and the set of
        networks that can actually carry this format.
        """
        if kind not in FORMAT_NETWORKS:
            raise ValueError(f'unknown post kind {kind!r}')
        if not media:
            return {"success": False, "error": f"no media for {kind}", "kind": kind}
        if not self.configured:
            logger.warning("Metricool not configured, skipping %s", kind)
            return {"success": False, "error": "Metricool credentials not configured",
                    "kind": kind}

        st = schedule_time
        if st.tzinfo is None:
            st = st.replace(tzinfo=timezone.utc)
        date_str = st.astimezone(_POST_TZ).strftime("%Y-%m-%dT%H:%M:%S")

        results = []
        try:
            async with httpx.AsyncClient() as client:
                for blog_id in self.blog_ids:
                    if blog_id == "5786828":
                        logger.info("Skipping blog %s: temporarily disabled", blog_id)
                        continue
                    networks = [n for n in self._networks_for_blog(blog_id)
                                if n in FORMAT_NETWORKS[kind]]
                    if not include_youtube:
                        networks = [n for n in networks if n != "youtube"]
                    if not include_tiktok:
                        networks = [n for n in networks if n != "tiktok"]
                    if not networks:
                        logger.info("blog %s: no eligible networks for %s", blog_id, kind)
                        continue

                    logger.info("scheduling %s to blog %s networks=%s at %s",
                                kind, blog_id, networks, date_str)
                    results.append(await self._schedule_for_blog(
                        client, blog_id, networks=networks, kind=kind, media=media,
                        copy=copy, date_str=date_str, alt_text=alt_text,
                        first_comment=first_comment, cover_ms=cover_ms, audio=audio))
        except Exception as e:  # noqa: BLE001 - reported, never raised past here
            logger.error("Metricool scheduling failed for %s: %s", kind, e)
            return {"success": False, "error": str(e), "kind": kind}

        successful = [r for r in results if r.get("success")]
        failed = [r for r in results if not r.get("success")]
        out = {
            "kind": kind,
            "success": bool(successful) and not failed,
            "results": results,
            "post_id": successful[0].get("post_id") if successful else None,
            "providers": successful[0].get("providers", []) if successful else [],
            "scheduled_time": date_str,
        }
        if failed:
            out["error"] = "; ".join(
                f"blog {r.get('blog_id')}: {r.get('error', 'unknown')}" for r in failed)
        if not results:
            out["success"] = False
            out["error"] = f"no eligible networks for {kind}"
        return out

    async def get_scheduled_posts(self) -> list:
        """Currently scheduled posts, across every blog. [] on any failure."""
        if not self.configured:
            return []
        posts = []
        try:
            async with httpx.AsyncClient() as client:
                for blog_id in self.blog_ids:
                    r = await client.get(
                        f"{self.base_url}/v2/scheduler/posts",
                        params={"userId": self.user_id, "blogId": blog_id},
                        headers=self._headers(), timeout=30.0)
                    if r.status_code == 200:
                        for post in r.json().get("data", []):
                            post["_blog_id"] = blog_id
                            posts.append(post)
            return posts
        except Exception:  # noqa: BLE001
            return []
