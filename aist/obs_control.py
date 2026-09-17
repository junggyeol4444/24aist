"""OBS 제어 (손) — obs-websocket 으로 스트림 시작/종료, 씬 전환.

obsws-python(동기 라이브러리)을 지연 import 한다 → 이 모듈은 패키지가
설치 안 돼 있어도 import 된다(핵심 로직 테스트가 깨지지 않게).
오케스트레이터에서는 asyncio.to_thread 로 감싸 호출한다.
"""

import logging
import time
from typing import Optional

from .config import ObsConfig

log = logging.getLogger("aist.obs")


class ObsError(Exception):
    pass


class ObsController:
    def __init__(self, cfg: ObsConfig):
        self.cfg = cfg
        self._client = None

    def connect(self):
        """OBS WebSocket 에 연결. 실패 시 (설정에 따라) OBS 를 직접 켜고 재시도."""
        try:
            import obsws_python as obs  # 지연 import
        except ImportError as e:
            raise ObsError(
                "obsws-python 이 설치되어 있지 않습니다. `pip install obsws-python`"
            ) from e

        def _try_connect():
            return obs.ReqClient(
                host=self.cfg.host, port=self.cfg.port,
                password=self.cfg.password or "", timeout=5,
            )

        try:
            self._client = _try_connect()
            log.info("OBS 연결됨 (%s:%s)", self.cfg.host, self.cfg.port)
            return self
        except Exception as first_err:  # noqa: BLE001 - 연결 실패 사유는 다양
            # OBS 자동 실행(2-2③): 안 떠 있으면 직접 켜고 기다렸다 재시도
            if not (self.cfg.launch_if_not_running and self.cfg.launch_command):
                raise ObsError(
                    f"OBS 연결 실패: {first_err}{self._why(first_err)}") from first_err
            if not self._launch_obs():
                raise ObsError(f"OBS 연결 실패(자동 실행도 실패): {first_err}") from first_err
            deadline = time.monotonic() + max(5, self.cfg.launch_wait_sec)
            last = first_err
            while time.monotonic() < deadline:
                time.sleep(2)
                try:
                    self._client = _try_connect()
                    log.info("OBS 자동 실행 후 연결됨 (%s:%s)", self.cfg.host, self.cfg.port)
                    return self
                except Exception as e:  # noqa: BLE001
                    last = e
            raise ObsError(f"OBS 자동 실행 후에도 연결 실패: {last}") from last

    def _why(self, err: Exception) -> str:
        """연결 실패 사유를 운영자 말로 덧붙인다.

        라이브러리 메시지는 영어라 "failed to identify client with the server"
        만 보면 무엇을 고쳐야 할지 알 수 없다. 이건 대부분 비밀번호 문제다.
        """
        text = str(err).lower()
        if "identify" in text or "authentication" in text or "4009" in text:
            if self.cfg.password:
                return ("\n  → 비밀번호가 틀린 것 같습니다. OBS 의 [도구] - "
                        "[obs-websocket 설정] 의 비밀번호와 .env 의 OBS_PASSWORD "
                        "가 같은지 확인하세요.")
            return ("\n  → OBS 쪽에 비밀번호가 설정돼 있는데 여기는 비어 있습니다. "
                    ".env 에 OBS_PASSWORD 를 넣으세요.")
        if "refused" in text or "timed out" in text or "timeout" in text:
            return ("\n  → OBS 가 켜져 있는지, [도구] - [obs-websocket 설정] 에서 "
                    "'웹소켓 서버 활성화' 가 켜져 있는지, 포트가 맞는지 확인하세요.")
        return ""

    @staticmethod
    def _split_command(cmd: str):
        """실행 명령 문자열을 인자 목록으로 쪼갠다.

        shlex 의 기본(POSIX) 모드는 윈도우 경로를 망가뜨린다:
          "C:/Program Files/obs-studio/bin/64bit/obs64.exe --x"
            → ['C:/Program', 'Files/obs-studio/bin/64bit/obs64.exe', '--x']
          "C:\\Program Files\\obs-studio\\bin\\64bit\\obs64.exe --x"
            → ['C:Program', 'Filesobs-studiobin64bitobs64.exe', '--x']
        둘 다 실행이 실패한다. 첫 번째 형태는 config.example.yaml 에 예시로
        적혀 있던 바로 그 문자열이다.

        윈도우에서는 posix=False 로 쪼개고(역슬래시를 이스케이프로 안 먹음),
        따옴표가 없는데 공백이 있는 경로는 전체를 한 덩어리로 본다.
        """
        import os
        import shlex
        if os.name != "nt":
            return shlex.split(cmd)
        lex = shlex.shlex(cmd, posix=False)
        lex.whitespace_split = True
        parts = [p.strip('"') for p in lex]
        if not parts:
            return parts
        # 따옴표 없이 공백 있는 경로를 쓴 경우: 실행 파일 조각을 다시 붙인다.
        # (.exe 로 끝나는 지점까지가 실행 파일)
        if not parts[0].lower().endswith((".exe", ".bat", ".cmd", ".com")):
            for i, part in enumerate(parts):
                if part.lower().endswith((".exe", ".bat", ".cmd", ".com")):
                    return [" ".join(parts[: i + 1])] + parts[i + 1:]
        return parts

    def _launch_obs(self) -> bool:
        """OBS 프로그램을 직접 실행(백그라운드). 성공 여부만 반환."""
        import subprocess
        try:
            args = self._split_command(self.cfg.launch_command)
            subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            log.info("OBS 자동 실행: %s", self.cfg.launch_command)
            return True
        except Exception as e:  # noqa: BLE001 - 경로 오류 등
            log.error("OBS 자동 실행 실패: %s", e)
            return False

    def _require(self):
        if self._client is None:
            raise ObsError("OBS 에 먼저 connect() 해야 합니다.")
        return self._client

    def _is_streaming(self) -> Optional[bool]:
        """지금 송출 중인지. 알 수 없으면 None."""
        try:
            status = self._require().get_stream_status()
            return bool(getattr(status, "output_active", False))
        except Exception:  # noqa: BLE001 - 상태 조회 실패는 치명적이지 않음
            return None

    def is_streaming(self) -> Optional[bool]:
        """지금 송출 중인지(외부용). 알 수 없으면 None."""
        return self._is_streaming()

    def stream_state(self) -> str:
        """송출 상태를 세 가지로 구분한다: live | down | unreachable.

        '못 물어봤다'와 '안 하고 있다'는 다르다. OBS 프로그램이 죽으면
        물어볼 수조차 없는데, 그건 '모르겠다'가 아니라 '송출이 확실히
        끊겼다'는 뜻이다(인코더가 없으니까). 예전에는 둘을 같이 None 으로
        묶어서, OBS 를 꺼도 방송이 아무 말 없이 계속 돌았다.
        """
        if self._client is None:
            return "unreachable"
        try:
            status = self._client.get_stream_status()
        except Exception:  # noqa: BLE001 - 끊김·타임아웃 등 사유는 다양
            return "unreachable"
        return "live" if getattr(status, "output_active", False) else "down"

    def connected(self) -> bool:
        """지금 OBS 에 붙어 있는지(외부용)."""
        return self._client is not None

    def refresh_browser_sources(self, url_contains: str = "") -> int:
        """웹UI 를 띄운 브라우저 소스를 새로고침한다. 새로고친 개수를 돌려준다.

        코어가 재시작되거나 순단이 나면 브라우저 소스가 물고 있던 웹소켓이
        끊긴다. 우리 프로세스는 다시 붙지만 브라우저 소스는 끊긴 채로
        남을 수 있고, 그러면 AI 가 말을 해도 시청자에게는 아무것도 안
        나간다(코어는 '재생 끝' 응답을 기다리느라 대화가 영영 안 끝난다).
        실제로 코어를 죽였다 살린 실행에서, 우리 쪽은 "재연결 성공" 인데
        그 뒤 90초마다 발화가 걸리고 화면은 조용한 상태가 재현됐다.

        운영자에게 "브라우저 소스를 새로고침하세요" 라고 로그로 부탁만
        하는 건 무인 운영에서 아무 의미가 없다. OBS 가 우리 손에 있으면
        우리가 직접 누른다.

        url_contains 가 있으면 그 문자열이 주소에 든 소스만 건드린다
        (알림창·오버레이 같은 다른 브라우저 소스를 괜히 깜빡이게 하지
        않기 위해서다).
        """
        cl = self._client
        if cl is None:
            return 0
        try:
            inputs = getattr(cl.get_input_list(), "inputs", []) or []
        except Exception as e:  # noqa: BLE001 - OBS 가 막 죽었을 수도 있다
            log.warning("브라우저 소스 목록을 못 읽었습니다: %s", e)
            return 0
        done = 0
        for item in inputs:
            if not isinstance(item, dict):
                continue
            if "browser" not in str(item.get("inputKind", "")).lower():
                continue
            name = item.get("inputName") or ""
            if not name:
                continue
            if url_contains:
                try:
                    settings = getattr(
                        cl.get_input_settings(name), "input_settings", {}) or {}
                except Exception:  # noqa: BLE001 - 소스 하나 때문에 멈추지 않는다
                    continue
                if url_contains not in str(settings.get("url", "")):
                    continue
            try:
                cl.press_input_properties_button(name, "refreshnocache")
            except Exception as e:  # noqa: BLE001 - 버튼 이름은 OBS 버전마다 다를 수 있다
                log.warning("브라우저 소스 새로고침 실패(%s): %s", name, e)
                continue
            log.info("OBS 브라우저 소스 새로고침: %s", name)
            done += 1
        return done

    def reconnect(self) -> bool:
        """끊긴 OBS 에 다시 붙어본다(꺼져 있으면 설정에 따라 켜기도 한다)."""
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass
        self._client = None
        try:
            self.connect()
            return True
        except ObsError as e:
            log.debug("OBS 재연결 실패: %s", e)
            return False

    def start_stream(self):
        """스트림 시작. start_stream=false 면 (테스트 단계) 건너뛴다.

        영상 동출(simulcast)이 켜져 있으면 추가 RTMP 출력도 함께 시작한다.
        """
        if not self.cfg.start_stream:
            log.info("obs.start_stream=false → 스트림 시작은 운영자 수동(건너뜀)")
            return
        cl = self._require()
        if self._is_streaming():
            log.info("이미 스트리밍 중 → 시작 생략")
            return
        try:
            cl.start_stream()
        except ObsError:
            raise
        except Exception as e:  # noqa: BLE001 - obsws 는 자기 예외를 던진다
            # 호출자는 ObsError 만 잡는다. 정규화하지 않으면 방송 사이클이
            # 엉뚱한 곳에서 끊긴다.
            raise ObsError(f"스트림 시작 실패: {e}") from e
        log.info("OBS 스트림 시작")
        self._simulcast(start=True)

    def stop_stream(self):
        if not self.cfg.start_stream:
            log.info("obs.start_stream=false → 스트림 종료도 운영자 수동(건너뜀)")
            return
        if self._client is None:
            # OBS 가 죽어서 방송을 내리는 길로 들어온 경우다. 여기서
            # "먼저 connect() 해야 합니다" 를 ERROR 로 찍으면 운영자에게는
            # 프로그램이 잘못된 것처럼 보인다. 이미 아는 사실을 조용히 넘긴다.
            log.info("OBS 연결이 이미 끊겨 있습니다 → 스트림 종료 생략")
            return
        cl = self._require()
        self._simulcast(start=False)
        if self._is_streaming() is False:
            # 이미 꺼져 있다. 그냥 stop 을 부르면 obsws 가 예외를 던지고,
            # 그게 방송 종료 절차 전체를 깨뜨린다(운영자가 OBS 에서 직접
            # 껐거나 스트림 키 오류로 자동 중단된 경우에 실제로 일어난다).
            log.info("이미 스트리밍이 아님 → 종료 생략")
            return
        try:
            cl.stop_stream()
        except ObsError:
            raise
        except Exception as e:  # noqa: BLE001 - obsws 는 자기 예외를 던진다
            raise ObsError(f"스트림 종료 실패: {e}") from e
        log.info("OBS 스트림 종료")

    def _simulcast(self, start: bool):
        """영상 동출(다중 RTMP) 추가 출력 제어.

        - plugin_autostart: 플러그인이 스트림 시작에 맞춰 스스로 켜지므로 별도
          호출 없음(대상만 로그로 알림).
        - vendor: obs-websocket vendor 요청으로 플러그인 전체 시작/종료 호출.
        플러그인이 없거나 요청이 실패해도 본 방송은 계속되도록 best-effort.
        """
        sc = self.cfg.simulcast
        if not sc.enabled:
            return
        names = ", ".join(t.name or t.url for t in sc.targets) or "(플러그인에 설정된 대상)"
        if sc.mode == "plugin_autostart":
            log.info("동출(%s): 플러그인 auto-start 가 처리 → 대상: %s",
                     "시작" if start else "종료", names)
            return
        # vendor 모드
        req = sc.start_request if start else sc.stop_request
        cl = self._require()
        try:
            cl.call_vendor_request(sc.vendor_name, req, None)
            log.info("동출 vendor 요청 성공: %s.%s (대상: %s)", sc.vendor_name, req, names)
        except Exception as e:  # noqa: BLE001 - 플러그인 없음/요청명 불일치 등
            log.warning("동출 vendor 요청 실패(%s.%s): %s — 본 방송은 계속. "
                        "플러그인 설치/요청명(start_request·stop_request) 확인",
                        sc.vendor_name, req, e)

    def set_scene(self, scene_name: str):
        cl = self._require()
        cl.set_current_program_scene(scene_name)
        log.info("OBS 씬 전환 → %s", scene_name)

    def close(self):
        client = self._client
        self._client = None
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
