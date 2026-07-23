// 화면 전환(목록 ↔ 새로 만들기 ↔ 편집)과 작업 진행률 폴링을 담당하는 최상위 컴포넌트

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Editor } from "./components/Editor";
import { EngineStatus } from "./components/EngineStatus";
import { ScriptComposer } from "./components/ScriptComposer";
import { SettingsDrawer } from "./components/SettingsDrawer";
import { formatSeconds } from "./format";
import type { DictionaryEntry, Engine, Job, Project, ProjectPayload, Voice } from "./types";

type View = "list" | "new" | "editor";

export default function App() {
  const [view, setView] = useState<View>("list");
  const [projects, setProjects] = useState<Project[]>([]);
  const [payload, setPayload] = useState<ProjectPayload | null>(null);
  const [engines, setEngines] = useState<Engine[]>([]);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [dictionary, setDictionary] = useState<DictionaryEntry[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [error, setError] = useState("");
  const pollTimer = useRef<number | null>(null);

  const loadShared = useCallback(async () => {
    try {
      const [engineList, voiceList, dict] = await Promise.all([
        api.engines(),
        api.listVoices(),
        api.listDictionary(),
      ]);
      setEngines(engineList.engines);
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

  // 작업이 끝날 때까지 1초 간격으로 폴링한다.
  // WebSocket 을 안 쓰는 이유: HEAXHub 는 Caddy 리버스 프록시 뒤 서브경로에 앱을 마운트하는데
  // WS 는 프록시 설정에 민감하다. 합성은 수십 초 단위라 폴링으로 충분하다.
  const trackJob = useCallback(
    (jobId: string) => {
      if (pollTimer.current) window.clearInterval(pollTimer.current);
      const tick = async () => {
        try {
          const next = await api.job(jobId);
          setJob(next);
          if (next.status === "done" || next.status === "error") {
            if (pollTimer.current) window.clearInterval(pollTimer.current);
            pollTimer.current = null;
            setPayload(await api.getProject(next.project_id));
          }
        } catch (err) {
          if (pollTimer.current) window.clearInterval(pollTimer.current);
          pollTimer.current = null;
          setError(String((err as Error).message ?? err));
        }
      };
      tick();
      pollTimer.current = window.setInterval(tick, 1000);
    },
    [],
  );

  useEffect(() => () => {
    if (pollTimer.current) window.clearInterval(pollTimer.current);
  }, []);

  async function open(projectId: string) {
    try {
      const next = await api.getProject(projectId);
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

  async function remove(projectId: string) {
    if (!window.confirm("이 프로젝트와 생성된 음성을 모두 지웁니다. 계속할까요?")) return;
    try {
      await api.deleteProject(projectId);
      await loadProjects();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <span
          className="brand"
          onClick={() => {
            setView("list");
            loadProjects();
          }}
        >
          🎙 VoiceRecorder <small>내레이션 음성 생성</small>
        </span>
        <span className="spacer" />
        <EngineStatus engines={engines} />
        <button className="btn small" onClick={() => setDrawer(true)}>
          화자 · 발음 사전
        </button>
        {view !== "new" && (
          <button className="btn small primary" onClick={() => setView("new")}>
            + 새 내레이션
          </button>
        )}
      </header>

      <main className="container">
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
              스크립트를 붙여넣으면 씬 단위로 나눠 음성을 만들고, mp3와 SRT 자막으로 내보냅니다.
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
                <div key={project.id} className="project-row" onClick={() => open(project.id)}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <strong>{project.title}</strong>
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
            voices={voices}
            onCancel={() => setView("list")}
            onCreated={(next) => {
              setPayload(next);
              setJob(null);
              setView("editor");
              loadProjects();
            }}
          />
        )}

        {view === "editor" && payload && (
          <Editor
            payload={payload}
            engines={engines}
            voices={voices}
            job={job}
            onPayload={setPayload}
            onJob={trackJob}
            onBack={() => {
              setView("list");
              loadProjects();
            }}
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
          onRefresh={loadShared}
          onError={setError}
        />
      )}

      <footer className="container" style={{ flex: "none", color: "var(--text-dim)", fontSize: 12 }}>
        {payload && view === "editor" && <>총 길이 {formatSeconds(payload.total_sec)} · </>}
        TTS 엔진은 상업 이용 가능한 MIT 라이선스 모델만 사용합니다.
      </footer>
    </div>
  );
}
