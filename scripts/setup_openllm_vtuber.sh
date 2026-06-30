#!/usr/bin/env bash
# =============================================================================
# Open-LLM-VTuber 다운로드 + 개조(페르소나 주입) 스크립트
#
# 이 자동화 레이어(aist)는 방송 코어로 Open-LLM-VTuber 를 쓴다.
# 이 스크립트가 코어를 받아오고, 우리 페르소나/TTS 설정을 conf.yaml 에 주입한다.
#
# 사용:
#   bash scripts/setup_openllm_vtuber.sh [대상디렉터리]
#   (기본 대상: third_party/Open-LLM-VTuber)
#
# 사전 준비: git, python3.10+, (권장) uv  —  https://docs.astral.sh/uv/
# 주의: GPU 환경이 필요하다(음성·아바타). 자세한 건 docs/INTEGRATION.md.
# =============================================================================
set -euo pipefail

REPO="https://github.com/Open-LLM-VTuber/Open-LLM-VTuber.git"
TARGET="${1:-third_party/Open-LLM-VTuber}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Open-LLM-VTuber 설치 위치: $TARGET"

command -v git >/dev/null 2>&1 || { echo "git 이 필요합니다."; exit 1; }

# 1) 코어 받아오기 (이미 있으면 업데이트)
if [ -d "$TARGET/.git" ]; then
  echo "==> 이미 받아져 있음 → git pull 로 업데이트"
  git -C "$TARGET" pull --ff-only || echo "   (pull 실패는 무시 가능)"
else
  echo "==> git clone"
  git clone --depth 1 "$REPO" "$TARGET"
fi

# 2) conf.yaml 준비 (템플릿 → conf.yaml)
if [ ! -f "$TARGET/conf.yaml" ]; then
  if [ -f "$TARGET/config_templates/conf.default.yaml" ]; then
    cp "$TARGET/config_templates/conf.default.yaml" "$TARGET/conf.yaml"
    echo "==> conf.default.yaml → conf.yaml 복사"
  else
    echo "   (conf 템플릿을 못 찾음 — 코어 버전 확인 필요)"
  fi
fi

# 3) 의존성 설치 (uv 권장)
if command -v uv >/dev/null 2>&1; then
  echo "==> uv 로 의존성 설치"
  ( cd "$TARGET" && uv sync ) || echo "   (uv sync 실패 — 수동 설치 필요할 수 있음)"
else
  echo "==> uv 가 없습니다. https://docs.astral.sh/uv/ 설치 권장."
  echo "   (대안) cd $TARGET && pip install -r requirements.txt"
fi

# 4) 페르소나/TTS 주입(개조) — aist 가 설치돼 있어야 함
echo "==> 페르소나 주입(개조) 시도"
if command -v aist >/dev/null 2>&1 && [ -f "$HERE/config/config.yaml" -o -f "$HERE/config.yaml" ]; then
  ( cd "$HERE" && aist build-persona --conf "$TARGET/conf.yaml" ) || \
    echo "   (build-persona 실패 — config.yaml/persona.yaml 준비 후 다시 실행)"
else
  echo "   aist 명령 또는 config.yaml 이 아직 없습니다. 나중에 직접:"
  echo "     aist build-persona --conf $TARGET/conf.yaml --live2d <모델명>"
fi

cat <<EOF

==> 완료. 다음 할 일:
  1) $TARGET/conf.yaml 에서 LLM 제공자/키, TTS(gpt_sovits_tts 의 api_url·ref_audio_path),
     live2d_model_name 을 채운다. (docs/INTEGRATION.md 참고)
  2) 코어 단독 실행으로 "AI 가 말하고 아바타가 움직이는지" 확인 (1단계).
  3) 우리 레이어: aist check / aist plan 으로 설정 점검 → aist broadcast-now (3·4단계).
EOF
