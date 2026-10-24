// 화면 전환(목록 ↔ 새로 만들기 ↔ 편집)과 작업 진행률 폴링을 담당하는 최상위 컴포넌트

import { Component, useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api } from "./api";
import { Editor } from "./components/Editor";
import { EngineStatus } from "./components/EngineStatus";
import { ScriptComposer } from "./components/ScriptComposer";
import { SettingsDrawer } from "./components/SettingsDrawer";
import { formatSeconds } from "./format";
import type { DictionaryEntry, Engine, Job, Project, ProjectPayload, Voice } from "./types";

type View = "list" | "new" | "editor";

export default function App() {
  return (
    <ErrorBoundary>
      <AppBody />
    </ErrorBoundary>
  );
}

function AppBody() {
  const [view, setView] = useState<View>("list");
  const [projects, setProjects] = useState<Project[]>([]);
  const [payload, setPayload] = useState<ProjectPayload | null>(null);
  const [engines, setEngines] = useState<Engine[]>([]);
  // 서버가 정한 기본 엔진(현재 MeloTTS)·속도(1.2배) — 새 내레이션의 첫 선택과 상단 배지에 쓴다
  const [defaultEngine, setDefaultEngine] = useState("");
  const [defaultSpeed, setDefaultSpeed] = useState(1.2);
  // 서버에 ffmpeg 가 없으면 합성 후처리가 전부 실패한다 — 처음부터 경고를 띄운다
  const [ffmpegOk, setFfmpegOk] = useState(true);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [dictionary, setDictionary] = useState<DictionaryEntry[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [error, setError] = useState("");
  // 진행 확인 요청이 실패하는 동안 — 폴링은 멈추지 않고 간격을 늘려 다시 시도한다
  const [connectionLost, setConnectionLost] = useState(false);
  // 지금 열려 있는 프로젝트 — 다른 프로젝트의 작업 결과·응답이 이 화면을 덮어쓰지 않게 한다
  const openProjectId = useRef<string | null>(null);
  const pollTimer = useRef<number | null>(null);
  const pollJobId = useRef<string | null>(null);

  const loadShared = useCallback(async () => {
    try {
      const [engineList, voiceList, dict] = await Promise.all([
        api.engines(),
        api.listVoices(),
        api.listDictionary(),
      ]);
      setEngines(engineList.engines);
      setDefaultEngine(engineList.default);
      setDefaultSpeed(engineList.default_speed);
      setFfmpegOk(engineList.ffmpeg);
      setVoices(voiceList.voices);
      setDictionary(dict.entries);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, []);

  const loadProjects = useCallback(async () => {
    try {
      setProjects((await api.listProjects()).projects);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, []);

  useEffect(() => {
    loadShared();
    loadProjects();
  }, [loadShared, loadProjects]);

  const stopPolling = useCallback(() => {
    if (pollTimer.current) window.clearTimeout(pollTimer.current);
    pollTimer.current = null;
    pollJobId.current = null;
    setConnectionLost(false);
  }, []);

  // 열린 프로젝트의 응답만 화면에 반영한다 (늦게 도착한 다른 프로젝트 응답은 버린다)
  const showPayload = useCallback((next: ProjectPayload) => {
    if (next.project.id === openProjectId.current) setPayload(next);
  }, []);

  // 작업이 끝날 때까지 1초 간격으로 폴링한다.
  // WebSocket 을 안 쓰는 이유: HEAXHub 는 Caddy 리버스 프록시 뒤 서브경로에 앱을 마운트하는데
  // WS 는 프록시 설정에 민감하다. 합성은 수십 초 단위라 폴링으로 충분하다.
  // 요청이 한 번 실패했다고 멈추면 작업이 끝나도 화면이 '합성 중'에 갇힌다 — 간격을 늘려 계속 묻는다.
  const trackJob = useCallback(
    (jobId: string) => {
      stopPolling();
      pollJobId.current = jobId;
      let failures = 0;
      const tick = async () => {
        if (pollJobId.current !== jobId) return;
        try {
          const next = await api.job(jobId);
          if (pollJobId.current !== jobId) return;
          failures = 0;
          setConnectionLost(false);
          if (next.project_id !== openProjectId.current) {
            stopPolling(); // 다른 프로젝트로 옮겨 갔다 — 그 작업은 다시 열 때 이어 본다
            return;
          }
          setJob(next);
          if (next.status === "done" || next.status === "error") {
            stopPolling();
            showPayload(await api.getProject(next.project_id));
            return;
          }
        } catch {
          failures += 1;
          setConnectionLost(true);
        }
        const delay = failures ? Math.min(1000 * 2 ** Math.min(failures, 4), 15000) : 1000;
        pollTimer.current = window.setTimeout(tick, delay);
      };
      tick();
    },
    [showPayload, stopPolling],
  );

  useEffect(() => () => stopPolling(), [stopPolling]);

  async function open(projectId: string) {
    try {
      stopPolling();
      openProjectId.current = projectId;
      const next = await api.getProject(projectId);
      if (openProjectId.current !== projectId) return;
      setPayload(next);
      setJob(next.job);
      setView("editor");
      if (next.job && (next.job.status === "queued" || next.job.status === "running")) {
        trackJob(next.job.id);
      }
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  function backToList() {
    stopPolling();
    openProjectId.current = null;
    setView("list");
    loadProjects();
  }

  async function remove(projectId: string) {
    if (!window.confirm("이 프로젝트와 생성된 음성을 모두 지웁니다. 계속할까요?")) return;
    try {
      await api.deleteProject(projectId);
      await loadProjects();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  // 발음 사전·화자를 바꾸면 열린 프로젝트의 '읽는 소리'·상태도 바로 다시 받아 온다
  async function refreshShared() {
    await loadShared();
    const pid = openProjectId.current;
    if (pid) {
      try {
        showPayload(await api.getProject(pid));
      } catch (err) {
        setError(String((err as Error).message ?? err));
      }
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <button type="button" className="brand" onClick={backToList}>
          🎙 VoiceRecorder <small>내레이션 음성 생성</small>
        </button>
        <span className="spacer" />
        <EngineStatus engines={engines} defaultEngine={defaultEngine} />
        <button className="btn small" onClick={() => setDrawer(true)}>
          화자 · 발음 사전
        </button>
        {view !== "new" && (
          <button
            className="btn small primary"
            onClick={() => {
              stopPolling();
              openProjectId.current = null;
              setView("new");
            }}
          >
            + 새 내레이션
          </button>
        )}
      </header>

      <main className="container">
        {!ffmpegOk && (
          <div className="error-banner">
            ⚠ 서버에 ffmpeg 가 없어 속도 조절 · mp3 내보내기 · 영상에 음성 입히기가 동작하지 않습니다.
            관리자에게 알려 주세요.
          </div>
        )}
        {connectionLost && (
          <div className="warn-banner">서버 연결이 잠시 끊겼습니다 — 작업 상태를 다시 확인하는 중입니다.</div>
        )}
        {error && (
          <div className="error-banner">
            <span style={{ flex: 1 }}>{error}</span>
            <button className="btn small" onClick={() => setError("")}>
              닫기
            </button>
          </div>
        )}

        {view === "list" && (
          <div className="card">
            <h2>내레이션 프로젝트</h2>
            <p className="hint">
              대본을 붙여넣으면 씬 단위로 나눠 음성을 만들고, mp3·SRT 자막으로 내보내거나 영상에 바로 입힙니다.
            </p>
            {projects.length === 0 ? (
              <div className="empty">
                아직 프로젝트가 없습니다.
                <br />
                <button
                  className="btn primary"
                  style={{ marginTop: 12 }}
                  onClick={() => setView("new")}
                >
                  첫 내레이션 만들기
                </button>
              </div>
            ) : (
              projects.map((project) => (
                <div
                  key={project.id}
                  className="project-row"
                  role="button"
                  tabIndex={0}
                  aria-label={`${project.title} 열기`}
                  onClick={() => open(project.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      open(project.id);
                    }
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <strong>{project.title}</strong>
                    {project.has_dub ? (
                      <span className="badge ready" style={{ marginLeft: 6 }}>
                        음성 입힌 영상
                      </span>
                    ) : (
                      project.has_video && (
                        <span className="badge info" style={{ marginLeft: 6 }}>
                          영상 있음
                        </span>
                      )
                    )}
                    <div className="scene-meta">
                      씬 {project.scene_count ?? 0}개 · {project.engine} ·{" "}
                      {new Date(project.updated_at * 1000).toLocaleString("ko-KR")}
                    </div>
                  </div>
                  <button
                    className="btn small danger"
                    onClick={(event) => {
                      event.stopPropagation();
                      remove(project.id);
                    }}
                    onKeyDown={(event) => event.stopPropagation()}
                  >
                    삭제
                  </button>
                </div>
              ))
            )}
          </div>
        )}

        {view === "new" && (
          <ScriptComposer
            engines={engines}
            defaultEngine={defaultEngine}
            defaultSpeed={defaultSpeed}
            voices={voices}
            onCancel={() => setView("list")}
            onCreated={(next) => {
              openProjectId.current = next.project.id;
              setPayload(next);
              setJob(null);
              setView("editor");
              loadProjects();
            }}
          />
        )}

        {view === "editor" && payload && (
          <Editor
            // 프로젝트가 바뀌면 편집 중이던 초안(다시 붙여넣기 등)이 다른 프로젝트로 넘어가지 않게 새로 그린다
            key={payload.project.id}
            payload={payload}
            engines={engines}
            voices={voices}
            job={job && job.project_id === payload.project.id ? job : null}
            onPayload={showPayload}
            onJob={trackJob}
            onBack={backToList}
            onError={setError}
          />
        )}
      </main>

      {drawer && (
        <SettingsDrawer
          engines={engines}
          voices={voices}
          dictionary={dictionary}
          onClose={() => setDrawer(false)}
          onRefresh={refreshShared}
        />
      )}

      <footer className="container" style={{ flex: "none", color: "var(--text-dim)", fontSize: 12 }}>
        {payload && view === "editor" && <>총 길이 {formatSeconds(payload.total_sec)} · </>}
        TTS 엔진은 상업 이용 가능한 MIT 라이선스 모델만 사용합니다.
      </footer>
    </div>
  );
}

/** 그리다 오류가 나면 빈 화면 대신 안내를 보여 준다. */
class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="container">
        <div className="error-banner" style={{ marginTop: 40 }}>
          <span style={{ flex: 1 }}>화면을 그리다 문제가 생겼습니다. 새로고침하면 대부분 해결됩니다.</span>
          <button className="btn small" onClick={() => window.location.reload()}>
            새로고침
          </button>
        </div>
      </div>
    );
  }
}
