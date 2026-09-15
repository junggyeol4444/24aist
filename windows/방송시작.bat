@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\activate.bat" ( echo 먼저 설치.bat 를 실행하세요. & pause & exit /b 1 )
call ".venv\Scripts\activate.bat"
echo === 완전 자동 운영 (스케줄러가 켜고 끔) ===
echo.
echo   [중요] 이 창을 X 로 닫지 마세요.
echo          윈도우가 프로그램을 바로 죽여서 OBS 스트림이 켜진 채 남습니다.
echo          시청자에게는 멈춘 화면이 계속 나갑니다.
echo.
echo   끄려면 : 중단.bat 을 더블클릭하세요 ^(다른 창에서^).
echo            마무리 인사 - OBS 스트림 종료 - 기록 저장까지 하고 끝냅니다.
echo.
echo   24시간 무인 운영은 자동시작등록.bat 을 쓰세요 ^(작업 스케줄러 등록^).
aist --config config.yaml --persona persona.yaml run
pause
