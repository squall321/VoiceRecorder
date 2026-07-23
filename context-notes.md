# Context Notes — VoiceRecorder

작업 중 내린 결정과 그 이유. 다음 세션이 재추론하지 않도록 계속 덧붙인다.

---

## 2026-07-23 — 초기 설계

### 왜 Chatterbox Multilingual을 주엔진으로 골랐나

요구는 "한국어 중심 + 라이선스 문제 없는 것"이었다. 실제로 확인한 사실만 적는다.

- `chatterbox-tts` 0.1.7 (PyPI): `license: MIT License, Copyright (c) 2025 Resemble AI`
- `ResembleAI/chatterbox` (HF API `cardData.license`): `mit`,
  `language`에 `ko` 포함 (총 23개 언어). 가중치 `t3_mtl23ls_v3.safetensors`.

즉 **코드도 가중치도 MIT**라 사내 상업 이용에 걸림이 없다. 한국어를 지원하면서
가중치까지 permissive인 조합은 조사 범위에서 이것과 MeloTTS 둘뿐이었다.

**탈락시킨 것들과 이유** (전부 직접 확인):

- `piper-tts` 1.5.0 → PyPI 메타데이터가 **GPL-3.0-or-later**. espeak-ng 바인딩 때문.
  GPL 전파 위험이 있어 사내 배포물에 넣지 않는다. (GitHub 리드미의 MIT 표기와 다르므로
  주의 — 실제 배포 패키지 기준으로 판단했다.)
- XTTS-v2 → 가중치가 Coqui Public Model License, **비상업 전용**.
- F5-TTS → 코드는 MIT지만 base 체크포인트가 Emilia 데이터셋 기반 **CC-BY-NC-4.0**.
- Kokoro-82M → Apache-2.0로 깨끗하지만 **한국어 미지원**. 영어 전용 요구가 생기면 그때 추가.

### 왜 MeloTTS는 같은 venv에 못 넣나

`melotts` 0.1.1의 requires_dist를 직접 읽어보니 `torch<2.0`, `transformers==4.27.4`,
`librosa==0.9.1`을 핀한다. Chatterbox는 `torch>=2.6`, `transformers==5.2.0`을 요구한다.
**해결 불가능한 충돌**이다.

→ MeloTTS는 별도 venv(`backend/.venv-melo`)에 설치하고 `scripts/melo_worker.py`를
subprocess로 호출하는 사이드카로 둔다. 없으면 그냥 `available: false`.
억지로 한 venv에 밀어넣다가 Chatterbox까지 깨뜨리는 것보다 낫다.

### torch를 왜 따로 설치하나 (가장 중요한 함정)

배포 GPU가 **RTX 5070 Ti = compute cap 12.0 (sm_120, Blackwell)** 이다.
`chatterbox-tts`는 `torch==2.6.0`을 핀하는데, 2.6.0 휠에는 sm_120 커널이 없다.
그대로 설치하면 import는 되고 `cuda.is_available()`도 True인데 **첫 커널 실행에서**
`no kernel image is available for execution on the device`로 죽는다 — 진단이 오래 걸리는
종류의 실패다.

확인한 사실: 시스템 python3.12의 `torch 2.12.0+cu130`은
`get_arch_list()`에 `sm_120`이 들어 있고 `cuda.is_available()`이 True다.

→ 설치 순서를 **torch(cu130) 먼저 → `chatterbox-tts --no-deps` → 나머지 의존성**으로
고정한다. `scripts/setup-backend.sh`가 이 순서를 강제하고, 순서를 어기면 pip가 torch를
2.6.0으로 다운그레이드해 버린다.

`gradio`는 chatterbox의 선언 의존성이지만 데모 UI용일 뿐이라 설치하지 않는다.

### 속도 조절을 왜 엔진 파라미터가 아니라 ffmpeg로 하나

Chatterbox에는 발화 속도 파라미터가 없다 (`exaggeration`, `cfg_weight`, `temperature`만
있다). 속도를 모델에서 못 건드리므로 합성 후 `ffmpeg -filter:a atempo=<x>`로 처리한다.
장점: 엔진이 바뀌어도 속도 조절 코드가 그대로 돈다. `atempo`는 한 번에 0.5~2.0만
받으므로 범위를 벗어나면 체이닝한다.

### 왜 SQLite + 파일시스템인가 (ORM 없이)

엔티티가 프로젝트/씬/보이스/잡 4개뿐이고 관계도 단순하다. SQLAlchemy를 얹으면 의존성만
늘고 얻는 게 없다. stdlib `sqlite3`로 충분하다.

DB와 오디오는 `VOICEREC_DATA_DIR`(기본 `/data`) 아래에 둔다. HEAXHub가 SIF에
`var/app_data/<slug>/`를 `/data`로 바인드하고, **SIF rootfs는 read-only**라 여기 외에는
쓸 수 없다. MaterialTwinWeb이 `MATERIALTWIN_DATA_DIR: /data`로 같은 패턴을 쓴다.

### 왜 WebSocket이 아니라 폴링인가

합성 진행률을 알려야 하는데, HEAXHub는 Caddy 리버스 프록시 뒤 서브경로에 앱을 마운트한다.
WebSocket은 프록시 설정에 의존적이라 깨지기 쉽다. 합성은 수십 초~수 분 단위 작업이라
1초 폴링으로 충분하다. 의존성도 0이다.

### 작업 큐를 왜 스레드 1개로 두나

GPU가 1장이다. 동시에 두 씬을 합성하면 VRAM만 두 배로 먹고 전체 시간은 안 줄어든다.
Celery/Redis를 붙일 이유가 없다 — 단일 워커 스레드 + SQLite job 테이블로 끝낸다.

### 입력 파서를 왜 2단으로 만드나

사용자가 준 실제 스크립트 형식이 `01 오프닝 (0:00–0:08) "본문"` 이다. 이걸 1급으로 파싱하되,
타임코드/번호 없이 문단만 붙여넣는 경우도 많을 것이므로 **빈 줄 기준 문단 분할**로 폴백한다.
타임코드가 있으면 목표 길이 대비 실제 합성 길이 델타를 보여줄 수 있어 (F7) 영상 편집에
바로 쓸 수 있다 — 이게 이 앱의 실제 값어치다.

구분자 주의: 사용자 스크립트는 **en dash(`–`, U+2013)** 를 쓴다. 하이픈만 처리하면 파싱이
전부 실패한다. `-` `–` `—` `~` 를 모두 받는다.

### 대용량 아티팩트는 Drive 경유

운영 서버 cae00은 사내 TLS 인터셉트 망이라 PyPI/HuggingFace/DockerHub에 못 닿는다
(HEAXHub `AGENTS.md`에 명시). Chatterbox 가중치가 ~2.5GB라 git에 넣을 수 없다.

→ HEAXHub가 이미 쓰는 rclone remote(`HEAX_DRIVE_REMOTE=ApptainerImages:HEAXHub/dist`)를
그대로 재사용하고 형제 폴더 `models/voice_recorder/`에 올린다.
`appdata-to-drive.sh`가 `dist` 형제로 `app-data/`를 쓰는 것과 같은 방식이다.
런타임은 `HF_HUB_OFFLINE=1`로 네트워크를 아예 안 타게 막는다.
