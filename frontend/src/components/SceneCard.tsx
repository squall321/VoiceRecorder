// 씬 하나 — 텍스트 편집, 개별 재생/재생성, 순서 이동, 씬별 화자·속도·간격 설정

import { useEffect, useState } from "react";
import { urls } from "../api";
import { formatDrift, formatSeconds, statusLabel, suggestSpeed } from "../format";
import type { DubOverrun, Scene, Voice } from "../types";

interface Props {
  scene: Scene;
  // 마지막 음성 입힌 영상에서 이 씬이 대본 시각을 넘쳤으면 그 내용 (stale 이면 지난 결과 기준)
  overrun?: DubOverrun;
  overrunStale?: boolean;
  projectId: string;
  voices: Voice[];
  busy: boolean;
  isFirst: boolean;
  isLast: boolean;
  onPatch: (patch: Record<string, unknown>) => void;
  onSynthesize: () => void;
  onMove: (direction: -1 | 1) => void;
  onDelete: () => void;
}

export function SceneCard({
  scene,
  overrun,
  overrunStale = false,
  projectId,
  voices,
  busy,
  isFirst,
  isLast,
  onPatch,
  onSynthesize,
  onMove,
  onDelete,
}: Props) {
  const [text, setText] = useState(scene.text);
  const [reading, setReading] = useState(scene.reading ?? "");
  const [open, setOpen] = useState(false);

  // 서버가 새 값을 주면(재파싱·재정렬 등) 편집 중이 아닌 한 따라간다
  useEffect(() => setText(scene.text), [scene.id, scene.text]);
  useEffect(() => setReading(scene.reading ?? ""), [scene.id, scene.reading]);

  // 읽는 법에 쌍 하나를 덧붙인다 — 이미 적어 둔 것은 지우지 않는다
  function addReading(pair: string) {
    const next = reading.trim() ? `${reading.trim()} · ${pair}` : pair;
    setReading(next);
    onPatch({ reading: next });
  }

  const drift = formatDrift(scene.drift_sec);
  const fit = suggestSpeed(scene.raw_duration_sec, scene.target_duration_sec);
  const dirty = text !== scene.text;

  return (
    <div className="scene" id={`scene-${scene.id}`}>
      <div className="scene-head">
        <span className="scene-num mono">
          {String(scene.number ?? scene.position + 1).padStart(2, "0")}
        </span>
        {scene.title && <span className="scene-title">{scene.title}</span>}
        <span className={`badge ${scene.status}`}>{statusLabel(scene.status)}</span>
        <span className="spacer" />
        {scene.duration_sec !== null && (
          <span className="scene-meta">
            {formatSeconds(scene.duration_sec)}
            {scene.target_duration_sec !== null && ` / 목표 ${formatSeconds(scene.target_duration_sec)}`}
          </span>
        )}
        {drift.text && <span className={drift.className}>{drift.text}</span>}
      </div>

      <textarea
        rows={Math.min(8, Math.max(2, Math.ceil(text.length / 60)))}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onBlur={() => dirty && onPatch({ text })}
      />

      <div className="reading-row">
        <span className="reading-label">읽는 법</span>
        <input
          type="text"
          value={reading}
          placeholder="예: AI → 에이아이 · 응력 → 응녁  (자막은 그대로, 소리만 바뀝니다)"
          onChange={(event) => setReading(event.target.value)}
          onBlur={() => reading !== (scene.reading ?? "") && onPatch({ reading })}
          onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
        />
      </div>

      {scene.normalized_text !== scene.text && (
        <div className="normalized">읽는 소리: {scene.normalized_text}</div>
      )}

      {scene.unread_latin.length > 0 && (
        <div className="latin-warning">
          ⚠ 영문 {scene.unread_latin.join(", ")} — 합성기가 건너뛸 수 있습니다. 읽는 법에 「
          {scene.unread_latin[0]} → 한글 소리」처럼 적어 주세요.
        </div>
      )}

      {scene.misread_hints.length > 0 && (
        <div className="misread-hints">
          {scene.misread_hints.map((hint) => (
            <span key={hint.word} className="misread-hint">
              「{hint.word}」→ [{hint.heard}]로 들린 적 있음
              {hint.suggest ? (
                <button
                  className="btn small"
                  title="읽는 법에 이 우회 표기를 넣습니다 (자막은 그대로)"
                  onClick={() => addReading(`${hint.word} → ${hint.suggest}`)}
                >
                  「{hint.suggest}」로 읽기{hint.confirmed ? "" : " (확인 필요)"}
                </button>
              ) : (
                <span> — 다른 말로 바꿔 쓰는 것을 권합니다</span>
              )}
            </span>
          ))}
        </div>
      )}

      {overrun && (
        <div className="latin-warning">
          ⚠ 음성 입힌 영상에서
          {overrun.pushed_sec > 0 && ` ${overrun.pushed_sec.toFixed(1)}초 늦게 시작`}
          {overrun.pushed_sec > 0 && overrun.over_sec > 0 && " ·"}
          {overrun.over_sec > 0 && ` 끝이 ${overrun.over_sec.toFixed(1)}초 넘침`}
          {overrunStale ? " (지난 결과 기준)" : ""} — 원고를 줄이거나 이 씬 속도를 올린 뒤 다시 만드세요.
        </div>
      )}

      {scene.error && <div className="scene-error">{scene.error}</div>}

      <div className="scene-actions">
        {scene.status === "ready" ? (
          <audio controls preload="none" src={`${urls.sceneAudio(projectId, scene.id)}?v=${scene.duration_sec}`} />
        ) : (
          <span className="scene-meta">아직 생성되지 않았습니다</span>
        )}
        <span className="spacer" />
        <button className="btn small" onClick={onSynthesize} disabled={busy}>
          {scene.status === "ready" ? "다시 생성" : "음성 생성"}
        </button>
        <button className="btn icon" onClick={() => setOpen(!open)} title="씬 설정">
          {open ? "▲ 설정" : "▼ 설정"}
        </button>
        <button className="btn icon" onClick={() => onMove(-1)} disabled={isFirst || busy} title="위로">
          ↑
        </button>
        <button className="btn icon" onClick={() => onMove(1)} disabled={isLast || busy} title="아래로">
          ↓
        </button>
        <button className="btn icon danger" onClick={onDelete} disabled={busy} title="씬 삭제">
          ✕
        </button>
      </div>

      {open && (
        <div className="scene-settings">
          <div className="grid cols-4">
            <label className="field">
              화자
              <select
                value={scene.voice_id ?? ""}
                onChange={(e) =>
                  e.target.value
                    ? onPatch({ voice_id: e.target.value })
                    : onPatch({ reset: ["voice_id"] })
                }
              >
                <option value="">프로젝트 기본</option>
                {voices.map((voice) => (
                  <option key={voice.id} value={voice.id}>
                    {voice.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              속도 ({(scene.speed ?? scene.effective_speed).toFixed(2)}×)
              <input
                type="range"
                min={0.5}
                max={2}
                step={0.05}
                value={scene.speed ?? scene.effective_speed}
                onChange={(e) => onPatch({ speed: Number(e.target.value) })}
              />
            </label>
            <label className="field">
              앞 무음 (ms)
              <input
                type="number"
                min={0}
                max={5000}
                step={50}
                value={scene.gap_before_ms}
                onChange={(e) => onPatch({ gap_before_ms: Number(e.target.value) })}
              />
            </label>
            <label className="field">
              뒤 무음 (ms)
              <input
                type="number"
                min={0}
                max={5000}
                step={50}
                value={scene.gap_after_ms}
                onChange={(e) => onPatch({ gap_after_ms: Number(e.target.value) })}
              />
            </label>
          </div>

          {fit !== null && Math.abs(fit - scene.effective_speed) > 0.02 && (
            <div className="btn-row" style={{ marginTop: 10 }}>
              <button className="btn small" onClick={() => onPatch({ speed: fit })}>
                목표 {formatSeconds(scene.target_duration_sec)}에 맞추기 (속도 {fit.toFixed(2)}×)
              </button>
            </div>
          )}

          <details style={{ marginTop: 12 }}>
            <summary style={{ cursor: "pointer", color: "var(--text-dim)", fontSize: 12.5 }}>
              고급 — 감정 강도 · 억양 안정성 · 무작위성 (바꾸면 음성을 다시 생성해야 합니다)
            </summary>
            <div className="grid cols-4" style={{ marginTop: 10 }}>
              <label className="field">
                감정 강도 ({(scene.exaggeration ?? scene.effective_exaggeration).toFixed(2)})
                <input
                  type="range"
                  min={0}
                  max={1.5}
                  step={0.05}
                  value={scene.exaggeration ?? scene.effective_exaggeration}
                  onChange={(e) => onPatch({ exaggeration: Number(e.target.value) })}
                />
              </label>
              <label className="field">
                억양 안정성 ({(scene.cfg_weight ?? scene.effective_cfg_weight).toFixed(2)})
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={scene.cfg_weight ?? scene.effective_cfg_weight}
                  onChange={(e) => onPatch({ cfg_weight: Number(e.target.value) })}
                />
              </label>
              <label className="field">
                무작위성 ({(scene.temperature ?? scene.effective_temperature).toFixed(2)})
                <input
                  type="range"
                  min={0.05}
                  max={1.5}
                  step={0.05}
                  value={scene.temperature ?? scene.effective_temperature}
                  onChange={(e) => onPatch({ temperature: Number(e.target.value) })}
                />
              </label>
              <div style={{ display: "flex", alignItems: "flex-end" }}>
                <button
                  className="btn small"
                  onClick={() =>
                    onPatch({ reset: ["speed", "exaggeration", "cfg_weight", "temperature", "voice_id"] })
                  }
                >
                  프로젝트 기본값으로
                </button>
              </div>
            </div>
          </details>
        </div>
      )}
    </div>
  );
}
