"""방송 후 리포트 — "다시보기 학습"을 파일로 (기획안 2-2).

방송이 끝나면 그 회차를 마크다운으로 정리한다:
누가 왔는지 / 단골 / 슈퍼챗 / 채팅·발화 통계 / AI 발화 전문(사고 점검용)
/ 다음 방송 예정. 운영자의 하루 5~10분 점검이 이 파일 하나로 끝나게.

무엇을 고칠지는 운영자가 읽고 판단한다 — 리포트는 사실만 정리한다.
"""

import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .memory import Memory
from .paths import unique_path
from .transcript import read_transcript

log = logging.getLogger("aist.report")


_MAX_LISTED = 20          # 리포트에 직접 나열하는 최대 건수
# 발화 전문을 리포트 안에 그대로 둘 최대 줄 수.
# 3시간 방송을 만들어 재보니 리포트 1367줄 중 1352줄(99%)이 이 칸이었다.
# 기획 2-2 의 "하루 5~10분 점검" 은 1350줄을 읽으라는 뜻이 아니다.
# 넘치면 옆에 따로 파일로 빼고, 리포트에는 앞뒤 몇 줄과 경로만 남긴다.
_SPEECH_INLINE_MAX = 40
_SPEECH_HEAD_TAIL = 10



# 이벤트 이름은 코드용 영어다. 운영자에게는 그대로 보여주면 안 된다 —
# 실제 실행에서 "tts_silent" 한 줄만 찍힌 리포트를 보고 운영자는 방송이
# 멀쩡히 끝난 줄 알았는데, 실제로는 코어가 죽었다 살아나고 5분 넘게
# 소리가 안 나간 방송이었다.
_EVENT_LABEL = {
    "tts_silent": "목소리가 안 나감(자막만) — TTS 문제",
    "core_lost": "코어 연결이 끊김",
    "core_recovered": "코어에 다시 붙음",
    "core_gone": "코어에 다시 못 붙어 방송을 내림",
    "core_mute": "소리·자막이 시청자에게 안 나감 — 방송을 내림",
    "core_stuck": "발화가 걸림(말 끝 신호가 안 옴)",
    "core_brain_dead": "AI 가 LLM 오류 문구를 읽음 — 방송을 내림",
    "web_ui_refresh": "웹UI(OBS 브라우저 소스)를 새로고침함",
    "chat_lost": "채팅 연결이 끊김",
    "transcript_lost": "방송 기록이 중간에 끊김 (아래 발화 수·발화 전문은 방송 전체가 아님)",
    "chat_never_connected": "채팅 플랫폼에 한 번도 못 붙음 (시청자가 없었던 게 아님)",
    "chat_gave_up": "채팅을 못 살려 혼잣말로 진행",
    "obs_down": "송출이 내려가 있어 다시 켬",
    "obs_reconnected": "OBS 에 다시 붙음",
    "obs_unreachable": "OBS 가 대답이 없어 방송을 내림",
    "obs_gave_up": "송출이 반복해서 내려가 방송을 내림",
    "obs_restart_failed": "송출을 다시 못 켜 방송을 내림",
    "ended_early": "마무리 인사도 못 하고 방송이 끊김",
    "stopped_by_operator": "운영자가 중단(중단.bat)해서 내림",
    "game": "게임/컨텐츠 진행",
}

# 이 중 하나라도 있으면 "정상적인 방송이 아니었다".
_SERIOUS = ("core_lost", "core_gone", "core_mute", "core_stuck",
            "chat_never_connected", "transcript_lost",
            "core_brain_dead", "chat_lost", "chat_gave_up", "obs_down",
            "obs_unreachable", "obs_gave_up", "obs_restart_failed",
            "ended_early")


def _trouble_lines(events) -> list:
    """이번 방송에 사고가 있었으면 맨 위에 한 덩어리로 적는다.

    운영자가 다음 날 리포트를 펴서 제일 먼저 보는 자리다. 여기에 없으면
    로그 파일을 열어 볼 사람은 없다고 봐야 한다(기획안 2-2 "하루 5~10분").
    """
    counts = {}
    for e in events:
        kind = str(e.get("kind", ""))
        if kind in _SERIOUS:
            counts[kind] = counts.get(kind, 0) + 1
    if not counts:
        return []
    parts = [f"{_EVENT_LABEL.get(k, k)} {n}회" for k, n in counts.items()]
    out = ["- ⚠ **이번 방송은 정상적으로 굴러가지 않았습니다**: " + ", ".join(parts)]
    if "ended_early" in counts or "core_gone" in counts or "core_mute" in counts:
        out.append("  - 방송이 예정보다 일찍 스스로 내려갔습니다. "
                   "`docs/OPERATOR.md` 의 '방송이 스스로 내려갔을 때' 를 보세요.")
    return out


def _won_total(superchats) -> int:
    """후원 금액 합계(원). 숫자로 읽히는 것만 더한다. 못 읽으면 0."""
    total = 0
    for sc in superchats:
        amount = str(sc.get("amount") or "")
        digits = re.sub(r"[^0-9]", "", amount)
        if digits and ("원" in amount or amount.strip().isdigit()):
            try:
                total += int(digits)
            except ValueError:
                continue
    return total


def _collapse(texts):
    """연달아 같은 말이면 (말, 횟수) 로 묶는다."""
    out = []
    for t in texts:
        if out and out[-1][0] == t:
            out[-1][1] += 1
        else:
            out.append([t, 1])
    return [(t, n) for t, n in out]


def _to_local(iso: str, tz_name: Optional[str]) -> str:
    """기억에 UTC 로 저장된 ISO 시각을 운영자가 보는 타임존으로 바꾼다.

    기억(memory)은 UTC 로 기록하는데 트랜스크립트·컨텐츠 팩의 파일명은
    설정 타임존을 쓴다. 그대로 두면 같은 방송의 산출물 세 개가 서로 다른
    시각을 갖는다(KST 면 9시간 차이). 운영자가 "어제 19시 방송 리포트" 를
    찾을 때 못 찾고, 리포트 본문의 '시작' 시각도 틀리게 보인다.
    """
    if not iso or iso == "?" or not tz_name:
        return iso
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.fromisoformat(iso).astimezone(ZoneInfo(tz_name)).isoformat()
    except Exception:  # noqa: BLE001 - tz 없음/형식 이상 → 원본 유지
        return iso


def _write_speech_file(out_dir: str, start: str, spoken: List[str]) -> Optional[Path]:
    """발화 전문을 리포트 옆에 따로 적는다. 실패하면 None(리포트는 계속 만든다)."""
    try:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        stem = (start[:16].replace(":", "").replace("T", "_") or "session")
        # 메모장에서 바로 열리게 .txt 로 둔다.
        path = unique_path(out / f"{stem}_발화전문.txt")
        body = [f"# AI 발화 전문 — {start[:16]}", ""]
        body += [ln[2:] if ln.startswith("- ") else ln for ln in spoken]
        path.write_text("\n".join(body), encoding="utf-8")
        return path
    except OSError as e:
        log.warning("발화 전문 파일을 따로 못 남겼습니다(리포트는 계속): %s", e)
        return None


def generate_report(
    memory: Memory,
    out_dir: str,
    transcript_path: Optional[Path] = None,
    next_stream: str = "",
    tz_name: Optional[str] = None,
) -> Optional[Path]:
    """직전 방송 세션의 리포트를 생성. 세션이 없으면 None."""
    if not memory._sessions:
        return None
    s = memory._sessions[-1]

    lines: List[str] = []
    start = _to_local(s.get("start") or "?", tz_name)
    # 종료 시각이 비어 있다 = 종료 절차를 못 밟고 프로세스가 죽었다는 뜻.
    # (정전·강제 재부팅·무인운영 재시작) 운영자가 알아야 하는 사실이다.
    raw_end = s.get("end")
    end = _to_local(raw_end, tz_name) if raw_end else "기록 없음 — 방송이 비정상 종료된 것으로 보입니다"
    lines.append(f"# 방송 리포트 — {start[:16]}")
    lines.append("")
    lines.append(f"- 시작: {start}")
    lines.append(f"- 종료: {end}")

    viewers = s.get("viewers", [])
    lines.append(f"- 시청자(채팅 기준): {len(viewers)}명"
                 + (f" — {', '.join(viewers[:20])}" if viewers else ""))
    regulars = memory.regulars()
    if regulars:
        lines.append(f"- 단골(여러 방송 출석): {', '.join(regulars)}")

    scs = s.get("superchats", [])
    total = _won_total(scs)
    head = f"- 슈퍼챗/후원: {len(scs)}건"
    if total:
        head += f" (합계 약 {total:,}원)"
    lines.append(head)
    # 실제 방송에서는 수십~수백 건이 된다. 전부 나열하면 리포트를 못 읽는다.
    for sc in scs[:_MAX_LISTED]:
        lines.append(f"  - {sc.get('author')} ({sc.get('amount')}): {sc.get('text')}")
    if len(scs) > _MAX_LISTED:
        lines.append(f"  - (그 외 {len(scs) - _MAX_LISTED}건 — 전체는 트랜스크립트에)")

    events = s.get("events", [])
    # 사고는 목록 속에 묻히면 안 된다 — 맨 위에 따로 적는다.
    if any(e.get("kind") == "tts_silent" for e in events):
        lines.append("- ⚠ 이번 방송은 **목소리가 나가지 않았습니다**(자막만). "
                     "코어 설정의 tts_model 과 TTS 서버를 확인하세요.")
    lines.extend(_trouble_lines(events))
    if events:
        lines.append(f"- 기록된 이벤트: {len(events)}건")
        for e in events[:20]:
            # 기억은 UTC 로 적히는데 리포트의 나머지는 운영자 타임존이다.
            # 그대로 두면 02:15 방송 리포트 안에 17:16 이벤트가 찍혀서
            # 트랜스크립트와 맞춰보려던 운영자가 헤맨다.
            when = _to_local(e.get("t", ""), tz_name)[:16]
            kind = str(e.get("kind", ""))
            label = _EVENT_LABEL.get(kind)
            lines.append(f"  - [{when}] {label or kind}"
                         + (f" ({kind})" if label else ""))
        if len(events) > 20:
            lines.append(f"  - (그 외 {len(events) - 20}건)")

    # 트랜스크립트 통계 + AI 발화 전문
    if transcript_path:
        records = read_transcript(transcript_path)
        chats = [r for r in records if r.get("who") == "viewer"]
        ai_lines = [r for r in records if r.get("who") == "ai"]
        by_platform = Counter(c.get("platform", "?") for c in chats)
        lines.append("")
        lines.append("## 통계")
        lines.append(f"- 채팅 수: {len(chats)}"
                     + (f" (플랫폼별: " + ", ".join(f"{k} {v}" for k, v in by_platform.items()) + ")"
                        if by_platform else ""))
        lines.append(f"- AI 발화 수: {len(ai_lines)}")
        lines.append(f"- 트랜스크립트: `{transcript_path}`")
        if ai_lines:
            # 같은 말이 연달아 나오면 한 줄로 묶는다. 3시간 방송이면 수천
            # 줄이라, 그대로 두면 정작 이상한 발언을 찾을 수가 없다.
            # (원본은 트랜스크립트 파일에 그대로 있다)
            speech = _collapse([r.get("text") for r in ai_lines])
            spoken = [f"- {t}" + (f"  (×{c})" if c > 1 else "") for t, c in speech]
            lines.append("")
            lines.append("## AI 발화 전문 (사고 발언 점검용)")
            if len(spoken) <= _SPEECH_INLINE_MAX:
                lines.extend(spoken)
            else:
                side = _write_speech_file(out_dir, start, spoken)
                head, tail = _SPEECH_HEAD_TAIL, _SPEECH_HEAD_TAIL
                lines.extend(spoken[:head])
                lines.append(f"- … (가운데 {len(spoken) - head - tail}줄 줄임) …")
                lines.extend(spoken[-tail:])
                lines.append("")
                if side is not None:
                    # 리포트 바로 옆에 있으니 파일 이름만 적는다.
                    lines.append(f"> 전체 {len(spoken)}줄은 따로 뺐습니다: "
                                 f"`{side.name}` (이 리포트와 같은 폴더)")
                    lines.append("> (메모장으로 열어 Ctrl+F 로 훑어보세요. "
                                 "이 리포트에 다 넣으면 1000줄이 넘어가 "
                                 "정작 이상한 발언을 못 찾습니다.)")
                else:
                    lines.append(f"> 전체 {len(spoken)}줄은 트랜스크립트에 "
                                 f"그대로 있습니다: `{transcript_path}`")

    if next_stream:
        lines.append("")
        lines.append(f"## 다음 방송\n- {next_stream}")

    lines.append("")
    lines.append("## 점검 메모 (운영자가 채우는 칸)")
    lines.append("- 어색했던 부분: ")
    lines.append("- 바꿀 것: ")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fname = (start[:16].replace(":", "").replace("T", "_") or "session") + ".md"
    # 같은 분에 두 번 방송하면 앞 리포트를 덮어쓴다.
    path = unique_path(out / fname)
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("방송 리포트 생성: %s", path)
    return path
