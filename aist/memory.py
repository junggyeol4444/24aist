"""장기기억 — 방송별 로그를 저장하고 "저번에~"를 가능하게 한다 (4-4, 6-6).

기본 백엔드는 JSON(신뢰성·이식성). 방송 1회 = 세션 1개로 저장한다.
- 누가 왔는지(단골 닉네임), 슈퍼챗, 게임 등 일어난 일을 기록
- 다음 방송 시작 공지/오프닝에서 recent_summary() 로 "저번에~" 활용
- regulars() 로 자주 오는 시청자(단골) 파악

chroma 백엔드는 의미검색용 확장 자리(미연결 시 JSON 으로 동작).
"""

import json
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .chat.base import ChatMessage
from .config import MemoryConfig

log = logging.getLogger("aist.memory")

# 방송 중 기억을 디스크에 다시 쓰는 최소 간격(초). 너무 잦으면 긴 방송
# 후반에 매 채팅마다 수백 KB 를 다시 쓰게 된다.
_CHECKPOINT_SEC = 30.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Memory:
    def __init__(self, cfg: MemoryConfig):
        self.cfg = cfg
        self.dir = Path(cfg.path)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sessions_file = self.dir / "sessions.json"
        # 진행 중인 세션만 따로 담는 작은 파일. 전체 기억을 30초마다 다시
        # 쓰면 1년치(약 27MB)에서 한 번에 380ms 씩 이벤트 루프가 멎고,
        # 3시간 방송이면 9.5GB 를 디스크에 쓴다(실측).
        self.current_file = self.dir / "current_session.json"
        self._sessions: List[Dict] = self._load()
        self._cur: Optional[Dict] = None
        self._last_save = 0.0
        # 지난번에 비정상 종료된 세션(있으면). 다음 방송을 시작할 때
        # 정식 기억으로 옮긴다 — 읽기 전용 명령(report 등)은 건드리지 않는다.
        self._orphan: Optional[Dict] = self._load_current()
        if self._orphan is not None:
            log.warning("지난 방송이 정상 종료되지 않았습니다 — 중간까지의 기억을 살립니다.")
            self._sessions.append(self._orphan)
        # chroma 백엔드(선택): 의미검색용 색인. 실패하면 키워드 검색으로 대체.
        self._chroma = self._init_chroma() if cfg.backend == "chroma" else None

    def _init_chroma(self):
        try:
            import chromadb  # 지연 import
        except ImportError:
            log.warning("chromadb 미설치 → recall 은 키워드 검색으로 동작. `pip install chromadb`")
            return None
        try:
            client = chromadb.PersistentClient(path=str(self.dir / "chroma"))
            col = client.get_or_create_collection("aist_sessions")
            log.info("chroma 기억 백엔드 초기화됨")
            return col
        except Exception as e:  # noqa: BLE001
            log.warning("chroma 초기화 실패(%s) → 키워드 검색으로 대체", e)
            return None

    def _load(self) -> List[Dict]:
        if self.sessions_file.exists():
            try:
                return json.loads(self.sessions_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                log.warning("기억 파일 읽기 실패 → 새로 시작")
        return []

    def _load_current(self) -> Optional[Dict]:
        """비정상 종료로 남은 '진행 중이던 세션' 파일을 읽는다."""
        if not self.current_file.exists():
            return None
        try:
            data = json.loads(self.current_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("진행 중이던 기억 파일을 읽지 못했습니다 → 무시")
            return None
        return data if isinstance(data, dict) and data.get("start") else None

    def _save_current(self) -> None:
        """진행 중인 세션 하나만 쓴다(작다 = 자주 써도 된다)."""
        if self._cur is None:
            return
        tmp = self.current_file.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(self._cur, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(self.current_file)
        except OSError as e:
            log.error("진행 중 기억 저장 실패(디스크 여유 공간 확인): %s", e)
            try:
                tmp.unlink()
            except OSError:
                pass

    def _clear_current(self) -> None:
        try:
            self.current_file.unlink()
        except OSError:
            pass

    def _save(self) -> None:
        """기억을 파일에 쓴다. 실패해도 예외를 올리지 않는다.

        여기서 예외가 올라가면 방송 종료 절차(_teardown)가 중간에 끊겨
        종료 공지가 안 나간다. 디스크가 차면 실제로 그렇게 됐다.
        기억을 못 남기는 건 심각하므로 로그로는 크게 알린다.
        """
        tmp = self.sessions_file.with_suffix(".json.tmp")
        try:
            tmp.write_text(
                json.dumps(self._sessions, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.sessions_file)
        except OSError as e:
            log.error("기억 저장 실패 — 이번 방송 기억이 남지 않습니다 "
                      "(디스크 여유 공간을 확인하세요): %s", e)
            try:
                tmp.unlink()
            except OSError:
                pass

    # --- 세션 라이프사이클 --------------------------------------------------
    def start_session(self) -> None:
        """방송 세션을 연다. 열자마자 디스크에도 남긴다.

        예전에는 end_session() 에서만 저장해서, 방송 중에 프로세스가 죽으면
        (정전·윈도우 강제 재부팅·무인운영 재시작) 그날 방송의 기억이 통째로
        사라졌다. 24시간 무인 운영에서 크래시는 예외가 아니라 일상이다.
        그래서 '시작 시점에 한 번 + 진행 중 주기적으로' 저장한다.
        _cur 는 _sessions 안의 바로 그 객체라, 이후 변경은 저장만 하면 남는다.
        """
        # 지난 방송이 크래시로 끝났다면, 그 기억을 지금 정식으로 옮겨 적는다.
        # (읽기 전용 명령이 아니라 '다음 방송 시작' 시점에만 파일을 건드린다)
        if self._orphan is not None:
            self._orphan = None
            self._save()
        self._cur = {
            "start": _now_iso(),
            "end": None,
            "events": [],
            "viewers": [],
            "superchats": [],
            "summary": "",
        }
        self._sessions.append(self._cur)
        self._save_current()
        self._last_save = time.monotonic()

    def _checkpoint(self) -> None:
        """진행 중인 세션을 가끔 디스크에 반영한다(크래시 대비)."""
        now = time.monotonic()
        if now - self._last_save < _CHECKPOINT_SEC:
            return
        self._last_save = now
        self._save_current()

    def record_event(self, kind: str, **data) -> None:
        if self._cur is None:
            return
        self._cur["events"].append({"t": _now_iso(), "kind": kind, **data})
        self._checkpoint()

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
        self._checkpoint()

    def end_session(self, summary: str = "") -> None:
        if self._cur is None:
            return
        self._cur["end"] = _now_iso()
        if summary:
            self._cur["summary"] = summary
        session = self._cur
        # start_session() 이 이미 _sessions 에 넣어뒀다. 여기서 또 붙이면
        # 같은 방송이 리포트·단골 집계에 두 번 잡힌다.
        if not any(x is session for x in self._sessions):
            self._sessions.append(session)
        self._cur = None
        self._save()
        self._clear_current()
        self._last_save = time.monotonic()
        self._index(session, len(self._sessions))

    def _session_text(self, s: Dict) -> str:
        parts = [s.get("summary", "")]
        parts += s.get("viewers", [])
        parts += [sc.get("text", "") for sc in s.get("superchats", [])]
        parts += [e.get("kind", "") for e in s.get("events", [])]
        return " ".join(p for p in parts if p) or "빈 방송"

    def _index(self, session: Dict, idx: int) -> None:
        if self._chroma is None:
            return
        try:
            self._chroma.add(
                documents=[self._session_text(session)],
                ids=[f"session-{idx}"],
                metadatas=[{"start": session.get("start", "")}],
            )
        except Exception as e:  # noqa: BLE001
            log.debug("chroma 색인 실패: %s", e)

    def recall(self, query: str, n: int = 3) -> List[str]:
        """과거 방송에서 query 와 관련된 내용을 회상한다("저번에 그거~").

        chroma 백엔드면 의미검색, 아니면 키워드 검색으로 동작한다.
        """
        if self._chroma is not None:
            try:
                res = self._chroma.query(query_texts=[query], n_results=n)
                docs = (res.get("documents") or [[]])[0]
                if docs:
                    return docs
            except Exception as e:  # noqa: BLE001
                log.debug("chroma 검색 실패(%s) → 키워드 검색", e)
        # 키워드 대체
        words = [w for w in query.lower().split() if w]
        hits = []
        for s in reversed(self._sessions):
            text = self._session_text(s)
            if any(w in text.lower() for w in words):
                hits.append(text)
            if len(hits) >= n:
                break
        return hits

    # --- 회상 --------------------------------------------------------------
    def recent_summary(self) -> str:
        """직전 방송 한 줄 요약. 시작 공지/오프닝의 "저번에~" 재료."""
        # 지금 방송 중인 세션도 _sessions 에 들어 있다. 그건 '저번' 이 아니다.
        past = [s for s in self._sessions if s is not self._cur]
        if not past:
            return ""
        last = past[-1]
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
