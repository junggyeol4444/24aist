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

from .base import ChatMessage, ChatSource, ProbeResult, probe_fail, probe_ok, probe_warn

log = logging.getLogger("aist.chat.twitcasting")

_API = "https://apiv2.twitcasting.tv"
# 이미 본 코멘트 id 보관 상한(오래 돌수록 무한히 쌓이지 않게)
_SEEN_MAX = 5000
_SEEN_KEEP = 2000


class TwitcastingChat(ChatSource):
    platform = "twitcasting"

    def __init__(self, user_id: str, access_token: str, poll_interval: float = 3.0):
        if not user_id:
            raise ValueError("트위캐스팅 user_id 가 필요합니다 (config chat.twitcasting.user_id).")
        if not access_token:
            raise ValueError("트위캐스팅 access_token 이 필요합니다 (.env TWITCASTING_ACCESS_TOKEN).")
        from ..safety import token_problem
        problem = token_problem("TWITCASTING_ACCESS_TOKEN", access_token)
        if problem:
            # 이걸 그냥 두면 폴링 때마다 latin-1 오류만 반복되고 채팅은
            # 영영 안 들어온다. 시작할 때 사람이 읽는 사유로 막는다.
            raise ValueError(problem)
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
        """(코멘트 목록, 이 방송이 끝났는지)."""
        import requests
        r = requests.get(f"{_API}/movies/{movie_id}/comments",
                         headers=self._headers(), params={"limit": 50}, timeout=10)
        if r.status_code in (404, 410):
            # 방송이 끝났거나 movie 가 바뀌었다. 계속 같은 movie 를 찔러봐야
            # 영영 빈 목록만 온다 — 채팅이 조용히 멈춘 것처럼 보인다.
            return [], True
        if r.status_code != 200:
            return [], False
        return (r.json() or {}).get("comments", []), False

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
                    self.connected_once = True
                comments, gone = await asyncio.to_thread(
                    self._fetch_comments, movie_id)
                if gone:
                    log.info("트위캐스팅: 이 방송(movie=%s)이 끝났습니다 — "
                             "새 방송을 다시 찾습니다.", movie_id)
                    movie_id = None
                    first = True          # 새 방송의 과거 댓글은 흘리지 않는다
                    self._seen.clear()
                    await asyncio.sleep(self.poll_interval)
                    continue
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
                # 몇 시간 방송이면 id 가 수천 개 쌓인다. 최근 것만 있으면 된다.
                if len(self._seen) > _SEEN_MAX:
                    self._seen = set(list(self._seen)[-_SEEN_KEEP:])
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

    async def probe(self) -> ProbeResult:
        try:
            mid = await asyncio.to_thread(self._current_movie_id)
            if mid:
                return probe_ok(f"라이브 OK(movie {mid})")
            return probe_warn("라이브 아님(방송 전이면 정상, 아니면 토큰 확인)")
        except Exception as e:
            return probe_fail(f"조회 실패(토큰 확인): {e}")

    async def close(self) -> None:
        self._closed = True
