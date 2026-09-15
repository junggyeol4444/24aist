"""리포트 파일명·본문 시각이 다른 산출물과 어긋나던 것.

윈도우에서 실제로 방송을 돌리고 산출물을 열어보다 찾았다(리눅스도 같다).
같은 방송인데 파일명 시각이 셋이 서로 달랐다:

    트랜스크립트 : 2026-09-15_1047.jsonl   ← 설정 타임존(KST)
    컨텐츠 팩    : 2026-09-15_1047.md      ← 설정 타임존(KST)
    리포트       : 2026-09-15_0147.md      ← UTC (9시간 차이)

기억(memory)은 UTC 로 기록하는데 리포트가 그 값을 그대로 파일명과 본문의
'시작/종료' 에 썼다. 운영자가 "어제 19시 방송 리포트" 를 찾으면 못 찾고,
리포트를 열어도 시작 시각이 틀리게 보인다.
(기획안 4-4 '이번 방송 로그 저장', 7-8 '로그 보며 점검')
"""

from datetime import datetime, timezone

import pytest

from aist.config import MemoryConfig
from aist.memory import Memory
from aist.report import _to_local, generate_report


def _memory_with_session(tmp_path):
    m = Memory(MemoryConfig(path=str(tmp_path / "mem")))
    m.start_session()
    m.end_session()
    return m


def test_report_filename_uses_configured_timezone(tmp_path):
    m = _memory_with_session(tmp_path)
    utc_start = m._sessions[-1]["start"]          # UTC ISO
    path = generate_report(m, str(tmp_path / "rep"), tz_name="Asia/Seoul")
    assert path is not None

    kst = (datetime.fromisoformat(utc_start)
           .astimezone(__import__("zoneinfo").ZoneInfo("Asia/Seoul")))
    assert path.stem.startswith(kst.strftime("%Y-%m-%d_%H%M")), \
        f"파일명이 KST 가 아니다: {path.name} (KST={kst})"


def test_report_body_shows_local_start_time(tmp_path):
    m = _memory_with_session(tmp_path)
    path = generate_report(m, str(tmp_path / "rep"), tz_name="Asia/Seoul")
    body = path.read_text(encoding="utf-8")
    assert "+09:00" in body, f"본문 시각이 KST 가 아니다:\n{body[:300]}"


def test_report_matches_transcript_filename(tmp_path):
    """같은 방송의 리포트와 트랜스크립트 파일명이 같은 시각이어야 한다."""
    from aist.transcript import Transcript
    import zoneinfo

    kst = zoneinfo.ZoneInfo("Asia/Seoul")
    m = Memory(MemoryConfig(path=str(tmp_path / "mem")))
    m.start_session()
    m.end_session()          # 여기서야 _sessions 에 들어간다
    start_local = datetime.fromisoformat(m._sessions[-1]["start"]).astimezone(kst)

    t = Transcript(str(tmp_path / "tr"))
    tpath = t.open_session(start_local)
    t.close()

    rpath = generate_report(m, str(tmp_path / "rep"),
                            transcript_path=tpath, tz_name="Asia/Seoul")
    assert rpath.stem == tpath.stem, \
        f"리포트 {rpath.stem} vs 트랜스크립트 {tpath.stem} — 시각이 어긋난다"


def test_no_timezone_keeps_old_behaviour(tmp_path):
    """tz_name 을 안 주면 예전처럼 저장된 값 그대로 쓴다."""
    m = _memory_with_session(tmp_path)
    utc_start = m._sessions[-1]["start"]
    path = generate_report(m, str(tmp_path / "rep"))
    assert path.stem.startswith(utc_start[:13].replace(":", "").replace("T", "_")[:13])


@pytest.mark.parametrize("bad", ["", "?", None])
def test_to_local_passes_through_junk(bad):
    assert _to_local(bad, "Asia/Seoul") == bad


def test_to_local_survives_unknown_timezone():
    iso = "2026-09-15T01:47:42+00:00"
    assert _to_local(iso, "Nowhere/Nothing") == iso
