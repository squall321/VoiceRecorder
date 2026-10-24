# VoiceRecorder 체크리스트

## 0. 조사·결정
- [x] HEAXHub 권장 스택(`templates/fastapi-react`) 규약 파악 — 상대경로 3종 세트
- [x] HEAXHub 앱 등록 패턴 파악 — 별도 리포 + `integrations/<slug>/.portal/manifest.yaml` 포인터
- [x] TTS 엔진 라이선스 검증 (Chatterbox MIT / MeloTTS MIT / piper GPL 제외 / XTTS·F5 비상업 제외)
- [x] GPU 제약 확인 — RTX 5070 Ti = sm_120, `torch==2.6.0` 불가 → cu130 torch 직접 설치
- [x] rclone remote 확인 — `ApptainerImages:HEAXHub/dist`

## 1. 프로젝트 뼈대
- [x] 리포 초기화 + origin(`squall321/VoiceRecorder`) 등록
- [x] PLAN.md / checklist.md / context-notes.md
- [x] `.gitignore` (venv, dist, node_modules, var/, 모델 가중치)
- [x] `backend/pyproject.toml` (python 3.12)
- [x] `scripts/setup-backend.sh` — torch 먼저, chatterbox `--no-deps`

## 2. 백엔드 — 도메인
- [x] `app/script_parser.py` — 씬 분할 (번호/제목/타임코드/본문)
- [x] `app/textnorm.py` — 숫자 한글 읽기 + 사용자 치환 사전
- [x] `app/models.py` — pydantic 스키마
- [x] `app/store.py` — SQLite 스키마 + CRUD
- [x] `app/audio.py` — ffmpeg atempo / concat / mp3 / 무음
- [x] `app/timeline.py` — 씬 길이 → 타임라인·SRT

## 3. 백엔드 — TTS
- [x] `app/tts/base.py` — 엔진 인터페이스
- [x] `app/tts/chatterbox_engine.py` — Chatterbox Multilingual (GPU/CPU, OOM 폴백)
- [x] `app/tts/melo_engine.py` — 선택적 사이드카 venv subprocess
- [x] `app/tts/registry.py` — 가용 엔진 탐지
- [x] `scripts/melo_worker.py` — 사이드카 venv에서 실행되는 CLI

## 4. 백엔드 — API
- [x] `app/jobs.py` — 단일 워커 스레드 + 진행률
- [x] `app/main.py` — `/api/*` 라우트 + StaticFiles 마운트 (순서 준수)
- [x] 프로젝트/씬 CRUD, 합성, 익스포트, 보이스 업로드, 발음 사전

## 5. 프론트엔드
- [x] Vite + React 18 + TS 뼈대 (`base: "./"`)
- [x] `src/api.ts` — 상대경로 fetch 클라이언트
- [x] 스크립트 붙여넣기 → 분할 미리보기 화면
- [x] 씬 리스트 (개별 재생성·미리듣기·순서·삭제)
- [x] 씬별 설정 패널 (화자/속도/간격/고급)
- [x] 목표 타임코드 대비 실제 길이 델타 표시 + 자동 속도 계산
- [x] 익스포트 (병합 mp3 + SRT 다운로드)
- [x] 발음 사전 편집
- [x] 보이스 프로필 업로드/관리

## 6. 배포 연동
- [x] `.portal/manifest.yaml` (`build.stack: fastapi_react`, health `/api/health`)
- [x] HEAXHub `integrations/voice-recorder/.portal/manifest.yaml` 포인터 배치
- [x] `scripts/fetch-models.sh` / `models-to-drive.sh` / `models-from-drive.sh`
- [x] README.md

## 7. 검증
- [x] `pytest` 87개 통과 — 파서 / 정규화 / 타임라인 / SRT / API 통합(ffmpeg 실제 실행)
- [x] Chatterbox 한국어 실합성 (모델 3GB 다운로드 → 파싱→정규화→합성 7.60s)
- [x] 사용자 실제 10씬 스크립트 전체 생성 → 병합 mp3 93.05s + SRT 10개 자막
- [x] 서브경로 통합 확인 (`--root-path /apps/voice_recorder` 에서 SPA·자산·API 전부 200)
- [x] `pnpm build` 성공 (타입 오류 0)
- [x] git commit 6개 + push (`squall321/VoiceRecorder` main)

## 8. 음성 씌우기 — 영상 더빙 (2026-10-24, PLAN §11)
- [x] SIF 빌드 훅에 ffmpeg 추가 (현재 포털 SIF 에 ffmpeg 없음)
- [x] textnorm — 영문 약어 철자, 숫자 뒤 단위, `·` 쉼표, 개·대·쌍·종·건 1~9 고유어
- [x] script_parser — 줄머리 타임코드·초 단위·시작만 있는 형식, 마크다운 제목 구간, 표(마크다운·TSV·칸 풀린 붙여넣기)
- [x] 씬별 읽는 법 — 파서 추출(열·`읽는 법:` 줄) + scenes.reading 컬럼 + 합성 반영 + API
- [x] video.py — ffprobe 정보, 먹싱(복사 → 실패 시 H.264), 원본 소리 섞기
- [x] 타임코드 고정 배치 + 배치 wav/mp3 + 실측 SRT + 경고 리포트
- [x] 작업 큐 dub (미생성 씬 합성 → 배치 → 먹싱) + 엔드포인트(영상 업·다운·삭제, 더빙, 결과 3종)
- [x] 프런트 — 영상 패널(업로드 진행률·미리보기·옵션·결과·경고), 씬 읽는 법 입력, 영문 남음 경고
- [x] pytest 149개 통과 + `pnpm build`
- [x] 로컬 실검증 — 실제 MeloTTS 1.2배로 4문장 합성+더빙 10초, 발화 시작이 배치 시각 +0.08초 이내, 브라우저 업로드→더빙→재생 확인
- [x] 덤으로 고친 기존 버그 — 내보내기 전 SRT 다운로드가 한글 제목에서 500
- [x] 포털 반영 — push → 스캐너 SIF 재빌드(ffmpeg 7.1) → `redeploy-app.sh voice-recorder` 전환, 포털 안 MeloTTS 더빙 실검증
- [x] 포털 모델 폴더에 MeloTTS 캐시 반입 + `fetch-models.sh` 에 부속 토크나이저 추가 (폐쇄망 대비)
- [x] 포털 발음 사전 기본 4개 (HWAX·응력·대책·전위치)
- [ ] 포털에 Chatterbox(3GB)·CosyVoice(9GB) 가중치 반입 — 지금은 그 엔진을 고르면 오프라인 오류 (사용자 확인 후)

## 남은 일 (다음 세션)
- [ ] **GPU 실합성 검증** — 검증 당시 GPU 를 vLLM(13GB)이 점유해 CPU 로만 확인했다.
      VRAM 이 3GB 이상 나면 `backend/.venv/bin/python scripts/smoke_chatterbox.py` 로 재확인.
      CPU RTF 는 3.4 (10씬 4분), GPU 로는 훨씬 빨라질 것.
- [ ] **MeloTTS 사이드카 실제 설치·검증** — `scripts/setup-melo.sh` 는 작성만 했고
      실행해 보지 않았다. Chatterbox CPU 폴백이 있어 없어도 앱은 돈다.
- [ ] **HEAXHub 리포 커밋** — `integrations/voice-recorder/.portal/manifest.yaml` 을
      배치만 하고 커밋하지 않았다 (별도 리포라 사용자 확인 후).
- [ ] `scripts/models-to-drive.sh` 실제 업로드 (3GB, 온라인 호스트에서)
