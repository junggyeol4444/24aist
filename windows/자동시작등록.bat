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
