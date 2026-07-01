#!/usr/bin/env bash
# =============================================================================
# 7단계: 24시간 서버화 — aist 를 systemd 서비스로 설치 (리눅스)
#
# 사용: bash deploy/install.sh
#  - 저장소 루트에 .venv 를 만들고 aist 를 설치
#  - systemd 유닛(aist.service)을 설치·활성화 (죽으면 5초 후 자동 재시작)
#  - 게임 사이드카까지 서비스로 걸려면: bash deploy/install.sh --with-minecraft
#
# 전제: config.yaml / persona.yaml / .env 가 저장소 루트에 준비돼 있어야 함.
# (코어 Open-LLM-VTuber·GPT-SoVITS·OBS 는 각자 실행/자동시작 설정 — INTEGRATION.md)
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="${SUDO_USER:-$(whoami)}"
WITH_MC=false
[ "${1:-}" = "--with-minecraft" ] && WITH_MC=true

echo "==> 설치 위치: $HERE (사용자: $RUN_USER)"

# 0) 준비물 확인
for f in config.yaml persona.yaml; do
  if [ ! -f "$HERE/$f" ]; then
    echo "오류: $HERE/$f 가 없습니다. config/${f%.yaml}.example.yaml 을 복사해 만드세요."
    exit 1
  fi
done
[ -f "$HERE/.env" ] || echo "경고: .env 가 없습니다(키/토큰). .env.example 참고."

# 1) 가상환경 + 설치
if [ ! -d "$HERE/.venv" ]; then
  echo "==> .venv 생성 + aist 설치(전체 의존성)"
  python3 -m venv "$HERE/.venv"
fi
"$HERE/.venv/bin/pip" install -q -e "$HERE[all]" || "$HERE/.venv/bin/pip" install -q -e "$HERE"

# 2) 설정 점검
"$HERE/.venv/bin/aist" --config "$HERE/config.yaml" --persona "$HERE/persona.yaml" check || true

# 3) systemd 유닛 설치
install_unit () {
  local src="$1" name="$2"
  echo "==> $name 설치"
  sed -e "s|__USER__|$RUN_USER|g" -e "s|__WORKDIR__|$HERE|g" "$src" \
    | sudo tee "/etc/systemd/system/$name" > /dev/null
}

install_unit "$HERE/deploy/systemd/aist.service" "aist.service"
if $WITH_MC; then
  install_unit "$HERE/deploy/systemd/aist-minecraft.service" "aist-minecraft.service"
fi

sudo systemctl daemon-reload
sudo systemctl enable --now aist.service
$WITH_MC && sudo systemctl enable --now aist-minecraft.service

cat <<EOF

==> 완료. 이제부터:
  상태 보기   : systemctl status aist
  로그 보기   : journalctl -u aist -f        (파일: $HERE/data/logs/aist.log)
  방송 리포트 : $HERE/.venv/bin/aist report   (매 방송 후 자동 생성됨: data/reports/)
  중지/재시작 : sudo systemctl stop|restart aist

죽으면 5초 후 자동 재시작됩니다(Restart=always). 하루 5~10분 점검은
data/reports/ 의 최신 리포트와 로그만 보면 됩니다.
EOF
