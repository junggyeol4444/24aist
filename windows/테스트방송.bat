@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\activate.bat" ( echo 먼저 설치.bat 를 실행하세요. & pause & exit /b 1 )
call ".venv\Scripts\activate.bat"
echo === 지금 한 방송만 (시작 수동, 종료는 자동) ===
echo   [Ctrl+C] 로 중단할 수 있어요.
aist --config config.yaml --persona persona.yaml broadcast-now
pause
