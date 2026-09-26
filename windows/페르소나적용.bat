@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

REM ============================================================
REM  페르소나 적용 — persona.yaml 을 고친 뒤 이걸 실행해야
REM  방송인의 성격이 실제로 바뀝니다.
REM  (방송인 성격은 코어의 conf.yaml 안에 박혀 있습니다)
REM ============================================================

if not exist ".venv\Scripts\activate.bat" (
  echo 먼저 설치.bat 를 실행하세요.
  pause & exit /b 1
)
call ".venv\Scripts\activate.bat"

if not exist "persona.yaml" (
  echo persona.yaml 이 없습니다. 설치.bat 를 먼저 실행하세요.
  pause & exit /b 1
)
if not exist "Open-LLM-VTuber\conf.yaml" (
  echo 코어 설정^(conf.yaml^)이 없습니다. 코어준비.bat 를 먼저 실행하세요.
  pause & exit /b 1
)

echo === 페르소나를 코어에 적용합니다 ===
aist --config config.yaml --persona persona.yaml build-persona --conf "Open-LLM-VTuber\conf.yaml"
if errorlevel 1 (
  echo.
  echo [오류] 적용 실패. 위 메시지를 확인하세요.
  pause & exit /b 1
)

echo.
echo 적용 끝. 코어가 켜져 있으면 다시 시작해야 반영됩니다^(코어실행.bat^).
pause
