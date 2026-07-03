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
                raise ObsError(f"OBS 연결 실패: {first_err}") from first_err
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

    def _launch_obs(self) -> bool:
        """OBS 프로그램을 직접 실행(백그라운드). 성공 여부만 반환."""
        import shlex
        import subprocess
        try:
            args = shlex.split(self.cfg.launch_command)
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

    def start_stream(self):
        """스트림 시작. start_stream=false 면 (테스트 단계) 건너뛴다.

        영상 동출(simulcast)이 켜져 있으면 추가 RTMP 출력도 함께 시작한다.
        """
        if not self.cfg.start_stream:
            log.info("obs.start_stream=false → 스트림 시작은 운영자 수동(건너뜀)")
            return
        cl = self._require()
        try:
            status = cl.get_stream_status()
            if getattr(status, "output_active", False):
                log.info("이미 스트리밍 중 → 시작 생략")
                return
        except Exception:  # 상태 조회 실패는 치명적이지 않음
            pass
        cl.start_stream()
        log.info("OBS 스트림 시작")
        self._simulcast(start=True)

    def stop_stream(self):
        if not self.cfg.start_stream:
            log.info("obs.start_stream=false → 스트림 종료도 운영자 수동(건너뜀)")
            return
        cl = self._require()
        self._simulcast(start=False)
        cl.stop_stream()
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
