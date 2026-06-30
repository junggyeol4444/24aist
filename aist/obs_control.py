"""OBS 제어 (손) — obs-websocket 으로 스트림 시작/종료, 씬 전환.

obsws-python(동기 라이브러리)을 지연 import 한다 → 이 모듈은 패키지가
설치 안 돼 있어도 import 된다(핵심 로직 테스트가 깨지지 않게).
오케스트레이터에서는 asyncio.to_thread 로 감싸 호출한다.
"""

import logging
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
        """OBS WebSocket 에 연결. 실패하면 ObsError."""
        try:
            import obsws_python as obs  # 지연 import
        except ImportError as e:
            raise ObsError(
                "obsws-python 이 설치되어 있지 않습니다. `pip install obsws-python`"
            ) from e
        try:
            self._client = obs.ReqClient(
                host=self.cfg.host,
                port=self.cfg.port,
                password=self.cfg.password or "",
                timeout=5,
            )
            log.info("OBS 연결됨 (%s:%s)", self.cfg.host, self.cfg.port)
        except Exception as e:  # noqa: BLE001 - 연결 실패 사유는 다양
            raise ObsError(f"OBS 연결 실패: {e}") from e
        return self

    def _require(self):
        if self._client is None:
            raise ObsError("OBS 에 먼저 connect() 해야 합니다.")
        return self._client

    def start_stream(self):
        """스트림 시작. start_stream=false 면 (테스트 단계) 건너뛴다."""
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

    def stop_stream(self):
        if not self.cfg.start_stream:
            log.info("obs.start_stream=false → 스트림 종료도 운영자 수동(건너뜀)")
            return
        cl = self._require()
        cl.stop_stream()
        log.info("OBS 스트림 종료")

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
