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
