@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

REM ============================================================
REM  24시간 무인 운영 등록 (윈도우 작업 스케줄러)
REM  리눅스의 deploy/systemd + install.sh 에 해당하는 윈도우 방식.
REM  컴퓨터에 로그인하면 코어 + AI 방송인이 자동으로 뜬다.
REM ============================================================

set "TASKNAME=24aist"
set "RUNNER=%~dp0무인운영.bat"

if not exist ".venv\Scripts\activate.bat" (
  echo 먼저 설치.bat 를 실행하세요.
  pause & exit /b 1
)
if not exist "config.yaml" (
  echo config.yaml 이 없습니다. 설치.bat 를 먼저 실행하고 설정을 채우세요.
  pause & exit /b 1
)

echo === 24시간 무인 운영 등록 ===
echo.
echo   작업 이름 : %TASKNAME%
echo   실행할 것 : %RUNNER%
echo   시점      : 이 컴퓨터에 로그인할 때마다
echo.
echo   ^(끄려면 자동시작해제.bat 을 실행하세요^)
echo.
echo   무인운영.bat 은 코어나 방송인이 죽으면 10초 뒤 다시 띄웁니다
echo   ^(리눅스 systemd 의 Restart=always 에 해당^).
echo.

REM 이미 등록돼 있어도 /f 가 덮어쓴다. 물어보지 않는다 —
REM choice 는 콘솔 입력이 필요해서, 입력이 없는 상황에서는 못 쓴다.
schtasks /query /tn "%TASKNAME%" >nul 2>nul
if %errorlevel%==0 echo 이미 등록돼 있습니다. 최신 설정으로 다시 등록합니다.

REM /rl highest 는 쓰지 않는다. 관리자 권한이 있어야 등록되는데
REM 방송 코어도 aist 도 승격이 필요 없다. 일반 사용자로 등록되게 둔다.
schtasks /create /tn "%TASKNAME%" /tr "\"%RUNNER%\"" /sc onlogon /f
if not errorlevel 1 call :harden
if errorlevel 1 (
  echo.
  echo [오류] 등록 실패.
  echo        이 파일을 마우스 오른쪽 - "관리자 권한으로 실행" 으로 다시 해보세요.
  echo        회사 PC 라면 정책으로 작업 등록이 막혀 있을 수 있습니다.
  echo        그럴 땐 시작프로그램 폴더에 무인운영.bat 바로가기를 넣으세요:
  echo          Win+R - shell:startup - 여기에 바로가기 붙여넣기
  pause & exit /b 1
)

echo.
echo ============================================
echo  등록 완료. 다음 로그인부터 자동으로 켜집니다.
echo.
echo  지금 바로 시작하려면 : 전체실행.bat
echo  등록 확인            : schtasks /query /tn "%TASKNAME%"
echo  해제                 : 자동시작해제.bat
echo.
echo  주의: 컴퓨터가 꺼져 있으면 방송도 안 됩니다. 절전/최대 절전도
echo        마찬가지입니다. 무인 운영하려면 절전을 꺼두세요
echo        ^(설정 - 시스템 - 전원 - 화면 및 절전 모드^).
echo ============================================
pause
goto :eof

REM --------------------------------------------------------------
REM  작업 스케줄러 기본값은 24시간 무인 운영에 맞지 않는다.
REM  schtasks 로 만든 작업의 기본값:
REM    - 실행 시간 제한 72시간   -> 3일 뒤 방송인이 강제 종료된다
REM    - 배터리면 시작 안 함     -> 노트북은 전원 뽑으면 안 켜진다
REM    - 배터리로 바뀌면 중지    -> 방송 중에 꺼진다
REM  전부 바꾼다. 실패해도 작업 자체는 남으므로 등록은 성공으로 둔다
REM  (기본값으로 도는 상태 — 그건 경고로 알린다).
REM --------------------------------------------------------------
:harden
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew;" ^
  "$s.ExecutionTimeLimit = 'PT0S';" ^
  "Set-ScheduledTask -TaskName '%TASKNAME%' -Settings $s | Out-Null;" ^
  "Write-Host '    실행 시간 제한 해제 / 배터리에서도 동작하도록 설정했습니다'" 2>nul
if errorlevel 1 (
  echo     [경고] 세부 설정을 못 바꿨습니다. 등록은 됐지만 기본값으로 돕니다.
  echo            기본값은 3일 뒤 작업이 종료되고, 노트북 배터리에서는
  echo            시작되지 않습니다. 작업 스케줄러에서 직접 바꾸세요:
  echo              작업 스케줄러 - 24aist - 속성 - 조건/설정 탭
  echo              - "컴퓨터의 AC 전원이 켜져 있는 경우에만" 체크 해제
  echo              - "다음 시간 초과 시 작업 중지" 체크 해제
)
exit /b 0
