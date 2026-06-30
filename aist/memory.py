"""장기기억 — 방송별 로그를 저장하고 "저번에~"를 가능하게 한다 (4-4, 6-6).

기본 백엔드는 JSON(신뢰성·이식성). 방송 1회 = 세션 1개로 저장한다.
- 누가 왔는지(단골 닉네임), 슈퍼챗, 게임 등 일어난 일을 기록
- 다음 방송 시작 공지/오프닝에서 recent_summary() 로 "저번에~" 활용
- regulars() 로 자주 오는 시청자(단골) 파악

chroma 백엔드는 의미검색용 확장 자리(미연결 시 JSON 으로 동작).
"""

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .chat.base import ChatMessage
from .config import MemoryConfig

log = logging.getLogger("aist.memory")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Memory:
    def __init__(self, cfg: MemoryConfig):
        self.cfg = cfg
        self.dir = Path(cfg.path)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sessions_file = self.dir / "sessions.json"
        if cfg.backend == "chroma":
            log.info("memory.backend=chroma 는 아직 의미검색 연결 전 → JSON 으로 기록합니다.")
        self._sessions: List[Dict] = self._load()
        self._cur: Optional[Dict] = None

    def _load(self) -> List[Dict]:
        if self.sessions_file.exists():
            try:
                return json.loads(self.sessions_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                log.warning("기억 파일 읽기 실패 → 새로 시작")
        return []

    def _save(self) -> None:
        tmp = self.sessions_file.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._sessions, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.sessions_file)

    # --- 세션 라이프사이클 --------------------------------------------------
    def start_session(self) -> None:
        self._cur = {
            "start": _now_iso(),
            "end": None,
            "events": [],
            "viewers": [],
            "superchats": [],
            "summary": "",
        }

    def record_event(self, kind: str, **data) -> None:
        if self._cur is None:
            return
        self._cur["events"].append({"t": _now_iso(), "kind": kind, **data})

    def note_chat(self, msg: ChatMessage) -> None:
        """채팅 한 줄을 기억에 반영(단골/슈퍼챗 추적). 파이프라인 콜백용."""
        if self._cur is None:
            return
        if msg.author and msg.author not in self._cur["viewers"]:
            self._cur["viewers"].append(msg.author)
        if msg.is_superchat:
            self._cur["superchats"].append(
                {"author": msg.author, "amount": msg.amount, "text": msg.text}
            )

    def end_session(self, summary: str = "") -> None:
        if self._cur is None:
            return
        self._cur["end"] = _now_iso()
        if summary:
            self._cur["summary"] = summary
        self._sessions.append(self._cur)
        self._cur = None
        self._save()

    # --- 회상 --------------------------------------------------------------
    def recent_summary(self) -> str:
        """직전 방송 한 줄 요약. 시작 공지/오프닝의 "저번에~" 재료."""
        if not self._sessions:
            return ""
        last = self._sessions[-1]
        if last.get("summary"):
            return f"저번 방송 때 {last['summary']}"
        parts = []
        nv = len(last.get("viewers", []))
        if nv:
            parts.append(f"{nv}명 정도 왔었고")
        nsc = len(last.get("superchats", []))
        if nsc:
            parts.append(f"슈퍼챗도 {nsc}건 있었어")
        if not parts:
            return ""
        return "저번 방송 땐 " + ", ".join(parts)

    def regulars(self, top: int = 5) -> List[str]:
        """여러 방송에 걸쳐 자주 보인 시청자(단골) 닉네임."""
        c: Counter = Counter()
        for s in self._sessions:
            for v in s.get("viewers", []):
                c[v] += 1
        return [name for name, cnt in c.most_common(top) if cnt >= 2]
