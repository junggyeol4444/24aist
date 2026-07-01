#!/usr/bin/env bash
# =============================================================================
# Open-LLM-VTuber 셋업 (vendoring 됨 → 받지 않고 준비만)
#
# 방송 코어(Open-LLM-VTuber)는 이 저장소 Open-LLM-VTuber/ 에 이미 포함되어
# 있다(개조 대상). 이 스크립트는:
#   1) 프론트엔드(웹 UI) 바이너리를 받고
#   2) (uv 있으면) 코어 의존성 설치
#   3) 한국어 개조 설정 conf.korean.yaml → conf.yaml 로 적용
#
# 사용: bash scripts/setup_openllm_vtuber.sh
# 사전: python3.10+, (권장) uv  /  GPU 환경(음성·아바타). docs/INTEGRATION.md 참고.
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
CORE="$HERE/Open-LLM-VTuber"

if [ ! -d "$CORE" ]; then
  echo "오류: $CORE 가 없습니다. 저장소가 온전한지 확인하세요."
  exit 1
fi

# 1) 프론트엔드(웹 UI) 받기
if [ ! -f "$CORE/frontend/index.html" ]; then
  echo "==> 프론트엔드 받기"
  bash "$HERE/scripts/fetch_frontend.sh"
else
  echo "==> 프론트엔드 이미 있음 → 건너뜀"
fi

# 2) 코어 의존성 설치
if command -v uv >/dev/null 2>&1; then
  echo "==> uv 로 코어 의존성 설치"
  ( cd "$CORE" && uv sync ) || echo "   (uv sync 실패 — 수동 설치 필요할 수 있음)"
else
  echo "==> uv 가 없습니다(https://docs.astral.sh/uv/ 권장)."
  echo "   (대안) cd $CORE && pip install -r requirements.txt"
fi

# 3) 한국어 개조 설정 적용
if [ ! -f "$CORE/conf.yaml" ]; then
  if [ -f "$CORE/conf.korean.yaml" ]; then
    cp "$CORE/conf.korean.yaml" "$CORE/conf.yaml"
    echo "==> conf.korean.yaml → conf.yaml 적용(페르소나/한국어 TTS 포함)"
  fi
else
  echo "==> conf.yaml 이 이미 있음 → 보존(덮어쓰지 않음)"
fi

cat <<EOF

==> 완료. 다음 할 일:
  1) $CORE/conf.yaml 에서 LLM 제공자/키, GPT-SoVITS 의 api_url·ref_audio_path,
     live2d_model_name 을 채운다. (docs/INTEGRATION.md)
  2) 코어 단독 실행으로 "AI 가 말하고 아바타가 움직이는지" 확인(1단계).
       cd $CORE && uv run run_server.py   # 또는 python run_server.py
  3) 우리 레이어: aist check / aist plan → aist broadcast-now (3·4단계).

  페르소나를 바꿨으면 다시 주입:
    aist build-persona --conf $CORE/conf.yaml --live2d <모델명>
EOF
