@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\activate.bat" ( echo 먼저 설치.bat 를 실행하세요. & pause & exit /b 1 )

echo ============================================
echo   전체 실행: 코어 + AI 방송인 자동 운영
echo ============================================
echo [1] 방송 코어를 새 창에서 시작...
start "Open-LLM-VTuber Core" cmd /c "%~dp0코어실행.bat"

echo [2] 코어가 뜰 때까지 대기(모델 로딩 때문에 몇 분 걸리기도 합니다)...
call ".venv\Scripts\activate.bat"
aist --config config.yaml --persona persona.yaml wait-core --timeout 300
if errorlevel 1 (
  echo.
  echo 코어가 안 떴습니다. 새로 열린 코어 창의 오류를 확인하세요.
  pause & exit /b 1
)

echo [3] AI 방송인 자동 운영 시작...
echo.
echo   [중요] 이 창도, 코어 창도 X 로 닫지 마세요.
echo          끄려면 중단.bat 을 더블클릭하세요 ^(다른 창에서^).
echo.
aist --config config.yaml --persona persona.yaml run

echo.
echo (참고) OBS 는 미리 켜두거나, config.yaml 의 obs.launch_if_not_running 을
echo         설정하면 자동으로 켜집니다.
pause
