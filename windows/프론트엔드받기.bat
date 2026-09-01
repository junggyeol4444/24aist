@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

REM ============================================================
REM  코어 웹UI(프론트엔드) 받기
REM  frontend\ 는 컴파일 산출물(wasm/onnx ~44MB)이라 저장소에 없다.
REM  이걸 안 받으면 코어가 떠도 화면이 안 나온다.
REM  (리눅스/맥은 scripts/fetch_frontend.sh 와 같은 일을 한다)
REM ============================================================

set "DEST=Open-LLM-VTuber\frontend"
set "URL=https://codeload.github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/tar.gz/refs/heads/build"

if exist "%DEST%\index.html" (
  echo 이미 받아져 있습니다: %DEST%\index.html
  echo 다시 받으려면 %DEST% 안의 파일을 지우고 실행하세요.
  pause & exit /b 0
)

where curl >nul 2>nul || ( echo [오류] curl 이 없습니다. 윈도우 10 이상이 필요합니다. & pause & exit /b 1 )
where tar  >nul 2>nul || ( echo [오류] tar 가 없습니다. 윈도우 10 이상이 필요합니다. & pause & exit /b 1 )

set "TMP_DIR=%TEMP%\aist_frontend"
if exist "%TMP_DIR%" rmdir /s /q "%TMP_DIR%"
mkdir "%TMP_DIR%"

echo ==^> 프론트엔드 build 산출물 다운로드...
curl -fsSL --max-time 300 -o "%TMP_DIR%\web.tar.gz" "%URL%"
if errorlevel 1 ( echo [오류] 다운로드 실패 - 인터넷 연결을 확인하세요. & rmdir /s /q "%TMP_DIR%" & pause & exit /b 1 )

echo ==^> 압축 해제...
tar -xzf "%TMP_DIR%\web.tar.gz" -C "%TMP_DIR%"
if errorlevel 1 ( echo [오류] 압축 해제 실패 & rmdir /s /q "%TMP_DIR%" & pause & exit /b 1 )

if not exist "%DEST%" mkdir "%DEST%"
for /d %%D in ("%TMP_DIR%\Open-LLM-VTuber-Web-*") do (
  xcopy /E /I /Y /Q "%%D\*" "%DEST%\" >nul
)
rmdir /s /q "%TMP_DIR%"

if exist "%DEST%\index.html" (
  echo ==^> 완료. %DEST% 에 index.html 이 들어왔습니다.
) else (
  echo [오류] 받긴 했는데 index.html 이 없습니다. 저장소 이슈를 확인하세요.
  pause & exit /b 1
)
pause
