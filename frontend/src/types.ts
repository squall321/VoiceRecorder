// 백엔드 API 응답 타입 정의

export type SceneStatus = "pending" | "stale" | "ready" | "error";

export interface ParsedScene {
  index: number;
  text: string;
  number: number | null;
  title: string | null;
  target_start_sec: number | null;
  target_end_sec: number | null;
  target_duration_sec: number | null;
  char_count: number;
  reading: string | null;
}

export interface ParseResponse {
  structured: boolean;
  scenes: ParsedScene[];
}

export interface Project {
  id: string;
  title: string;
  raw_script: string;
  engine: string;
  language: string;
  voice_id: string | null;
  speed: number;
  gap_ms: number;
  read_numbers: boolean;
  exaggeration: number;
  cfg_weight: number;
  temperature: number;
  created_at: number;
  updated_at: number;
  scene_count?: number;
}

export interface Scene {
  id: string;
  project_id: string;
  position: number;
  number: number | null;
  title: string | null;
  text: string;
  // 읽는 법 — 'AI → 에이아이 · 6만 → 육만'. 자막(text)은 그대로, 합성 소리만 바뀐다
  reading: string | null;
  normalized_text: string;
  // 정규화 뒤에도 남은 영문 — 한국어 합성기가 건너뛸 수 있다
  unread_latin: string[];
  // 이 엔진이 잘못 읽었던 말 — suggest 를 읽는 법에 넣으면 우회된다(confirmed=false 는 아직 확인 안 됨)
  misread_hints: { word: string; heard: string; suggest: string | null; confirmed: boolean }[];
  target_start_sec: number | null;
  target_end_sec: number | null;
  target_duration_sec: number | null;
  voice_id: string | null;
  speed: number | null;
  gap_before_ms: number;
  gap_after_ms: number;
  exaggeration: number | null;
  cfg_weight: number | null;
  temperature: number | null;
  duration_sec: number | null;
  raw_duration_sec: number | null;
  status: SceneStatus;
  error: string | null;
  start_sec: number | null;
  end_sec: number | null;
  drift_sec: number | null;
  effective_speed: number;
  effective_voice_id: string | null;
  effective_exaggeration: number;
  effective_cfg_weight: number;
  effective_temperature: number;
}

export interface Job {
  id: string;
  project_id: string;
  kind: "synthesize" | "export" | "dub";
  status: "queued" | "running" | "done" | "error";
  total: number;
  done: number;
  current: string | null;
  error: string | null;
  result: Record<string, unknown> | null;
}

export interface FitReport {
  total_sec: number;
  over_budget: {
    number: number | null;
    title: string | null;
    target_sec: number;
    min_sec: number;
  }[];
}

export interface VideoInfo {
  filename: string;
  duration_sec: number;
  width: number | null;
  height: number | null;
  video_codec: string | null;
  has_audio: boolean;
  size_bytes: number;
  uploaded_at: number;
}

// 대본 시각에 못 맞춘 문장 — 앞 문장이 길어 밀렸거나(pushed) 목표 끝을 넘겼다(over)
export interface DubOverrun {
  scene_id: string;
  position: number;
  number: number | null;
  title: string | null;
  text: string;
  target_start_sec: number | null;
  target_end_sec: number | null;
  start_sec: number;
  end_sec: number;
  pushed_sec: number;
  over_sec: number;
}

export interface DubInfo {
  video_sec: number;
  narration_end_sec: number;
  total_sec: number;
  beyond_video_sec: number;
  scene_count: number;
  overruns: DubOverrun[];
  original_volume: number;
  video_copied: boolean;
  original_mixed: boolean;
  mp4_bytes: number;
  created_at: number;
  // 만든 뒤 대본·음성·영상이 바뀌었다
  stale: boolean;
}

export interface ProjectPayload {
  project: Project;
  scenes: Scene[];
  total_sec: number;
  ready_count: number;
  job: Job | null;
  fit_report?: FitReport;
  video: VideoInfo | null;
  dub: DubInfo | null;
}

export interface Engine {
  id: string;
  name: string;
  description: string;
  license: string;
  supports_voice_cloning: boolean;
  languages: Record<string, string>;
  available: boolean;
  detail: string;
  device: string | null;
}

export interface Voice {
  id: string;
  name: string;
  filename: string;
  duration_sec: number;
  transcript: string;
  created_at: number;
}

export interface DictionaryEntry {
  id: string;
  source: string;
  target: string;
  created_at: number;
}
