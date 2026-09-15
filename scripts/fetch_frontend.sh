#!/usr/bin/env bash
# =============================================================================
# Open-LLM-VTuber 웹 UI(프론트엔드) 받기
#
# 프론트엔드는 별도 저장소(Open-LLM-VTuber-Web)의 컴파일된 build 산출물이다.
# 바이너리(wasm/onnx ~44MB)라 git 에 커밋하지 않고 이 스크립트로 받는다.
# 받은 파일은 Open-LLM-VTuber/frontend/ 에 풀리며 .gitignore 로 커밋 제외된다.
#
# 이걸 안 받으면 코어가 떠도 화면이 안 나온다. 그래서 실패하면 조용히
# 넘어가지 않고, 손으로 받는 방법까지 알려준다.
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HERE/Open-LLM-VTuber/frontend"
REPO="Open-LLM-VTuber/Open-LLM-VTuber-Web"
BRANCH="build"
# codeload 가 막힌 망(사내 프록시 등)이 있어 github.com 경유도 시도한다.
URLS=(
  "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH"
  "https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz"
)
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [ -f "$DEST/index.html" ]; then
  echo "==> 이미 받아져 있음: $DEST/index.html (건너뜀)"
  exit 0
fi

got=""
for url in "${URLS[@]}"; do
  echo "==> 프론트엔드 build 산출물 다운로드: $url"
  if curl -fsSL --max-time 300 -o "$TMP/web.tar.gz" "$url"; then
    got="$url"
    break
  fi
  echo "    실패 — 다음 주소로 다시 시도합니다."
done

if [ -z "$got" ]; then
  cat >&2 <<EOF

[오류] 프론트엔드를 받지 못했습니다. (네트워크/프록시/방화벽 차단일 수 있습니다)

  이걸 안 받으면 코어가 떠도 화면이 안 나옵니다. 손으로 받으려면:

    1) 브라우저로 https://github.com/$REPO/tree/$BRANCH 접속
    2) Code - Download ZIP 으로 내려받기
    3) 압축을 풀어 안의 내용물(index.html, assets, libs ...)을
       $DEST/ 에 그대로 복사

  받은 뒤 확인:  aist check   ('코어 웹UI : OK' 가 떠야 합니다)

EOF
  exit 1
fi

echo "==> 압축 해제 - $DEST"
mkdir -p "$DEST"
tar -xzf "$TMP/web.tar.gz" -C "$TMP"
SRC="$(find "$TMP" -maxdepth 1 -type d -name 'Open-LLM-VTuber-Web-*' | head -1)"
if [ -z "$SRC" ]; then
  echo "[오류] 받은 압축 안에 예상한 디렉터리가 없습니다. 저장소 구조가 바뀌었을 수 있습니다." >&2
  exit 1
fi
# README.md 는 보존하고 나머지를 채운다
cp -a "$SRC"/. "$DEST"/

if [ ! -f "$DEST/index.html" ]; then
  echo "[오류] 풀긴 했는데 index.html 이 없습니다. 저장소 구조를 확인하세요." >&2
  exit 1
fi
# 웹UI 가 /proxy-ws 에 붙게 한다. 안 하면 웹UI 는 /client-ws 로 붙고,
# 그 경로는 채팅을 넣은 쪽에만 결과를 돌려줘서 화면에 아무것도 안 나온다.
python3 -m aist.frontend_patch "$DEST" 2>/dev/null \
  || python -m aist.frontend_patch "$DEST" 2>/dev/null \
  || echo "    [경고] 웹UI 주소 설정을 못 넣었습니다 — 웹UI 설정에서 WebSocket URL 을 /proxy-ws 로 바꾸세요."

echo "==> 완료. $DEST 에 index.html / assets / libs 가 들어왔습니다."
echo "   (이 파일들은 .gitignore 로 커밋에서 제외됩니다)"
