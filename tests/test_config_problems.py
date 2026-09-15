"""설정값 자체의 오류 — "설정은 맞아 보이는데 정작 방송이 이상한" 부류.

패키지가 다 깔려 있고 pytest 가 전부 통과해도 여기 걸리면 방송이
조용히 엉뚱하게 돈다. 실제로 깨진 config 로 돌려보다 발견한 것들이다.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aist.config import Config, EndJudgeConfig
from aist.end_judge import EndJudge
from aist.preflight import config_problems

KST = ZoneInfo("Asia/Seoul")


def _cfg(**over):
    c = Config()
    # 예제 기본값은 공지가 켜져 있고 channel_id 가 0 이라 경고가 뜬다.
    c.announce.on_start = False
    c.announce.on_end = False
    c.announce.discord.enabled = False
    for k, v in over.items():
        setattr(c, k, v)
    return c


def test_clean_config_has_no_problems():
    c = _cfg()
    c.scheduler.weekly = {"mon": ["19:00"]}
    assert config_problems(c) == []


# --------------------------- 타임존 ----------------------------------------
def test_typo_timezone_is_caught():
    """오타 난 타임존은 조용히 UTC 로 떨어져 방송이 9시간 어긋난다."""
    c = _cfg()
    c.scheduler.timezone = "Asia/Seuol"      # Seoul 오타
    c.scheduler.weekly = {"mon": ["19:00"]}
    probs = config_problems(c)
    assert any("타임존" in p for p in probs)


def test_valid_timezone_passes():
    c = _cfg()
    c.scheduler.timezone = "Asia/Seoul"
    c.scheduler.weekly = {"mon": ["19:00"]}
    assert not any("타임존" in p for p in config_problems(c))


# --------------------------- 요일 키 ----------------------------------------
def test_korean_weekday_key_is_caught():
    """한글 요일 키를 쓰면 그 요일이 조용히 휴방이 된다."""
    c = _cfg()
    c.scheduler.weekly = {"월": ["19:00"], "tue": ["19:00"]}
    assert any("요일 키" in p for p in config_problems(c))


def test_all_valid_weekday_keys_pass():
    c = _cfg()
    c.scheduler.weekly = {d: [] for d in
                          ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    c.scheduler.weekly["mon"] = ["19:00"]
    assert not any("요일 키" in p for p in config_problems(c))


# --------------------------- 시각 형식 --------------------------------------
def test_bad_time_format_is_caught():
    c = _cfg()
    c.scheduler.weekly = {"mon": ["25:00"]}
    assert any("시각" in p for p in config_problems(c))


# --------------------------- 전부 휴방 --------------------------------------
def test_all_days_off_with_auto_run_is_caught():
    c = _cfg()
    c.scheduler.enabled = True
    c.scheduler.weekly = {d: [] for d in
                          ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    assert any("하나도 없습니다" in p for p in config_problems(c))


def test_all_days_off_is_fine_when_auto_run_off():
    c = _cfg()
    c.scheduler.enabled = False
    c.scheduler.weekly = {d: [] for d in
                          ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    assert not any("하나도 없습니다" in p for p in config_problems(c))


# --------------------------- 종료 판단 값 -----------------------------------
def test_min_greater_than_max_is_caught():
    c = _cfg()
    c.scheduler.weekly = {"mon": ["19:00"]}
    c.end_judge.min_minutes = 200
    c.end_judge.max_minutes = 180
    assert any("min_minutes" in p for p in config_problems(c))


# --------------------------- 공지 --------------------------------------------
def test_announce_on_but_nowhere_to_post():
    c = Config()
    c.scheduler.weekly = {"mon": ["19:00"]}
    c.announce.on_start = True
    c.announce.discord.enabled = False
    c.announce.naver_cafe.enabled = False
    assert any("아무 데도" in p for p in config_problems(c))


def test_discord_enabled_without_channel_id():
    c = Config()
    c.scheduler.weekly = {"mon": ["19:00"]}
    c.announce.discord.enabled = True
    c.announce.discord.channel_id = 0
    assert any("channel_id" in p for p in config_problems(c))


# --------------------------- 마무리 예고가 사라지던 버그 --------------------
def _phases(cfg, start):
    ej = EndJudge(cfg, start)
    seen = {}
    for m in range(0, 400):
        d = ej.evaluate(start + timedelta(minutes=m), None)
        seen.setdefault(d.phase.name, m)
        if d.phase.name == "END":
            break
    return seen


def test_pre_notice_survives_short_broadcast():
    """방송이 min_minutes 로 짧아져도 마무리 예고가 나와야 한다.

    예고 시각을 min_end 로 당기는데 예정 종료도 min_end 라서 둘이 같아지면
    예고가 영영 안 나왔다. 그러면 예고 없이 갑자기 마무리 인사하고 끊긴다
    — 기획안 4-3 이 금지한 "뚝 끄기"가 그대로 일어난다.
    """
    cfg = EndJudgeConfig(scheduled_end_hhmm="00:00")   # config.example.yaml 값
    start = datetime(2026, 9, 15, 23, 0, tzinfo=KST)   # 23:00 시작 → 60분 방송
    seen = _phases(cfg, start)
    assert "PRE_NOTICE" in seen, f"예고 단계가 사라졌다: {seen}"
    assert seen["PRE_NOTICE"] < seen["END"]


def test_pre_notice_still_normal_on_full_length_broadcast():
    cfg = EndJudgeConfig(scheduled_end_hhmm="00:00")
    start = datetime(2026, 9, 15, 19, 0, tzinfo=KST)   # 180분 방송
    seen = _phases(cfg, start)
    assert seen["PRE_NOTICE"] == 160      # 종료 20분 전 그대로
    assert seen["END"] == 180


def test_pre_notice_never_lands_after_end():
    """어떤 시작 시각에서도 예고가 종료보다 늦으면 안 된다."""
    cfg = EndJudgeConfig(scheduled_end_hhmm="00:00")
    for h in range(0, 24):
        start = datetime(2026, 9, 15, h, 0, tzinfo=KST)
        seen = _phases(cfg, start)
        assert "PRE_NOTICE" in seen, f"{h:02d}시 시작에서 예고 없음: {seen}"
        assert seen["PRE_NOTICE"] < seen["END"], f"{h:02d}시 시작에서 예고가 종료 이후"


# --------------------------- 윈도우 타임존 --------------------------------
# Wine 에 윈도우 파이썬을 올려 aist check 를 실제로 돌려보다 찾았다.
# 윈도우에는 시스템 타임존 DB 가 없다(TZPATH 가 비어 있다). tzdata 패키지가
# 없으면 정상적인 'Asia/Seoul' 도 ZoneInfoNotFoundError 를 낸다.
#
# 그러면 orchestrator._now() 가 조용히 PC 로컬 시간으로 떨어져서
# config 의 timezone 설정이 통째로 무시된다 — 24시간 자동 운영의 스케줄러가
# 설정대로 안 돈다. 리눅스에서는 멀쩡해서 리눅스만 테스트하면 안 보인다.
def test_tzdata_is_a_windows_dependency():
    """윈도우에서 zoneinfo 가 돌려면 tzdata 가 반드시 깔려야 한다."""
    import tomllib
    with open("pyproject.toml", "rb") as fh:
        data = tomllib.load(fh)
    deps = data["project"]["dependencies"]
    tz = [d for d in deps if d.lower().startswith("tzdata")]
    assert tz, f"tzdata 가 핵심 의존성에 없습니다: {deps}"
    assert "win32" in tz[0], f"윈도우 마커가 없습니다: {tz[0]}"


def test_missing_tzdata_gives_actionable_message(monkeypatch):
    """tzdata 가 없어서 실패한 것을 '오타'라고 안내하면 안 된다.

    멀쩡한 Asia/Seoul 을 고치라고 하면 운영자가 헤맨다.
    """
    import builtins
    import zoneinfo
    real_import = builtins.__import__

    def no_tzdata(name, *a, **k):
        if name == "tzdata":
            raise ImportError("no tzdata")
        return real_import(name, *a, **k)

    def boom(key):
        raise zoneinfo.ZoneInfoNotFoundError(f"No time zone found with key {key}")

    monkeypatch.setattr(builtins, "__import__", no_tzdata)
    monkeypatch.setattr(zoneinfo, "ZoneInfo", boom)
    monkeypatch.setattr(zoneinfo, "TZPATH", ())

    c = _cfg()
    c.scheduler.timezone = "Asia/Seoul"      # 멀쩡한 값
    c.scheduler.weekly = {"mon": ["19:00"]}
    probs = config_problems(c)
    msg = " ".join(probs)
    assert "tzdata" in msg, f"해결 방법(pip install tzdata)이 없습니다: {probs}"
    assert "오타" not in msg


def test_now_warns_instead_of_silently_falling_back(caplog):
    """타임존을 못 쓰면 조용히 넘어가지 말고 알려야 한다."""
    import logging
    from aist import orchestrator as orch

    orch._tz_warned.clear()
    with caplog.at_level(logging.ERROR):
        orch._now("Nowhere/Nothing")
    assert any("로컬 시간" in r.getMessage() for r in caplog.records), \
        f"경고가 없습니다: {[r.getMessage() for r in caplog.records]}"


def test_now_warns_only_once_per_timezone(caplog):
    """매 호출마다 찍으면 24시간 로그가 폭발한다."""
    import logging
    from aist import orchestrator as orch

    orch._tz_warned.clear()
    with caplog.at_level(logging.ERROR):
        for _ in range(20):
            orch._now("Nowhere/Nothing")
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1, f"{len(errors)}번 찍혔습니다"


# ---- "방송이 안 됩니다" 는 진짜 안 될 때만 ----
def test_discord_channel_missing_does_not_block_broadcast():
    """디스코드 채널 ID 가 비었다고 방송이 안 되는 건 아니다.

    예시 설정 그대로면 discord.enabled=true / channel_id=0 이라, 점검이
    "지금 상태로는 방송이 안 됩니다" 라고 단정했다 — 거짓말이다.
    """
    c = Config()
    c.announce.discord.enabled = True
    c.announce.discord.channel_id = 0
    probs = [p for p in config_problems(c) if "channel_id" in p]
    assert probs, "문제로 알리기는 해야 한다"
    assert all(getattr(p, "blocking", True) is False for p in probs)


def test_timezone_problem_still_blocks():
    c = Config()
    c.scheduler.timezone = "Asia/Seoull"
    probs = [p for p in config_problems(c) if "타임존" in p]
    assert probs and all(getattr(p, "blocking", True) for p in probs)


def test_check_does_not_declare_failure_for_non_blocking_only(tmp_path, monkeypatch, capsys):
    """막는 문제가 없으면 '방송이 안 됩니다' 가 나오면 안 된다."""
    import argparse

    import aist.cli as cli
    import aist.preflight as pf
    from aist.persona import Persona

    c = Config()
    c.announce.discord.enabled = True
    c.announce.discord.channel_id = 0
    monkeypatch.setattr(cli, "_load", lambda args: (c, Persona()))
    monkeypatch.setattr(pf, "missing", lambda cfg: [])
    monkeypatch.setattr(pf, "core_frontend_ready", lambda: (True, ""))
    monkeypatch.setattr(pf, "core_conf_ready", lambda: (True, ""))
    monkeypatch.setattr(pf, "core_deps_ready", lambda: (True, "ok"))
    monkeypatch.setattr(pf, "core_python_ok", lambda: (True, "3.12"))
    monkeypatch.setattr(pf, "core_proxy_ready", lambda: (True, "켜짐"))
    monkeypatch.setattr(pf, "frontend_proxy_ready", lambda: (True, "설정됨"))

    rc = cli.cmd_check(argparse.Namespace(config="x", persona="y"))
    out = capsys.readouterr().out
    assert "방송이 안 됩니다" not in out, out
    assert "channel_id" in out          # 알리기는 한다
    assert rc == 0
