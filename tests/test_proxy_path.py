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
