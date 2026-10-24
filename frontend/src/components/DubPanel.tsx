// 영상에 음성 입히기 — 영상 업로드·미리보기, 원본 소리 옵션, 결과 재생·다운로드, 넘친 씬 경고

import { useEffect, useRef, useState } from "react";
import { api, urls } from "../api";
import { formatBytes, formatSeconds } from "../format";
import type { DubInfo, Job, ProjectPayload } from "../types";
import { JobProgress } from "./JobProgress";
import { FOCUS_SCENE_EVENT } from "./SceneCard";

interface Props {
  payload: ProjectPayload;
  job: Job | null;
  busy: boolean;
  onPayload: (payload: ProjectPayload) => void;
  onJob: (jobId: string) => void;
  onError: (message: string) => void;
}

const ORIGINAL_VOLUMES = [
  { value: 0, label: "끄기 — 내레이션만" },
  { value: 0.25, label: "작게 깔기 (25%)" },
  { value: 1, label: "그대로 (100%)" },
];

export function DubPanel({ payload, job, busy, onPayload, onJob, onError }: Props) {
  const { project, scenes, video, dub } = payload;
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadAbort = useRef<AbortController | null>(null);
  const [uploading, setUploading] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  // 다시 만들 때는 지난번 원본 소리 설정을 그대로 쓴다
  const [volume, setVolume] = useState(dub?.original_volume ?? 0);

  // 다른 화면으로 나가면 올리던 영상 업로드도 멈춘다 (다른 프로젝트에 결과가 덮이지 않게)
  useEffect(() => () => uploadAbort.current?.abort(), []);

  const pendingCount = scenes.filter((s) => s.status !== "ready").length;
  const timed = scenes.some((s) => s.target_start_sec !== null);
  const dubJob = job && job.kind === "dub" && (job.status === "queued" || job.status === "running") ? job : null;
  const locked = busy || submitting || uploading !== null;

  async function upload(file: File | undefined) {
    if (!file) return;
    const controller = new AbortController();
    uploadAbort.current = controller;
    setUploading(0);
    try {
      onPayload(await api.uploadVideo(project.id, file, setUploading, controller.signal));
    } catch (err) {
      if (!controller.signal.aborted) onError(String((err as Error).message ?? err));
    } finally {
      uploadAbort.current = null;
      setUploading(null);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  function pickFile() {
    if (dub && !window.confirm("새 영상을 올리면 지금 음성 입힌 결과가 지워집니다. 계속할까요?")) return;
    fileInput.current?.click();
  }

  async function run<T>(action: () => Promise<T>) {
    if (submitting) return;
    setSubmitting(true);
    try {
      await action();
    } catch (err) {
      onError(String((err as Error).message ?? err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="card">
      <h2>영상에 음성 입히기</h2>
      <p className="hint">
        영상을 올리면 각 씬을 대본의 시작 시각에 놓아 영상에 입힙니다. 영상 타이밍과 말 속도는 바꾸지
        않고, 대본 시각을 넘친 씬은 아래와 씬 카드에 알려 줍니다.
      </p>
      {!timed && scenes.length > 0 && (
        <div className="fit-banner warn" style={{ marginTop: 0, marginBottom: 10 }}>
          대본에 타임코드가 없어 씬을 씬 사이 무음 간격대로 처음부터 이어 붙입니다.
        </div>
      )}

      <input
        ref={fileInput}
        type="file"
        accept="video/*,.mp4,.mov,.m4v,.mkv,.webm"
        hidden
        onChange={(event) => upload(event.target.files?.[0])}
      />

      {uploading !== null ? (
        <>
          <div className={`progress${uploading >= 1 ? " indeterminate" : ""}`}>
            <span style={{ width: `${Math.max(4, Math.round(uploading * 100))}%` }} />
          </div>
          <div className="btn-row">
            <p className="hint" style={{ margin: 0 }}>
              {uploading < 1 ? `영상 올리는 중 ${Math.round(uploading * 100)}%` : "영상 확인 중…"}
            </p>
            {uploading < 1 && (
              <button className="btn small" onClick={() => uploadAbort.current?.abort()}>
                취소
              </button>
            )}
          </div>
        </>
      ) : video ? (
        <div className="dub-media">
          <video controls preload="metadata" src={`${urls.video(project.id)}?v=${video.uploaded_at}`} />
          <div style={{ minWidth: 0 }}>
            <strong style={{ wordBreak: "break-all" }}>{video.filename}</strong>
            <div className="scene-meta">
              {formatSeconds(video.duration_sec)}
              {video.width && video.height ? ` · ${video.width}×${video.height}` : ""} ·{" "}
              {video.has_audio ? "원본 소리 있음" : "원본 소리 없음"} · {formatBytes(video.size_bytes)}
            </div>
            <div className="btn-row" style={{ marginTop: 8 }}>
              <button className="btn small" disabled={locked} onClick={pickFile}>
                영상 바꾸기
              </button>
              <button
                className="btn small danger"
                disabled={locked}
                onClick={() => {
                  if (window.confirm("올린 영상과 음성 입힌 결과를 지웁니다. 계속할까요?")) {
                    run(() => api.deleteVideo(project.id).then(onPayload));
                  }
                }}
              >
                영상 빼기
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div
          className={`dropzone${dragOver ? " over" : ""}`}
          role="button"
          tabIndex={0}
          aria-label="영상 파일 고르기"
          onClick={pickFile}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              pickFile();
            }
          }}
          onDragOver={(event) => {
            event.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragOver(false);
            upload(event.dataTransfer.files?.[0]);
          }}
        >
          영상 파일을 끌어다 놓거나 눌러서 고르세요 (mp4 · mov · webm · mkv)
        </div>
      )}

      {video && (
        <div className="btn-row" style={{ marginTop: 12 }}>
          {video.has_audio && (
            <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              원본 소리
              <select
                value={volume}
                style={{ width: "auto" }}
                onChange={(event) => setVolume(Number(event.target.value))}
              >
                {ORIGINAL_VOLUMES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <span className="spacer" />
          <button
            className="btn primary"
            disabled={locked || scenes.length === 0}
            onClick={() => run(() => api.dub(project.id, volume).then((r) => onJob(r.job_id)))}
          >
            {dubJob
              ? "만드는 중…"
              : pendingCount > 0
                ? `음성 입힌 영상 만들기 (음성 ${pendingCount}씬 먼저 생성)`
                : "음성 입힌 영상 만들기"}
          </button>
        </div>
      )}

      {dubJob && (
        <div style={{ marginTop: 10 }}>
          <JobProgress job={dubJob} />
        </div>
      )}

      {video && dub && <DubResult projectId={project.id} dub={dub} />}
    </div>
  );
}

// 넘친 씬을 누르면 그 씬 카드로 스크롤해 잠깐 강조하고, 속도를 고칠 수 있게 설정을 연다
function jumpToScene(sceneId: string) {
  const card = document.getElementById(`scene-${sceneId}`);
  if (!card) return;
  window.dispatchEvent(new CustomEvent(FOCUS_SCENE_EVENT, { detail: sceneId }));
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.classList.add("is-selected");
  window.setTimeout(() => card.classList.remove("is-selected"), 2000);
}

function DubResult({ projectId, dub }: { projectId: string; dub: DubInfo }) {
  const clean = dub.overruns.length === 0 && dub.beyond_video_sec <= 0;
  return (
    <div className="dub-result">
      {dub.stale && (
        <div className="fit-banner warn" style={{ marginTop: 0, marginBottom: 10 }}>
          만든 뒤 대본·음성·영상이 바뀌었습니다. 다시 만들어야 반영됩니다.
        </div>
      )}
      <video controls preload="metadata" src={`${urls.dubVideo(projectId)}?v=${dub.created_at}`} />
      <div className="btn-row" style={{ marginTop: 10 }}>
        <a className="btn" href={urls.dubVideo(projectId)} download>
          ⬇ 음성 입힌 mp4 ({formatBytes(dub.mp4_bytes)})
        </a>
        <a className="btn" href={urls.dubAudio(projectId)} download title="영상 길이에 맞춰 배치한 내레이션 — 편집기 0초에 맞춰 올리면 됩니다">
          ⬇ 영상 시각 기준 mp3
        </a>
        <a className="btn" href={urls.dubSrt(projectId)} download title="실제로 소리가 난 시각으로 만든 자막">
          ⬇ 영상 시각 기준 자막(SRT)
        </a>
        <span className="scene-meta">
          내레이션 끝 {formatSeconds(dub.narration_end_sec)} / 영상 {formatSeconds(dub.video_sec)}
          {dub.video_copied ? "" : " · 영상 다시 인코딩함"}
        </span>
      </div>

      {clean ? (
        <div className="fit-banner ok">✓ 모든 씬이 대본 시각 안에 들어갔습니다.</div>
      ) : (
        <div className="fit-banner warn">
          {dub.overruns.length > 0 && (
            <>
              <div>
                ⚠ 대본 시각을 넘친 씬 {dub.overruns.length}개 — 누르면 그 씬으로 이동합니다. 원고를 줄이거나 속도를
                올린 뒤 다시 만드세요.
              </div>
              <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                {dub.overruns.map((o) => (
                  <li key={o.scene_id}>
                    <button className="link-button" onClick={() => jumpToScene(o.scene_id)} title="그 씬으로 이동">
                      {String(o.number ?? o.position + 1).padStart(2, "0")} {o.title ?? "씬"}
                    </button>{" "}
                    <span className="mono">
                      {formatSeconds(o.start_sec)}–{formatSeconds(o.end_sec)}
                    </span>
                    {o.pushed_sec > 0 && ` · 앞 씬 때문에 ${o.pushed_sec.toFixed(1)}초 늦게 시작`}
                    {o.over_sec > 0 && ` · 끝 ${o.over_sec.toFixed(1)}초 넘침`} — {o.text}
                    {o.text.length >= 40 ? "…" : ""}
                  </li>
                ))}
              </ul>
            </>
          )}
          {dub.beyond_video_sec > 0 && (
            <div style={{ marginTop: dub.overruns.length > 0 ? 6 : 0 }}>
              ⚠ 내레이션이 영상보다 {dub.beyond_video_sec.toFixed(1)}초 깁니다 — 마지막 화면이 멈춘 채
              소리가 이어집니다.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
