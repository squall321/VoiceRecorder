// 모든 fetch URL 은 선행 슬래시 없는 상대경로다.
// 페이지가 /apps/voice_recorder/ 아래에서 서빙되면 "api/projects" 가 자동으로
// /apps/voice_recorder/api/projects 로 풀린다. 절대경로로 박으면 서브경로에서 깨진다.

import type {
  DictionaryEntry,
  Engine,
  Job,
  ParseResponse,
  Project,
  ProjectPayload,
  Voice,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers:
      init?.body instanceof FormData
        ? init?.headers
        : { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      /* 본문이 JSON 이 아니면 상태줄을 그대로 쓴다 */
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  engines: () => request<{ engines: Engine[]; default: string }>("api/engines"),

  parse: (raw_script: string) =>
    request<ParseResponse>("api/scripts/parse", {
      method: "POST",
      body: JSON.stringify({ raw_script }),
    }),

  listProjects: () => request<{ projects: Project[] }>("api/projects"),

  createProject: (payload: Record<string, unknown>) =>
    request<ProjectPayload>("api/projects", { method: "POST", body: JSON.stringify(payload) }),

  getProject: (id: string) => request<ProjectPayload>(`api/projects/${id}`),

  patchProject: (id: string, patch: Record<string, unknown>) =>
    request<ProjectPayload>(`api/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  replaceScript: (id: string, raw_script: string) =>
    request<ProjectPayload>(`api/projects/${id}/script`, {
      method: "PUT",
      body: JSON.stringify({ raw_script }),
    }),

  deleteProject: (id: string) => request<void>(`api/projects/${id}`, { method: "DELETE" }),

  addScene: (id: string, text: string, after_scene_id?: string) =>
    request<ProjectPayload>(`api/projects/${id}/scenes`, {
      method: "POST",
      body: JSON.stringify({ text, after_scene_id: after_scene_id ?? null }),
    }),

  patchScene: (id: string, sceneId: string, patch: Record<string, unknown>) =>
    request<ProjectPayload>(`api/projects/${id}/scenes/${sceneId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  deleteScene: (id: string, sceneId: string) =>
    request<ProjectPayload>(`api/projects/${id}/scenes/${sceneId}`, { method: "DELETE" }),

  reorder: (id: string, scene_ids: string[]) =>
    request<ProjectPayload>(`api/projects/${id}/scenes/reorder`, {
      method: "POST",
      body: JSON.stringify({ scene_ids }),
    }),

  // 전 씬 속도를 한 값으로 통일한다 (씬별 override 제거)
  applySpeed: (id: string, speed: number) =>
    request<ProjectPayload>(`api/projects/${id}/apply-speed`, {
      method: "POST",
      body: JSON.stringify({ speed }),
    }),

  // 전 씬을 스크립트 타임코드에 자동으로 맞춘다 (짧으면 무음, 넘치면 배속)
  fitTimecode: (id: string, maxSpeed = 2.0) =>
    request<ProjectPayload>(`api/projects/${id}/fit-timecode`, {
      method: "POST",
      body: JSON.stringify({ max_speed: maxSpeed }),
    }),

  synthesize: (id: string, scene_ids?: string[], force = false) =>
    request<{ job_id: string; scene_count: number }>(`api/projects/${id}/synthesize`, {
      method: "POST",
      body: JSON.stringify({ scene_ids: scene_ids ?? null, force }),
    }),

  exportProject: (id: string) =>
    request<{ job_id: string }>(`api/projects/${id}/export`, { method: "POST" }),

  job: (jobId: string) => request<Job>(`api/jobs/${jobId}`),

  listVoices: () => request<{ voices: Voice[] }>("api/voices"),

  uploadVoice: (name: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Voice>(`api/voices?name=${encodeURIComponent(name)}`, {
      method: "POST",
      body: form,
    });
  },

  deleteVoice: (voiceId: string) => request<void>(`api/voices/${voiceId}`, { method: "DELETE" }),

  listDictionary: () => request<{ entries: DictionaryEntry[] }>("api/dictionary"),

  addDictionaryEntry: (source: string, target: string) =>
    request<{ id: string }>("api/dictionary", {
      method: "POST",
      body: JSON.stringify({ source, target }),
    }),

  deleteDictionaryEntry: (entryId: string) =>
    request<void>(`api/dictionary/${entryId}`, { method: "DELETE" }),
};

// 오디오·다운로드는 <audio src> / <a href> 로 직접 물리므로 URL 만 만들어 준다.
export const urls = {
  sceneAudio: (projectId: string, sceneId: string) =>
    `api/projects/${projectId}/scenes/${sceneId}/audio`,
  voiceAudio: (voiceId: string) => `api/voices/${voiceId}/audio`,
  exportAudio: (projectId: string) => `api/projects/${projectId}/export/audio`,
  exportSrt: (projectId: string) => `api/projects/${projectId}/export/srt`,
};
