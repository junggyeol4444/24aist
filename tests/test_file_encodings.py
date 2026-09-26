"""설정 파일 인코딩 — 운영자는 메모장으로 편집한다.

README 가 "config.yaml / persona.yaml / .env 를 메모장으로 열어 채우기"
라고 안내한다. 메모장은 저장할 때 인코딩을 고를 수 있고, UTF-8 이 아니면
전부 UnicodeDecodeError 로 죽었다. 에러 메시지가
    'utf-8' codec can't decode byte 0xb9 in position 81
이라 코딩을 안 하는 운영자는 손쓸 방법이 없었다.

.env 의 BOM 은 더 나빴다 — 죽지도 않고 첫 줄의 키만 조용히 사라져서
"키를 넣었는데 비어있음으로 나온다"는 추적 불가능한 증상이 됐다.
"""

import os

import pytest

from aist.cli import _load_dotenv
from aist.config import ConfigError, load_config, read_text_lenient
from aist.persona import Persona

_CONFIG_SRC = "config/config.example.yaml"
_PERSONA_SRC = "config/persona.example.yaml"


def _write(tmp_path, name, text, encoding, bom=b""):
    p = tmp_path / name
    p.write_bytes(bom + text.encode(encoding, "replace"))
    return p


@pytest.fixture
def config_text():
    return read_text_lenient(_CONFIG_SRC)


@pytest.fixture
def persona_text():
    return read_text_lenient(_PERSONA_SRC)


# --------------------------- config.yaml -----------------------------------
@pytest.mark.parametrize("label, encoding, bom", [
    ("메모장 UTF-8", "utf-8", b""),
    ("메모장 UTF-8 BOM", "utf-8", b"\xef\xbb\xbf"),
    ("메모장 유니코드(UTF-16)", "utf-16", b""),
    ("메모장 ANSI(한국어 윈도우 = CP949)", "cp949", b""),
])
def test_config_loads_in_notepad_encodings(tmp_path, config_text, label, encoding, bom):
    p = _write(tmp_path, "config.yaml", config_text, encoding, bom)
    cfg = load_config(p)
    assert cfg.scheduler.timezone == "Asia/Seoul"


@pytest.mark.parametrize("label, encoding", [
    ("유니코드(UTF-16)", "utf-16"),
    ("ANSI(CP949)", "cp949"),
])
def test_persona_loads_in_notepad_encodings(tmp_path, persona_text, label, encoding):
    p = _write(tmp_path, "persona.yaml", persona_text, encoding)
    persona = Persona.load(p)
    assert persona.name


# --------------------------- .env ------------------------------------------
@pytest.fixture(autouse=True)
def _clean_env():
    os.environ.pop("AIST_TEST_KEY", None)
    yield
    os.environ.pop("AIST_TEST_KEY", None)


def test_dotenv_bom_on_first_line_still_reads_key(tmp_path):
    """BOM 이 붙으면 첫 줄 키가 '\\ufeffAIST_TEST_KEY' 가 되어 사라졌다."""
    p = tmp_path / ".env"
    p.write_bytes(b"\xef\xbb\xbfAIST_TEST_KEY=abc123\r\n")
    _load_dotenv(str(p))
    assert os.environ.get("AIST_TEST_KEY") == "abc123"


@pytest.mark.parametrize("data", [
    b"AIST_TEST_KEY=abc123\n",
    b"AIST_TEST_KEY=abc123\r\n",                       # 윈도우 줄바꿈
    b'AIST_TEST_KEY="abc123"\n',                       # 따옴표
    b"  AIST_TEST_KEY = abc123  \n",                   # 앞뒤 공백
    "AIST_TEST_KEY=abc123\n".encode("utf-16"),         # 메모장 유니코드
    "# 키 설명\nAIST_TEST_KEY=abc123\n".encode("cp949"),  # 메모장 ANSI
])
def test_dotenv_reads_common_notepad_output(tmp_path, data):
    p = tmp_path / ".env"
    p.write_bytes(data)
    _load_dotenv(str(p))
    assert os.environ.get("AIST_TEST_KEY") == "abc123"


def test_dotenv_keeps_equals_inside_value(tmp_path):
    p = tmp_path / ".env"
    p.write_bytes(b"AIST_TEST_KEY=ab=cd\n")
    _load_dotenv(str(p))
    assert os.environ.get("AIST_TEST_KEY") == "ab=cd"


def test_dotenv_does_not_override_existing_env(tmp_path):
    os.environ["AIST_TEST_KEY"] = "원래값"
    p = tmp_path / ".env"
    p.write_text("AIST_TEST_KEY=새값\n", encoding="utf-8")
    _load_dotenv(str(p))
    assert os.environ["AIST_TEST_KEY"] == "원래값"


# --------------------------- 정말 못 읽는 파일 ------------------------------
def test_unreadable_file_gives_korean_guidance(tmp_path):
    """알 수 없는 바이트면 파이썬 에러 대신 사람이 읽는 안내를 준다."""
    p = tmp_path / "config.yaml"
    p.write_bytes(bytes([0x80, 0x81, 0xfe, 0x00, 0x9f, 0x90]))
    with pytest.raises(ConfigError) as e:
        read_text_lenient(p)
    assert "UTF-8" in str(e.value)
