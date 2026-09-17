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
REM 같은 실패가 빨리 반복되면(설정 오류 등) 간격을 늘린다. 안 그러면
REM 10초마다 영원히 같은 실패를 반복하는데, 사람이 안 보는 자리라
REM 아무도 모른다. 5분까지 늘리고 뭘 확인해야 하는지 화면에 남긴다.
set "SLOW_WAIT=300"
set "FAST_FAIL_LIMIT=5"
set /a FAST_FAILS=0
set /a ROUND=0

:loop
set /a ROUND+=1
set "WAIT=%RESTART_WAIT%"
if %FAST_FAILS% GEQ %FAST_FAIL_LIMIT% set "WAIT=%SLOW_WAIT%"
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
  echo   [경고] 코어가 안 떴습니다. %WAIT%초 뒤 다시 시도합니다.
  set /a FAST_FAILS+=1
  call :warn_if_stuck
  call :sleep %WAIT%
  goto loop
)

echo   자동 운영 시작...
REM 방송이 얼마나 돌았는지 재서, 켜자마자 죽는 것과 정상 운영 뒤 멈춘
REM 것을 구분한다. 전자는 고쳐야 할 문제고 후자는 그냥 재시작하면 된다.
call :now_sec START_SEC
aist --config config.yaml --persona persona.yaml run
call :now_sec END_SEC
set /a LASTED=END_SEC-START_SEC

REM 시각을 못 재면(PowerShell 없음 등) 실패 횟수를 건드리지 않는다.
REM 잘못 세면 멀쩡히 도는 방송의 재시도 간격을 5분으로 늘려버린다.
if "%START_SEC%"=="0" goto :skip_count
if "%END_SEC%"=="0" goto :skip_count
if %LASTED% LSS 60 (set /a FAST_FAILS+=1) else (set /a FAST_FAILS=0)
:skip_count

echo.
if "%START_SEC%"=="0" (
  echo ==== [%date% %time%] 운영이 멈췄습니다. %WAIT%초 뒤 재시작 ====
) else (
  echo ==== [%date% %time%] 운영이 멈췄습니다 ^(%LASTED%초 만에^). %WAIT%초 뒤 재시작 ====
)
call :warn_if_stuck
call :sleep %WAIT%
goto loop

REM --------------------------------------------------------------
REM  같은 실패가 계속되면 화면에 뭘 봐야 하는지 남긴다.
REM  무인 자리라 당장은 아무도 안 보지만, 나중에 운영자가 창을 열면
REM  바로 보인다. 이게 없으면 "왜 방송이 안 되지?" 만 남는다.
REM --------------------------------------------------------------
:warn_if_stuck
if %FAST_FAILS% LSS %FAST_FAIL_LIMIT% exit /b 0
echo.
echo   ************************************************************
echo   * 켜자마자 멈추기를 %FAST_FAILS%번 반복했습니다.
echo   * 재시도 간격을 %SLOW_WAIT%초로 늘립니다.
echo   *
echo   * 그냥 두면 계속 이 상태입니다. 확인하세요:
echo   *   1^) 점검.bat 을 실행해 [X] 로 나오는 줄
echo   *   2^) data\logs\aist.log 의 마지막 부분
echo   *   3^) 코어 창^(Open-LLM-VTuber^)의 오류
echo   ************************************************************
echo.
exit /b 0

REM --------------------------------------------------------------
REM  현재 시각을 epoch 초로. 결과를 %1 이름의 변수에 넣는다.
REM
REM  %time% 을 잘라 쓰면 안 된다 — 표시 형식이 로캘/설정마다 다르다.
REM  (한국어 윈도우는 "오후 3:52:10", 12시간제면 "3:52:10 AM")
REM  그래서 PowerShell 로 받는다. 재시작할 때만 부르므로 느려도 된다.
REM  PowerShell 이 없거나 실패하면 0 을 둔다 — 부르는 쪽이 0 이면
REM  '측정 못 함'으로 보고 실패 횟수를 세지 않는다.
REM --------------------------------------------------------------
:now_sec
set "%~1=0"
for /f "usebackq delims=" %%S in (`powershell -NoProfile -Command "[int][double]::Parse((Get-Date -UFormat %%s))" 2^>nul`) do set "%~1=%%S"
exit /b 0

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
