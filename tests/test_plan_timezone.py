"""예정표가 엉뚱한 시각을 진짜처럼 보여주지 않는지.

타임존 이름에 오타가 있으면(또는 윈도우에 tzdata 가 없으면) zoneinfo 가
실패하고 PC 로컬 시간으로 떨어진다. 그런데 `aist plan` 은 그 사실을 한
줄도 안 알리고, UTC 시각에 'Asia/Seoul' 이라는 이름표를 붙여서 예정표를
찍었다. 운영자는 그 표를 믿고 방송 시각을 맞추는데 실제로는 9시간
어긋난 채로 돈다.
"""

import types

from aist.cli import cmd_plan


def _args(tmp_path, tz):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "platform: rehearsal\n"
        "scheduler: { enabled: true, timezone: \"%s\", "
        "weekly: { thu: [\"20:00\"] } }\n" % tz,
        encoding="utf-8")
    return types.SimpleNamespace(config=str(cfg),
                                 persona=str(tmp_path / "없음.yaml"),
                                 log="ERROR", count=2)


def test_타임존을_못_쓰면_그렇다고_말한다(tmp_path, capsys):
    cmd_plan(_args(tmp_path, "Asia/Seoull"))
    out = capsys.readouterr().out
    assert "쓸 수 없어" in out
    # 잘못된 이름표를 시각 옆에 붙이지 않는다
    assert "현재(Asia/Seoull)" not in out
    assert "PC 로컬" in out


def test_정상_타임존이면_조용히_그_이름으로_보여준다(tmp_path, capsys):
    cmd_plan(_args(tmp_path, "Asia/Seoul"))
    out = capsys.readouterr().out
    assert "현재(Asia/Seoul)" in out
    assert "쓸 수 없어" not in out
