"""기획안 잔여 항목 검증: 오프닝·사전공지·임베드·OBS실행·컨텐츠 팩."""

import json
from datetime import datetime, timedelta, timezone

from aist.config import DiscordAnnounce, ObsConfig
from aist.persona import Persona
import aist.orchestrator as orch_mod


# ------------------------- 방송 오프닝 (4-1) -------------------------
def test_opening_cue_is_greeting_not_setup():
    cue = orch_mod._CUE_OPENING
    assert cue.startswith("(매니저 귓속말:")
    assert "인사" in cue                 # 여는 인사로 시작
    assert "세팅" not in cue             # 방송 켜고 세팅 확인은 말이 안 됨
    assert "언급하지 마" in cue


# ------------------------- 디스코드 임베드/이미지 (5-1) -------------------------
def _announcer(**kw):
    from aist.announce.discord_bot import DiscordAnnouncer
    return DiscordAnnouncer(DiscordAnnounce(channel_id=1, **kw), "token")


def test_discord_plain_payload():
    p = _announcer().build_payload("방송 시작!", "제목")
    assert p["content"] == "방송 시작!"
    assert "embeds" not in p


def test_discord_embed_payload_with_mention_and_image_url():
    p = _announcer(use_embed=True, mention_role_id=42,
                   image_url="https://x/img.png").build_payload("본문", "방송 시작")
    assert p["content"] == "<@&42>"
    e = p["embeds"][0]
    assert e["title"] == "방송 시작" and e["description"] == "본문"
    assert e["image"]["url"] == "https://x/img.png"
    assert p["allowed_mentions"] == {"roles": ["42"]}


def test_discord_embed_local_image_uses_attachment():
    p = _announcer(use_embed=True, image_path="/tmp/thumb.png").build_payload("b", "t")
    assert p["embeds"][0]["image"]["url"] == "attachment://thumb.png"


# ------------------------- OBS 자동 실행 (2-2③) -------------------------
def test_obs_launch_invokes_command(monkeypatch):
    from aist.obs_control import ObsController
    calls = []

    class FakeProc:
        pass

    def fake_popen(args, **kw):
        calls.append(args)
        return FakeProc()

    import subprocess
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    c = ObsController(ObsConfig(launch_if_not_running=True,
                                launch_command="obs --disable-shutdown-check"))
    assert c._launch_obs() is True
    assert calls == [["obs", "--disable-shutdown-check"]]


def test_obs_launch_failure_returns_false(monkeypatch):
    from aist.obs_control import ObsController
    import subprocess

    def boom(*a, **k):
        raise FileNotFoundError("no obs")

    monkeypatch.setattr(subprocess, "Popen", boom)
    c = ObsController(ObsConfig(launch_if_not_running=True, launch_command="obs"))
    assert c._launch_obs() is False


# ------------------------- 컨텐츠 팩 (2-2⑦) -------------------------
def _records_with_burst(tmp_path):
    """3분차에 채팅 급증이 있는 가짜 트랜스크립트."""
    start = datetime(2026, 7, 1, 20, 0, tzinfo=timezone.utc)
    recs = [{"t": start.isoformat(), "who": "system", "event": "broadcast_start"}]
    # 평상시: 0~2분에 1개씩
    for m in range(3):
        recs.append({"t": (start + timedelta(minutes=m, seconds=10)).isoformat(),
                     "who": "viewer", "author": "a", "text": f"잔잔{m}"})
    # 급증: 3분차에 8개
    for i in range(8):
        recs.append({"t": (start + timedelta(minutes=3, seconds=i * 5)).isoformat(),
                     "who": "viewer", "author": f"u{i}", "text": "ㅋㅋㅋㅋ 대박"})
    path = tmp_path / "2026-07-01_2000.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs),
                    encoding="utf-8")
    return path


def test_find_highlights_detects_burst(tmp_path):
    from aist.content import find_highlights
    from aist.transcript import read_transcript
    path = _records_with_burst(tmp_path)
    hl = find_highlights(read_transcript(path))
    assert hl, "급증 구간을 찾아야 함"
    stamp, count, sample = hl[0]
    assert stamp == "00:03:00" and count == 8
    assert "대박" in sample


def test_content_pack_generated(tmp_path):
    from aist.content import generate_content_pack
    path = _records_with_burst(tmp_path)
    out = generate_content_pack(Persona(name="별이"), path, str(tmp_path / "content"))
    text = out.read_text(encoding="utf-8")
    assert "하이라이트 후보" in text and "00:03:00" in text
    assert "다시보기 제목 후보" in text and "별이" in text


def test_content_pack_none_without_transcript(tmp_path):
    from aist.content import generate_content_pack
    assert generate_content_pack(Persona(), None, str(tmp_path)) is None


# ------------------------- 사전 공지 (2-2②) -------------------------
def test_pre_announce_default_on():
    """사람도 방송 전에 미리 알린다 — 사전 공지는 기본값(30분 전)."""
    from aist.config import AnnounceConfig
    assert AnnounceConfig().pre_announce_minutes == 30
