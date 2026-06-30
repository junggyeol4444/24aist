"""트위캐스팅(TwitCasting) 채팅 리더 — 공식 API v2 코멘트 폴링.

공식 API 라 OAuth2 액세스 토큰이 필요하다(.env TWITCASTING_ACCESS_TOKEN).
흐름:
  1) GET /users/{user_id}/current_live → 현재 라이브의 movie_id
  2) GET /movies/{movie_id}/comments 주기적 폴링 → 새 코멘트만 yield
헤더: Accept: application/json, X-Api-Version: 2.0, Authorization: Bearer ...

처음 폴링분은 과거 댓글이라 흘리지 않고(seen 처리), 이후 새 댓글만 보낸다.
requests 지연 import, 호출은 asyncio.to_thread.
"""

import asyncio
import logging
from typing import AsyncIterator, Optional, Set

from .base import ChatMessage, ChatSource

log = logging.getLogger("aist.chat.twitcasting")

_API = "https://apiv2.twitcasting.tv"


class TwitcastingChat(ChatSource):
    platform = "twitcasting"

    def __init__(self, user_id: str, access_token: str, poll_interval: float = 3.0):
        if not user_id:
            raise ValueError("트위캐스팅 user_id 가 필요합니다 (config chat.twitcasting.user_id).")
        if not access_token:
            raise ValueError("트위캐스팅 access_token 이 필요합니다 (.env TWITCASTING_ACCESS_TOKEN).")
        self.user_id = user_id
        self.access_token = access_token
        self.poll_interval = poll_interval
        self._closed = False
        self._seen: Set[str] = set()

    def _headers(self):
        return {
            "Accept": "application/json",
            "X-Api-Version": "2.0",
            "Authorization": f"Bearer {self.access_token}",
        }

    def _current_movie_id(self) -> Optional[str]:
        import requests
        r = requests.get(f"{_API}/users/{self.user_id}/current_live",
                         headers=self._headers(), timeout=10)
        if r.status_code != 200:
            return None
        return ((r.json() or {}).get("movie") or {}).get("id")

    def _fetch_comments(self, movie_id: str):
        import requests
        r = requests.get(f"{_API}/movies/{movie_id}/comments",
                         headers=self._headers(), params={"limit": 50}, timeout=10)
        if r.status_code != 200:
            return []
        return (r.json() or {}).get("comments", [])

    async def messages(self) -> AsyncIterator[ChatMessage]:
        movie_id = None
        first = True
        while not self._closed:
            try:
                if movie_id is None:
                    movie_id = await asyncio.to_thread(self._current_movie_id)
                    if movie_id is None:
                        await asyncio.sleep(self.poll_interval)
                        continue
                    log.info("트위캐스팅 라이브 발견 (movie=%s)", movie_id)
                comments = await asyncio.to_thread(self._fetch_comments, movie_id)
            except Exception as e:
                log.warning("트위캐스팅 폴링 오류: %s", e)
                await asyncio.sleep(self.poll_interval)
                continue
            # 오래된 것부터 보내기 위해 역순(API 는 최신순)
            for c in reversed(comments):
                cid = str(c.get("id"))
                if cid in self._seen:
                    continue
                self._seen.add(cid)
                if first:
                    continue  # 첫 폴링분(과거 댓글)은 흘리지 않음
                user = c.get("from_user") or {}
                yield ChatMessage(
                    author=user.get("name") or user.get("screen_id") or "?",
                    text=c.get("message", ""),
                    platform=self.platform, raw=c,
                )
            first = False
            await asyncio.sleep(self.poll_interval)

    async def close(self) -> None:
        self._closed = True
