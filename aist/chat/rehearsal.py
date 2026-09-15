"""리허설용 가짜 채팅 — 플랫폼·키 없이 방송 루프를 돌려보기 위한 것.

코어(Open-LLM-VTuber)만 띄워두면 실제 방송 흐름(여는 인사 → 채팅 반응 →
혼잣말 → 마무리 인사)이 그대로 도는지 눈으로 확인할 수 있다. 플랫폼
계정도, 스트림 키도, OBS 도 필요 없다.

실제 방송에는 쓰지 않는다(`platform: rehearsal` 일 때만 만들어진다).
"""

import asyncio
import random
from datetime import datetime, timezone
from typing import AsyncIterator

from .base import ChatMessage, ChatSource, ProbeResult, probe_fail, probe_ok, probe_warn

# 사람이 실제로 치는 정도의 짧은 말들. 방송인이 반응할 거리를 준다.
_LINES = [
    "안녕하세요~", "오늘도 왔어요", "ㅋㅋㅋㅋㅋ", "목소리 좋다",
    "오늘 뭐 해요?", "저 처음 왔어요", "노래 불러주세요",
    "밥은 먹었어요?", "여기 자주 오는 편", "화면 잘 나와요",
    "그거 진짜예요?", "오 방금 그거 웃김", "다음 방송 언제예요?",
]
_NAMES = ["별하나", "지나가던시청자", "새벽감성", "김뚝딱", "라면조아", "익명123"]


class RehearsalChat(ChatSource):
    """일정 간격으로 가짜 채팅을 흘려보낸다. 가끔 후원도 섞는다."""

    platform = "rehearsal"

    def __init__(self, interval_sec: float = 4.0, superchat_every: int = 7,
                 seed: int | None = None):
        self.interval_sec = max(0.2, interval_sec)
        self.superchat_every = max(0, superchat_every)
        self._rand = random.Random(seed)
        self._n = 0

    async def messages(self) -> AsyncIterator[ChatMessage]:
        while True:
            await asyncio.sleep(self.interval_sec)
            self._n += 1
            now = datetime.now(timezone.utc)
            is_sc = self.superchat_every and self._n % self.superchat_every == 0
            if is_sc:
                yield ChatMessage(
                    author=self._rand.choice(_NAMES), text="오늘 방송 재밌어요!",
                    platform=self.platform, timestamp=now,
                    is_superchat=True, amount="5,000원",
                )
            else:
                yield ChatMessage(
                    author=self._rand.choice(_NAMES),
                    text=self._rand.choice(_LINES),
                    platform=self.platform, timestamp=now,
                )

    async def probe(self) -> ProbeResult:
        return probe_ok(f"리허설용 가짜 채팅 (약 {self.interval_sec:g}초마다)")
