// 작업 진행 표시 — 대기 중·모델 로딩처럼 진척이 0 인 동안도 움직여 '멈춘 것처럼' 보이지 않게 한다

import type { Job } from "../types";

const KIND_LABEL: Record<string, string> = {
  synthesize: "합성 중",
  export: "병합 중",
  dub: "음성 입히는 중",
};

export function JobProgress({ job }: { job: Job }) {
  const queued = job.status === "queued";
  const ratio = job.total ? job.done / job.total : 0;
  const label = queued
    ? "대기 중 — 앞 작업이 끝나면 시작합니다"
    : `${KIND_LABEL[job.kind] ?? "작업 중"} · ${job.current ?? "준비"} (${job.done}/${job.total})`;
  return (
    <div role="status" aria-live="polite">
      <div className={`progress${queued || ratio === 0 ? " indeterminate" : ""}`}>
        <span style={{ width: `${Math.max(4, ratio * 100)}%` }} />
      </div>
      <p className="hint" style={{ margin: 0 }}>
        {label}
      </p>
    </div>
  );
}
