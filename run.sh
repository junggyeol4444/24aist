#!/usr/bin/env bash
# 리눅스/맥 간편 실행기. 사용:
#   ./run.sh setup      # 설치 + 설정 파일 준비
#   ./run.sh doctor     # 배선 점검
#   ./run.sh test       # 지금 한 방송(테스트)
#   ./run.sh start       # 완전 자동 운영
#   ./run.sh report      # 리포트 + 컨텐츠 팩
#   ./run.sh core        # 방송 코어(Open-LLM-VTuber) 실행
set -euo pipefail
cd "$(dirname "$0")"
CMD="${1:-help}"

ensure_venv() {
  if [ ! -d ".venv" ]; then python3 -m venv .venv; fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
}

case "$CMD" in
  setup)
    ensure_venv
    python -m pip install -U pip >/dev/null
    pip install -e ".[vtuber,obs,discord,platforms,naver,llm]"
    [ -f config.yaml ]  || cp config/config.example.yaml  config.yaml
    [ -f persona.yaml ] || cp config/persona.example.yaml persona.yaml
    [ -f .env ]         || cp .env.example .env
    aist --config config.yaml --persona persona.yaml check
    echo "설치 끝. config.yaml / persona.yaml / .env 를 채운 뒤 ./run.sh doctor" ;;
  doctor)  ensure_venv; aist --config config.yaml --persona persona.yaml doctor ;;
  test)    ensure_venv; aist --config config.yaml --persona persona.yaml broadcast-now ;;
  start)   ensure_venv; aist --config config.yaml --persona persona.yaml run ;;
  report)  ensure_venv; aist --config config.yaml --persona persona.yaml report;
           aist --config config.yaml --persona persona.yaml content ;;
  core)    ( cd Open-LLM-VTuber && { command -v uv >/dev/null && uv run run_server.py || python run_server.py; } ) ;;
  *) echo "사용: ./run.sh [setup|doctor|test|start|report|core]" ;;
esac
