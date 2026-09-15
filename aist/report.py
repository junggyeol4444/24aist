"""방송 후 리포트 — "다시보기 학습"을 파일로 (기획안 2-2).

방송이 끝나면 그 회차를 마크다운으로 정리한다:
누가 왔는지 / 단골 / 슈퍼챗 / 채팅·발화 통계 / AI 발화 전문(사고 점검용)
/ 다음 방송 예정. 운영자의 하루 5~10분 점검이 이 파일 하나로 끝나게.

무엇을 고칠지는 운영자가 읽고 판단한다 — 리포트는 사실만 정리한다.
"""

import logging
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .memory import Memory
from .paths import unique_path
from .transcript import read_transcript

log = logging.getLogger("aist.report")


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
    start = _to_local(s.get("start", "?"), tz_name)
    end = _to_local(s.get("end", "?"), tz_name)
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
    lines.append(f"- 슈퍼챗/후원: {len(scs)}건")
    for sc in scs:
        lines.append(f"  - {sc.get('author')} ({sc.get('amount')}): {sc.get('text')}")

    events = s.get("events", [])
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
            for r in ai_lines:
                lines.append(f"- {r.get('text')}")

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
