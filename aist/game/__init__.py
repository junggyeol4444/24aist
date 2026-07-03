"""게임 플레이 (8단계, 선택) — 봇 연동이 쉬운 게임부터.

구조: 게임 쪽은 사이드카(예: mineflayer 봇, game/minecraft/bot.js)가 맡고,
이벤트를 WebSocket JSON 으로 중계한다. 여기의 GameFeed 는 그 이벤트를
받아 AI 반응(코어 text-input)으로 잇는다. 게임 중에도 채팅 소통은
채팅 파이프라인이 그대로 유지한다(기획안 8단계 요구).
"""

from .minecraft import MinecraftFeed

__all__ = ["MinecraftFeed"]
