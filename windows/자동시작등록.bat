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
set "RUNNER=%~dp0전체실행.bat"

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

schtasks /query /tn "%TASKNAME%" >nul 2>nul
if %errorlevel%==0 (
  echo 이미 등록돼 있습니다. 다시 등록할까요?
  choice /c YN /m "덮어쓰기"
  if errorlevel 2 ( echo 그대로 둡니다. & pause & exit /b 0 )
  schtasks /delete /tn "%TASKNAME%" /f >nul
)

schtasks /create /tn "%TASKNAME%" /tr "\"%RUNNER%\"" /sc onlogon /rl highest /f
if errorlevel 1 (
  echo.
  echo [오류] 등록 실패.
  echo        이 파일을 마우스 오른쪽 - "관리자 권한으로 실행" 으로 다시 해보세요.
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
