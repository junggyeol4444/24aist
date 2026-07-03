"""마인크래프트 연동 — mineflayer 사이드카의 이벤트를 AI 반응으로 잇는다.

사이드카(game/minecraft/bot.js)가 보내는 이벤트(JSON 한 줄씩):
  {"event": "spawn"}
  {"event": "death"}
  {"event": "respawn"}
  {"event": "kicked", "reason": "..."}
  {"event": "health_low", "health": 4}
  {"event": "chat", "username": "Steve", "message": "hi"}

처리:
- react_events 에 있는 이벤트 → 상황 안내 큐를 코어로 보내 AI 가
  캐릭터답게 반응하게 한다("어 죽었다" 등 — 정확한 말은 페르소나가 정함).
- 게임 내 채팅(chat) → forward_game_chat=true 면 시청자 채팅처럼
  [닉/minecraft] 태그로 전달(게임 중에도 소통 유지).

사이드카가 죽으면 재연결한다(best-effort). websockets 지연 import.
"""

import asyncio
import json
import logging
from typing import Optional

from ..config import GameConfig
from ..vtuber_bridge import VTuberBridge

log = logging.getLogger("aist.game.minecraft")

# 이벤트 → 상황 안내 큐. "이렇게 말해라"가 아니라 상황만 알린다(3부 원칙).
_EVENT_CUES = {
    "spawn": "(게임 상황: 마인크래프트 월드에 접속했어.)",
    "death": "(게임 상황: 방금 게임에서 죽었어.)",
    "respawn": "(게임 상황: 리스폰해서 다시 시작했어.)",
    "kicked": "(게임 상황: 서버에서 튕겼어.)",
    "health_low": "(게임 상황: 체력이 얼마 안 남았어. 위험한 상황이야.)",
}


class MinecraftFeed:
    def __init__(self, bridge: VTuberBridge, cfg: GameConfig,
                 on_event=None):
        self.bridge = bridge
        self.cfg = cfg
        self.on_event = on_event      # 트랜스크립트/기억 기록용 콜백(선택)
        self._closed = False
        self._ws = None

    async def run(self, stop_event: asyncio.Event):
        """사이드카에 붙어 이벤트를 소비. stop_event 로 종료."""
        consumer = asyncio.create_task(self._consume())
        try:
            await stop_event.wait()
        finally:
            self._closed = True
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)
            if self._ws is not None:
                try:
                    await self._ws.close()
                finally:
                    self._ws = None

    async def _consume(self):
        import websockets  # 지연 import
        while not self._closed:
            try:
                async with websockets.connect(self.cfg.ws_url, max_size=None) as ws:
                    self._ws = ws
                    log.info("마인크래프트 사이드카 연결됨 (%s)", self.cfg.ws_url)
                    async for raw in ws:
                        try:
                            data = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        await self._handle(data)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if self._closed:
                    break
                log.warning("사이드카 연결 끊김: %s (5초 후 재연결)", e)
                await asyncio.sleep(5)

    async def _handle(self, data: dict):
        event = data.get("event", "")
        if self.on_event is not None:
            try:
                self.on_event(data)
            except Exception:
                log.debug("게임 이벤트 콜백 실패", exc_info=True)

        if event == "chat":
            if self.cfg.forward_game_chat:
                username = data.get("username", "?")
                message = data.get("message", "")
                if message:
                    await self._safe_say(message, source=username, platform="minecraft")
            return

        if event in self.cfg.react_events:
            cue = _EVENT_CUES.get(event)
            if cue is None:
                cue = f"(게임 상황: {event})"
            await self._safe_say(cue)

    async def _safe_say(self, text: str, source: Optional[str] = None,
                        platform: Optional[str] = None):
        try:
            await self.bridge.say_to_ai(text, source=source, platform=platform)
        except Exception as e:
            log.debug("게임 반응 전달 실패(무시): %s", e)

    async def send_command(self, cmd: dict):
        """사이드카로 명령 전송(예: {"cmd":"say","text":"gg"}). 선택 기능."""
        if self._ws is None:
            raise RuntimeError("사이드카에 연결돼 있지 않습니다.")
        await self._ws.send(json.dumps(cmd, ensure_ascii=False))
