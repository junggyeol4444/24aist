"""aist 실행 진입점 (PyInstaller 로 aist.exe 를 만들 때 사용).

일반 사용은 `aist ...` 명령을 쓰면 되고, 이 파일은 exe 빌드용이다.
(windows/EXE만들기.bat 참고)
"""
from aist.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
