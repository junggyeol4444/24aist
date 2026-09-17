"""점검(doctor)이 "그래서 켜도 되냐" 에 답하는지.

점검.bat 가 부르는 건 check 가 아니라 doctor 다. 그런데 doctor 는 [X] 를
줄줄이 찍어놓고 "위 항목을 확인하세요" 로 끝났다. 코딩 안 하는 운영자가
그걸 보고 지금 방송을 켜도 되는지 판단할 방법이 없다.
"""

import types

from aist.cli import cmd_doctor


def _args(tmp_path, cfg_text):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(cfg_text, encoding="utf-8")
    return types.SimpleNamespace(config=str(cfg), persona=str(tmp_path / "없음.yaml"),
                                 log="ERROR")


_DEAD = """
platform: rehearsal
vtuber: { ws_url: "ws://127.0.0.1:19998/proxy-ws", connect_timeout_sec: 1 }
obs: { host: "127.0.0.1", port: 4998, start_stream: true }
announce: { discord: {enabled: false}, naver_cafe: {enabled: false} }
scheduler: { enabled: false }
"""


def test_코어가_죽어_있으면_켜면_안_된다고_말한다(tmp_path, capsys):
    rc = cmd_doctor(_args(tmp_path, _DEAD))
    out = capsys.readouterr().out
    assert rc == 1
    assert "지금 켜면 방송이 안 됩니다" in out
    # 코어 문제가 맨 앞 — 코어가 안 붙으면 나머지는 볼 것도 없다
    body = out.split("지금 켜면 방송이 안 됩니다")[1]
    bullets = [x for x in body.splitlines() if x.startswith("  - ")]
    assert bullets and "코어" in bullets[0], bullets
    # 무엇을 하면 되는지까지 — 이 OS 에서 실제로 누를 것으로.
    # (websockets 가 없는 환경이면 코어에 붙어보기도 전에 걸린다)
    import importlib.util
    if importlib.util.find_spec("websockets") is not None:
        from aist import preflight
        assert preflight.hint(*preflight.CMD_CORE_RUN) in out
    else:
        assert "websockets" in body


def test_송출_자동이_아니면_OBS_문구도_달라진다(tmp_path, capsys):
    cmd_doctor(_args(tmp_path, _DEAD.replace("start_stream: true",
                                             "start_stream: false")))
    out = capsys.readouterr().out
    assert "OBS 를 제어하지 못합니다" in out
