#!/usr/bin/env bash
# =============================================================================
# Open-LLM-VTuber 웹 UI(프론트엔드) 받기
#
# 프론트엔드는 별도 저장소(Open-LLM-VTuber-Web)의 컴파일된 build 산출물이다.
# 바이너리(wasm/onnx ~44MB)라 git 에 커밋하지 않고 이 스크립트로 받는다.
# 받은 파일은 Open-LLM-VTuber/frontend/ 에 풀리며 .gitignore 로 커밋 제외된다.
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HERE/Open-LLM-VTuber/frontend"
URL="https://codeload.github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/tar.gz/refs/heads/build"
TMP="$(mktemp -d)"

echo "==> 프론트엔드 build 산출물 다운로드"
curl -fsSL --max-time 120 -o "$TMP/web.tar.gz" "$URL"

echo "==> 압축 해제 → $DEST"
mkdir -p "$DEST"
tar -xzf "$TMP/web.tar.gz" -C "$TMP"
SRC="$(find "$TMP" -maxdepth 1 -type d -name 'Open-LLM-VTuber-Web-*' | head -1)"
# README.md 는 보존하고 나머지를 채운다
cp -a "$SRC"/. "$DEST"/
rm -rf "$TMP"

echo "==> 완료. $DEST 에 index.html / assets / libs 가 들어왔습니다."
echo "   (이 파일들은 .gitignore 로 커밋에서 제외됩니다)"
