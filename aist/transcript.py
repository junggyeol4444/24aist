"""방송 트랜스크립트 — 시청자 채팅 + AI 발화를 JSONL 로 기록한다.

목적(기획안 2-2, 8-2):
- 사고 발언 점검: AI 가 라이브에서 실제로 뭐라고 말했는지 파일로 남긴다.
  (코어가 보내는 {"type":"audio","display_text":{...}} 에서 발화 텍스트 추출)
- 다시보기 학습: 방송 후 리포트(report.py)의 원천 데이터.

한 방송 = 한 파일: data/logs/transcripts/2026-07-01_2000.jsonl
한 줄 = 한 사건: {"t": ISO시각, "who": "viewer|ai|system", ...}
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .chat.base import ChatMessage
from .safety import strip_expressions
from .paths import unique_path

log = logging.getLogger("aist.transcript")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Transcript:
    def __init__(self, dir_path: str):
        self.dir = Path(dir_path)
        self._fh = None
        self.path: Optional[Path] = None
        self._write_failed = False

    def open_session(self, start_dt: datetime) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        name = start_dt.strftime("%Y-%m-%d_%H%M") + ".jsonl"
        # 같은 분에 방송이 두 번 시작하면 한 파일에 섞인다(append 모드).
        self.path = unique_path(self.dir / name)
        self._fh = self.path.open("a", encoding="utf-8")
        self.log_event("broadcast_start")
        return self.path

    def _write(self, record: dict) -> None:
        if self._fh is None:
            return
        record["t"] = _now_iso()
        try:
            self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._fh.flush()
        except (OSError, ValueError) as e:
            # OSError: 디스크 참 / 권한. ValueError: 핸들이 이미 닫힘.
            # 채팅마다 경고를 찍으면 로그가 폭발하므로 한 번만 알리고
            # 이후로는 기록을 포기한다(방송은 계속 돌아야 한다).
            if not self._write_failed:
                self._write_failed = True
                log.error("트랜스크립트 기록 실패 — 이번 방송은 기록 없이 진행합니다: %s", e)
            self._fh = None

    @property
    def write_failed(self) -> bool:
        """이번 방송 기록이 중간에 끊겼는지(디스크 참·권한 등)."""
        return self._write_failed

    def log_chat(self, msg: ChatMessage) -> None:
        self._write({
            "who": "viewer", "platform": msg.platform, "author": msg.author,
            "text": msg.text, "superchat": msg.is_superchat,
            **({"amount": msg.amount} if msg.amount else {}),
        })

    def log_ai(self, text: str) -> None:
        if text:
            self._write({"who": "ai", "text": text})

    def log_event(self, kind: str, /, **data) -> None:
        self._write({**data, "who": "system", "event": kind})

    def on_core_message(self, data: dict) -> None:
        """코어 drain 훅 — AI 실제 발화(audio payload 의 display_text)를 기록."""
        try:
            if data.get("type") == "audio":
                dt = data.get("display_text") or {}
                text = dt.get("text") if isinstance(dt, dict) else ""
                # 표정 키워드([joy] 등)는 시청자에게 안 나가는 연출 지시다.
                # 기록에 남기면 '발화 전문' 이 그걸로 뒤덮인다.
                text = strip_expressions(text or "")
                if text:
                    self.log_ai(text)
        except Exception:  # 기록 실패가 방송을 멈추면 안 됨
            log.debug("코어 메시지 트랜스크립트 기록 실패", exc_info=True)

    def close(self) -> None:
        if self._fh is not None:
            self.log_event("broadcast_end")
            try:
                self._fh.close()
            finally:
                self._fh = None


def read_transcript(path: Path):
    """JSONL 파일 → record 리스트(리포트용). 깨진 줄은 건너뜀."""
    records = []
    if not Path(path).exists():
        return records
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records
