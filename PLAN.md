# VoiceRecorder — 내레이션 스크립트 → 음성(mp3) 생성 플랫폼

HEAXHub 서브 웹 플랫폼 (`fastapi_react` 스택). 영상 내레이션 스크립트를 붙여넣으면
씬 단위로 쪼개어 자연스러운 한국어 음성을 만들고, 씬별로 다듬은 뒤 병합 mp3 + SRT 자막을
내려받는다.

## 1. 문제

영상 내레이션 더빙은 성우 섭외·녹음·재녹음 루프가 길다. 문장 하나만 고쳐도 전체 재녹음이
필요하고, 타임코드에 맞추려면 수차례 왕복한다. 사내에서 쓸 수 있는 TTS는 라이선스가
비상업(XTTS-v2 CPML, F5-TTS CC-BY-NC)이거나 GPL(piper-tts 1.5.0)이라 그대로 쓰기 어렵다.

## 2. 해결

- **상업 이용 가능 라이선스만** 사용한다 (아래 §5).
- 스크립트를 **씬 단위**로 자동 분할하고, **씬 하나만 재생성**할 수 있게 한다.
- 스크립트에 적힌 **목표 타임코드와 실제 음성 길이를 비교**해 과부족을 즉시 보여준다.
- 결과물은 **병합 mp3 + SRT 자막**으로 한 번에 내보낸다.

## 3. 입력 형식

사용자가 실제로 쓰는 형식을 1급으로 지원한다.

```
01 오프닝 (0:00–0:08) "질문 하나가 의사결정문이 되기까지 — HWAX 협업진단 플랫폼."

02 문제 배정 (0:08–0:19) "신제품 초기안의 최고 온도는 83.4도. 허용 기준을 넘겼습니다."
```

- `번호` `제목` `(시작–끝)` `"본문"` → 4개 필드로 파싱. 구분자는 `–`(en dash) `-` `~` 모두 허용.
- 타임코드·번호·제목이 없으면 **빈 줄 기준 문단 분할**로 폴백한다.
- 본문 따옴표는 `"` `"` `'` `'` `"` 모두 벗겨낸다.

## 4. 기능 범위

| # | 기능 | 비고 |
|---|---|---|
| F1 | 스크립트 붙여넣기 → 씬 자동 분할 미리보기 | 저장 전 확인 |
| F2 | 씬 단위 개별 합성·재합성·미리듣기 | 수정된 씬만 재생성 |
| F3 | 씬 순서 변경 / 추가 / 삭제 | |
| F4 | 씬별 화자·속도·앞뒤 무음 간격 조절 | 속도는 ffmpeg `atempo` |
| F5 | 전체 병합 mp3 다운로드 | ffmpeg concat + 192k mp3 |
| F6 | SRT 자막 동시 출력 | 실제 합성 길이 기반 타임라인 |
| F7 | 목표 타임코드 대비 실제 길이 차이 표시 | 스크립트에 타임코드가 있을 때 |
| F8 | 발음 치환 사전 (숫자 한글 읽기 + 사용자 규칙) | `83.4도` → `팔십삼 점 사 도` |
| F9 | 참조 음성 업로드로 화자 지정 (voice cloning) | Chatterbox `audio_prompt` |

## 5. TTS 엔진 — 라이선스 검증 결과

조사 시점 2026-07-23. **상업 이용 가능한 것만 채택**한다.

| 엔진 | 코드 라이선스 | 가중치 라이선스 | 한국어 | 판정 |
|---|---|---|---|---|
| **Chatterbox Multilingual** (Resemble AI) | MIT (`chatterbox-tts` 0.1.7) | **MIT** (`ResembleAI/chatterbox`) | ✅ `ko` 포함 23개 언어 | **채택 — 주엔진** |
| **MeloTTS-Korean** (MyShell) | MIT | **MIT** (`myshell-ai/MeloTTS-Korean`) | ✅ | **채택 — 선택적 CPU 사이드카** |
| Kokoro-82M | Apache-2.0 | Apache-2.0 | ❌ 미지원 | 보류 (영어 전용 요구 생기면) |
| piper-tts 1.5.0 | **GPL-3.0-or-later** | — | 제한적 | ✗ 제외 (GPL 전파) |
| XTTS-v2 (Coqui) | MPL-2.0 | **CPML — 비상업** | ✅ | ✗ 제외 |
| F5-TTS | MIT | **CC-BY-NC-4.0** (Emilia) | ✅ | ✗ 제외 |

### 왜 MeloTTS는 "사이드카"인가

MeloTTS는 `torch<2.0`, `transformers==4.27.4`, `librosa==0.9.1`을 핀한다. Chatterbox는
`transformers==5.2.0`, `torch>=2.6`을 요구한다. **한 venv에 공존 불가**다. 따라서
MeloTTS는 별도 venv(`backend/.venv-melo`)에 설치하고 subprocess로 호출하는 선택적
엔진으로 둔다. 설치돼 있지 않으면 `/api/engines`가 `available: false`로 보고하고 UI에서
선택지가 비활성화된다.

CPU만 있는 서버에서는 MeloTTS 사이드카가 없어도 **Chatterbox가 CPU로 폴백**해 동작한다
(느리지만 결과는 동일). 즉 CPU 폴백은 2중이다.

## 6. GPU 제약 (중요)

배포 대상 GPU는 **RTX 5070 Ti = compute capability 12.0 (sm_120, Blackwell)**.
`chatterbox-tts`가 핀한 `torch==2.6.0`은 sm_120 커널을 담고 있지 않아 그대로 설치하면
런타임에 `no kernel image is available for execution on the device`로 죽는다.

→ **`chatterbox-tts`는 `--no-deps`로 설치하고 torch/torchaudio는 cu130 인덱스에서
직접 설치**한다 (`torch 2.12.0+cu130`, arch list에 `sm_120` 포함 확인됨).
`scripts/setup-backend.sh`가 이 순서를 강제한다.

## 7. 아키텍처

HEAXHub `fastapi_react` 스택 규약을 그대로 따른다 — 서브경로(`/apps/voice_recorder/`)에서
자산·API가 깨지지 않도록:

- `frontend/vite.config.ts`: `base: "./"` → 번들 자산 URL 전부 상대경로
- `frontend/src/api.ts`: `fetch("api/...")` — 선행 슬래시 금지
- `backend/app/main.py`: `/api/*` 라우트를 **먼저** 선언하고 그 뒤 `frontend/dist`를 `/`에 마운트
- 런처가 `$PORT` / `$ROOT_PATH` 주입 → `uvicorn --root-path $ROOT_PATH`

```
브라우저 ──▶ Caddy(/apps/voice_recorder/) ──▶ uvicorn ──┬─ /api/*      FastAPI
                                                        └─ /*          React SPA (dist)
                                                                │
                                          ThreadPool 합성 워커 ──┴─▶ Chatterbox(GPU/CPU)
                                                                     └─▶ ffmpeg (atempo/concat/mp3)
```

- **저장소**: SQLite (stdlib `sqlite3`, ORM 없음) + 파일시스템. `VOICEREC_DATA_DIR`(기본 `/data`,
  HEAXHub가 `var/app_data/voice_recorder/`를 바인드) 아래에 DB·오디오·모델 캐시를 둔다.
  SIF rootfs는 read-only라 여기 외에는 쓸 수 없다.
- **작업 큐**: 단일 워커 스레드 + SQLite job 테이블. GPU 1장이라 동시 합성은 의미가 없다.
  진행률은 폴링(`GET /api/jobs/{id}`)으로 노출한다 — 포털 리버스 프록시 뒤에서 WebSocket보다 안전하다.

## 8. 대용량 아티팩트는 Drive 경유

운영 서버(cae00)는 HuggingFace·PyPI에 못 닿는다. 모델 가중치(Chatterbox ~2.5GB)는
**rclone Google Drive**로 실어 보낸다 — HEAXHub `dist-to-drive.sh` / `appdata-to-drive.sh`와
같은 remote(`HEAX_DRIVE_REMOTE`)를 쓰고 `models/` 하위 폴더에 둔다.

```
scripts/fetch-models.sh        # (온라인) HF → var/models/ 로 내려받기
scripts/models-to-drive.sh     # (온라인) var/models/ → Drive:.../models/voice_recorder/
scripts/models-from-drive.sh   # (폐쇄망) Drive → var/models/  ※ 앱은 이 경로만 본다
```

`HF_HUB_OFFLINE=1` + `HF_HOME=$VOICEREC_DATA_DIR/models` 로 런타임이 네트워크를 아예
타지 않게 한다.

## 9. 성공 기준

1. `01 오프닝 (0:00–0:08) "..."` 형식 10개 씬 스크립트를 붙여넣으면 씬 10개로 정확히 분할된다.
2. 씬 하나의 텍스트를 고치고 재합성하면 **그 씬의 오디오만** 갱신된다.
3. 병합 mp3를 받아 재생하면 씬 사이 무음 간격이 설정값대로 들어가 있다.
4. SRT의 각 자막 시작·끝 시각이 병합 mp3의 실제 발화 구간과 일치한다.
5. `pytest`가 파서·타임라인·SRT·정규화에 대해 전부 통과한다.
6. `pnpm build` + `uvicorn --root-path /apps/voice_recorder` 로 서브경로에서 자산·API가 200을 준다.

## 10. 범위 밖 (하지 않는 것)

- 다국어 UI, 사용자 계정/권한 (HEAXHub 포털이 인증을 담당)
- 배경음악 믹싱, 영상 합성
- 실시간 스트리밍 합성 (배치 생성으로 충분)
