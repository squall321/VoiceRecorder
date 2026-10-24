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
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers:
        init?.body instanceof FormData
          ? init?.headers
          : { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    // 브라우저는 연결 실패를 'Failed to fetch' 로만 알려 준다 — 사용자가 알아들을 말로 바꾼다
    throw new Error("서버에 연결하지 못했습니다 — 잠시 뒤 다시 시도해 주세요");
  }
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
  engines: () =>
    request<{ engines: Engine[]; default: string; default_speed: number; ffmpeg: boolean }>(
      "api/engines",
    ),

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

  // 영상은 수백 MB 라 XHR 로 올린다 — 업로드 진행률 이벤트가 fetch 에는 없다.
  // 바디는 파일 원본 그대로(multipart 아님), 파일 이름은 쿼리로 넘긴다.
  uploadVideo: (id: string, file: File, onProgress: (ratio: number) => void, signal?: AbortSignal) =>
    new Promise<ProjectPayload>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      signal?.addEventListener("abort", () => {
        xhr.abort();
        reject(new Error("영상 업로드를 취소했습니다"));
      });
      xhr.open("PUT", `api/projects/${id}/video?filename=${encodeURIComponent(file.name)}`);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(event.loaded / event.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText) as ProjectPayload);
          return;
        }
        let detail = `${xhr.status} ${xhr.statusText}`;
        try {
          const body = JSON.parse(xhr.responseText);
          if (typeof body?.detail === "string") detail = body.detail;
        } catch {
          /* 본문이 JSON 이 아니면 상태줄을 그대로 쓴다 */
        }
        reject(new Error(detail));
      };
      xhr.onerror = () => reject(new Error("영상 업로드 중 연결이 끊겼습니다"));
      xhr.send(file);
    }),

  deleteVideo: (id: string) =>
    request<ProjectPayload>(`api/projects/${id}/video`, { method: "DELETE" }),

  // 음성 입힌 영상 만들기 — 미생성 씬 합성 → 타임코드 배치 → 먹싱
  dub: (id: string, originalVolume: number) =>
    request<{ job_id: string; synthesize_count: number }>(`api/projects/${id}/dub`, {
      method: "POST",
      body: JSON.stringify({ original_volume: originalVolume }),
    }),

  job: (jobId: string) => request<Job>(`api/jobs/${jobId}`),

  listVoices: () => request<{ voices: Voice[] }>("api/voices"),

  uploadVoice: (name: string, file: File, transcript = "") => {
    const form = new FormData();
    form.append("file", file);
    const qs = `name=${encodeURIComponent(name)}&transcript=${encodeURIComponent(transcript)}`;
    return request<Voice>(`api/voices?${qs}`, { method: "POST", body: form });
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
  video: (projectId: string) => `api/projects/${projectId}/video`,
  dubVideo: (projectId: string) => `api/projects/${projectId}/dub/video`,
  dubAudio: (projectId: string) => `api/projects/${projectId}/dub/audio`,
  dubSrt: (projectId: string) => `api/projects/${projectId}/dub/srt`,
};
