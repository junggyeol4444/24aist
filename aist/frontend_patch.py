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
_OLD_DEFAULTS = ("ws://127.0.0.1:12393/client-ws", "ws://localhost:12393/client-ws")


def _script(ws_url: str) -> str:
    olds = ", ".join(f'"{u}"' for u in _OLD_DEFAULTS)
    return (
        f'    <script id="{MARK}">\n'
        "      // 방송 자동화(aist)가 넣은 줄 — 웹UI 를 /proxy-ws 에 붙인다.\n"
        "      // (웹UI 는 localStorage 에 JSON 문자열로 저장한다)\n"
        "      try {\n"
        f'        var want = "{ws_url}";\n'
        f"        var stale = [{olds}];\n"
        '        var cur = window.localStorage.getItem("wsUrl");\n'
        "        var val = null;\n"
        "        if (cur) { try { val = JSON.parse(cur); } catch (e) { val = cur; } }\n"
        "        if (!val || stale.indexOf(val) !== -1) {\n"
        '          window.localStorage.setItem("wsUrl", JSON.stringify(want));\n'
        "        }\n"
        "      } catch (e) {}\n"
        "    </script>\n"
    )


def is_patched(index_html: Path) -> bool:
    try:
        return MARK in index_html.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def patch_index(frontend_dir, ws_url: Optional[str] = None) -> str:
    """frontend/index.html 에 부트스트랩을 넣는다. 사람이 읽는 결과 문자열."""
    ws_url = ws_url or DEFAULT_WS
    index = Path(frontend_dir) / "index.html"
    if not index.is_file():
        return f"[건너뜀] index.html 이 없습니다: {index}"
    html = index.read_text(encoding="utf-8", errors="replace")

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
    index.write_text(html, encoding="utf-8")
    return f"웹UI 를 {ws_url} 에 붙게 설정했습니다: {index}"


def main(argv=None) -> int:
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("사용법: python -m aist.frontend_patch <frontend 경로> [ws_url]")
        return 2
    print(patch_index(argv[0], argv[1] if len(argv) > 1 else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
