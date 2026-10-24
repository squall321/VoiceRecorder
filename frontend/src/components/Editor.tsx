// 프로젝트 편집 화면 — 머리(제목·대본 다시 붙여넣기)·툴바(전체 생성·맞춤·내보내기) + 음성 입히기 + 씬 목록

import { useEffect, useState } from "react";
import { api, urls } from "../api";
import { formatSeconds } from "../format";
import type { Engine, FitReport, Job, ParseResponse, ProjectPayload, Voice } from "../types";
import { DubPanel } from "./DubPanel";
import { CommitNumber, CommitRange } from "./inputs";
import { JobProgress } from "./JobProgress";
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
  const [scriptPreview, setScriptPreview] = useState<ParseResponse | null>(null);
  const [titleDraft, setTitleDraft] = useState(project.title);
  const [newSceneText, setNewSceneText] = useState("");
  const [fitReport, setFitReport] = useState<FitReport | null>(null);
  // 작업을 시작하는 요청이 오가는 동안 — 버튼을 두 번 눌러 같은 작업이 두 번 생기지 않게 잠근다
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => setTitleDraft(project.title), [project.title]);

  // 다시 붙여넣는 대본도 나누기 전에 어떻게 나뉘는지 보여 준다
  useEffect(() => {
    if (!showScript || !scriptDraft.trim()) {
      setScriptPreview(null);
      return;
    }
    const timer = window.setTimeout(() => {
      api.parse(scriptDraft).then(setScriptPreview).catch(() => setScriptPreview(null));
    }, 350);
    return () => window.clearTimeout(timer);
  }, [scriptDraft, showScript]);

  const jobBusy = job !== null && (job.status === "queued" || job.status === "running");
  const busy = jobBusy || submitting;
  const pending = scenes.filter((s) => s.status !== "ready");
  const engine = engines.find((e) => e.id === project.engine);
  const canClone = engine?.supports_voice_cloning ?? false;
  const exportJob = job?.kind === "export" && job.status === "done" ? job : null;
  // 내보낸 뒤 대본·음성이 바뀌었으면 받아 둔 mp3 는 옛 것이다
  const exportStale = exportJob?.updated_at != null && project.updated_at > exportJob.updated_at + 1;
  // 씬별로 속도를 따로 만진 씬 수 — 이 씬들은 전체 슬라이더를 따르지 않는다
  const speedOverrideCount = scenes.filter((s) => s.speed != null).length;
  const allReady = scenes.length > 0 && scenes.every((s) => s.status === "ready");
  // 시작 시각만 적힌 대본은 마지막 씬에 끝이 없다 — 한 씬이라도 목표 길이가 있으면 맞출 수 있다
  const hasTimecodes = scenes.some((s) => s.target_duration_sec != null);
  const fitBlocked = !hasTimecodes
    ? "대본에 타임코드가 없어 맞출 수 없습니다"
    : !allReady
      ? "모든 씬의 음성을 먼저 만들어야 맞출 수 있습니다"
      : "";
  // 마지막 음성 입힌 영상에서 시각을 넘친 씬 — 씬 카드에 바로 보여 고칠 곳을 찾게 한다
  const overrunById = new Map((payload.dub?.overruns ?? []).map((o) => [o.scene_id, o]));
  const timedInPreview = scriptPreview?.scenes.filter((s) => s.target_start_sec !== null).length ?? 0;

  async function run<T>(action: () => Promise<T>): Promise<T | undefined> {
    try {
      return await action();
    } catch (err) {
      onError(String((err as Error).message ?? err));
      return undefined;
    }
  }

  async function submit(action: () => Promise<unknown>) {
    if (submitting) return;
    setSubmitting(true);
    try {
      await run(action);
    } finally {
      setSubmitting(false);
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

  function commitTitle() {
    const next = titleDraft.trim();
    if (!next) {
      setTitleDraft(project.title);
      return;
    }
    if (next !== project.title) run(() => api.patchProject(project.id, { title: next }).then(onPayload));
  }

  function resplit() {
    const message =
      payload.ready_count > 0
        ? `만든 음성 ${payload.ready_count}개와 씬에서 고친 문장·읽는 법·속도·무음이 모두 지워집니다. 계속할까요?`
        : "씬에서 고친 문장·읽는 법·속도·무음이 모두 지워집니다. 계속할까요?";
    if (!window.confirm(message)) return;
    submit(() =>
      api.replaceScript(project.id, scriptDraft).then((next) => {
        onPayload(next);
        setShowScript(false);
      }),
    );
  }

  return (
    <>
      <div className="card">
        <div className="btn-row">
          <button className="btn small" onClick={onBack}>
            ← 목록
          </button>
          <input
            className="title-input"
            aria-label="프로젝트 제목 (내려받는 파일 이름에 쓰입니다)"
            title="눌러서 고칠 수 있습니다 — 내려받는 파일 이름에 쓰입니다"
            value={titleDraft}
            onChange={(e) => setTitleDraft(e.target.value)}
            onBlur={commitTitle}
            onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          />
          <span className="badge pending">
            {payload.ready_count}/{scenes.length} 씬 완료
          </span>
          <span className="badge info">총 {formatSeconds(payload.total_sec)}</span>
          {engine && !engine.available && <span className="badge error">{engine.detail}</span>}
          <span className="spacer" />
          <button className="btn small" onClick={() => setShowScript(!showScript)}>
            대본 {showScript ? "닫기" : "다시 붙여넣기"}
          </button>
        </div>

        <div className="btn-row" style={{ marginTop: 10 }}>
          <button
            className="btn primary"
            disabled={busy || pending.length === 0}
            onClick={() => submit(() => api.synthesize(project.id).then((r) => onJob(r.job_id)))}
          >
            {pending.length > 0 ? `음성 생성 (${pending.length}씬)` : "모두 생성됨"}
          </button>
          <button
            className="btn"
            disabled={busy || Boolean(fitBlocked)}
            title="기본 속도로 들어가는 씬은 그대로 두고 뒤를 무음으로 채우며, 넘치는 씬만 빠르게 해 타임코드에 맞춥니다"
            onClick={() =>
              submit(() =>
                api.fitTimecode(project.id).then((p) => {
                  onPayload(p);
                  setFitReport(p.fit_report ?? null);
                }),
              )
            }
          >
            ⧗ 타임코드에 맞춤
          </button>
          <button
            className="btn"
            disabled={busy || payload.ready_count === 0}
            title="씬을 무음 간격대로 이어 붙인 mp3 와 자막입니다 (영상 시각 기준은 아래 '영상에 음성 입히기')"
            onClick={() => submit(() => api.exportProject(project.id).then((r) => onJob(r.job_id)))}
          >
            이어 붙인 mp3 + 자막 내보내기
            {payload.ready_count > 0 && payload.ready_count < scenes.length
              ? ` (완료된 ${payload.ready_count}/${scenes.length}씬)`
              : ""}
          </button>
        </div>
        {fitBlocked && hasTimecodes && (
          <p className="hint" style={{ margin: "6px 0 0" }}>
            ⧗ 타임코드에 맞춤 — {fitBlocked}
          </p>
        )}

        {jobBusy && <JobProgress job={job!} />}

        {job?.status === "error" && <div className="error-banner">{job.error}</div>}

        {fitReport &&
          (fitReport.over_budget.length === 0 ? (
            <div className="fit-banner ok">
              ✓ 전 씬을 타임코드에 맞췄습니다 · 총 {formatSeconds(fitReport.total_sec)}
            </div>
          ) : (
            <div className="fit-banner warn">
              <div>
                ⚠ {fitReport.over_budget.length}개 씬은 최대 배속으로도 슬롯을 넘칩니다. 원고를 줄이거나 슬롯을
                늘려야 합니다.
              </div>
              <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                {fitReport.over_budget.map((o) => (
                  <li key={`${o.number}-${o.title}`}>
                    {String(o.number ?? "").padStart(2, "0")} {o.title} — 슬롯 {o.target_sec}s, 최소 {o.min_sec}s (약{" "}
                    {Math.ceil(((o.min_sec - o.target_sec) / o.min_sec) * 100)}% 줄여야)
                  </li>
                ))}
              </ul>
            </div>
          ))}

        {(exportJob || payload.ready_count > 0) && (
          <div className="btn-row" style={{ marginTop: 10 }}>
            {exportJob && (
              <a className="btn" href={urls.exportAudio(project.id)} download>
                ⬇ 이어 붙인 mp3
                {typeof exportJob.result?.mp3_bytes === "number" &&
                  ` (${Math.round((exportJob.result.mp3_bytes as number) / 1024)} KB)`}
              </a>
            )}
            <a className="btn" href={urls.exportSrt(project.id)} download>
              ⬇ 이어 붙인 자막(SRT)
            </a>
            {exportStale && (
              <span className="scene-meta">내보낸 뒤 바뀌었습니다 — 다시 내보내야 반영됩니다</span>
            )}
          </div>
        )}
      </div>

      {showScript && (
        <div className="card">
          <h2>대본 다시 붙여넣기</h2>
          <p className="hint">
            씬을 새로 나눕니다.{" "}
            <strong>만든 음성과, 씬에서 고친 문장·읽는 법·속도·무음은 모두 지워집니다.</strong> 올린 영상은
            남습니다.
          </p>
          <textarea
            rows={12}
            aria-label="다시 붙여넣을 대본"
            value={scriptDraft}
            onChange={(e) => setScriptDraft(e.target.value)}
          />
          {scriptPreview && (
            <p className="hint" style={{ margin: "6px 0 0" }}>
              미리보기 — 씬 {scriptPreview.scenes.length}개 · 타임코드 있는 씬 {timedInPreview}개
              {scriptPreview.structured ? "" : " · 번호·타임코드 없이 문단으로 나눔"}
            </p>
          )}
          <div className="btn-row" style={{ marginTop: 10 }}>
            <button className="btn primary" disabled={busy || !scriptPreview?.scenes.length} onClick={resplit}>
              씬 다시 나누기
            </button>
            <button className="btn" onClick={() => setShowScript(false)}>
              취소
            </button>
          </div>
        </div>
      )}

      <DubPanel
        payload={payload}
        job={job}
        busy={busy}
        onPayload={onPayload}
        onJob={onJob}
        onError={onError}
      />

      <div className="card">
        <h2>전체 기본값</h2>
        <div className="grid cols-4">
          <label className="field">
            화자
            <select
              value={project.voice_id ?? ""}
              disabled={!canClone}
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
            {!canClone && (
              <span className="scene-meta">화자 복제를 지원하지 않는 엔진입니다 ({engine?.name ?? "현재 엔진"})</span>
            )}
          </label>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <CommitRange
              value={project.speed}
              min={0.5}
              max={2}
              step={0.05}
              disabled={busy}
              label={(v) => `말 속도 (전체 ${v.toFixed(2)}×)`}
              onCommit={(v) => run(() => api.patchProject(project.id, { speed: v }).then(onPayload))}
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
          </div>
          <CommitNumber
            label="씬 사이 무음 (ms)"
            value={project.gap_ms}
            min={0}
            max={5000}
            step={50}
            disabled={busy}
            onCommit={(v) => run(() => api.patchProject(project.id, { gap_ms: v }).then(onPayload))}
          />
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
              숫자·영문 약어를 한글로 읽기
            </span>
          </label>
        </div>
      </div>

      {scenes.map((scene, index) => (
        <SceneCard
          key={scene.id}
          scene={scene}
          overrun={overrunById.get(scene.id)}
          overrunStale={payload.dub?.stale ?? false}
          projectId={project.id}
          voices={voices}
          canClone={canClone}
          busy={busy}
          isFirst={index === 0}
          isLast={index === scenes.length - 1}
          onPatch={(patch) => patchScene(scene.id, patch)}
          onSynthesize={() =>
            submit(() => api.synthesize(project.id, [scene.id]).then((r) => onJob(r.job_id)))
          }
          onMove={(direction) => move(scene.id, direction)}
          onDelete={() => run(() => api.deleteScene(project.id, scene.id).then(onPayload))}
        />
      ))}

      <div className="card">
        <h2>씬 추가</h2>
        <textarea
          rows={2}
          aria-label="덧붙일 씬의 내레이션"
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
