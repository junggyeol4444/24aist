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
if errorlevel 3 (
  echo.
  echo [안내] 방송 코어가 죽어서 방송을 멈췄습니다.
  echo        코어 창을 닫고 전체실행.bat 을 다시 실행하면, 아직 방송 시간이
  echo        남아 있을 때 같은 방송을 이어서 켭니다.
  echo        사람 없이 돌릴 때는 무인운영.bat 을 쓰세요 ^(코어를 알아서 다시 띄웁니다^).
)

echo.
echo (참고) OBS 는 미리 켜두거나, config.yaml 의 obs.launch_if_not_running 을
echo         설정하면 자동으로 켜집니다.
pause
