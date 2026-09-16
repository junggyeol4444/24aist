"""AI 목소리가 시청자에게 가는 경로(/proxy-ws).

코어에는 두 개의 WebSocket 경로가 있다.
  /client-ws : 1:1. 채팅을 넣은 그 클라이언트에게만 결과(오디오·자막)를
               돌려준다. 우리가 여기로 채팅을 넣으면 AI 의 목소리가 우리
               프로세스로만 오고, OBS 가 잡는 웹UI 에는 아무것도 안 간다.
               게다가 코어는 '재생 끝났다'는 응답을 우리에게서 기다리며
               conversation-chain-end 를 영원히 안 보낸다(코어 소스의
               finalize_conversation_turn 은 타임아웃이 없다).
  /proxy-ws  : 웹UI 와 우리를 같은 대화에 물리고, 코어가 보내는 모든
               메시지를 양쪽에 뿌린다. 재생 완료 응답은 웹UI 가 보낸다.

즉 /client-ws 로 두면 방송은 도는 것처럼 보이는데 시청자에게는 멈춘
아바타와 무음만 나간다. 그래서 경로는 설정 실수가 아니라 구조 문제다.
"""

from pathlib import Path

import yaml

from aist.config import Config, load_config
from aist.preflight import config_problems, core_proxy_ready, frontend_proxy_ready

ROOT = Path(__file__).resolve().parents[1]

SAMPLE_INDEX = """\
<!doctype html>
<html>
  <head>
    <meta charset="UTF-8" />
    <script type="module" crossorigin src="./assets/main.js"></script>
  </head>
  <body><div id="root"></div></body>
</html>
"""


def test_default_endpoint_is_proxy():
    assert Config().vtuber.ws_url.endswith("/proxy-ws")


def test_example_config_uses_proxy():
    cfg = load_config(ROOT / "config" / "config.example.yaml")
    assert cfg.vtuber.ws_url.endswith("/proxy-ws"), cfg.vtuber.ws_url


def test_client_ws_is_reported_as_blocking():
    c = Config()
    c.vtuber.ws_url = "ws://127.0.0.1:12393/client-ws"
    probs = [p for p in config_problems(c) if "client-ws" in p]
    assert probs, "경로가 잘못됐는데 아무 말도 안 한다"
    assert all(getattr(p, "blocking", True) for p in probs)
    assert any("proxy-ws" in p for p in probs), "고칠 주소를 알려줘야 한다"


def test_korean_core_conf_enables_proxy():
    conf = ROOT / "Open-LLM-VTuber" / "conf.korean.yaml"
    data = yaml.safe_load(conf.read_text(encoding="utf-8"))
    assert data["system_config"]["enable_proxy"] is True


def test_core_proxy_ready_detects_disabled(tmp_path):
    core = tmp_path / "Open-LLM-VTuber"
    core.mkdir()
    (core / "conf.yaml").write_text("system_config:\n  enable_proxy: false\n",
                                    encoding="utf-8")
    ok, msg = core_proxy_ready(tmp_path)
    assert ok is False and "enable_proxy" in msg

    (core / "conf.yaml").write_text("system_config:\n  enable_proxy: true\n",
                                    encoding="utf-8")
    assert core_proxy_ready(tmp_path)[0] is True


def test_frontend_patch_points_web_ui_at_proxy(tmp_path):
    from aist.frontend_patch import is_patched, patch_index

    fe = tmp_path / "frontend"
    fe.mkdir()
    (fe / "index.html").write_text(SAMPLE_INDEX, encoding="utf-8")
    assert is_patched(fe / "index.html") is False

    patch_index(fe, "ws://127.0.0.1:12393/proxy-ws")
    html = (fe / "index.html").read_text(encoding="utf-8")
    assert is_patched(fe / "index.html") is True
    assert "proxy-ws" in html
    # 웹UI 본체(type=module)보다 먼저 실행돼야 값이 반영된다
    assert html.index("aist-proxy-ws-bootstrap") < html.index('type="module"')

    # 두 번 넣어도 하나만 남는다
    patch_index(fe, "ws://127.0.0.1:12393/proxy-ws")
    assert (fe / "index.html").read_text(encoding="utf-8").count(
        "aist-proxy-ws-bootstrap") == 1


def test_frontend_proxy_ready_reports_unpatched(tmp_path):
    fe = tmp_path / "Open-LLM-VTuber" / "frontend"
    fe.mkdir(parents=True)
    (fe / "index.html").write_text(SAMPLE_INDEX, encoding="utf-8")
    ok, msg = frontend_proxy_ready(tmp_path)
    assert ok is False and "client-ws" in msg

    from aist.frontend_patch import patch_index
    patch_index(fe)
    assert frontend_proxy_ready(tmp_path)[0] is True


# --------- 코어가 '시작조차' 못 하던 것들 (실제로 코어를 띄워서 찾음) ---------
def test_core_startup_files_are_shipped():
    """실제로 코어를 띄워 보니 이것들이 없어서 파이썬 예외로 죽었다.

      avatars/          → "Directory 'avatars' does not exist"
      mcp_servers.json  → "File 'mcp_servers.json' does not exist"
    새로 받은 사람은 코어 창이 깜빡이고 사라지는 것만 본다.
    """
    core = ROOT / "Open-LLM-VTuber"
    assert (core / "avatars").is_dir(), "avatars/ 가 없으면 코어가 안 뜬다"
    assert (core / "mcp_servers.json").is_file(), "mcp_servers.json 이 없으면 코어가 안 뜬다"
    import json
    assert "mcp_servers" in json.loads(
        (core / "mcp_servers.json").read_text(encoding="utf-8"))


def test_preflight_catches_missing_startup_files(tmp_path):
    from aist.preflight import core_startup_files_ready

    core = tmp_path / "Open-LLM-VTuber"
    core.mkdir()
    ok, msg = core_startup_files_ready(tmp_path)
    assert ok is False and "avatars" in msg and "mcp_servers.json" in msg

    (core / "avatars").mkdir()
    (core / "mcp_servers.json").write_text("{}", encoding="utf-8")
    assert core_startup_files_ready(tmp_path)[0] is True


def test_core_proxy_does_not_crash_on_silent_payload():
    """TTS 가 실패하면 코어는 audio=None 인 '무음 payload' 를 보낸다.

    그 자리에서 len(None) 이 터지면서 메시지가 어떤 클라이언트에게도 안 갔고,
    웹UI 가 재생 완료를 못 보내 대화가 영영 안 끝났다 — 그 뒤로 방송인이
    한 마디도 못 한다. (실제 코어를 띄워 재현하고 고쳤다)
    """
    src = (ROOT / "Open-LLM-VTuber" / "src" / "open_llm_vtuber"
           / "proxy_handler.py").read_text(encoding="utf-8")
    assert "len(message.get('audio', ''))" not in src, "수정이 되돌아갔습니다"
    assert "len(message.get('audio') or '')" in src

    # 같은 계산을 그대로 돌려본다(audio=None 이어도 안 터져야 한다)
    message = {"type": "audio", "audio": None, "volumes": [],
               "display_text": {"text": "안녕"}}
    log_msg = {**{k: v for k, v in message.items() if k != "audio"},
               "audio": f"[Audio data, {len(message.get('audio') or '')} bytes truncated]"}
    assert log_msg["display_text"]["text"] == "안녕"


def test_korean_conf_does_not_download_a_gigabyte_for_unused_asr():
    """이 방송은 마이크를 안 쓴다. 그런데 코어는 시작할 때 음성인식을 무조건
    초기화한다. 기본값(sherpa_onnx_asr)은 첫 실행에서 1GB 를 받는다."""
    conf = yaml.safe_load(
        (ROOT / "Open-LLM-VTuber" / "conf.korean.yaml").read_text(encoding="utf-8"))
    assert conf["character_config"]["asr_config"]["asr_model"] != "sherpa_onnx_asr"


def test_core_trims_conversation_memory():
    """방송이 길어져도 LLM 에 보내는 대화가 무한히 늘면 안 된다.

    코어의 기본 동작은 상한이 없어서, 매 응답마다 지금까지의 모든 대화를
    다시 보낸다. 실제로 재보니 채팅 30건에 LLM 이 받는 메시지가 60개까지
    늘었고(계속 증가), 상한을 켜면 42개에서 평평해졌다. 몇 시간짜리 방송
    에서는 갈수록 느려지다가 컨텍스트 한도에서 응답이 끊긴다.
    """
    core = ROOT / "Open-LLM-VTuber" / "src" / "open_llm_vtuber"
    agent = (core / "agent" / "agents" / "basic_memory_agent.py").read_text(
        encoding="utf-8")
    assert "_trim_memory" in agent, "대화 기록 상한 처리가 사라졌습니다"
    assert "self._trim_memory()" in agent

    factory = (core / "agent" / "agent_factory.py").read_text(encoding="utf-8")
    assert "max_memory_messages" in factory, "설정값이 에이전트로 전달되지 않습니다"

    conf = yaml.safe_load(
        (ROOT / "Open-LLM-VTuber" / "conf.korean.yaml").read_text(encoding="utf-8"))
    limit = (conf["character_config"]["agent_config"]["agent_settings"]
             ["basic_memory_agent"]["max_memory_messages"])
    assert isinstance(limit, int) and limit > 0, f"상한이 꺼져 있습니다: {limit}"
