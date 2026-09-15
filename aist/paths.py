"""산출물 경로 — 같은 분에 방송이 두 번 시작해도 서로 안 덮게 한다.

방송 산출물(트랜스크립트·리포트·컨텐츠 팩)의 파일명은 방송 시작 시각의
분까지만 쓴다. 평소에는 방송이 몇 시간 간격이라 겹칠 일이 없지만,
무인운영 재시작 루프에서 방송이 켜자마자 죽고 다시 뜨면 같은 분에 두 번
시작한다(재시작 간격이 10초였다). broadcast-now 를 연달아 눌러도 같다.

그때 벌어지던 일 — 3회 연속으로 돌려서 확인했다:
  트랜스크립트 : "a" 모드라 세 방송이 한 파일에 섞였다.
                 리포트의 'AI 발화 전문' 과 하이라이트 분석이 세 방송을
                 합쳐서 본다.
  리포트/컨텐츠 : write_text 라 그냥 덮어썼다. 앞 방송 것이 사라졌다.

그래서 이미 있으면 _2, _3 을 붙인다. 평소 파일명 형식은 그대로 두고
겹칠 때만 구분한다(운영자가 보던 이름이 안 바뀌게).
"""

from pathlib import Path

_MAX_TRIES = 1000


def unique_path(path: Path) -> Path:
    """이미 있으면 이름 뒤에 _2, _3 … 을 붙여 안 겹치는 경로를 돌려준다."""
    path = Path(path)
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for n in range(2, _MAX_TRIES):
        cand = parent / f"{stem}_{n}{suffix}"
        if not cand.exists():
            return cand
    # 여기까지 오면 뭔가 크게 이상한 상황이다. 덮어쓰느니 그대로 돌려준다.
    return path
