@echo off
chcp 65001 >nul
setlocal
set "TASKNAME=24aist"

echo === 24시간 무인 운영 해제 ===
schtasks /query /tn "%TASKNAME%" >nul 2>nul
if errorlevel 1 (
  echo 등록돼 있지 않습니다. 할 일이 없습니다.
  pause & exit /b 0
)

schtasks /delete /tn "%TASKNAME%" /f
if errorlevel 1 (
  echo [오류] 해제 실패. 관리자 권한으로 다시 실행해보세요.
  pause & exit /b 1
)
echo 해제됐습니다. 이제 자동으로 켜지지 않습니다.
echo ^(수동 실행은 전체실행.bat^)
pause
