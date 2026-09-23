"""웹UI 가 코어 주소를 '지금 페이지 주소'에서 읽는지.

예전 패치는 ws://127.0.0.1:12393 을 박아 넣었다. 코어 포트를 바꾸면
(윈도우가 12393 을 예약 범위로 잡아 코어가 못 뜨는 경우 등) 웹UI 는 없는
포트로 붙으려다 빈 화면만 냈다 — 실제 코어를 12500 에 띄우고 진짜 웹UI
빌드를 크로미움으로 열어 확인했다. 배경 그림도 12393 으로 저장돼 깨졌다.
"""
import json
import shutil
import subprocess

import pytest

from aist.frontend_patch import _script, patch_index, patch_state

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node 가 없어 스크립트를 실행해 볼 수 없다")

_HARNESS = r"""
const args = JSON.parse(process.argv[process.argv.length - 1]);
const store = {};
for (const [k, v] of Object.entries(args.stored)) store[k] = JSON.stringify(v);
global.location = args.location;
global.window = { WebSocket: function () {},
  localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; } } };
__SCRIPT__
const out = {};
for (const k of Object.keys(store)) out[k] = JSON.parse(store[k]);
console.log(JSON.stringify(out));
"""


def _run(location, stored=None):
    body = _script("ws://127.0.0.1:12393/proxy-ws")
    js = body.split(">", 1)[1].rsplit("</script>", 1)[0]
    src = _HARNESS.replace("__SCRIPT__", js)
    r = subprocess.run(["node", "-e", src,
                        json.dumps({"location": location, "stored": stored or {}})],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


_P12500 = {"protocol": "http:", "host": "127.0.0.1:12500"}


@needs_node
def test_다른_포트에서_열면_그_포트로_붙는다():
    got = _run(_P12500)
    assert got["wsUrl"] == "ws://127.0.0.1:12500/proxy-ws"
    assert got["baseUrl"] == "http://127.0.0.1:12500"
    assert got["backgroundUrl"].startswith("http://127.0.0.1:12500/bg/")


@needs_node
def test_예전_패치가_남긴_12393_은_고친다():
    got = _run(_P12500, {
        "wsUrl": "ws://127.0.0.1:12393/proxy-ws",
        "baseUrl": "http://127.0.0.1:12393",
        "backgroundUrl": "http://127.0.0.1:12393/bg/room.jpeg"})
    assert got["wsUrl"] == "ws://127.0.0.1:12500/proxy-ws"
    assert got["baseUrl"] == "http://127.0.0.1:12500"
    assert got["backgroundUrl"] == "http://127.0.0.1:12500/bg/room.jpeg"


@needs_node
def test_운영자가_직접_넣은_주소는_안_건드린다():
    mine = {"wsUrl": "ws://192.168.0.9:9999/proxy-ws",
            "baseUrl": "http://192.168.0.9:9999",
            "backgroundUrl": "http://192.168.0.9:9999/bg/my.png"}
    assert _run(_P12500, dict(mine)) == mine


@needs_node
def test_다른_PC_의_OBS_가_LAN_주소로_열어도_된다():
    got = _run({"protocol": "http:", "host": "192.168.0.5:12393"})
    assert got["wsUrl"] == "ws://192.168.0.5:12393/proxy-ws"
    assert got["baseUrl"] == "http://192.168.0.5:12393"


@needs_node
def test_기본_포트면_웹UI_기본값을_굳이_바꾸지_않는다():
    got = _run({"protocol": "http:", "host": "127.0.0.1:12393"})
    assert got == {"wsUrl": "ws://127.0.0.1:12393/proxy-ws"}


@needs_node
def test_파일로_열면_넘겨준_주소를_쓴다():
    got = _run({"protocol": "file:", "host": ""})
    assert got == {"wsUrl": "ws://127.0.0.1:12393/proxy-ws"}


def test_포트를_박아_넣던_예전_패치는_점검에서_걸린다(tmp_path):
    s = _script("ws://127.0.0.1:12393/proxy-ws")
    old = "\n".join(l for l in s.splitlines() if "location" not in l)
    idx = tmp_path / "index.html"
    idx.write_text("<html><head>\n" + old + "\n</head><body>"
                   '<script type="module" src="/a.js"></script></body></html>',
                   encoding="utf-8")
    assert patch_state(idx) == "old"
    patch_index(tmp_path)
    assert patch_state(idx) == "current"


def test_코어_포트와_ws_url_포트가_다르면_알려준다(tmp_path):
    from aist.preflight import core_port_mismatch
    core = tmp_path / "Open-LLM-VTuber"
    core.mkdir()
    # 실제 코어 설정처럼 포트를 따옴표 문자열로 적어도 읽는다.
    (core / "conf.yaml").write_text("system_config:\n  port: '12500'\n",
                                    encoding="utf-8")
    msg = core_port_mismatch("ws://127.0.0.1:12393/proxy-ws", tmp_path)
    assert "12500" in msg and "12393" in msg
    assert core_port_mismatch("ws://127.0.0.1:12500/proxy-ws", tmp_path) == ""
    assert core_port_mismatch("ws://x/proxy-ws", tmp_path / "없음") == ""
