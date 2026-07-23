// 상단바의 TTS 엔진 상태 배지 — 어떤 디바이스로 도는지, 라이선스가 뭔지 바로 보여준다

import type { Engine } from "../types";

export function EngineStatus({ engines }: { engines: Engine[] }) {
  if (engines.length === 0) return null;
  const active = engines.find((e) => e.available) ?? engines[0];

  return (
    <span
      className={`badge ${active.available ? "info" : "error"}`}
      title={`${active.name} · ${active.license}\n${active.detail}`}
    >
      {active.available ? "●" : "○"} {active.name}
      {active.device ? ` · ${active.device}` : ""}
    </span>
  );
}
