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
    if events:
        lines.append(f"- 기록된 이벤트: {len(events)}건")
        for e in events[:20]:
            lines.append(f"  - [{e.get('t','')[:16]}] {e.get('kind')}")

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
            lines.append("")
            lines.append("## AI 발화 전문 (사고 발언 점검용)")
            # 같은 말이 연달아 나오면 한 줄로 묶는다. 3시간 방송이면 수천
            # 줄이라, 그대로 두면 정작 이상한 발언을 찾을 수가 없다.
            # (원본은 트랜스크립트 파일에 그대로 있다)
            for text, count in _collapse([r.get("text") for r in ai_lines]):
                lines.append(f"- {text}" + (f"  (×{count})" if count > 1 else ""))

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
