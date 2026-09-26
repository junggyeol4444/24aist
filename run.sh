#!/usr/bin/env bash
# 리눅스/맥 간편 실행기. 사용:
#   ./run.sh setup      # 설치 + 설정 파일 준비
#   ./run.sh doctor     # 배선 점검
#   ./run.sh rehearse   # 리허설(플랫폼·키·OBS 없이 흐름만)
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
    # 방송 코어 준비: 웹UI(커밋 안 된 컴파일 산출물) + conf.yaml + 코어 의존성.
    # 이걸 빠뜨리면 aist 만 설치되고 정작 방송은 안 된다.
    CORE_OK=1
    bash scripts/setup_openllm_vtuber.sh || CORE_OK=0
    # check 는 '아직 방송 불가'면 1 을 돌려준다(정상). set -e 로 죽지 않게.
    aist --config config.yaml --persona persona.yaml check || true
    if [ "$CORE_OK" = "1" ]; then
      echo "설치 끝. config.yaml / persona.yaml / .env 를 채운 뒤 ./run.sh doctor"
    else
      # 실패를 "설치 끝"이라고 말하지 않는다. 사용자가 다 된 줄 알고
      # 다음 단계로 넘어가면 원인을 못 찾는다.
      echo
      echo "[실패] 코어 준비가 덜 끝났습니다. 위 '실행 준비 상태' 에서 [X] 인 줄을"
      echo "       먼저 해결하세요. aist 자체와 설정 파일은 준비됐습니다."
      echo "       다시 시도: bash scripts/setup_openllm_vtuber.sh"
      exit 1
    fi ;;
  doctor)  ensure_venv; aist --config config.yaml --persona persona.yaml doctor ;;
  wait-core) ensure_venv; shift || true
           aist --config config.yaml --persona persona.yaml wait-core "$@" ;;
  rehearse) ensure_venv; shift || true
           aist --config config.yaml --persona persona.yaml rehearse "$@" ;;
  test)    ensure_venv; aist --config config.yaml --persona persona.yaml broadcast-now ;;
  start)   ensure_venv; aist --config config.yaml --persona persona.yaml run ;;
  report)  ensure_venv; aist --config config.yaml --persona persona.yaml report;
           aist --config config.yaml --persona persona.yaml content ;;
  core)    ( cd Open-LLM-VTuber && { command -v uv >/dev/null && uv run run_server.py || python run_server.py; } ) ;;
  *) echo "사용: ./run.sh [setup|doctor|wait-core|rehearse|test|start|report|core]" ;;
esac
