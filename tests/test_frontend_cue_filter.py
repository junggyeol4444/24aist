"""웹UI 에 매니저 귓속말이 자막으로 뜨지 않게 하는 필터.

코어는 우리가 보내는 text-input 을 그대로 복사해 user-input-transcription 으로
다른 클라이언트(= OBS 가 잡는 웹UI)에 뿌린다(proxy_message_queue.
_forward_message). 실제로 코어에 붙여 엿들어보니 이렇게 왔다:

  {"type": "user-input-transcription",
   "text": "(매니저 귓속말: 방송 방금 시작했어. 방송 여는 인사로 시작해줘...)"}

웹UI 는 이걸 "사용자가 한 말" 자막으로 띄운다. 코어에 끄는 설정은 없고,
다른 입력 방식(ai-speak-signal)은 우리 문장을 싣지 못한다. 그래서 우리가
index.html 에 넣는 스크립트에서 괄호로 시작하는 것만 걸러낸다.

진짜 Chromium 으로도 확인했다(onmessage/addEventListener 두 방식 모두, 필터를
뺀 대조군에서는 귓속말이 앱에 그대로 들어감). 여기서는 node 로 같은 스크립트를
실제로 실행해 본다.
"""

import json
import shutil
import subprocess

import pytest

from aist.frontend_patch import MARK, _script, patch_index

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node 가 없어 스크립트를 실행해 볼 수 없다")

_HARNESS = r"""
// 브라우저 대신 쓰는 최소 WebSocket — 이벤트 순서는 브라우저와 같다
// (같은 대상의 리스너는 등록 순서대로, stopImmediatePropagation 이면 멈춤).
class FakeWS {
  constructor(url, protocols) { this.url = url; this._ls = []; this._on = null;
                                this.readyState = 1; }
  addEventListener(t, fn) { if (t === "message") this._ls.push(fn); }
  set onmessage(fn) { this._on = fn; this._ls.push((ev) => this._on && this._on(ev)); }
  get onmessage() { return this._on; }
  _deliver(data) {
    let stopped = false;
    const ev = { data, stopImmediatePropagation() { stopped = true; } };
    for (const fn of this._ls) { fn(ev); if (stopped) break; }
  }
}
FakeWS.CONNECTING = 0; FakeWS.OPEN = 1; FakeWS.CLOSING = 2; FakeWS.CLOSED = 3;
const store = {};
global.window = { WebSocket: FakeWS,
  localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; } } };

__SCRIPT__

const WS = window.WebSocket;
const got = { prop: [], listener: [] };
const a = new WS("ws://x/"); a.onmessage = ev => got.prop.push(ev.data);
const b = new WS("ws://x/", []); b.addEventListener("message", ev => got.listener.push(ev.data));
for (const m of JSON.parse(process.argv[process.argv.length - 1])) { a._deliver(m); b._deliver(m); }
console.log(JSON.stringify({ got, open: WS.OPEN, patched: !!WS.__aistCueFilter }));
"""


def _run(messages):
    body = _script("ws://127.0.0.1:12393/proxy-ws")
    js = body.split(">", 1)[1].rsplit("</script>", 1)[0]
    src = _HARNESS.replace("__SCRIPT__", js)
    r = subprocess.run(["node", "-e", src, json.dumps(messages)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _t(text):
    return json.dumps({"type": "user-input-transcription", "text": text},
                      ensure_ascii=False)


@needs_node
def test_귓속말은_걸러지고_나머지는_그대로():
    msgs = [
        _t("(매니저 귓속말: 비밀 지시)"),
        _t("별하나 (치지직): 안녕"),
        json.dumps({"type": "audio", "display_text": {"text": "안녕"}}),
        _t("  （전각 귓속말"),
        "hello-not-json",
    ]
    out = _run(msgs)
    for style in ("prop", "listener"):
        got = out["got"][style]
        assert not any("귓속말" in m for m in got), (style, got)
        assert len(got) == 3, (style, got)
    assert out["open"] == 1 and out["patched"] is True


@needs_node
def test_필터가_있어도_시청자_채팅_자막은_간다():
    """시청자 채팅은 소독 단계에서 괄호로 시작할 수 없게 해뒀다."""
    out = _run([_t("라면조아 (유튜브): 오늘 뭐 해요?")])
    assert len(out["got"]["prop"]) == 1


def test_두_번_패치해도_필터는_하나(tmp_path):
    (tmp_path / "index.html").write_text(
        '<html><head></head><body><script type="module" src="/a.js"></script>'
        "</body></html>", encoding="utf-8")
    patch_index(tmp_path)
    patch_index(tmp_path)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert html.count(f'id="{MARK}"') == 1
    assert html.count("__aistCueFilter = true") == 1


# ---------------- 이미 설치한 운영자도 새 필터를 받는지 ----------------
def _old_patch_html():
    """귓속말 필터가 없던 예전 버전 패치를 흉내낸다."""
    s = _script("ws://127.0.0.1:12393/proxy-ws")
    cut = s.index("        var OrigWS = window.WebSocket;")
    end = s.index("      } catch (e) {}\n    </script>")
    old = s[:cut] + s[end:]
    return ('<html><head><title>x</title>\n' + old + '</head><body>'
            '<script type="module" src="/a.js"></script></body></html>')


def test_예전_패치는_점검에서_걸린다(tmp_path):
    """MARK 만 보면 '설정됨' 으로 나와서 운영자는 필터가 없는 걸 모른다."""
    from aist.frontend_patch import patch_state
    idx = tmp_path / "index.html"
    idx.write_text(_old_patch_html(), encoding="utf-8")
    assert patch_state(idx) == "old"
    patch_index(tmp_path)
    assert patch_state(idx) == "current"


def test_출력_인코딩이_깨져도_성공은_성공(tmp_path):
    """패치는 성공했는데 결과 문장을 print 하다 한글에서 죽어 종료코드 1.

    배치는 그걸 보고 "웹UI 주소 설정을 못 넣었습니다" 를 띄웠다(Wine 에서 재현).
    cp1252 처럼 한글을 못 쓰는 출력으로 실제 프로세스를 돌려 확인한다.
    """
    import os
    import sys
    idx = tmp_path / "index.html"
    idx.write_text(_old_patch_html(), encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    r = subprocess.run([sys.executable, "-m", "aist.frontend_patch", str(tmp_path)],
                       capture_output=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert "__aistCueFilter" in idx.read_text(encoding="utf-8")
