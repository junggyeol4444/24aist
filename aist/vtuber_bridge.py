"""Open-LLM-VTuber 브릿지 — 방송 코어(두뇌+입+얼굴)에 입력을 흘려보낸다.

Open-LLM-VTuber 는 WebSocket 서버(`/client-ws`, 기본 포트 12393)를 연다.
우리가 보내는 메시지 타입(코어 소스 기준):
  - {"type": "text-input", "text": "..."}   → AI 가 그 입력에 반응(대화 트리거)
  - {"type": "ai-speak-signal"}             → 능동 발화(혼잣말) 트리거
  - {"type": "interrupt-signal", "text": ""} → 현재 발화 끼어들기/중단

채팅 한 줄을 받으면 text-input 으로 그대로 흘려보내, 코어의 LLM+페르소나가
반응을 만들고 TTS+Live2D 로 출력한다. 여기서 채팅을 선별하거나 딜레이를
주지 않는다(그 판단은 운영자 몫).

websockets 는 지연 import.
"""

import asyncio
import json
import logging
from typing import Optional

from .config import VTuberConfig

log = logging.getLogger("aist.vtuber")

# 플랫폼 한글 표기(동출 때 어디서 온 채팅인지 자연스럽게 알리는 용도)
_PLATFORM_KR = {
    "twitch": "트위치", "youtube": "유튜브", "chzzk": "치지직",
    "soop": "숲", "kick": "킥", "twitcasting": "트위캐스팅",
    "minecraft": "게임",
}


def format_chat_line(text: str, source: Optional[str] = None,
                     platform: Optional[str] = None) -> str:
    """채팅 한 줄을 자연스러운 형식으로. 로봇 태그([닉/twitch]) 금지.

    - "neo: 안녕"                (기본)
    - "neo (치지직): 안녕"       (동출 등 플랫폼 구분이 필요할 때만)
    """
    if not source:
        return text
    if platform:
        kr = _PLATFORM_KR.get(platform, platform)
        return f"{source} ({kr}): {text}"
    return f"{source}: {text}"


class VTuberBridge:
    def __init__(self, cfg: VTuberConfig):
        self.cfg = cfg
        self._ws = None
        self._lock = asyncio.Lock()

    async def connect(self):
        try:
            import websockets  # 지연 import
        except ImportError as e:
            raise RuntimeError(
                "websockets 가 설치되어 있지 않습니다. `pip install websockets`"
            ) from e
        # reconnect=True 면 코어가 조금 늦게 떠도 되도록 초기 연결을 재시도한다.
        attempts = 6 if self.cfg.reconnect else 1
        last_err = None
        for i in range(attempts):
            try:
                self._ws = await asyncio.wait_for(
                    websockets.connect(self.cfg.ws_url, max_size=None),
                    timeout=self.cfg.connect_timeout_sec,
                )
                log.info("Open-LLM-VTuber 연결됨 (%s)", self.cfg.ws_url)
                return self
            except Exception as e:  # noqa: BLE001 - 연결 실패 사유 다양
                last_err = e
                if i < attempts - 1:
                    wait = min(2 ** i, 10)
                    log.info("코어 연결 재시도 %d/%d (%.0fs 후): %s", i + 1, attempts, wait, e)
                    await asyncio.sleep(wait)
        raise last_err

    async def _send(self, payload: dict):
        if self._ws is None:
            raise RuntimeError("VTuber 코어에 먼저 connect() 해야 합니다.")
        async with self._lock:
            await self._ws.send(json.dumps(payload, ensure_ascii=False))

    async def say_to_ai(self, text: str, source: Optional[str] = None,
                        platform: Optional[str] = None):
        """채팅/입력을 AI 에게 전달해 반응을 만들게 한다.

        source(닉네임)가 있으면 "닉: 내용" 자연 형식으로, platform 은
        동출처럼 구분이 필요할 때만 넘긴다("닉 (치지직): 내용").
        AI 가 따라 읽어도 어색하지 않은 형식만 쓴다.
        """
        await self._send({"type": "text-input",
                          "text": format_chat_line(text, source, platform)})

    async def proactive_speak(self):
        """채팅이 정말 없을 때 혼잣말 트리거(능동 발화)."""
        await self._send({"type": "ai-speak-signal"})

    async def interrupt(self, heard_text: str = ""):
        await self._send({"type": "interrupt-signal", "text": heard_text})

    async def recv_loop(self, on_message=None):
        """코어가 보내는 메시지(자막/오디오 시작 등)를 받는다. 선택 사용.

        on_message(dict) 콜백이 있으면 호출. 종료 판단의 보조 신호로 쓸 수
        있다(예: audio-play-start 로 발화 중 여부 파악).
        """
        if self._ws is None:
            raise RuntimeError("connect() 먼저.")
        async for raw in self._ws:
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if on_message is not None:
                on_message(data)

    async def close(self):
        if self._ws is not None:
            try:
                await self._ws.close()
            finally:
                self._ws = None
