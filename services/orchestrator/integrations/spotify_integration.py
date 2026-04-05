"""
Samantha OS — Spotify Integration
Music playback control via Spotify Web API.

Setup:
  1. Create app at https://developer.spotify.com/dashboard
  2. Set redirect URI to http://localhost:8888/callback
  3. Set SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET in .env
  4. Run OAuth flow: python -m integrations.spotify_oauth

Requires Spotify Premium for playback control.
"""

from __future__ import annotations
import os
import json
import logging
from datetime import datetime, timedelta

import httpx

from integrations import BaseIntegration, IntegrationAction

logger = logging.getLogger("samantha.spotify")

SPOTIFY_API = "https://api.spotify.com/v1"
SPOTIFY_AUTH = "https://accounts.spotify.com"


class SpotifyIntegration(BaseIntegration):
    name = "spotify"
    display_name = "Spotify"
    description = "Play music, control playback, get recommendations"
    icon = "🎵"
    requires_auth = True

    def __init__(self):
        super().__init__()
        self.client_id: str = ""
        self.client_secret: str = ""
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.token_expiry: datetime | None = None
        self._token_file: str = "config/spotify_token.json"

    async def initialize(self, config: dict) -> bool:
        self.client_id = config.get("client_id", os.getenv("SPOTIFY_CLIENT_ID", ""))
        self.client_secret = config.get("client_secret", os.getenv("SPOTIFY_CLIENT_SECRET", ""))
        self._token_file = config.get("token_file", "config/spotify_token.json")

        if not self.client_id:
            logger.info("Spotify: not configured (set SPOTIFY_CLIENT_ID)")
            return False

        if os.path.exists(self._token_file):
            with open(self._token_file) as f:
                data = json.load(f)
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                exp = data.get("expiry")
                if exp:
                    self.token_expiry = datetime.fromisoformat(exp)

            if self.token_expiry and datetime.now() > self.token_expiry:
                await self._refresh()

            return bool(self.access_token)

        logger.info("Spotify: OAuth required. Run: python -m integrations.spotify_oauth")
        return False

    async def _refresh(self):
        if not self.refresh_token:
            return
        try:
            import base64
            auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{SPOTIFY_AUTH}/api/token", headers={
                    "Authorization": f"Basic {auth}",
                }, data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                })
                data = resp.json()
                self.access_token = data.get("access_token")
                self.token_expiry = datetime.now() + timedelta(seconds=data.get("expires_in", 3600))
                with open(self._token_file, "w") as f:
                    json.dump({"access_token": self.access_token, "refresh_token": self.refresh_token,
                               "expiry": self.token_expiry.isoformat()}, f)
        except Exception as e:
            logger.error(f"Spotify refresh failed: {e}")

    async def _api(self, method: str, path: str, **kwargs) -> dict:
        if self.token_expiry and datetime.now() > self.token_expiry:
            await self._refresh()
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, f"{SPOTIFY_API}{path}",
                headers={"Authorization": f"Bearer {self.access_token}"}, **kwargs)
            if resp.status_code == 204:
                return {"ok": True}
            resp.raise_for_status()
            return resp.json()

    def get_actions(self) -> list[IntegrationAction]:
        return [
            IntegrationAction(
                name="play_music",
                description="Play music on Spotify",
                keywords=["play", "music", "song", "listen to", "put on", "play some"],
                parameters=["query", "type"],
                examples=["Play some jazz", "Put on Radiohead", "Play Clair de Lune"],
            ),
            IntegrationAction(
                name="playback_control",
                description="Control Spotify playback",
                keywords=["pause", "resume", "skip", "next", "previous", "volume", "stop music"],
                parameters=["action", "volume"],
                examples=["Pause the music", "Skip this song", "Turn the volume down"],
            ),
            IntegrationAction(
                name="now_playing",
                description="What's currently playing",
                keywords=["what's playing", "current song", "what song", "what is this"],
                examples=["What's playing right now?", "What song is this?"],
            ),
        ]

    async def execute(self, action_name: str, params: dict) -> dict:
        handlers = {
            "play_music": self._play,
            "playback_control": self._control,
            "now_playing": self._now_playing,
        }
        handler = handlers.get(action_name)
        if not handler:
            return {"error": f"Unknown action: {action_name}"}
        return await handler(params)

    async def _play(self, params: dict) -> dict:
        query = params.get("query", "")
        search_type = params.get("type", "track")
        if not query:
            return {"error": "What should I play?"}

        try:
            results = await self._api("GET", "/search", params={
                "q": query, "type": search_type, "limit": 1,
            })
            items = results.get(f"{search_type}s", {}).get("items", [])
            if not items:
                return {"error": f"Couldn't find '{query}' on Spotify"}

            item = items[0]
            uri = item["uri"]

            # Start playback
            body = {"context_uri": uri} if search_type in ("album", "playlist") else {"uris": [uri]}
            await self._api("PUT", "/me/player/play", json=body)

            return {
                "playing": True,
                "name": item.get("name", query),
                "artist": item.get("artists", [{}])[0].get("name", "") if search_type == "track" else "",
                "type": search_type,
            }
        except Exception as e:
            return {"error": str(e)}

    async def _control(self, params: dict) -> dict:
        action = params.get("action", "")
        try:
            if action in ("pause", "stop"):
                await self._api("PUT", "/me/player/pause")
                return {"action": "paused"}
            elif action in ("resume", "play"):
                await self._api("PUT", "/me/player/play")
                return {"action": "resumed"}
            elif action in ("next", "skip"):
                await self._api("POST", "/me/player/next")
                return {"action": "skipped"}
            elif action == "previous":
                await self._api("POST", "/me/player/previous")
                return {"action": "previous"}
            elif action == "volume":
                vol = params.get("volume", 50)
                await self._api("PUT", "/me/player/volume", params={"volume_percent": vol})
                return {"action": "volume", "volume": vol}
            return {"error": f"Unknown control: {action}"}
        except Exception as e:
            return {"error": str(e)}

    async def _now_playing(self, params: dict) -> dict:
        try:
            data = await self._api("GET", "/me/player/currently-playing")
            if not data or not data.get("item"):
                return {"playing": False}
            item = data["item"]
            return {
                "playing": data.get("is_playing", False),
                "name": item.get("name", "Unknown"),
                "artist": ", ".join(a.get("name", "") for a in item.get("artists", [])),
                "album": item.get("album", {}).get("name", ""),
                "progress_ms": data.get("progress_ms", 0),
                "duration_ms": item.get("duration_ms", 0),
            }
        except Exception as e:
            return {"error": str(e)}

    def get_context_for_llm(self) -> str | None:
        return "You can play music on Spotify, control playback (pause, skip, volume), and check what's playing."
