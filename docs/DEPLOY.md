# 배포 — HEAX 연합(SIF) 등록 + 모델 Drive 파이프라인

VoiceRecorder 를 "통째로" 다른 서버(폐쇄망 cae00)로 옮겨 돌리는 방법. 다른 HEAX 앱과
**똑같이 HEAXHub 가 SIF 로 빌드·서빙**한다 — 자체 venv 독립 서비스가 아니다. torch·Chatterbox·
MeloTTS·CosyVoice 스택은 SIF 빌드 훅이 컨테이너에 심고, 무거운 **가중치만** `/data` 볼륨으로
Drive 를 태워 나른다.

## 어떻게 도는가 (SIF 경로)

1. **카탈로그 등록**: HEAXHub `integrations/voice-recorder/.portal/manifest.yaml`
   (id=voice_recorder, `build.stack: fastapi_react`, launch.env=`VOICEREC_DATA_DIR=/data`·
   `VOICEREC_MODELS_DIR=/data/models`·`HF_HOME=/data/models`·`HF_HUB_OFFLINE=1`, `resources.gpu: true`).
2. **SIF 빌드**: 스캐너가 GitHub main clone → `fastapi_react.def` 렌더.
   - Stage1 frontend(pnpm build) → Stage2 `pip install -e backend` →
   - Stage3 opt-in 훅 `scripts/heaxhub-build.sh`:
     - system python(3.12): torch(cu130 기본) + Chatterbox
     - `/app/backend/.venv-melo`(uv python 3.10): MeloTTS
     - `/app/backend/.venv-cosy`(uv python 3.10) + `/app/vendor/CosyVoice`: CosyVoice3
   - 산출: `HEAXHub/var/sifs/voice_recorder.sif` (fat SIF, 멀티 GB — 온라인 빌드).
3. **서빙**: `apptainer instance start` → Caddy `/apps/voice_recorder/` → `127.0.0.1:$PORT`.
   런처가 `/data` 볼륨(=`var/app_data/voice_recorder/`)을 바인드하고 3계약 env 를 주입한다.
   - **GPU**: manifest `resources.gpu: true` + 호스트에 NVIDIA 가 있으면 런처가 `--nv` 를 붙여
     Chatterbox 가 GPU 로 돈다. GPU 없으면 CPU 폴백(torch 는 CUDA 미탐지 → CPU). MeloTTS·CosyVoice
     사이드카는 원래 CPU.
   - **torch 인덱스**: 훅 기본은 cu130(sm_120/RTX50). 다른 GPU 세대는
     `scripts/heaxhub-build.sh` 의 `VOICEREC_TORCH_INDEX` 기본값을 맞는 인덱스로 바꿔 빌드한다
     (apptainer %post 는 호스트 env 를 안 받으므로 값 주입이 아니라 스크립트 수정).

## 가중치는 SIF 가 아니라 /data (Drive)

SIF 에는 코드·의존성·사전(unidic)만 있고 **모델 가중치는 없다**. 가중치는 런타임 볼륨
`/data/models`(=`VOICEREC_MODELS_DIR`=`HF_HOME`)에서 오고, `HF_HUB_OFFLINE=1` 이라 네트워크를
안 탄다. HEAXHub 호스트에서 그 볼륨 실경로는 `HEAXHub/var/app_data/voice_recorder/models` 다.

```bash
# ── 온라인 박스: 가중치 준비 + Drive 업로드 ──
cd VoiceRecorder
scripts/fetch-models.sh        # Chatterbox 등 기본 가중치
scripts/setup-melo.sh          # MeloTTS 한국어 BERT 캐시
scripts/setup-cosy.sh          # CosyVoice3 0.5B 가중치(~2GB)
scripts/models-to-drive.sh     # var/models → Drive:HEAXHub/models/voice_recorder

# ── 폐쇄망/온라인 어느 쪽이든 HEAXHub 호스트: 가중치를 /data 볼륨 실경로로 복원 ──
VOICEREC_MODELS_DIR="$HOME/.../HEAXHub/var/app_data/voice_recorder/models" \
  scripts/models-from-drive.sh
```

`VOICEREC_MODELS_DIR` 를 HEAXHub app_data 로 향하게 하는 것이 핵심 — 그래야 SIF 의 `/data/models`
바인드가 가중치를 본다(기본값 `var/models` 로 받으면 SIF 볼륨과 어긋난다).

## SIF 자체를 폐쇄망으로

```bash
cd HEAXHub
deploy/apptainer/redeploy-app.sh voice_recorder --rebuild   # (온라인) 강제 리빌드
deploy/apptainer/dist-to-drive.sh                           # per-app SIF → Drive
# (폐쇄망) deploy/apptainer/dist-from-drive.sh — git·빌드 없이 SIF 수신
```

## 레거시(독립 서비스 경로 — 폐기)

`scripts/serve.sh` 는 예전 "자체 venv 독립 서비스" 잔재다. HEAX 연동/배포는 위 SIF 경로가 맡고,
`serve.sh` 는 로컬 개발 편의용으로만 남긴다(HWAXPortal services.yaml 등록도 제거됨).
