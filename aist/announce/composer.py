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
from pathlib import Path
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


# 오프라인 변주: 머리+꼬리 조합(수십 가지) + 최근 사용 기억으로 반복 회피.
# LLM 을 켜면 어차피 매번 새로 작성되고, 이건 LLM 없이도 단조롭지 않게.
_START_HEADS: List[str] = [
    "오늘 방송 켰어요!", "ㅎㅇ 방송 시작~", "심심한데 방송이나 켤까 하다가 진짜 켬",
    "방송 시작했어요 :)", "오늘도 방송 ON", "자 오늘도 가봅시다", "짠, 방송 켰다",
    "슬슬 시작해볼까요", "왔어요 왔어 방송", "오늘 방송 고고",
]
_START_TAILS: List[str] = [
    "편하게 놀러와요", "들렀다 가요", "같이 놀아요", "오늘도 달려봅시다",
    "심심하면 오세요", "채팅 치러 와요", "",
]
_END_HEADS: List[str] = [
    "오늘 방송 끝!", "여기까지~", "오늘은 이만 마무리할게요", "방송 종료!",
    "오늘도 수고했어요 우리", "자, 오늘은 여기까지", "끝났습니다~", "오늘 방송 마감",
]
_END_TAILS: List[str] = [
    "와줘서 고마워요", "다음에 또 봐요", "푹 쉬어요", "오늘도 즐거웠어요",
    "내일 또 봐요", "",
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


def _offline_varied(ctx: AnnounceContext, rng: random.Random,
                    avoid: Optional[set] = None):
    """(최종 문구, 조합 원형) 을 돌려준다. 원형이 최근 이력에 있으면 다시 뽑는다."""
    heads = _START_HEADS if ctx.kind == "start" else _END_HEADS
    tails = _START_TAILS if ctx.kind == "start" else _END_TAILS
    avoid = avoid or set()
    base = ""
    for _ in range(15):   # 최근 쓴 조합은 피해서 다시 뽑기
        base = rng.choice(heads)
        tail = rng.choice(tails)
        if tail:
            base += " " + tail
        if base not in avoid:
            break
    text = base
    if ctx.kind == "start" and ctx.recent_note:
        text += f" ({ctx.recent_note})"
    if ctx.kind == "end" and ctx.next_stream_hint:
        text += f" {ctx.next_stream_hint}!"
    # 길이·이모지 변주(어떤 날은 이모지, 어떤 날은 아님)
    if rng.random() < 0.5:
        text += " " + rng.choice(_EMOJI)
    return text, base


def _load_history(path: Path) -> List[str]:
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_history(path: Path, history: List[str]) -> None:
    try:
        import json
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history[-20:], ensure_ascii=False), encoding="utf-8")
    except OSError:
        log.debug("공지 이력 저장 실패(무시)")


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
    history_path: Optional[Path] = None,
) -> str:
    """공지 본문을 만든다. (디스코드 역할 멘션은 게시 단계에서 별도로 붙음)

    history_path 를 주면 최근 쓴 문구를 기억해 같은 공지가 반복되지 않게
    한다(오프라인 변주일 때 특히 중요 — 반복은 봇 티).
    """
    rng = rng or random
    now = now or datetime.now()

    if cfg.style == "fixed":
        tmpl = cfg.fixed_start_template if ctx.kind == "start" else cfg.fixed_end_template
        return tmpl.format(link=ctx.link or cfg.link).strip()

    # style == "varied"
    history = _load_history(history_path) if history_path else []
    text = ""
    base = ""
    if llm is not None and llm.available():
        try:
            text = _llm_varied(persona, ctx, llm).strip()
            base = text
        except Exception:  # noqa: BLE001 - LLM 실패 시 오프라인 변주로 폴백
            log.exception("LLM 공지 생성 실패 → 오프라인 변주로 대체")
            text = ""
    if not text:
        text, base = _offline_varied(ctx, rng, avoid=set(history[-cfg.history_size:]))
    if history_path:
        history.append(base)
        _save_history(history_path, history)

    # 시작 공지엔 링크를 붙인다(본문에 이미 없으면).
    link = ctx.link or cfg.link
    if ctx.kind == "start" and link and link not in text:
        text = f"{text}\n{link}"
    return text.strip()
