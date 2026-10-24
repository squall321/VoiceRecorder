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

---

## 2026-10-24 — 음성 씌우기(영상 더빙)

### 왜 VoiceRecorder 에 두나

사용자가 선택했다. 포털에서 음성 도구는 이미 VoiceRecorder 이고 파서·발음 사전·타임코드
비교가 다 여기 있다. WebDesignAgents 영상과의 연결(녹음 길이로 씬 dur 재조정)은 다음 단계다.

### 포털 SIF 에 ffmpeg 가 없었다

`apptainer exec var/sifs/voice-recorder.sif which ffmpeg` 가 실패한다. 베이스가 python slim 이고
빌드 훅이 git·build-essential 만 깔았다. 속도 조절(atempo)·mp3 내보내기·보이스 업로드가 포털에서는
전부 실패하는 상태였다. 빌드 훅 apt 줄에 ffmpeg 를 넣는다.

### 배치는 fit-timecode 가 아니라 "타임코드 고정"

기존 `fit-timecode` 는 넘치는 씬의 속도를 올리고 맞는 씬은 1.0 배로 되돌린다. 사용자는 1.2 배로
고정해 듣고 승인해 왔고, 넘치면 속도 대신 원고를 고친다. 그래서 더빙은 속도를 건드리지 않고
문장을 시작 시각에 놓는다. 겹치면 0.2초 숨을 두고 뒤로 민다(이전 수작업은 0초였으나 붙어 들린다).
`fit-timecode` 를 먼저 돌렸다면 겹침이 줄 뿐 결과는 같다 — 두 기능이 충돌하지 않는다.

### MeloTTS 속도는 계속 atempo

수작업 녹음은 MeloTTS 자체 `speed` 인자를 썼다. 앱은 엔진과 무관하게 ffmpeg atempo 로 속도를
입히고, 그래서 속도만 바꿀 땐 모델을 다시 돌리지 않는다. 엔진 속도로 바꾸면 이 구조(원본 wav 재사용,
apply-speed, fit-timecode)가 전부 흔들린다. 1.2 배에서는 atempo 음질 차이가 작아 그대로 둔다.
듣고 차이가 크면 그때 엔진 속도를 옵션으로 붙인다.

### 읽는 법은 "전체 덮어쓰기"가 아니라 "원문 → 읽기" 쌍

합성 텍스트를 통째로 따로 저장하면 원문(자막)을 고칠 때 합성 텍스트가 옛 내용으로 남는다.
쌍으로 두면 원문을 고쳐도 계속 적용된다. 사용자 대본의 「읽는 법」 칸도 이미
`AI → 에이아이 · 6만 → 육만` 처럼 쌍으로 적혀 온다. 적용 순서는 씬 읽는 법 → 전역 사전 → 규칙.

### 개·대·쌍·종·건은 1~9 만 고유어

사용자 대본의 읽는 법이 `14개 → 십사 개`, `76개 → 칠십육 개` 로 지정한다. 기존 규칙은 1~99 를
고유어로 읽어 `스무 개`·`열네 개`가 됐다. 명·시·살·번 등은 그대로 1~99 고유어다(열두 시, 스무 살).

### 영문 대문자 약어를 앱이 철자로 바꾼다

MeloTTS 의 `normalize_english` 는 한 글자와 몇 단어(AI·PC·CEO…)만 사전에 있고 나머지 영문은
그대로 소문자로 g2p 에 넘겨 사실상 소리가 빠진다. 그래서 `[A-Z][A-Z0-9]*` 토큰을 글자 이름으로
바꾼다(PLM → 피엘엠, S26 → 에스이십육). 숫자로 시작하는 토큰(3D)과 소문자가 섞인 단어(Screw)는
규칙으로 못 읽으므로 그대로 두고, 화면에 "영문이 남았다" 경고를 띄워 읽는 법을 적게 한다.
한국어(language=ko)에서만 적용한다.

### 업로드는 multipart 가 아니라 원본 바디 PUT

Starlette multipart 는 파일을 먼저 임시 파일로 스풀한다. SIF rootfs 는 read-only 이고 영상은
수백 MB 다. 요청 바디를 그대로 `/data/projects/<id>/video/` 로 흘려 쓴다. 진행률은 XHR 업로드
이벤트로 보인다. Caddy 라우트에 본문 크기 제한은 없다(proxy_manager 확인).

### 먹싱

영상은 `-c:v copy`(재인코딩 없음)로 붙이고, mp4 에 못 넣는 코덱이면 libx264 로 다시 인코딩한다.
내레이션은 영상 길이까지 무음으로 채워 AAC 로 넣는다. 내레이션이 영상보다 길면 경고만 하고
그대로 둔다(플레이어는 마지막 화면을 유지한다). 원본 소리는 볼륨 0 이면 버리고, 0 보다 크면
`amix normalize=0` 으로 섞는다(내레이션 크기가 원본 소리 유무로 바뀌지 않게).

### 테스트 데이터는 합성 문장만

GitHub 리포가 공개다(`api.github.com/repos/squall321/VoiceRecorder` 익명 200). 사용자가 붙여 준
실제 대본은 사내 과제 내용이라 형식만 흉내 낸 합성 예제로 테스트한다. 실제 대본 18개는 리포 밖
(세션 스크래치)에서만 파서에 돌려 확인했다 — 18개 모두 씬·시각이 맞게 나뉘었다.

### 파서 형식 판별 순서와 그 이유

표(마크다운·탭·칸 풀린 붙여넣기) → 줄머리 시각/시각 있는 마크다운 제목 → 기존 블록 파서.
기존 `01 제목 (0:00–0:08) "본문"`·`Hook [0:00–0:07] — 본문` 은 줄머리 시각이 아니라서 큐 형식으로
판정되지 않고 기존 블록 파서로 간다 — 기존 동작과 테스트를 건드리지 않으려고 이렇게 나눴다.
오탐을 막는 제한: 초 단위 시작 시각은 괄호 안(`[6.1초]`)일 때만, 괄호 없는 맨 숫자 범위(`3-4개`)는
시각이 아니다. 시각 있는 제목이 하나라도 있으면 그 앞 줄은 머리말이다('45초–1:45 구간이 어렵다는
피드백' 같은 메모를 큐로 오인하지 않게).

엑셀 칸이 한 줄씩 풀린 붙여넣기(빈 칸 = 전각 공백 줄)는 터미널 붙여넣기에서 실제로 두 번 받았다.
헤더 칸(숫자 없는 짧은 칸 3개 이상, 본문·시각 열 포함)을 찾고 그 수만큼 칸을 묶어 행으로 만든다.
빈 칸이 전각 공백 없이 사라지면 칸이 밀리므로 그때는 브라우저에서 탭 구분으로 붙여 넣어야 한다.

### 문서 제목 줄은 버린다

블록 형식 대본 맨 위의 'OO 소개영상 — 내레이션 대본 (2분 57초 · 14씬)' 이 씬이 되면 영상 0초에
읽혀 첫 문장과 겹친다. 타임코드 씬이 2개 이상일 때 첫 타임코드 씬 앞의 시각 없는 덩어리를 버린다.
(타임코드가 없는 대본은 기존대로 머리말도 살린다.)

### 검증 결과 (2026-10-24)

- pytest 149개 통과(파서 형식 17개·더빙 E2E 8개 추가, 실제 ffmpeg 로 복사·VP8 재인코딩·원본 소리 섞기·Range).
- 실제 MeloTTS(CPU 사이드카) 1.2배로 4문장 + 20초 영상: 작업 10초, mp4 = h264 복사 + aac.
  배치 wav 의 실제 발화 시작이 배치 시각보다 0.075~0.09초 늦다 — MeloTTS 출력 앞 무음이라 정상.
- 브라우저(Playwright)로 업로드 진행 → 영상 교체 시 이전 결과 삭제 → 더빙 → 재생·다운로드·경고 확인.

### 포털 반영 때 드러난 것 (2026-10-24)

- 푸시하면 HEAXHub 스캐너(5분 주기)가 커밋 변화를 보고 SIF 를 스스로 다시 빌드한다. 빌더에는 잠금이 없고
  임시 경로(`<slug>.sif.building`)가 고정이라, 그때 `redeploy-app.sh --rebuild` 를 같이 돌리면 서로의 임시
  파일을 지운다. 그래서 스캐너 빌드가 끝나기를 기다렸다가 `redeploy-app.sh voice-recorder`(전환만)를 돌렸다.
  새 SIF 는 Debian trixie 베이스라 ffmpeg 7.1(libx264·aac·libmp3lame·amix normalize)이 들어간다.
- 포털 데이터의 모델 폴더(`HEAXHub/var/app_data/voice_recorder/models/hub`)가 비어 있었다. `HF_HUB_OFFLINE=1`
  이라 포털에서는 세 엔진 모두 합성할 수 없던 상태였다. MeloTTS 관련 캐시 7개(657MB)를 로컬 `var/models`
  에서 복사해 넣었고, 인스턴스 안에서 MeloTTS 1.2배 더빙(합성·배치·먹싱)이 24초에 끝나는 것을 확인했다.
  Chatterbox(3GB)·CosyVoice(9GB) 가중치는 아직 포털에 없다 — 그 엔진을 고르면 오프라인 오류가 난다.
- MeloTTS 는 import 할 때 모든 언어 모듈이 자기 BERT 토크나이저를 불러온다(한국어만 써도 일본어·영어·
  프랑스어·스페인어·다국어 토크나이저가 필요). `fetch-models.sh` 가 MeloTTS-Korean 본체만 받고 이들을 빠뜨려
  폐쇄망에서도 같은 오류가 날 상태였다 — 토크나이저 파일만 `allow_patterns` 로 받게 고쳤다.
