"""유튜브 라이브 채팅 리더 — pytchat 사용 + 라이브 영상 ID 자동발견.

video_id 는 매 방송 바뀐다. 완전 자동화(사람 손 없이)를 위해 channel
(핸들 @이름 또는 채널 ID UC…)을 주면, 방송 시작 시
https://www.youtube.com/<채널>/live 페이지에서 현재 라이브의 videoId 를
추출한다(비공식·best-effort — 페이지 구조가 바뀌면 보정 필요).

pytchat 는 동기 라이브러리라 블로킹 호출을 asyncio.to_thread 로 감싸
모든 메시지를 빠짐없이 흘려보낸다. pytchat/requests 지연 import.
"""

import asyncio
import logging
import re
from typing import AsyncIterator, Optional

from .base import (ChatMessage, ChatSource, ProbeResult, RetryLog,
                   import_problem, probe_fail, probe_ok, probe_warn)

log = logging.getLogger("aist.chat.youtube")

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
# 라이브 페이지 주소(테스트에서 바꿔 끼울 수 있게 상수로 둔다)
_BASE = "https://www.youtube.com"
_VIDEO_ID_RE = re.compile(r'"videoId"\s*:\s*"([\w-]{11})"')


def resolve_live_video_id(channel: str) -> Optional[str]:
    """채널 핸들(@이름)/채널 ID(UC…) → 현재 라이브 videoId. 없으면 None."""
    import requests
    channel = channel.strip()
    if channel.startswith("UC"):
        url = f"{_BASE}/channel/{channel}/live"
    else:
        handle = channel if channel.startswith("@") else "@" + channel
        url = f"{_BASE}/{handle}/live"
    r = requests.get(url, headers=_UA, timeout=15)
    if r.status_code != 200:
        return None
    # 라이브가 아니면 /live 가 채널 홈으로 이동해 videoId 가 없거나
    # isLiveNow 가 없다. 둘 다 확인한다.
    if '"isLiveNow":true' not in r.text and '"isLive":true' not in r.text:
        return None
    m = _VIDEO_ID_RE.search(r.text)
    return m.group(1) if m else None


class YouTubeChat(ChatSource):
    platform = "youtube"

    def __init__(self, video_id: str = "", channel: str = "",
                 poll_interval: float = 1.0):
        if not video_id and not channel:
            raise ValueError(
                "유튜브 video_id(라이브 영상 ID) 또는 channel(핸들/채널ID)이 필요합니다."
            )
        self.video_id = video_id
        self.channel = channel
        self.poll_interval = poll_interval
        self._chat = None
        self._closed = False
        # 같은 실패를 5초마다 영원히 찍지 않는다. 다른 플랫폼은 이미
        # 이렇게 하는데 유튜브만 빠져 있었다 — 3시간 방송이면 같은 줄이
        # 2천 개 넘게 쌓여 회전 로그가 밀린다.
        self._retry = RetryLog(log, "유튜브 채팅", base=5.0, cap=60.0)
        # 라이브가 시작되기를 기다리는 건 '사고'가 아니라 정상이다.
        # 그래도 30초마다 같은 줄을 찍으면 로그가 그걸로 덮인다.
        self._waits = 0

    async def _ensure_video_id(self) -> Optional[str]:
        if self.video_id:
            return self.video_id
        vid = await asyncio.to_thread(resolve_live_video_id, self.channel)
        if vid:
            log.info("유튜브 라이브 자동발견: %s → video=%s", self.channel, vid)
        return vid

    async def messages(self) -> AsyncIterator[ChatMessage]:
        try:
            import pytchat  # 지연 import
        except ImportError as e:
            # 다시 시도해도 안 고쳐진다. 예외를 올리면 오케스트레이터가
            # 소스를 계속 새로 만들며 같은 실패를 반복한다 — 다른
            # 플랫폼처럼 fatal 로 알리고 조용히 물러난다.
            fatal = import_problem(e, "pytchat")
            log.error("%s", fatal)
            self.fatal = fatal or "pytchat 미설치"
            return

        while not self._closed:
            try:
                vid = await self._ensure_video_id()
            except Exception as e:  # noqa: BLE001 - DNS·타임아웃 등
                # 예전에는 이 예외가 messages() 밖으로 그대로 나갔다.
                # 순간적인 네트워크 끊김 한 번에 그 방송의 유튜브 채팅이
                # 통째로 끝났다(실제 실행으로 확인). 다른 플랫폼처럼
                # 제자리에서 다시 시도한다.
                if self._closed:
                    break
                await asyncio.sleep(self._retry.failure(e))
                continue
            if not vid:
                # 아직 방송 전인 경우가 대부분이다(자동발견의 정상 동작).
                self._waits += 1
                if self._waits in (1, 10) or self._waits % 60 == 0:
                    log.info("유튜브: 아직 라이브가 아님(%s) — 30초마다 다시 봅니다"
                             "(%d번째)", self.channel, self._waits)
                await asyncio.sleep(30)
                continue
            self._waits = 0
            try:
                self._chat = pytchat.create(video_id=vid)
                log.info("유튜브 라이브 채팅 연결됨 (video=%s)", vid)
                self._retry.success()
                while self._chat.is_alive() and not self._closed:
                    data = await asyncio.to_thread(self._chat.get)
                    for item in data.sync_items():
                        is_sc = getattr(item, "type", "") in ("superChat", "superSticker")
                        yield ChatMessage(
                            author=getattr(item.author, "name", "?"),
                            text=getattr(item, "message", "") or "",
                            platform=self.platform,
                            is_superchat=is_sc,
                            amount=getattr(item, "amountString", ""),
                            raw=item,
                        )
                    await asyncio.sleep(self.poll_interval)
            except Exception as e:
                if self._closed:
                    break
                await asyncio.sleep(self._retry.failure(e))
            finally:
                if self._chat is not None:
                    try:
                        self._chat.terminate()
                    except Exception:
                        pass
                    self._chat = None
                # 자동발견 모드면 다음 루프에서 새 라이브를 다시 찾는다
                if self.channel and not self._closed:
                    self.video_id = ""

    async def probe(self) -> ProbeResult:
        if self.video_id:
            return probe_ok(f"video_id 직접 지정됨({self.video_id})")
        try:
            vid = await asyncio.to_thread(resolve_live_video_id, self.channel)
            if vid:
                return probe_ok(f"라이브 발견(video {vid})")
            return probe_warn("라이브 아님(방송 전이면 정상 — 시작하면 자동발견)")
        except Exception as e:
            return probe_fail(f"자동발견 실패: {e}")

    async def close(self) -> None:
        self._closed = True
        if self._chat is not None:
            try:
                self._chat.terminate()
            finally:
                self._chat = None
