"""공지 문구 생성 — 페르소나 말투 + 그날 맥락 + (선택) 변주.

- style="varied"(기본): LLM 이 매번 다르게 작성. LLM 이 없거나 dummy 면
  오프라인 변주 풀로 대체(테스트/키 없는 환경에서도 단조롭지 않게).
- style="fixed": 고정 템플릿. 운영자가 고정 문구를 원하면 이걸로.
- 새벽 시간대 게시는 should_post() 로 피한다.

변주는 '선택'이다. 운영자가 fixed 로 바꾸면 변주하지 않는다.
"""

import logging
import random
from dataclasses import dataclass
from datetime import datetime, time
from typing import List, Optional

from ..config import AnnounceConfig
from ..llm import LLMClient
from ..persona import Persona

log = logging.getLogger("aist.announce.composer")


@dataclass
class AnnounceContext:
    kind: str = "start"          # start | end
    link: str = ""
    next_stream_hint: str = ""   # 예: "다음엔 금요일에"
    recent_note: str = ""        # 예: "저번에 그 게임 이어서"


_START_POOL: List[str] = [
    "오늘 방송 켰어요! 편하게 놀러와요",
    "ㅎㅇ 오늘도 달려봅시다",
    "심심한데 방송이나 켤까~ 지금 시작!",
    "방송 시작했어요 :) 들렀다 가요",
    "오늘도 방송 ON! 같이 놀아요",
]
_END_POOL: List[str] = [
    "오늘 방송 끝! 와줘서 고마워요",
    "여기까지~ 다음에 또 봐요",
    "오늘은 이만 마무리할게요. 푹 쉬어요",
    "방송 종료! 오늘도 즐거웠어요",
]
_EMOJI: List[str] = ["🎮", "✨", "🙌", "🌙", "🔥"]


def _in_window(now_t: time, start: time, end: time) -> bool:
    """[start, end) 구간 포함 여부. 자정을 넘는 구간(예: 23:00~06:00)도 처리."""
    if start <= end:
        return start <= now_t < end
    return now_t >= start or now_t < end  # wrap-around


def _parse_hhmm(s: str) -> time:
    h, m = s.strip().split(":")
    return time(hour=int(h), minute=int(m))


def should_post(now: datetime, cfg: AnnounceConfig) -> bool:
    """지금 공지를 올려도 되는 시간인지. 새벽 회피 설정을 반영."""
    if not cfg.avoid_late_night:
        return True
    try:
        start = _parse_hhmm(cfg.late_night_window[0])
        end = _parse_hhmm(cfg.late_night_window[1])
    except (IndexError, ValueError):
        return True
    if _in_window(now.time(), start, end):
        log.info("새벽 시간대(%s~%s) → 공지 게시 회피", cfg.late_night_window[0], cfg.late_night_window[1])
        return False
    return True


def _offline_varied(ctx: AnnounceContext, rng: random.Random) -> str:
    pool = _START_POOL if ctx.kind == "start" else _END_POOL
    text = rng.choice(pool)
    if ctx.kind == "start" and ctx.recent_note:
        text += f" ({ctx.recent_note})"
    if ctx.kind == "end" and ctx.next_stream_hint:
        text += f" {ctx.next_stream_hint}!"
    # 길이·이모지 변주(어떤 날은 이모지, 어떤 날은 아님)
    if rng.random() < 0.5:
        text += " " + rng.choice(_EMOJI)
    return text


def _llm_varied(
    persona: Persona, ctx: AnnounceContext, llm: LLMClient
) -> str:
    system = persona.render_system_prompt()
    bits = []
    if ctx.kind == "start":
        bits.append("지금 막 방송을 시작했어. SNS/디스코드에 올릴 '시작 공지'를 써줘.")
    else:
        bits.append("방송을 마쳤어. SNS/디스코드에 올릴 '종료 공지'를 써줘.")
    if ctx.recent_note:
        bits.append(f"오늘 맥락: {ctx.recent_note}")
    if ctx.next_stream_hint:
        bits.append(f"다음 방송: {ctx.next_stream_hint}")
    bits.append(
        "조건: 페르소나 말투 유지, 1~2문장, 매번 다른 느낌으로, 과하지 않게. "
        "링크/멘션은 시스템이 따로 붙이니 본문만 써. 따옴표 없이."
    )
    return llm.complete(system, "\n".join(bits))


def compose(
    persona: Persona,
    ctx: AnnounceContext,
    cfg: AnnounceConfig,
    llm: Optional[LLMClient] = None,
    now: Optional[datetime] = None,
    rng: Optional[random.Random] = None,
) -> str:
    """공지 본문을 만든다. (디스코드 역할 멘션은 게시 단계에서 별도로 붙음)"""
    rng = rng or random
    now = now or datetime.now()

    if cfg.style == "fixed":
        tmpl = cfg.fixed_start_template if ctx.kind == "start" else cfg.fixed_end_template
        return tmpl.format(link=ctx.link or cfg.link).strip()

    # style == "varied"
    text = ""
    if llm is not None and llm.available():
        try:
            text = _llm_varied(persona, ctx, llm).strip()
        except Exception:  # noqa: BLE001 - LLM 실패 시 오프라인 변주로 폴백
            log.exception("LLM 공지 생성 실패 → 오프라인 변주로 대체")
            text = ""
    if not text:
        text = _offline_varied(ctx, rng)

    # 시작 공지엔 링크를 붙인다(본문에 이미 없으면).
    link = ctx.link or cfg.link
    if ctx.kind == "start" and link and link not in text:
        text = f"{text}\n{link}"
    return text.strip()
