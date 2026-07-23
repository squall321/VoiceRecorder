// 우측 드로어 — 보이스 프로필 업로드/관리, 발음 사전, 엔진 라이선스 정보

import { useState } from "react";
import { api, urls } from "../api";
import type { DictionaryEntry, Engine, Voice } from "../types";

interface Props {
  engines: Engine[];
  voices: Voice[];
  dictionary: DictionaryEntry[];
  onClose: () => void;
  onRefresh: () => void;
  onError: (message: string) => void;
}

export function SettingsDrawer({ engines, voices, dictionary, onClose, onRefresh, onError }: Props) {
  const [voiceName, setVoiceName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");

  async function run(action: () => Promise<unknown>) {
    try {
      await action();
      onRefresh();
    } catch (err) {
      onError(String((err as Error).message ?? err));
    }
  }

  async function upload() {
    if (!file) return;
    setUploading(true);
    await run(() => api.uploadVoice(voiceName || file.name, file));
    setUploading(false);
    setFile(null);
    setVoiceName("");
  }

  const cloningEngine = engines.find((e) => e.supports_voice_cloning && e.available);

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer">
        <div className="btn-row" style={{ marginBottom: 16 }}>
          <h2 style={{ margin: 0 }}>설정</h2>
          <span className="spacer" />
          <button className="btn small" onClick={onClose}>
            닫기
          </button>
        </div>

        <div className="card">
          <h2>화자 (참조 음성)</h2>
          <p className="hint">
            {cloningEngine
              ? "3~10초 분량의 깨끗한 음성을 올리면 그 목소리로 내레이션을 만듭니다. wav·mp3·m4a 모두 됩니다."
              : "현재 사용 가능한 엔진이 음성 복제를 지원하지 않습니다."}
          </p>
          <div className="grid" style={{ gap: 8 }}>
            <input
              type="text"
              placeholder="이름 (예: 남성 차분한 톤)"
              value={voiceName}
              onChange={(e) => setVoiceName(e.target.value)}
            />
            <input
              type="file"
              accept="audio/*"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <button className="btn primary" onClick={upload} disabled={!file || uploading}>
              {uploading ? "올리는 중…" : "업로드"}
            </button>
          </div>

          <ul className="list-plain" style={{ marginTop: 12 }}>
            {voices.length === 0 && <li style={{ color: "var(--text-dim)" }}>등록된 화자 없음</li>}
            {voices.map((voice) => (
              <li key={voice.id}>
                <span style={{ flex: 1 }}>
                  {voice.name}{" "}
                  <span className="scene-meta">{voice.duration_sec.toFixed(1)}초</span>
                </span>
                <audio controls preload="none" src={urls.voiceAudio(voice.id)} style={{ width: 160 }} />
                <button
                  className="btn icon danger"
                  onClick={() => run(() => api.deleteVoice(voice.id))}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="card">
          <h2>발음 사전</h2>
          <p className="hint">
            모델이 잘못 읽는 약어·고유명사를 소리 나는 대로 바꿔 둡니다. 모든 프로젝트에 적용됩니다.
          </p>
          <div className="grid cols-2" style={{ gap: 8 }}>
            <input
              type="text"
              placeholder="원문 (HWAX)"
              value={source}
              onChange={(e) => setSource(e.target.value)}
            />
            <input
              type="text"
              placeholder="읽는 소리 (에이치왁스)"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            />
          </div>
          <button
            className="btn"
            style={{ marginTop: 8 }}
            disabled={!source.trim() || !target.trim()}
            onClick={() =>
              run(() =>
                api.addDictionaryEntry(source.trim(), target.trim()).then(() => {
                  setSource("");
                  setTarget("");
                }),
              )
            }
          >
            규칙 추가
          </button>

          <ul className="list-plain" style={{ marginTop: 12 }}>
            {dictionary.length === 0 && <li style={{ color: "var(--text-dim)" }}>규칙 없음</li>}
            {dictionary.map((entry) => (
              <li key={entry.id}>
                <span style={{ flex: 1 }}>
                  <code>{entry.source}</code> → {entry.target}
                </span>
                <button
                  className="btn icon danger"
                  onClick={() => run(() => api.deleteDictionaryEntry(entry.id))}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="card">
          <h2>TTS 엔진</h2>
          <p className="hint">상업 이용 가능한 라이선스(MIT)만 탑재했습니다.</p>
          <ul className="list-plain">
            {engines.map((engine) => (
              <li key={engine.id} style={{ flexDirection: "column", alignItems: "flex-start", gap: 2 }}>
                <span>
                  <span className={`badge ${engine.available ? "ready" : "pending"}`}>
                    {engine.available ? "사용 가능" : "미설치"}
                  </span>{" "}
                  <strong>{engine.name}</strong>
                </span>
                <span className="scene-meta">{engine.description}</span>
                <span className="scene-meta">라이선스: {engine.license}</span>
                <span className="scene-meta">{engine.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      </aside>
    </>
  );
}
