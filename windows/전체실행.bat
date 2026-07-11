@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\activate.bat" ( echo 먼저 설치.bat 를 실행하세요. & pause & exit /b 1 )

echo ============================================
echo   전체 실행: 코어 + AI 방송인 자동 운영
echo ============================================
echo [1] 방송 코어를 새 창에서 시작...
start "Open-LLM-VTuber Core" cmd /c "%~dp0코어실행.bat"

echo [2] 코어가 뜰 때까지 20초 대기...
timeout /t 20 >nul

echo [3] AI 방송인 자동 운영 시작...
call ".venv\Scripts\activate.bat"
aist --config config.yaml --persona persona.yaml run

echo.
echo (참고) OBS 는 미리 켜두거나, config.yaml 의 obs.launch_if_not_running 을
echo         설정하면 자동으로 켜집니다.
pause
