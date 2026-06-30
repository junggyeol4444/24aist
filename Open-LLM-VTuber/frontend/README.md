# frontend/ — 프론트엔드(웹 UI)는 여기로 받습니다

Open-LLM-VTuber 의 웹 UI 는 별도 저장소(Open-LLM-VTuber-Web)의 **컴파일된
build 산출물**입니다(onnxruntime wasm/onnx 등 ~44MB의 바이너리). "수정하는
소스"가 아니라 런타임 실행 파일이라, **git 에는 커밋하지 않고** 스크립트로
받습니다.

```bash
# 저장소 루트(24aist)에서:
bash scripts/fetch_frontend.sh
```

이 스크립트가 `Open-LLM-VTuber/frontend/` 아래에 index.html / assets / libs 를
채웁니다. 받은 파일들은 `.gitignore` 로 커밋에서 제외됩니다.

> 웹 UI 가 Live2D 아바타를 브라우저에 렌더하고, 그 화면을 OBS 로 캡처합니다.
> 자세한 연결은 `24aist/docs/INTEGRATION.md` 참고.
