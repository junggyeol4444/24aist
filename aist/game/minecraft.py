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
from ..safety import sanitize_incoming
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
                 on_event=None, on_chat=None):
        self.bridge = bridge
        self.cfg = cfg
        self.on_event = on_event      # 트랜스크립트/기억 기록용 콜백(선택)
        # 게임 안 채팅을 넘길 곳(비동기). 채팅 파이프라인에 물려야
        # '입 하나'·폭주 처리·기록이 시청자 채팅과 똑같이 적용된다.
        # 없으면 예전처럼 코어로 직접 보낸다(테스트·단독 사용).
        self.on_chat = on_chat
        self._closed = False
        self._ws = None
        self._last_cue = {}          # 이벤트별 마지막 반응 시각(도배 방지)

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
                # 게임 채팅도 시청자 채팅과 똑같이 소독한다. 안 하면 게임
                # 서버의 다른 플레이어가 개행으로 시스템 신호를 위조해
                # 방송인을 조종할 수 있다(시청자 채팅에는 있는 보호가
                # 여기만 빠져 있었다).
                message, username = sanitize_incoming(
                    data.get("message", ""), data.get("username", "?"))
                if message:
                    await self._forward_chat(message, username)
            return

        if event in self.cfg.react_events:
            if not self._cue_allowed(event):
                return
            cue = _EVENT_CUES.get(event)
            if cue is None:
                # 모르는 이벤트 이름도 외부 입력이다 — 그대로 큐에 넣으면
                # 사이드카가 임의 문자열로 시스템 신호를 만들 수 있다.
                safe_event, _ = sanitize_incoming(str(event), "")
                cue = f"(게임 상황: {safe_event})"
            await self._safe_say(cue)

    async def _forward_chat(self, message: str, username: str):
        """게임 안 채팅을 시청자 채팅과 같은 길로 넣는다.

        예전에는 코어로 바로 쐈다. 그러면 방송인이 게임 채팅 하나하나에
        전부 대답하느라 시청자 채팅이 묻힌다 — 2초에 한 줄 오는 한산한
        서버로 3분을 돌려보니, 코어가 받은 134줄 중 80줄이 게임 채팅이었다.
        """
        if self.on_chat is None:
            await self._safe_say(message, source=username, platform="minecraft")
            return
        from ..chat.base import ChatMessage
        try:
            await self.on_chat(ChatMessage(
                author=username, text=message, platform="minecraft",
                from_game=True))
        except Exception as e:  # noqa: BLE001 - 게임 때문에 방송이 죽지 않게
            log.debug("게임 채팅 전달 실패(무시): %s", e)

    def _cue_allowed(self, event: str) -> bool:
        """같은 이벤트에 너무 자주 반응하지 않게 한다.

        health_low 같은 이벤트는 사이드카가 초당 여러 번 보낼 수 있다.
        게임 상황 안내는 채팅 파이프라인('입 하나')을 거치지 않고 코어로
        바로 가기 때문에, 막지 않으면 AI 가 게임 안내에 파묻혀 시청자
        채팅에 반응을 못 한다. 간격은 운영자가 정한다(0 이면 제한 없음).
        """
        cooldown = float(getattr(self.cfg, "event_cooldown_sec", 0) or 0)
        if cooldown <= 0:
            return True
        import time as _t
        now = _t.monotonic()
        last = self._last_cue.get(event)
        if last is not None and now - last < cooldown:
            return False
        self._last_cue[event] = now
        return True

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
