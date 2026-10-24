// 상단바의 TTS 엔진 상태 배지 — 어떤 디바이스로 도는지, 라이선스가 뭔지 바로 보여준다

import type { Engine } from "../types";

/** 기본 엔진이 쓸 수 있으면 그것, 아니면 첫 가용 엔진 — 새 내레이션의 첫 선택도 같은 규칙을 쓴다. */
export function pickDefaultEngine(engines: Engine[], defaultEngine: string): Engine | undefined {
  return engines.find((e) => e.id === defaultEngine && e.available) ?? engines.find((e) => e.available);
}

export function EngineStatus({ engines, defaultEngine }: { engines: Engine[]; defaultEngine: string }) {
  if (engines.length === 0) return null;
  const active = pickDefaultEngine(engines, defaultEngine) ?? engines[0];

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
