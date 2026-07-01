"""시작 자동화 (심장박동) — 5단계.

요일별 패턴으로 다음 방송 시각을 계산한다. 랜덤 변주(jitter)는 선택이며
기본 0(정확히 그 시각)이다. "봇 티 난다"며 코드가 강제로 변주를 넣지
않는다 — 넣을지는 운영자가 config 로 정한다.

순수 함수 위주로 짜서, 종료판단과 함께 GPU/네트워크 없이 테스트된다.
"""

import random
from datetime import datetime, time, timedelta
from typing import List, Optional

from .config import SchedulerConfig

# datetime.weekday(): 월=0 ... 일=6
_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse_hhmm(s: str) -> time:
    parts = s.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"시각 형식이 잘못됨(HH:MM 이어야 함): {s!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"시각 범위 오류: {s!r}")
    return time(hour=h, minute=m)


class Scheduler:
    def __init__(self, cfg: SchedulerConfig):
        self.cfg = cfg

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled

    def _times_for(self, weekday_key: str) -> List[time]:
        raw = self.cfg.weekly.get(weekday_key, []) or []
        return sorted(_parse_hhmm(s) for s in raw)

    def next_slot(self, now: datetime, lookahead_days: int = 15) -> Optional[datetime]:
        """now 이후의 다음 예정 슬롯(랜덤 변주 적용 전). 휴방일은 건너뛴다.

        앞으로 lookahead_days 일 안에 어떤 시각도 없으면(전부 휴방) None.
        now 의 tzinfo 를 그대로 따른다(aware 면 aware, naive 면 naive).
        """
        for offset in range(0, lookahead_days):
            day = (now + timedelta(days=offset)).date()
            key = _WEEKDAYS[day.weekday()]
            for t in self._times_for(key):
                slot = datetime.combine(day, t, tzinfo=now.tzinfo)
                if slot >= now:
                    return slot
        return None

    def next_start(
        self,
        now: datetime,
        rng: Optional[random.Random] = None,
    ) -> Optional[datetime]:
        """실제 시작 시각 = 다음 슬롯 + (선택) 랜덤 변주.

        rng 를 주입할 수 있어 테스트에서 결정적이다. 변주로 인해 과거가
        되면 now 로 당긴다(이미 지난 시각에 시작하지 않게).
        """
        slot = self.next_slot(now)
        if slot is None:
            return None
        j = self.cfg.start_jitter_min
        if j and j > 0:
            r = rng or random
            if self.cfg.jitter_mode == "symmetric":
                delta = r.randint(-j, j)
            else:  # "after" — 늦게만 흩뜨림
                delta = r.randint(0, j)
            slot = slot + timedelta(minutes=delta)
            if slot < now:
                slot = now
        return slot

    @staticmethod
    def seconds_until(target: datetime, now: datetime) -> float:
        return max(0.0, (target - now).total_seconds())

    def is_rest_day(self, now: datetime) -> bool:
        """오늘 예정된 시각이 하나도 없으면 휴방일."""
        key = _WEEKDAYS[now.date().weekday()]
        return len(self._times_for(key)) == 0
