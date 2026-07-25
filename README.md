# VoiceRecorder

영상 내레이션 스크립트를 붙여넣으면 **씬 단위로 나눠 한국어 음성을 만들고**, 씬별로 다듬은 뒤
**병합 mp3 + SRT 자막**으로 내보내는 웹 앱. HEAXHub 서브 플랫폼(`fastapi_react` 스택)으로 등록된다.

```
스크립트 붙여넣기 → 씬 자동 분할 → 씬별 음성 생성/수정 → mp3 + SRT 다운로드
```

## 무엇이 다른가

- **씬 하나만 다시 만든다.** 문장 하나 고쳤다고 20분짜리 내레이션을 통째로 재생성하지 않는다.
- **속도 조절은 모델을 다시 돌리지 않는다.** 합성 원본을 남겨두고 ffmpeg `atempo` 로만 다시 렌더링한다.
- **목표 타임코드와 실제 길이를 비교해 준다.** 스크립트에 `(0:00–0:08)` 이 있으면 실제 합성 길이와의
  차이를 씬마다 표시하고, "목표에 맞추기" 버튼이 필요한 속도를 계산해 넣는다.
- **라이선스가 깨끗하다.** 코드도 가중치도 MIT 인 모델만 쓴다 (§ TTS 엔진).

## 입력 형식

사용자가 실제로 쓰는 형식을 그대로 인식한다.

```
01 오프닝 (0:00–0:08) "질문 하나가 의사결정문이 되기까지 — HWAX 협업진단 플랫폼."

02 문제 배정 (0:08–0:19) "신제품 초기안의 최고 온도는 83.4도. 허용 기준을 넘겼습니다."
```

- `번호` `제목` `(시작–끝)` `"본문"` → 네 필드로 분해. 구분자는 `–` `-` `—` `~` 모두 허용한다.
- 번호·타임코드가 없으면 **빈 줄 기준 문단 분할**로 폴백한다.
- 숫자는 한국어로 읽어 준다 — `83.4도` → `팔십삼 점 사 도`, `6명` → `여섯 명`, `2라운드` → `이라운드`.
- 모델이 잘못 읽는 약어는 **발음 사전**에 등록한다 — `HWAX` → `에이치왁스`.

## TTS 엔진 — 상업 이용 가능한 것만

조사 시점 2026-07-23, **배포 패키지 기준**으로 확인했다.

| 엔진 | 코드 | 가중치 | 한국어 | 채택 |
|---|---|---|---|---|
| **Chatterbox Multilingual** (Resemble AI) | MIT | **MIT** | ✅ 23개 언어 중 하나 | **주엔진** |
| **MeloTTS** (MyShell) | MIT | **MIT** | ✅ | 선택적 CPU 사이드카 |
| Kokoro-82M | Apache-2.0 | Apache-2.0 | ❌ | 보류 (영어 전용 요구 시) |
| piper-tts 1.5.0 | **GPL-3.0-or-later** | — | 제한적 | ✗ 제외 |
| XTTS-v2 (Coqui) | MPL-2.0 | **CPML (비상업)** | ✅ | ✗ 제외 |
| F5-TTS | MIT | **CC-BY-NC-4.0** | ✅ | ✗ 제외 |

> piper 는 GitHub 리드미에 MIT 로 적혀 있지만 PyPI 배포 패키지(`piper-tts` 1.5.0)의 메타데이터는
> GPL-3.0-or-later 다 (espeak-ng 바인딩). 실제 배포물 기준으로 판단해 제외했다.

Chatterbox 는 **참조 음성 3~10초**를 올리면 그 목소리로 내레이션을 만든다(voice cloning).

## 설치

Python **3.12**, Node 20, ffmpeg 가 필요하다.

```bash
scripts/setup-backend.sh        # 백엔드 venv (설치 순서가 중요 — 아래 참고)
scripts/fetch-models.sh         # Chatterbox 가중치 ~3GB 를 var/models 로
cd frontend && pnpm install && pnpm build
```

### 설치 순서가 중요한 이유

`chatterbox-tts` 는 `torch==2.6.0` 을 핀하는데, 그 휠에는 **sm_120(Blackwell, RTX 50 시리즈)**
커널이 없다. 그대로 설치하면 import 도 되고 `cuda.is_available()` 도 `True` 인데 **첫 커널 실행에서**
`no kernel image is available for execution on the device` 로 죽는다.

`setup-backend.sh` 는 그래서 **torch(cu130) 를 먼저 깔고 `chatterbox-tts` 를 `--no-deps` 로**
설치한다. 순서를 바꾸면 pip 가 torch 를 2.6.0 으로 되돌려 버린다.

앱은 시작할 때 GPU 아키텍처가 torch 빌드의 `get_arch_list()` 에 있는지 검사하고, 없으면
`/api/engines` 에 이유를 그대로 노출한다. VRAM 이 모자라면 **자동으로 CPU 로 폴백**한다.

## 실행

### 로컬 개발

```bash
# 백엔드 (터미널 1)
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

# 프런트 (터미널 2) — vite dev 가 /api 를 8000 으로 프록시한다
cd frontend && pnpm dev        # http://localhost:5273
```

### 서브경로 통합 확인 (HEAXHub 와 같은 조건)

```bash
cd frontend && pnpm build
cd ../backend
PORT=8000 ROOT_PATH=/apps/voice_recorder \
  .venv/bin/uvicorn app.main:app --port $PORT --root-path $ROOT_PATH
# http://localhost:8000/ 에서 SPA + /api/* 가 함께 동작
```

## HEAXHub 연합 등록 (재부팅 자동 기동)

VoiceRecorder 는 torch(cu130)+Chatterbox 메인 venv 와 CosyVoice 사이드카(.venv-cosy)를 쓰는
무거운 앱이라 HEAXHub 표준 SIF 빌드에 안 담긴다. 그래서 heax-hub 안의 앱이 아니라
**자체 venv 로 도는 독립 서비스**로 등록한다 (MXWhitePaper 방식).

```yaml
# HWAXPortal/infra/services.yaml
- name: voice-recorder
  host: local
  discover: VoiceRecorder
  start: ./scripts/serve.sh          # 오프라인 env 세팅 + uvicorn :8177
  health: http://localhost:8177/api/health
  tier: 10
```

재부팅하면 `hwax-stack.service`(linger)가 `services.py up` 으로 다른 서비스들과 함께 자동
기동한다. 수동 기동/재기동은 `HWAXPortal` 에서
`backend/.venv/bin/python infra/scripts/services.py up voice-recorder`.

## 폐쇄망(cae00) 배포 — Drive 파이프라인

운영 서버는 HuggingFace·PyPI·DockerHub·modelscope 에 못 닿는다. 앱이 의존하는 큰 데이터는
전부 git 밖(`.gitignore`)이라, HEAXHub 가 이미 쓰는 **rclone Google Drive remote 를 재사용**해
실어 나른다 (`HEAX_DRIVE_REMOTE`, `models/`·`app-data/` 하위 폴더).

| 데이터 | 크기 | 온라인 → Drive | Drive → 폐쇄망 |
|---|---|---|---|
| 모델 가중치 (Chatterbox·CosyVoice3·MeloTTS) + **wetext FST** | ~13GB | `models-to-drive.sh` | `models-from-drive.sh` |
| 운영 데이터 (프로젝트 DB + 생성 오디오) | 가변 | `data-to-drive.sh` | `data-from-drive.sh` |
| 코드 | — | `git push` | `git clone` |
| venv (메인+사이드카) | ~15GB | — (플랫폼 종속) | `setup-backend.sh`+`setup-cosy.sh` (사내 pip 미러) |

```bash
# ── 온라인 스테이징 ──
scripts/fetch-models.sh      # 세 엔진 가중치 + wetext 를 var/models 로 원스톱 조달
scripts/models-to-drive.sh   # var/models (모델+wetext) → Drive
scripts/data-to-drive.sh     # var/data (DB 는 sqlite .backup 원자 스냅샷 + tar) → Drive

# ── 폐쇄망 서버 ──
scripts/deploy-from-drive.sh # 모델+wetext+운영데이터 원스톱 복원 (내부적으로 models/data-from-drive)
scripts/setup-backend.sh && scripts/setup-cosy.sh   # venv (사내 pip 미러)
```

`serve.sh` 가 `HF_HUB_OFFLINE=1`, `HF_HOME=var/models`, `MODELSCOPE_CACHE=var/models/modelscope`
를 세팅해 런타임이 네트워크를 아예 타지 않는다. wetext FST 를 `var/models` 안에 두는 이유가
이것 — 모델 Drive 전송에 함께 실려 폐쇄망에서 modelscope.cn 재접속이 필요 없다.

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/health` | 헬스체크 |
| GET | `/api/engines` | 엔진 목록·가용성·디바이스·라이선스 |
| POST | `/api/scripts/parse` | 원문 → 씬 미리보기 (저장 안 함) |
| POST | `/api/projects` | 프로젝트 생성 (스크립트 파싱 포함) |
| GET/PATCH/DELETE | `/api/projects/{id}` | 프로젝트 조회·설정·삭제 |
| PUT | `/api/projects/{id}/script` | 스크립트 교체 (씬 재분할) |
| POST/PATCH/DELETE | `/api/projects/{id}/scenes[/{sid}]` | 씬 추가·수정·삭제 |
| POST | `/api/projects/{id}/scenes/reorder` | 순서 변경 |
| GET | `/api/projects/{id}/scenes/{sid}/audio` | 씬 미리듣기 (wav) |
| POST | `/api/projects/{id}/synthesize` | 합성 작업 제출 (기본: 변경된 씬만) |
| POST | `/api/projects/{id}/export` | 병합 mp3 + SRT 생성 |
| GET | `/api/jobs/{id}` | 작업 진행률 |
| GET | `/api/projects/{id}/export/audio` \| `/srt` | 결과 다운로드 |
| GET/POST/DELETE | `/api/voices[/{id}]` | 참조 음성 관리 |
| GET/POST/PUT/DELETE | `/api/dictionary[/{id}]` | 발음 사전 |

## 테스트

```bash
cd backend && .venv/bin/python -m pytest
```

API 테스트는 TTS 엔진만 스텁으로 갈아끼우고 **ffmpeg 병합·SRT 생성은 실제로 돌린다** — 병합 mp3 의
길이가 계산된 타임라인과 일치하는지까지 검증한다.

GPU 실합성 스모크:

```bash
backend/.venv/bin/python scripts/smoke_chatterbox.py
```

## 설계 배경

`PLAN.md` 와 `context-notes.md` 에 왜 이렇게 만들었는지(엔진 선택 근거, torch 함정, MeloTTS 를
사이드카로 뺀 이유, WebSocket 대신 폴링을 쓴 이유)를 남겨 두었다.

## 라이선스

내부 사용. 번들된 TTS 모델은 MIT (Resemble AI Chatterbox, MyShell MeloTTS).
