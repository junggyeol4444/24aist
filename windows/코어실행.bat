@echo off
chcp 65001 >nul
cd /d "%~dp0..\Open-LLM-VTuber"

echo === 방송 코어 (Open-LLM-VTuber) 실행 ===
if not exist "conf.yaml" (
  if exist "conf.korean.yaml" (
    copy "conf.korean.yaml" "conf.yaml" >nul
    echo conf.korean.yaml -^> conf.yaml 적용(한국어/페르소나)
  )
)
if not exist "frontend\index.html" (
  echo [안내] 웹UI(화면)가 없습니다. windows\코어준비.bat 을 먼저 실행하세요.
  echo        ^(웹UI + 코어 의존성 + conf.yaml 을 한 번에 준비합니다^)
  pause & exit /b 1
)

where uv >nul 2>nul
if %errorlevel%==0 (
  uv run run_server.py
) else (
  echo uv 가 없어 python 으로 실행합니다.
  if exist "..\.venv\Scripts\activate.bat" call "..\.venv\Scripts\activate.bat"
  python run_server.py
  if errorlevel 1 (
    echo.
    echo [오류] 코어가 뜨지 않았습니다. 의존성이 안 깔렸을 수 있습니다.
    echo        windows\코어준비.bat 을 실행한 뒤 다시 시도하세요.
  )
)
pause
