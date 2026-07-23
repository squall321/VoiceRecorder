// 시간·차이값 표시 헬퍼

export function formatSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const total = Math.max(0, value);
  const minutes = Math.floor(total / 60);
  const seconds = total - minutes * 60;
  return `${minutes}:${seconds.toFixed(1).padStart(4, "0")}`;
}

export function formatDrift(drift: number | null): { text: string; className: string } {
  if (drift === null) return { text: "", className: "" };
  const rounded = Math.round(drift * 10) / 10;
  if (Math.abs(rounded) < 0.35) return { text: "목표에 맞음", className: "drift fit" };
  if (rounded > 0) return { text: `+${rounded.toFixed(1)}초 초과`, className: "drift over" };
  return { text: `${rounded.toFixed(1)}초 부족`, className: "drift under" };
}

const STATUS_LABEL: Record<string, string> = {
  ready: "완료",
  stale: "변경됨",
  pending: "생성 전",
  error: "오류",
};

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

/** 목표 길이에 맞추려면 속도를 얼마로 두어야 하는지. 원본 길이 기준으로 계산한다. */
export function suggestSpeed(rawDuration: number | null, target: number | null): number | null {
  if (!rawDuration || !target || target <= 0) return null;
  const speed = rawDuration / target;
  if (speed < 0.5 || speed > 2.0) return null;
  return Math.round(speed * 100) / 100;
}
