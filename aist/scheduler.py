"""시작 자동화 (심장박동) — 5단계.

요일별 패턴으로 다음 방송 시각을 계산한다. 랜덤 변주(jitter)는 선택이며
기본 0(정확히 그 시각)이다. "봇 티 난다"며 코드가 강제로 변주를 넣지
않는다 — 넣을지는 운영자가 config 로 정한다.

순수 함수 위주로 짜서, 종료판단과 함께 GPU/네트워크 없이 테스트된다.
"""

import logging
import random
from datetime import datetime, time, timedelta
from typing import List, Optional

from .config import SchedulerConfig

log = logging.getLogger("aist.scheduler")

# datetime.weekday(): 월=0 ... 일=6
_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse_hhmm(s) -> time:
    """"HH:MM" → time. 사람이 고칠 수 있는 한국어 오류만 올린다.

    따옴표를 빼고 `- 19:00` 이라고 적으면 YAML 이 그걸 **숫자 1140** 으로
    읽는다(YAML 1.1 의 60진수 표기). 그대로 두면 'int 에 strip 이 없다'
    같은 파이썬 오류가 뜨는데, 운영자는 뭘 고쳐야 할지 알 수 없다.
    """
    if isinstance(s, bool) or not isinstance(s, str):
        if isinstance(s, int) and 0 <= s < 24 * 60:
            h, m = divmod(s, 60)
            raise ValueError(
                f'시각에 따옴표가 빠졌습니다 → "{h:02d}:{m:02d}" 처럼 따옴표로 '
                f"감싸세요. (따옴표가 없으면 YAML 이 숫자 {s} 로 읽습니다)")
        raise ValueError(f'시각은 "HH:MM" 형식의 문자열이어야 합니다: {s!r}')
    parts = s.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"시각 형식이 잘못됨(HH:MM 이어야 함): {s!r}")
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(f"시각에 숫자가 아닌 게 있습니다(HH:MM): {s!r}") from None
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"시각 범위 오류: {s!r}")
    return time(hour=h, minute=m)


def as_time_list(raw) -> list:
    """설정의 요일 값 → 시각 문자열 목록. 한 줄로 적은 것도 받아준다."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]          # weekly: {mon: "19:00"} 처럼 한 줄로 적은 경우
    if isinstance(raw, (list, tuple)):
        return list(raw)
    return [raw]              # 숫자 등 — _parse_hhmm 이 사람 말로 알려준다


class Scheduler:
    def __init__(self, cfg: SchedulerConfig):
        self.cfg = cfg
        self._warned = set()   # 같은 오류를 반복해서 찍지 않기 위해

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled

    def _times_for(self, weekday_key: str) -> List[time]:
        """그 요일의 시작 시각들. 잘못 적힌 항목은 건너뛰고 로그로 알린다.

        하나가 잘못됐다고 예외를 올리면 24시간 루프가 통째로 죽는다.
        (`aist check` 가 같은 문제를 미리 잡아 보여준다.)
        """
        out: List[time] = []
        for raw in as_time_list(self.cfg.weekly.get(weekday_key)):
            try:
                out.append(_parse_hhmm(raw))
            except ValueError as e:
                key = (weekday_key, str(raw))
                if key not in self._warned:
                    self._warned.add(key)
                    log.error("스케줄 %s 의 시각을 못 읽어 건너뜁니다: %s",
                              weekday_key, e)
        return sorted(out)

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
