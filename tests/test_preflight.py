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


# ------------------- 방송인 목소리(코어 TTS) 점검 -------------------
def _core_conf(tmp_path, tts_block: str):
    core = tmp_path / "Open-LLM-VTuber"
    core.mkdir(parents=True, exist_ok=True)
    (core / "conf.yaml").write_text(
        "character_config:\n  tts_config:\n" + tts_block, encoding="utf-8")
    return tmp_path


def test_tts_check_catches_empty_ref_audio(tmp_path):
    """기본으로 실려 있는 gpt_sovits 는 ref_audio_path 가 비어 있다.

    그대로 방송하면 코어가 조용히 실패해서 자막만 나가고 목소리가 안 난다
    (실제 코어에서 audio=0바이트로 확인). 켜기 전에 잡아야 한다.
    """
    from aist.preflight import core_tts_config
    root = _core_conf(tmp_path,
                      "    tts_model: 'gpt_sovits_tts'\n"
                      "    gpt_sovits_tts:\n"
                      "      api_url: 'http://127.0.0.1:9880/tts'\n"
                      "      ref_audio_path: ''\n")
    ok, msg = core_tts_config(root)
    assert ok is False and "ref_audio_path" in msg


def test_tts_check_catches_dead_local_server(tmp_path):
    from aist.preflight import core_tts_config
    root = _core_conf(tmp_path,
                      "    tts_model: 'gpt_sovits_tts'\n"
                      "    gpt_sovits_tts:\n"
                      "      api_url: 'http://127.0.0.1:9880/tts'\n"
                      "      ref_audio_path: 'voice/ref.wav'\n")
    ok, msg = core_tts_config(root)
    assert ok is False and "서버" in msg


def test_tts_check_passes_for_server_less_model(tmp_path):
    """별도 서버가 필요 없는 TTS 면 통과해야 한다(오탐 방지)."""
    from aist.preflight import core_tts_config
    root = _core_conf(tmp_path,
                      "    tts_model: 'edge_tts'\n"
                      "    edge_tts:\n"
                      "      voice: 'ko-KR-SunHiNeural'\n")
    assert core_tts_config(root) == (True, "edge_tts")


def test_tts_check_reports_missing_model(tmp_path):
    from aist.preflight import core_tts_config
    root = _core_conf(tmp_path, "    azure_tts:\n      api_key: ''\n")
    ok, msg = core_tts_config(root)
    assert ok is False and "tts_model" in msg


def test_llm_check_catches_dead_local_server(tmp_path):
    """로컬 LLM(ollama 등)이 안 떠 있으면 점검이 잡아야 한다.

    저장소에 실린 코어 설정은 ollama(localhost:11434)를 쓴다. 그런데
    윈도우 설치 순서 어디에도 ollama 를 설치·실행하는 단계가 없다.
    예전에는 "떠 있어야 합니다" 한 줄과 함께 OK 로 넘겼다 — 운영자는
    점검을 통과한 줄 알고 방송을 켜고, 방송인은 대답 대신 영어 오류
    문구를 읽는다(실제 코어에서 확인한 동작).
    """
    from aist.preflight import core_llm_config

    core = tmp_path / "Open-LLM-VTuber"
    core.mkdir(parents=True)
    (core / "conf.yaml").write_text(
        "character_config:\n"
        "  agent_config:\n"
        "    agent_settings:\n"
        "      basic_memory_agent:\n"
        "        llm_provider: 'ollama_llm'\n"
        "    llm_configs:\n"
        "      ollama_llm:\n"
        "        base_url: 'http://127.0.0.1:11434/v1'\n"
        "        model: 'qwen2.5:latest'\n", encoding="utf-8")
    ok, msg = core_llm_config(tmp_path)
    assert ok is False and "안 떠 있습니다" in msg


def test_llm_check_passes_for_a_filled_cloud_key(tmp_path):
    """클라우드 LLM 은 키만 채워져 있으면 통과한다(네트워크는 안 본다)."""
    from aist.preflight import core_llm_config

    core = tmp_path / "Open-LLM-VTuber"
    core.mkdir(parents=True)
    (core / "conf.yaml").write_text(
        "character_config:\n"
        "  agent_config:\n"
        "    agent_settings:\n"
        "      basic_memory_agent:\n"
        "        llm_provider: 'openai_llm'\n"
        "    llm_configs:\n"
        "      openai_llm:\n"
        "        llm_api_key: 'sk-real-looking-key'\n"
        "        model: 'gpt-4o-mini'\n", encoding="utf-8")
    assert core_llm_config(tmp_path)[0] is True
