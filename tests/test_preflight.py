"""preflight — '설정은 맞는데 정작 못 도는' 상태를 잡는지.

check 가 패키지 미설치를 못 보고 "점검 완료"를 찍던 회귀를 막는다.
"""

from aist import preflight
from aist.config import load_config


def _cfg():
    return load_config("config/config.example.yaml")


def test_core_websockets_is_always_blocking():
    """코어 연결은 실패하면 사이클이 중단되므로 blocking 이어야 한다."""
    ns = {n.module: n for n in preflight.needs(_cfg())}
    assert "websockets" in ns
    assert ns["websockets"].blocking is True


def test_obs_not_required_when_start_stream_off():
    """start_stream=False 면 송출은 운영자 수동이라 obsws 가 필수는 아니다."""
    cfg = _cfg()
    cfg.obs.start_stream = False
    cfg.obs.launch_if_not_running = False
    assert "obsws_python" not in {n.module for n in preflight.needs(cfg)}

    cfg.obs.start_stream = True
    assert "obsws_python" in {n.module for n in preflight.needs(cfg)}


def test_disabled_features_are_not_required():
    """꺼둔 기능의 패키지를 요구하지 않아야 한다(공지/기억)."""
    cfg = _cfg()
    cfg.announce.discord.enabled = False
    cfg.announce.naver_cafe.enabled = False
    cfg.memory.backend = "json"
    cfg.llm.provider = "dummy"
    mods = {n.module for n in preflight.needs(cfg)}
    assert "chromadb" not in mods
    assert "selenium" not in mods
    assert "openai" not in mods


def test_optional_features_are_non_blocking():
    """공지 LLM 이 없어도 방송 자체는 돌아간다 → blocking 아님."""
    cfg = _cfg()
    cfg.llm.provider = "openai"
    ns = {n.module: n for n in preflight.needs(cfg)}
    assert ns["openai"].blocking is False


def test_same_package_merged_once():
    """websockets 는 코어와 채팅 양쪽이 쓰지만 한 줄로 합쳐진다."""
    cfg = _cfg()
    cfg.platform = "twitch"
    ns = [n for n in preflight.needs(cfg) if n.module == "websockets"]
    assert len(ns) == 1
    assert "코어" in ns[0].feature and "채팅" in ns[0].feature


def test_install_hint_lists_extras():
    hint = preflight.install_hint(preflight.needs(_cfg()))
    assert hint.startswith('pip install -e ".[')
    assert "vtuber" in hint


def test_frontend_missing_is_reported():
    """frontend/index.html 이 없으면 '준비됨'이라고 하면 안 된다."""
    ok, msg = preflight.core_frontend_ready(preflight.repo_root())
    expected = (preflight.repo_root() / "Open-LLM-VTuber" / "frontend" / "index.html").is_file()
    assert ok is expected
    if not ok:
        assert "프론트엔드" in msg or "Open-LLM-VTuber" in msg


def test_gate_blocks_when_blocking_package_missing(capsys):
    """방송 명령은 필수 패키지가 없으면 '시작 전에' 막아야 한다."""
    from aist.cli import _gate
    cfg = _cfg()
    cfg.platform = "youtube"          # pytchat 필요
    if not preflight.Need("", "pytchat", "pytchat", "youtube", True).installed:
        assert _gate(cfg, force=False) is False
        assert "방송을 시작할 수 없습니다" in capsys.readouterr().out
        # --force 면 경고만 하고 통과
        assert _gate(cfg, force=True) is True


def test_gate_passes_when_nothing_blocking(monkeypatch):
    """막을 게 없으면 그냥 통과."""
    from aist.cli import _gate
    monkeypatch.setattr(preflight, "missing", lambda cfg: [])
    assert _gate(_cfg(), force=False) is True


def test_core_conf_missing_is_reported():
    """conf.yaml 이 없으면 코어가 안 뜬다 — '준비됨'이라고 하면 안 된다."""
    ok, msg = preflight.core_conf_ready(preflight.repo_root())
    expected = (preflight.repo_root() / "Open-LLM-VTuber" / "conf.yaml").is_file()
    assert ok is expected
    if not ok:
        assert "conf.yaml" in msg


def test_core_conf_ready_when_present(tmp_path):
    core = tmp_path / "Open-LLM-VTuber"
    core.mkdir()
    (core / "conf.korean.yaml").write_text("x", encoding="utf-8")
    ok, msg = preflight.core_conf_ready(tmp_path)
    assert ok is False and "setup_openllm_vtuber" in msg

    (core / "conf.yaml").write_text("x", encoding="utf-8")
    ok, _ = preflight.core_conf_ready(tmp_path)
    assert ok is True


def test_core_deps_reported_when_missing(tmp_path):
    """코어 의존성이 없으면 '준비됨'이라고 하면 안 된다."""
    core = tmp_path / "Open-LLM-VTuber"
    core.mkdir()
    ok, msg = preflight.core_deps_ready(tmp_path)
    if not ok:
        assert "코어 의존성 미설치" in msg

    # 코어 전용 .venv 가 있으면 준비된 것으로 본다(uv 로 따로 도는 경우).
    (core / ".venv").mkdir()
    ok2, msg2 = preflight.core_deps_ready(tmp_path)
    assert ok2 is True and ".venv" in msg2


def test_core_python_range_is_checked(monkeypatch):
    """코어가 지원하지 않는 파이썬이면 '준비됨'이라고 하면 안 된다."""
    import types
    for ver, expect_ok in [((3, 12), True), ((3, 11), True),
                           ((3, 13), False), ((3, 14), False), ((3, 9), False)]:
        monkeypatch.setattr(preflight, "sys",
                            types.SimpleNamespace(version_info=ver))
        ok, msg = preflight.core_python_ok()
        assert ok is expect_ok, f"{ver}: {msg}"
        if not ok:
            assert "코어" in msg


def test_core_python_ok_when_core_absent(monkeypatch, tmp_path):
    """코어 pyproject 가 없으면 막지 않는다(판단 근거가 없다)."""
    ok, msg = preflight.core_python_ok(tmp_path)
    assert ok is True
