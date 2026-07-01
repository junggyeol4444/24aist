"""종료 판단 (감각) — 4단계. 기획안의 "진짜 핵심".

AI 가 감으로 분위기를 읽는 게 아니라, "종료할 만한 상황"을 조건으로
정의해 조합한다. 어떤 조건을 쓸지/값을 얼마로 할지는 전부 운영자가
config 로 정한다. 랜덤 변주도 선택이다.

종료 트리거(조합):
- 최대 방송 시간 도달 (가장 기본)
- 최소 방송 시간 보장 (켜자마자 끄지 않음 — 항상 지켜짐)
- (선택) 채팅 저조 지속 → 조기 종료 고려
- (선택) 정해진 종료 시각대 넘으면 마무리
- (선택) 종료 시각 랜덤 변주
- 자연스러운 마무리(뚝 끄지 않음): 예고(PRE_NOTICE) → 마무리 인사 → 종료

evaluate() 는 '현재 시점에 어떤 단계여야 하는가'를 멱등하게 돌려준다.
실제 "예고 멘트/마무리 인사를 한 번만 한다"는 전이 처리는 오케스트레이터가
한다(여기선 판단만).
"""

import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Optional

from .config import EndJudgeConfig


class Phase(str, Enum):
    LIVE = "live"            # 계속 진행
    PRE_NOTICE = "pre_notice"  # "슬슬 마무리할까" 예고 단계 (wind_down)
    END = "end"             # 지금 종료 (오케스트레이터가 마무리 인사 후 OBS 종료)


@dataclass
class EndDecision:
    phase: Phase
    trigger: str    # "" | "max_time" | "scheduled_end" | "chat_low"
    detail: str     # 사람이 읽는 사유(로그용, 한국어)


def _parse_hhmm(s: str) -> time:
    h, m = s.strip().split(":")
    return time(hour=int(h), minute=int(m))


class EndJudge:
    """방송 1회분의 종료를 판단. 시작 시 종료 시각을 미리 확정한다."""

    def __init__(
        self,
        cfg: EndJudgeConfig,
        start: datetime,
        rng: Optional[random.Random] = None,
    ):
        self.cfg = cfg
        self.start = start

        # 종료 랜덤 변주(선택). 0 이면 정확히 max_minutes.
        self._jitter_min = 0
        if cfg.end_jitter_min and cfg.end_jitter_min > 0:
            r = rng or random
            self._jitter_min = r.randint(-cfg.end_jitter_min, cfg.end_jitter_min)

        self.hard_end = start + timedelta(minutes=cfg.max_minutes + self._jitter_min)
        self.min_end = start + timedelta(minutes=cfg.min_minutes)
        self.scheduled_end = self._scheduled_end_dt(start)

        # 예정 종료 시각 = (정해진 종료 시각 vs 최대 시간) 중 빠른 쪽,
        # 단 최소 방송 시간은 무조건 보장.
        if self.scheduled_end is not None and self.scheduled_end < self.hard_end:
            candidate, reason = self.scheduled_end, "scheduled_end"
        else:
            candidate, reason = self.hard_end, "max_time"

        if candidate < self.min_end:
            self.planned_end = self.min_end   # 최소 시간 보장이 종료를 뒤로 민 경우
        else:
            self.planned_end = candidate
        self.planned_trigger = reason

    def _scheduled_end_dt(self, start: datetime) -> Optional[datetime]:
        if not self.cfg.scheduled_end_hhmm:
            return None
        t = _parse_hhmm(self.cfg.scheduled_end_hhmm)
        cand = datetime.combine(start.date(), t, tzinfo=start.tzinfo)
        if cand <= start:           # 그 시각이 이미 지났으면 다음 날로
            cand += timedelta(days=1)
        return cand

    def evaluate(
        self,
        now: datetime,
        last_chat_time: Optional[datetime] = None,
    ) -> EndDecision:
        """현재 시점의 종료 단계를 판단한다(멱등)."""
        effective_end = self.planned_end
        trigger = self.planned_trigger

        # (선택) 채팅 저조 → 조기 종료. 단 최소 방송 시간 이후에만.
        if self.cfg.chat_low.enabled and last_chat_time is not None:
            elapsed_min = (now - self.start).total_seconds() / 60.0
            quiet_min = (now - last_chat_time).total_seconds() / 60.0
            if (
                elapsed_min >= self.cfg.min_minutes
                and quiet_min >= self.cfg.chat_low.quiet_minutes
                and now < effective_end
            ):
                effective_end = now
                trigger = "chat_low"

        if now >= effective_end:
            return EndDecision(Phase.END, trigger, self._detail(trigger))

        # 자연스러운 마무리 예고 단계(선택). 최소 시간 전에는 예고하지 않음.
        wd = self.cfg.wind_down
        if wd.enabled and wd.pre_notice_minutes_before_end > 0:
            pre_at = effective_end - timedelta(minutes=wd.pre_notice_minutes_before_end)
            if pre_at < self.min_end:
                pre_at = self.min_end
            if now >= pre_at:
                return EndDecision(Phase.PRE_NOTICE, trigger, "마무리 예고 단계")

        return EndDecision(Phase.LIVE, "", "")

    def _detail(self, trigger: str) -> str:
        return {
            "max_time": f"최대 방송 시간 도달(약 {self.cfg.max_minutes}분, 변주 {self._jitter_min:+d}분)",
            "scheduled_end": f"정해진 종료 시각대({self.cfg.scheduled_end_hhmm}) 도달",
            "chat_low": f"채팅 저조 {self.cfg.chat_low.quiet_minutes}분 지속(최소 시간 이후)",
        }.get(trigger, "종료 조건 충족")
