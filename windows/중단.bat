@echo off
chcp 65001 >nul
cd /d "%~dp0.."

REM ============================================================
REM  방송 중단 (사고 났을 때)
REM
REM  창을 X 로 닫거나 Ctrl+C 를 누르면 방송이 제대로 안 내려갑니다:
REM    - 창 닫기: 윈도우가 프로세스를 바로 죽여서 OBS 스트림이 켜진 채
REM               남습니다. 시청자에게는 멈춘 화면이 계속 나갑니다.
REM    - Ctrl+C : cmd 가 "현재 배치 작업을 끝내시겠습니까 (Y/N)?" 를 먼저
REM               묻는데, 여기서 Y 를 누르면 정리 중간에 끊길 수 있습니다.
REM
REM  이 파일은 방송인에게 "마무리하고 내려와" 라고 시킵니다.
REM  OBS 스트림 종료 · 기록 저장까지 하고 끝냅니다.
REM ============================================================

if not exist ".venv\Scripts\activate.bat" (
  echo 먼저 설치.bat 를 실행하세요.
  pause & exit /b 1
)
call ".venv\Scripts\activate.bat"

echo ============================================
echo   방송 중단
echo ============================================
echo.
echo  도는 방송이 있으면 몇 초 안에 마무리 절차로 들어갑니다.
echo  ^(마무리 인사 - OBS 스트림 종료 - 기록 저장^)
echo.

aist --config config.yaml --persona persona.yaml stop --reason "운영자가 중단.bat 실행"

echo.
echo  방송 창을 보면서 "방송 종료" 가 뜨는지 확인하세요.
echo  다음 방송은 예정대로 켜집니다 ^(중단 표시는 자동으로 지워집니다^).
echo.
pause
