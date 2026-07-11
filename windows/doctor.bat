@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\activate.bat" ( echo 먼저 install.bat 를 실행하세요. & pause & exit /b 1 )
call ".venv\Scripts\activate.bat"
echo === 배선 점검: 코어 WS / OBS / 플랫폼 채팅 ===
aist --config config.yaml --persona persona.yaml doctor
pause
