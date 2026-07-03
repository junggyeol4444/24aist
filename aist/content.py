"""종료 후 컨텐츠 제작 (2-2⑦) — 다시보기에서 잘라 쓸 재료를 만든다.

방송이 끝나면 트랜스크립트를 분석해서:
- 하이라이트 후보: 채팅이 급증한 구간(방송 시작 기준 오프셋) → 운영자가
  다시보기(VOD)에서 그 시점을 잘라 클립/쇼츠로 만들면 됨
- 다시보기 제목 후보: LLM 이 있으면 페르소나 말투로, 없으면 템플릿 변주
- 커뮤니티 공지 초안

결과는 마크다운 한 장(data/content/*.md). 실제 영상 편집은 운영자 몫이고,
여기는 "어디를 자를지 + 뭐라고 올릴지"를 준비해 주는 단계다.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .llm import LLMClient
from .persona import Persona
from .transcript import read_transcript

log = logging.getLogger("aist.content")


def _parse_iso(t: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(t)
    except (ValueError, TypeError):
        return None


def find_highlights(records: List[dict], window_sec: int = 60,
                    top: int = 5, min_count: int = 3) -> List[Tuple[str, int, str]]:
    """채팅 급증 구간을 찾는다 → [(방송 기준 오프셋 "HH:MM:SS", 채팅수, 대표채팅)].

    방송 시작(broadcast_start) 기준으로 window_sec 단위 버킷에 시청자
    채팅을 세고, 많은 순으로 top 개(겹치지 않게)를 돌려준다.
    """
    start = None
    for r in records:
        if r.get("who") == "system" and r.get("event") == "broadcast_start":
            start = _parse_iso(r.get("t", ""))
            break
    if start is None:
        return []

    buckets = {}          # bucket_idx -> [count, 대표채팅]
    for r in records:
        if r.get("who") != "viewer":
            continue
        t = _parse_iso(r.get("t", ""))
        if t is None:
            continue
        off = (t - start).total_seconds()
        if off < 0:
            continue
        idx = int(off // window_sec)
        if idx not in buckets:
            buckets[idx] = [0, r.get("text", "")]
        buckets[idx][0] += 1

    ranked = sorted(buckets.items(), key=lambda kv: kv[1][0], reverse=True)
    out = []
    used = set()
    for idx, (count, sample) in ranked:
        if count < min_count:
            break
        if idx in used or (idx - 1) in used or (idx + 1) in used:
            continue  # 인접 구간 중복 방지
        used.add(idx)
        sec = idx * window_sec
        stamp = f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"
        out.append((stamp, count, sample))
        if len(out) >= top:
            break
    return out


_TITLE_TEMPLATES = [
    "{name}의 오늘 방송 하이라이트",
    "오늘자 {name} 방송 레전드 모음",
    "{name} 방송 풀버전 다시보기",
    "이거 보고 가요 — {name} 오늘 방송",
]


def _title_drafts(persona: Persona, llm: Optional[LLMClient],
                  highlight_note: str) -> List[str]:
    if llm is not None and llm.available():
        try:
            raw = llm.complete(
                persona.render_system_prompt(),
                "오늘 방송 다시보기(VOD)에 붙일 제목 후보 3개를 한 줄에 하나씩 써줘. "
                f"낚시성 말고 캐릭터 말투로. 참고: {highlight_note or '평범한 수다 방송'}",
            )
            lines = [ln.strip("-• ").strip() for ln in raw.splitlines() if ln.strip()]
            if lines:
                return lines[:3]
        except Exception:  # noqa: BLE001 - LLM 실패 시 템플릿으로
            log.debug("제목 초안 LLM 실패 → 템플릿", exc_info=True)
    return [t.format(name=persona.name) for t in _TITLE_TEMPLATES[:3]]


def generate_content_pack(
    persona: Persona,
    transcript_path: Optional[Path],
    out_dir: str,
    llm: Optional[LLMClient] = None,
) -> Optional[Path]:
    """트랜스크립트 → 컨텐츠 팩(md). 트랜스크립트 없으면 None."""
    if not transcript_path or not Path(transcript_path).exists():
        return None
    records = read_transcript(Path(transcript_path))
    highlights = find_highlights(records)

    lines = [f"# 컨텐츠 팩 — {Path(transcript_path).stem}", ""]
    lines.append("## 하이라이트 후보 (다시보기에서 자를 지점)")
    if highlights:
        for stamp, count, sample in highlights:
            lines.append(f"- **{stamp}** 근처 — 채팅 {count}개 급증 (예: \"{sample}\")")
    else:
        lines.append("- (채팅 급증 구간 없음 — 조용한 방송)")

    note = f"{highlights[0][0]} 근처가 제일 반응 좋았음" if highlights else ""
    lines.append("")
    lines.append("## 다시보기 제목 후보")
    for t in _title_drafts(persona, llm, note):
        lines.append(f"- {t}")

    lines.append("")
    lines.append("## 커뮤니티 공지 초안")
    lines.append(f"- 오늘 방송 다시보기 올라왔어요! "
                 + (f"{highlights[0][0]} 부분 꼭 보세요 ㅋㅋ" if highlights else "편하게 보고 가요~"))

    lines.append("")
    lines.append("※ 실제 클립/편집은 운영자가. 여기는 재료(어디를 자를지/뭐라고 올릴지)까지.")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / (Path(transcript_path).stem + ".md")
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("컨텐츠 팩 생성: %s", path)
    return path
