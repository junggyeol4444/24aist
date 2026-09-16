"""설정 파일의 각 섹션이 실제로 읽히는지.

safety 섹션이 config.example.yaml 에 문서화돼 있는데도 load_config 가
읽지 않아, 운영자가 금지어를 적어도 아무 일도 안 일어났다. 섹션 하나를
빠뜨리면 그 기능 전체가 조용히 죽으므로 구조적으로 막는다.
"""

import dataclasses

import yaml

from aist.config import Config, load_config


def _sections():
    for f in dataclasses.fields(Config):
        if f.name == "secrets":          # .env 에서 채운다(파일에서 읽지 않음)
            continue
        if dataclasses.is_dataclass(f.type):
            yield f.name, f.type


def _probe_field(cls):
    """그 섹션에서 값을 바꿔볼 수 있는 스칼라 필드 하나와 바꾼 값."""
    for f in dataclasses.fields(cls):
        default = f.default
        if isinstance(default, bool):
            return f.name, (not default)
        if isinstance(default, str) and f.name not in ("password",):
            return f.name, default + "_확인용"
        if isinstance(default, int):
            return f.name, default + 7
    return None, None


def test_every_section_is_actually_read(tmp_path):
    missed = []
    for name, cls in _sections():
        key, value = _probe_field(cls)
        if key is None:
            continue
        p = tmp_path / f"{name}.yaml"
        p.write_text(yaml.safe_dump({name: {key: value}}, allow_unicode=True),
                     encoding="utf-8")
        try:
            cfg = load_config(p)
        except Exception as e:      # 값 검증에 걸리는 섹션은 건너뛴다
            print(f"({name}.{key} 검증됨: {e})")
            continue
        got = getattr(getattr(cfg, name), key)
        if got != value:
            missed.append(f"{name}.{key}: 파일에 {value!r} 를 적었는데 {got!r}")
    assert not missed, "설정 섹션이 무시되고 있습니다:\n  " + "\n  ".join(missed)


def test_safety_section_is_read(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "safety:\n"
        "  banned_words: ['금지어']\n"
        "  stop_flag_path: 'data/내가정한경로'\n"
        "  stop_broadcast_on_hit: true\n",
        encoding="utf-8")
    cfg = load_config(p)
    assert cfg.safety.banned_words == ["금지어"]
    assert cfg.safety.stop_flag_path == "data/내가정한경로"
    assert cfg.safety.stop_broadcast_on_hit is True


def test_typo_key_is_reported_not_silently_ignored(tmp_path):
    """오타 난 키를 조용히 무시하면 '바꿨는데 아무 일도 안 일어난다' 가 된다."""
    p = tmp_path / "c.yaml"
    p.write_text(
        "end_judge:\n"
        "  max_minute: 120\n"           # s 빠짐
        "  wind_down:\n"
        "    closing_greting: true\n"   # e 빠짐
        "saftey:\n"                     # 섹션 이름 오타
        "  banned_words: []\n",
        encoding="utf-8")
    cfg = load_config(p)
    joined = " | ".join(cfg.unknown_keys)
    assert "end_judge.max_minute" in joined and "max_minutes" in joined
    assert "closing_greting" in joined and "closing_greeting" in joined
    assert "saftey" in joined and "safety" in joined
    # 제대로 적은 설정은 경고가 없어야 한다
    p2 = tmp_path / "ok.yaml"
    p2.write_text("end_judge:\n  max_minutes: 120\n", encoding="utf-8")
    assert load_config(p2).unknown_keys == []


def test_example_config_has_no_unknown_keys():
    """동봉한 예시 설정이 경고를 내면 안 된다."""
    from pathlib import Path
    example = Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"
    cfg = load_config(example)
    assert cfg.unknown_keys == [], cfg.unknown_keys


def test_every_setting_appears_in_the_example_file():
    """운영자가 만지는 값은 전부 예시 파일에 있어야 한다.

    config.py 첫 줄의 원칙이 그렇다("운영자가 만지는 모든 값은 YAML 에
    있다"). 새 설정을 코드에만 추가하면 운영자는 그런 게 있는 줄도
    모르고, 점검 메시지에 나오는 키를 자기 설정 파일에서 찾지 못한다.
    (실제로 이번에 추가한 9개가 그 상태였다)

    secrets.* 는 .env 에 들어가므로 제외한다.
    """
    import dataclasses
    from pathlib import Path

    from aist.config import Config

    text = Path("config/config.example.yaml").read_text(encoding="utf-8")

    def walk(cls, prefix=""):
        names = []
        for f in dataclasses.fields(cls):
            full = f"{prefix}{f.name}"
            if dataclasses.is_dataclass(f.type):
                names += walk(f.type, full + ".")
            else:
                names.append(full)
        return names

    skip = {"unknown_keys"}
    missing = [n for n in walk(Config)
               if not n.startswith("secrets.") and n not in skip
               and n.rsplit(".", 1)[-1] not in text]
    assert not missing, f"예시 파일에 안 적힌 설정: {missing}"


def test_example_config_still_loads():
    """예시 파일을 고치다 형식이 깨지면 안 된다."""
    from aist.config import load_config

    cfg = load_config("config/config.example.yaml")
    assert cfg.obs.stream_check_sec > 0
    assert cfg.scheduler.retry_max >= 0
    assert cfg.broadcast.core_mute_max_strikes >= 0
    assert not cfg.unknown_keys, cfg.unknown_keys


def test_operator_guide_quotes_real_log_lines():
    """운영자 가이드가 '이 문장이 뜨면 이걸 확인하세요' 라고 적어놨는데
    정작 코드에 그 문장이 없으면, 운영자는 로그에서 찾지 못한다.

    (메시지를 고칠 때 문서도 같이 고치라는 뜻의 테스트다)
    """
    from pathlib import Path

    code = "\n".join(p.read_text(encoding="utf-8")
                     for p in Path("aist").rglob("*.py"))
    guide = Path("docs/OPERATOR.md").read_text(encoding="utf-8")
    phrases = [
        "코어가 말을 해도 시청자에게 나가지 않는 상태입니다",
        "방송인이 LLM 오류 문구만 반복해서 읽고 있습니다",
        "OBS 송출이 또 내려갔습니다",
        "채팅을 살릴 수 없습니다",
        "연속으로 소리 없이(자막만) 나갔습니다",
        "기억 파일을 읽지 못했습니다",
    ]
    for ph in phrases:
        assert ph in guide, f"가이드에서 빠짐: {ph}"
        assert ph in code, f"코드에 없는 문장을 가이드가 인용함: {ph}"
