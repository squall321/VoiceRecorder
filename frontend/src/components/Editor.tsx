// 프로젝트 편집 화면 — 툴바(전체 생성·내보내기·다운로드) + 씬 목록

import { useState } from "react";
import { api, urls } from "../api";
import { formatSeconds } from "../format";
import type { Engine, Job, ProjectPayload, Voice } from "../types";
import { SceneCard } from "./SceneCard";

interface Props {
  payload: ProjectPayload;
  engines: Engine[];
  voices: Voice[];
  job: Job | null;
  onPayload: (payload: ProjectPayload) => void;
  onJob: (jobId: string) => void;
  onBack: () => void;
  onError: (message: string) => void;
}

export function Editor({ payload, engines, voices, job, onPayload, onJob, onBack, onError }: Props) {
  const { project, scenes } = payload;
  const [showScript, setShowScript] = useState(false);
  const [scriptDraft, setScriptDraft] = useState(project.raw_script);
  const [newSceneText, setNewSceneText] = useState("");

  const busy = job !== null && (job.status === "queued" || job.status === "running");
  const pending = scenes.filter((s) => s.status !== "ready");
  const engine = engines.find((e) => e.id === project.engine);
  const exported = job?.kind === "export" && job.status === "done";
  // 씬별로 속도를 따로 만진 씬 수 — 이 씬들은 전체 슬라이더를 따르지 않는다
  const speedOverrideCount = scenes.filter((s) => s.speed != null).length;

  async function run<T>(action: () => Promise<T>): Promise<T | undefined> {
    try {
      return await action();
    } catch (err) {
      onError(String((err as Error).message ?? err));
      return undefined;
    }
  }

  const patchScene = (sceneId: string, patch: Record<string, unknown>) =>
    run(() => api.patchScene(project.id, sceneId, patch).then(onPayload));

  const move = (sceneId: string, direction: -1 | 1) => {
    const order = scenes.map((s) => s.id);
    const from = order.indexOf(sceneId);
    const to = from + direction;
    if (to < 0 || to >= order.length) return;
    [order[from], order[to]] = [order[to], order[from]];
    run(() => api.reorder(project.id, order).then(onPayload));
  };

  return (
    <>
      <div className="card">
        <div className="btn-row">
          <button className="btn small" onClick={onBack}>
            ← 목록
          </button>
          <h2 style={{ margin: 0 }}>{project.title}</h2>
          <span className="badge pending">
            {payload.ready_count}/{scenes.length} 씬 완료
          </span>
          <span className="badge info">총 {formatSeconds(payload.total_sec)}</span>
          {engine && !engine.available && <span className="badge error">{engine.detail}</span>}
          <span className="spacer" />
          <button
            className="btn primary"
            disabled={busy || pending.length === 0}
            onClick={() => run(() => api.synthesize(project.id).then((r) => onJob(r.job_id)))}
          >
            {pending.length > 0 ? `음성 생성 (${pending.length}씬)` : "모두 생성됨"}
          </button>
          <button
            className="btn"
            disabled={busy || payload.ready_count === 0}
            onClick={() => run(() => api.exportProject(project.id).then((r) => onJob(r.job_id)))}
          >
            mp3 + 자막 내보내기
          </button>
        </div>

        {busy && (
          <>
            <div className="progress">
              <span style={{ width: `${job!.total ? (job!.done / job!.total) * 100 : 5}%` }} />
            </div>
            <p className="hint" style={{ margin: 0 }}>
              {job!.kind === "export" ? "병합 중" : "합성 중"} · {job!.current ?? "준비"} (
              {job!.done}/{job!.total})
            </p>
          </>
        )}

        {job?.status === "error" && <div className="error-banner">{job.error}</div>}

        {(exported || payload.ready_count > 0) && (
          <div className="btn-row" style={{ marginTop: 10 }}>
            {exported && (
              <a className="btn" href={urls.exportAudio(project.id)} download>
                ⬇ mp3 다운로드
                {typeof job?.result?.mp3_bytes === "number" &&
                  ` (${Math.round((job.result.mp3_bytes as number) / 1024)} KB)`}
              </a>
            )}
            <a className="btn" href={urls.exportSrt(project.id)} download>
              ⬇ SRT 자막 다운로드
            </a>
            <span className="spacer" />
            <button className="btn small" onClick={() => setShowScript(!showScript)}>
              원본 스크립트 {showScript ? "닫기" : "다시 붙여넣기"}
            </button>
          </div>
        )}
      </div>

      {showScript && (
        <div className="card">
          <h2>스크립트 다시 붙여넣기</h2>
          <p className="hint">
            씬을 새로 나눕니다. <strong>기존에 생성한 음성은 모두 사라집니다.</strong>
          </p>
          <textarea rows={12} value={scriptDraft} onChange={(e) => setScriptDraft(e.target.value)} />
          <div className="btn-row" style={{ marginTop: 10 }}>
            <button
              className="btn primary"
              onClick={() =>
                run(() =>
                  api.replaceScript(project.id, scriptDraft).then((next) => {
                    onPayload(next);
                    setShowScript(false);
                  }),
                )
              }
            >
              씬 다시 나누기
            </button>
            <button className="btn" onClick={() => setShowScript(false)}>
              취소
            </button>
          </div>
        </div>
      )}

      <div className="card">
        <h2>전체 기본값</h2>
        <div className="grid cols-4">
          <label className="field">
            화자
            <select
              value={project.voice_id ?? ""}
              onChange={(e) =>
                run(() =>
                  api.patchProject(project.id, { voice_id: e.target.value || null }).then(onPayload),
                )
              }
            >
              <option value="">기본 목소리</option>
              {voices.map((voice) => (
                <option key={voice.id} value={voice.id}>
                  {voice.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            말 속도 (전체 {project.speed.toFixed(2)}×)
            <input
              type="range"
              min={0.5}
              max={2}
              step={0.05}
              value={project.speed}
              onChange={(e) =>
                run(() =>
                  api.patchProject(project.id, { speed: Number(e.target.value) }).then(onPayload),
                )
              }
            />
            {speedOverrideCount > 0 ? (
              <button
                className="btn small"
                style={{ marginTop: 4 }}
                disabled={busy}
                onClick={() => run(() => api.applySpeed(project.id, project.speed).then(onPayload))}
                title={`씬 ${speedOverrideCount}개에 개별 속도가 걸려 있어 전체 슬라이더를 따르지 않습니다. 눌러서 ${project.speed.toFixed(2)}×로 통일합니다.`}
              >
                씬 {speedOverrideCount}개 개별 속도 · 전체 통일
              </button>
            ) : (
              <span className="scene-meta" style={{ marginTop: 4 }}>
                모든 씬에 적용됨
              </span>
            )}
          </label>
          <label className="field">
            씬 사이 무음 (ms)
            <input
              type="number"
              min={0}
              max={5000}
              step={50}
              value={project.gap_ms}
              onChange={(e) =>
                run(() =>
                  api.patchProject(project.id, { gap_ms: Number(e.target.value) }).then(onPayload),
                )
              }
            />
          </label>
          <label className="field" style={{ justifyContent: "flex-end" }}>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <input
                type="checkbox"
                checked={project.read_numbers}
                style={{ width: "auto" }}
                onChange={(e) =>
                  run(() =>
                    api
                      .patchProject(project.id, { read_numbers: e.target.checked })
                      .then(onPayload),
                  )
                }
              />
              숫자를 한글로 읽기
            </span>
          </label>
        </div>
      </div>

      {scenes.map((scene, index) => (
        <SceneCard
          key={scene.id}
          scene={scene}
          projectId={project.id}
          voices={voices}
          busy={busy}
          isFirst={index === 0}
          isLast={index === scenes.length - 1}
          onPatch={(patch) => patchScene(scene.id, patch)}
          onSynthesize={() =>
            run(() => api.synthesize(project.id, [scene.id]).then((r) => onJob(r.job_id)))
          }
          onMove={(direction) => move(scene.id, direction)}
          onDelete={() => run(() => api.deleteScene(project.id, scene.id).then(onPayload))}
        />
      ))}

      <div className="card">
        <h2>씬 추가</h2>
        <textarea
          rows={2}
          value={newSceneText}
          onChange={(e) => setNewSceneText(e.target.value)}
          placeholder="마지막에 덧붙일 내레이션 문장"
        />
        <div className="btn-row" style={{ marginTop: 10 }}>
          <button
            className="btn"
            disabled={!newSceneText.trim()}
            onClick={() =>
              run(() =>
                api.addScene(project.id, newSceneText.trim()).then((next) => {
                  onPayload(next);
                  setNewSceneText("");
                }),
              )
            }
          >
            씬 추가
          </button>
        </div>
      </div>
    </>
  );
}
