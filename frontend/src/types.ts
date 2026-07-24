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
  normalized_text: string;
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
  kind: "synthesize" | "export";
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

export interface ProjectPayload {
  project: Project;
  scenes: Scene[];
  total_sec: number;
  ready_count: number;
  job: Job | null;
  fit_report?: FitReport;
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
  created_at: number;
}

export interface DictionaryEntry {
  id: string;
  source: string;
  target: string;
  created_at: number;
}
