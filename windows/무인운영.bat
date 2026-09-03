@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0.."

REM ============================================================
REM  24시간 무인 운영 (사람이 안 보는 상태로 돈다)
REM
REM  리눅스 systemd 유닛의 Restart=always 에 해당한다:
REM  코어나 방송인이 죽으면 잠깐 기다렸다가 다시 띄운다.
REM  자동시작등록.bat 이 이 파일을 작업 스케줄러에 등록한다.
REM
REM  사람이 직접 볼 때는 전체실행.bat 을 쓰세요(여긴 pause 가 없습니다).
REM ============================================================

if not exist ".venv\Scripts\activate.bat" (
  echo [오류] 설치가 안 됐습니다. 설치.bat 를 먼저 실행하세요.
  exit /b 1
)
if not exist "config.yaml" (
  echo [오류] config.yaml 이 없습니다. 설치.bat 를 먼저 실행하고 설정을 채우세요.
  exit /b 1
)

call ".venv\Scripts\activate.bat"

set "RESTART_WAIT=10"
set /a ROUND=0

:loop
set /a ROUND+=1
echo.
echo ==== [%date% %time%] 운영 시작 (%ROUND%번째) ====

REM 코어가 이미 떠 있으면 또 띄우지 않는다.
aist --config config.yaml --persona persona.yaml wait-core --timeout 5 >nul 2>nul
if errorlevel 1 (
  echo   방송 코어 시작...
  start "Open-LLM-VTuber Core" cmd /c "%~dp0코어실행.bat" nopause
) else (
  echo   방송 코어 이미 떠 있음
)

echo   코어 준비 대기...
aist --config config.yaml --persona persona.yaml wait-core --timeout 600
if errorlevel 1 (
  echo   [경고] 코어가 안 떴습니다. %RESTART_WAIT%초 뒤 다시 시도합니다.
  call :sleep %RESTART_WAIT%
  goto loop
)

echo   자동 운영 시작...
aist --config config.yaml --persona persona.yaml run

echo.
echo ==== [%date% %time%] 운영이 멈췄습니다. %RESTART_WAIT%초 뒤 재시작 ====
call :sleep %RESTART_WAIT%
goto loop

REM --------------------------------------------------------------
REM  %1 초 대기.
REM  timeout 은 stdin 이 리다이렉트돼 있으면
REM      ERROR: Input redirection is not supported
REM  로 즉시 빠져나온다. 작업 스케줄러로 도는 무인 상태가 바로 그 조건이라
REM  대기가 통째로 사라지고 재시작 루프가 전속력으로 돈다.
REM  그래서 timeout 을 먼저 시도하되, 실패하면 ping 으로 잰다(어디서나 된다).
REM --------------------------------------------------------------
:sleep
timeout /t %~1 /nobreak >nul 2>nul
if not errorlevel 1 exit /b 0
set /a _PINGS=%~1+1
ping -n %_PINGS% 127.0.0.1 >nul 2>nul
exit /b 0
