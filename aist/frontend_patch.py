"""웹UI(프론트엔드)가 /proxy-ws 에 붙게 만든다.

코어의 웹UI 는 기본적으로 ws://127.0.0.1:12393/client-ws 에 붙는다.
그런데 /client-ws 는 "채팅을 넣은 클라이언트에게만" 결과를 돌려주는
1:1 경로다. 우리가 채팅을 넣으면 AI 의 목소리·자막이 우리 프로세스로만
오고, OBS 가 잡는 웹UI 에는 아무것도 안 간다 — 시청자에게는 멈춰 있는
아바타와 무음만 나간다.

같은 대화에 둘 다 물리려면 양쪽 모두 /proxy-ws 로 가야 한다. 웹UI 의
주소는 설정 화면에서 바꿀 수 있지만(브라우저 localStorage 에 저장),
운영자에게 OBS 브라우저 소스 안에서 그걸 하라고 할 수는 없다.
그래서 받아온 index.html 에 짧은 스크립트를 넣어, 저장된 값이 없거나
예전 기본값(/client-ws)일 때만 /proxy-ws 로 맞춰준다.
운영자가 직접 다른 주소를 넣어둔 경우에는 건드리지 않는다.
"""

import re
from pathlib import Path
from typing import Optional

MARK = "aist-proxy-ws-bootstrap"
DEFAULT_WS = "ws://127.0.0.1:12393/proxy-ws"
_OLD_DEFAULTS = ("ws://127.0.0.1:12393/client-ws", "ws://localhost:12393/client-ws",
                 # 예전 버전의 이 패치가 넣던 값. 코어 포트를 바꾸면 이 값이
                 # OBS 브라우저 소스에 남아 옛 포트로 붙으려 한다.
                 "ws://127.0.0.1:12393/proxy-ws", "ws://localhost:12393/proxy-ws")
# 웹UI 의 모델·배경 주소 기본값(웹UI 코드에 박혀 있다).
_OLD_BASES = ("http://127.0.0.1:12393", "http://localhost:12393")


def _script(ws_url: str) -> str:
    olds = ", ".join(f'"{u}"' for u in _OLD_DEFAULTS)
    old_bases = ", ".join(f'"{u}"' for u in _OLD_BASES)
    return (
        f'    <script id="{MARK}">\n'
        # 함수로 감싼다. 감싸지 않으면 var 들이 전역(window.b 등)이 되어,
        # 뒤에 오는 평범한 script 가 같은 이름을 let/const 로 선언하는 순간
        # 그 script 가 SyntaxError 로 통째로 죽는다(node 로 재현).
        "      (function () {\n"
        "      // 방송 자동화(aist)가 넣은 줄 — 웹UI 를 /proxy-ws 에 붙인다.\n"
        "      // (웹UI 는 localStorage 에 JSON 문자열로 저장한다)\n"
        # 이 페이지는 코어가 직접 내준다. 그러니 '지금 이 페이지의 주소'가
        # 곧 코어 주소다. 예전에는 127.0.0.1:12393 을 박아 넣어서, 코어
        # 포트를 바꾸면(윈도우가 12393 을 예약해 코어가 못 뜨는 경우가 있다)
        # 웹UI 가 없는 포트로 붙으려다 빈 화면만 나왔다 — 실제 크로미움으로
        # 12500 에서 띄워 확인. 다른 PC 의 OBS 가 LAN 주소로 열 때도 같다.
        "      try {\n"
        f'        var want = "{ws_url}";\n'
        "        var base = null;\n"
        "        try {\n"
        '          if (location.protocol === "http:" || location.protocol === "https:") {\n'
        '            want = (location.protocol === "https:" ? "wss://" : "ws://")\n'
        '                   + location.host + "/proxy-ws";\n'
        "            base = location.protocol + \"//\" + location.host;\n"
        "          }\n"
        "        } catch (e) {}\n"
        f"        var stale = [{olds}];\n"
        "        var read = function (k) {\n"
        "          var cur = window.localStorage.getItem(k);\n"
        "          if (!cur) return null;\n"
        "          try { return JSON.parse(cur); } catch (e) { return cur; }\n"
        "        };\n"
        '        var val = read("wsUrl");\n'
        "        if (!val || (val !== want && stale.indexOf(val) !== -1)) {\n"
        '          window.localStorage.setItem("wsUrl", JSON.stringify(want));\n'
        "        }\n"
        "        if (base) {\n"
        f"          var staleBase = [{old_bases}];\n"
        '          var b = read("baseUrl");\n'
        "          if ((!b && base !== staleBase[0]) ||\n"
        "              (b && b !== base && staleBase.indexOf(b) !== -1)) {\n"
        '            window.localStorage.setItem("baseUrl", JSON.stringify(base));\n'
        "          }\n"
        # 배경 그림 주소는 웹UI 가 baseUrl 설정과 상관없이 박힌 기본값
        # (12393)으로 만들어 저장해 버린다 — 실제 크로미움에서 확인.
        # 옛 주소로 저장돼 있으면 앞부분만 지금 주소로 바꾼다.
        '          var bg = read("backgroundUrl");\n'
        "          if (!bg && base !== staleBase[0]) {\n"
        '            bg = staleBase[0] + "/bg/ceiling-window-room-night.jpeg";\n'
        "          }\n"
        "          for (var i = 0; bg && i < staleBase.length; i++) {\n"
        "            if (base !== staleBase[i] && bg.indexOf(staleBase[i] + \"/\") === 0) {\n"
        '              window.localStorage.setItem("backgroundUrl",\n'
        "                JSON.stringify(base + bg.slice(staleBase[i].length)));\n"
        "              break;\n"
        "            }\n"
        "          }\n"
        "        }\n"
        "      } catch (e) {}\n"
        # --- 무대 뒤 자막 차단 ---
        # 코어는 우리가 보내는 text-input 을 그대로 복사해서
        # user-input-transcription 으로 다른 클라이언트(= 이 웹UI)에 뿌린다
        # (proxy_message_queue._forward_message). 웹UI 는 그걸 "사용자가 한 말"
        # 자막으로 띄운다. 그러면 매니저 귓속말이 OBS 화면에 그대로 나간다:
        #   (매니저 귓속말: 방송 방금 시작했어. 방송 여는 인사로 시작해줘...)
        # 코어에는 이걸 끄는 설정이 없고, 다른 입력 방식도 없다
        # (ai-speak-signal 은 우리 문장을 못 싣는다). 그래서 여기서 막는다.
        #
        # 괄호로 시작하는 것만 버린다 — 그게 무대 뒤 신호의 약속이고,
        # 시청자 채팅은 소독 단계에서 괄호로 시작할 수 없게 해뒀다.
        # 무슨 일이 생겨도 원래대로 흘려보낸다(웹UI 를 깨뜨리는 게 최악이다).
        "      try {\n"
        "        var OrigWS = window.WebSocket;\n"
        "        if (OrigWS && !OrigWS.__aistCueFilter) {\n"
        "          var isCue = function (raw) {\n"
        "            try {\n"
        '              if (typeof raw !== "string") return false;\n'
        '              if (raw.indexOf("user-input-transcription") === -1) return false;\n'
        "              var d = JSON.parse(raw);\n"
        '              if (!d || d.type !== "user-input-transcription") return false;\n'
        '              var t = (d.text || "").replace(/^[\\s\\u200b]+/, "");\n'
        '              return t.charAt(0) === "(" || t.charAt(0) === "\\uff08";\n'
        "            } catch (e) { return false; }\n"
        "          };\n"
        "          var Patched = function (url, protocols) {\n"
        "            var ws = arguments.length > 1 ? new OrigWS(url, protocols)\n"
        "                                          : new OrigWS(url);\n"
        "            try {\n"
        '              ws.addEventListener("message", function (ev) {\n'
        "                if (isCue(ev.data)) { ev.stopImmediatePropagation(); }\n"
        "              });\n"
        "            } catch (e) {}\n"
        "            return ws;\n"
        "          };\n"
        "          Patched.prototype = OrigWS.prototype;\n"
        '          ["CONNECTING", "OPEN", "CLOSING", "CLOSED"].forEach(function (k) {\n'
        "            try { Patched[k] = OrigWS[k]; } catch (e) {}\n"
        "          });\n"
        "          Patched.__aistCueFilter = true;\n"
        "          window.WebSocket = Patched;\n"
        "        }\n"
        "      } catch (e) {}\n"
        "      })();\n"
        "    </script>\n"
    )


# 지금 버전의 패치에만 있는 표식. 예전에 패치해 둔 웹UI 는 MARK 는 있어도
# 귓속말 필터가 없다 — MARK 만 보면 "설정됨" 으로 나와서 운영자는 모른다.
CURRENT_FEATURE = "__aistCueFilter"
# 코어 주소를 페이지 주소에서 읽는 버전(예전 것은 12393 을 박아 넣었다).
_CURRENT_ADDR = "location.host"


def is_patched(index_html: Path) -> bool:
    """웹UI 가 지금 버전의 설정으로 패치돼 있는지."""
    return patch_state(index_html) == "current"


def patch_state(index_html: Path) -> str:
    """none | old | current"""
    try:
        html = index_html.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "none"
    if MARK not in html:
        return "none"
    if CURRENT_FEATURE in html and _CURRENT_ADDR in html:
        return "current"
    return "old"


def patch_index(frontend_dir, ws_url: Optional[str] = None) -> str:
    """frontend/index.html 에 부트스트랩을 넣는다. 사람이 읽는 결과 문자열."""
    ws_url = ws_url or DEFAULT_WS
    index = Path(frontend_dir) / "index.html"
    if not index.is_file():
        return f"[실패] index.html 이 없습니다: {index}"
    try:
        html = index.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"[실패] index.html 을 읽지 못했습니다: {e}"

    # 이전에 넣은 블록은 지우고 새로 넣는다(주소가 바뀌었을 수 있다).
    html = re.sub(rf'[ \t]*<script id="{MARK}">.*?</script>\n?', "",
                  html, flags=re.S)

    block = _script(ws_url)
    # 웹UI 본체는 type="module" 이라 문서 파싱 뒤에 돈다. 그 앞(head)에
    # 평범한 script 로 넣으면 항상 먼저 실행된다.
    m = re.search(r"[ \t]*<script type=\"module\"", html)
    if m:
        html = html[:m.start()] + block + html[m.start():]
    elif "</head>" in html:
        html = html.replace("</head>", block + "  </head>", 1)
    else:
        return "[실패] index.html 구조를 못 알아보겠습니다(head/script 없음)."
    try:
        index.write_text(html, encoding="utf-8")
    except OSError as e:
        # 읽기 전용 폴더·권한 문제. 트레이스백 대신 사람 말로 돌려준다.
        return f"[실패] index.html 에 쓰지 못했습니다: {e}"
    return f"웹UI 를 {ws_url} 에 붙게 설정했습니다: {index}"


def main(argv=None) -> int:
    import sys
    # 배치에서 직접 불리는 진입점이다(프론트엔드받기.bat). aist CLI 는 출력
    # 인코딩을 UTF-8 로 맞추는데 여기는 그 길을 안 거친다. 그래서 콘솔이
    # 한글을 못 쓰는 코드페이지면 결과 문장을 print 하다가 UnicodeEncodeError
    # 로 죽고 종료코드 1 을 낸다 — 패치는 이미 성공했는데도. 배치는 그걸
    # 보고 "웹UI 주소 설정을 못 넣었습니다" 경고를 띄운다(실제로 그랬다).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("사용법: python -m aist.frontend_patch <frontend 경로> [ws_url]")
        return 2
    msg = patch_index(argv[0], argv[1] if len(argv) > 1 else None)
    print(msg)
    # 예전에는 실패해도 0 을 돌려줬다. 그래서 프론트엔드받기.bat 과
    # fetch_frontend.sh 에 적어둔 "[경고] 웹UI 주소 설정을 못 넣었습니다"
    # 가 영영 안 뜬다 — 운영자는 "완료" 만 보고 넘어가고, 방송을 켜면
    # AI 가 말을 해도 OBS 화면에 아무것도 안 나온다(무음 방송).
    return 1 if msg.startswith(("[실패]", "[건너뜀]")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
