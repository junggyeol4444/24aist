import asyncio
import json
import re
import uuid
from datetime import datetime
from typing import List, Optional, Dict
from loguru import logger

from ..agent.output_types import DisplayText, Actions
from ..live2d_model import Live2dModel
from ..tts.tts_interface import TTSInterface
from ..utils.stream_audio import prepare_audio_payload
from .types import WebSocketSend


class TTSTaskManager:
    """Manages TTS tasks and ensures ordered delivery to frontend while allowing parallel TTS generation"""

    def __init__(self) -> None:
        self.task_list: List[asyncio.Task] = []
        self._lock = asyncio.Lock()
        # Queue to store ordered payloads
        self._payload_queue: asyncio.Queue[Dict] = asyncio.Queue()
        # Task to handle sending payloads in order
        self._sender_task: Optional[asyncio.Task] = None
        # Counter for maintaining order
        self._sequence_counter = 0
        self._next_sequence_to_send = 0

    async def speak(
        self,
        tts_text: str,
        display_text: DisplayText,
        actions: Optional[Actions],
        live2d_model: Live2dModel,
        tts_engine: TTSInterface,
        websocket_send: WebSocketSend,
    ) -> None:
        """
        Queue a TTS task while maintaining order of delivery.

        Args:
            tts_text: Text to synthesize
            display_text: Text to display in UI
            actions: Live2D model actions
            live2d_model: Live2D model instance
            tts_engine: TTS engine instance
            websocket_send: WebSocket send function
        """
        if len(re.sub(r'[\s.,!?，。！？\'"』」）】\s]+', "", tts_text)) == 0:
            logger.debug("Empty TTS text, sending silent display payload")
            # Get current sequence number for silent payload
            current_sequence = self._sequence_counter
            self._sequence_counter += 1

            # Start sender task if not running
            if not self._sender_task or self._sender_task.done():
                self._sender_task = asyncio.create_task(
                    self._process_payload_queue(websocket_send)
                )

            await self._send_silent_payload(display_text, actions, current_sequence)
            return

        logger.debug(
            f"🏃Queuing TTS task for: '''{tts_text}''' (by {display_text.name})"
        )

        # Get current sequence number
        current_sequence = self._sequence_counter
        self._sequence_counter += 1

        # Start sender task if not running
        if not self._sender_task or self._sender_task.done():
            self._sender_task = asyncio.create_task(
                self._process_payload_queue(websocket_send)
            )

        # Create and queue the TTS task
        task = asyncio.create_task(
            self._process_tts(
                tts_text=tts_text,
                display_text=display_text,
                actions=actions,
                live2d_model=live2d_model,
                tts_engine=tts_engine,
                sequence_number=current_sequence,
            )
        )
        self.task_list.append(task)

    async def _process_payload_queue(self, websocket_send: WebSocketSend) -> None:
        """
        Process and send payloads in correct order.
        Runs continuously until all payloads are processed.
        """
        buffered_payloads: Dict[int, Dict] = {}

        while True:
            try:
                # Get payload from queue
                payload, sequence_number = await self._payload_queue.get()
                buffered_payloads[sequence_number] = payload

                # Send payloads in order
                while self._next_sequence_to_send in buffered_payloads:
                    next_payload = buffered_payloads.pop(self._next_sequence_to_send)
                    await websocket_send(json.dumps(next_payload))
                    self._next_sequence_to_send += 1

                self._payload_queue.task_done()

            except asyncio.CancelledError:
                break

    async def _send_silent_payload(
        self,
        display_text: DisplayText,
        actions: Optional[Actions],
        sequence_number: int,
    ) -> None:
        """Queue a silent audio payload"""
        audio_payload = prepare_audio_payload(
            audio_path=None,
            display_text=display_text,
            actions=actions,
        )
        await self._payload_queue.put((audio_payload, sequence_number))

    async def _process_tts(
        self,
        tts_text: str,
        display_text: DisplayText,
        actions: Optional[Actions],
        live2d_model: Live2dModel,
        tts_engine: TTSInterface,
        sequence_number: int,
    ) -> None:
        """Process TTS generation and queue the result for ordered delivery"""
        audio_file_path = None
        try:
            audio_file_path = await self._generate_audio(tts_engine, tts_text)
            payload = prepare_audio_payload(
                audio_path=audio_file_path,
                display_text=display_text,
                actions=actions,
            )
            # Queue the payload with its sequence number
            await self._payload_queue.put((payload, sequence_number))

        except Exception as e:
            logger.error(f"Error preparing audio payload: {e}")
            # Queue silent payload for error case
            payload = prepare_audio_payload(
                audio_path=None,
                display_text=display_text,
                actions=actions,
            )
            await self._payload_queue.put((payload, sequence_number))

        finally:
            if audio_file_path:
                tts_engine.remove_file(audio_file_path)
                logger.debug("Audio cache file cleaned.")

    async def _generate_audio(self, tts_engine: TTSInterface, text: str) -> str:
        """Generate audio file from text"""
        logger.debug(f"🏃Generating audio for '''{text}'''...")
        audio_path = await tts_engine.async_generate_audio(
            text=text,
            file_name_no_ext=f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}",
        )
        return await self._post_process_audio(audio_path)

    async def _post_process_audio(self, audio_path: str) -> str:
        """[aist 개조] TTS 출력 후처리 훅 — RVC 2차 변조 등(기획안 3-4).

        환경변수 AIST_TTS_POST_CMD 가 설정돼 있으면 그 명령을 실행한다.
        명령의 {in} 이 오디오 파일 경로로 치환되며(없으면 끝에 추가),
        명령은 해당 파일을 제자리(in-place)에서 변환해야 한다.
        실패해도 원본 오디오로 방송은 계속된다(best-effort).
        예: AIST_TTS_POST_CMD="bash /path/rvc_convert.sh {in}"
        """
        import os

        cmd = os.environ.get("AIST_TTS_POST_CMD", "").strip()
        if not cmd or not audio_path:
            return audio_path
        try:
            args = post_cmd_args(cmd, audio_path)
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
            except asyncio.TimeoutError:
                proc.kill()
                logger.warning("TTS 후처리 명령 시간 초과(30s) — 원본 오디오 사용")
                return audio_path
            # [24aist 개조] 명령이 실패로 끝나도 예전에는 아무 말이 없었다 —
            # 목소리 변조가 빠진 채 방송이 나가는데 운영자는 모른다.
            if proc.returncode != 0:
                tail = (err or b"").decode("utf-8", "replace").strip()[-300:]
                logger.warning(
                    f"TTS 후처리 명령이 실패로 끝났습니다(종료 코드 {proc.returncode})"
                    f" — 원본 오디오 사용. {tail}")
        except Exception as e:
            logger.warning(f"TTS 후처리 실패({e}) — 원본 오디오 사용")
        return audio_path

    def clear(self) -> None:
        """Clear all pending tasks and reset state"""
        self.task_list.clear()
        if self._sender_task:
            self._sender_task.cancel()
        self._sequence_counter = 0
        self._next_sequence_to_send = 0
        # Create a new queue to clear any pending items
        self._payload_queue = asyncio.Queue()


def post_cmd_args(cmd: str, audio_path: str) -> list:
    """[24aist 개조] AIST_TTS_POST_CMD 를 실행할 인자 목록으로 바꾼다.

    윈도우에서 POSIX 방식으로 쪼개면 경로의 역슬래시가 전부 사라진다:
    'C:\\rvc\\convert.bat {in}' → 'C:rvcconvert.bat' (없는 파일 → 매번 실패,
    원본 목소리로 방송이 나가는데 경고 한 줄만 남는다). 윈도우에서는 윈도우
    방식으로 쪼개고 따옴표만 벗긴다. .bat/.cmd 는 cmd /c 로 돌린다.
    """
    import os
    import shlex

    if os.name == "nt":
        parts = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] == '"' else a
                 for a in shlex.split(cmd, posix=False)]
    else:
        parts = shlex.split(cmd)
    if any("{in}" in a for a in parts):
        args = [a.replace("{in}", audio_path) for a in parts]
    else:
        args = parts + [audio_path]
    if os.name == "nt" and args and args[0].lower().endswith((".bat", ".cmd")):
        args = ["cmd", "/c"] + args
    return args
