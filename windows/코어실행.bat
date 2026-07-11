@echo off
chcp 65001 >nul
cd /d "%~dp0..\Open-LLM-VTuber"

echo === 방송 코어 Open-LLM-VTuber 실행 ===

REM conf.yaml 이 없으면 한국어 개조본을 적용
if not exist "conf.yaml" if exist "conf.korean.yaml" (
  copy "conf.korean.yaml" "conf.yaml" >nul
  echo conf.korean.yaml -^> conf.yaml 적용 [한국어/페르소나]
)

if not exist "frontend\index.html" (
  echo [안내] 프론트엔드 웹UI 가 없습니다. 저장소 루트에서
  echo        scripts\fetch_frontend.sh 로 먼저 받으세요.
)

where uv >nul 2>nul && goto :use_uv || goto :use_py

:use_uv
uv run run_server.py
goto :done

:use_py
echo uv 가 없어 python 으로 실행합니다. 의존성 미설치면 실패할 수 있어요.
echo   권장: https://docs.astral.sh/uv/ 설치 후 uv sync
python run_server.py

:done
pause
