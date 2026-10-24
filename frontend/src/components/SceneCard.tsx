// 씬 하나 — 텍스트·읽는 법 편집, 개별 재생/재생성, 순서 이동, 씬별 화자·속도·간격 설정, 넘침·오독 안내

import { useEffect, useRef, useState } from "react";
import { urls } from "../api";
import { formatDrift, formatRange, formatSeconds, statusLabel, suggestSpeed, withRo } from "../format";
import type { DubOverrun, Scene, Voice } from "../types";
import { AutoTextarea, CommitNumber, CommitRange } from "./inputs";

// 음성 입힌 결과의 넘친 씬을 누르면 이 이벤트로 그 씬의 설정(속도)을 연다
export const FOCUS_SCENE_EVENT = "voicerec:focus-scene";

interface Props {
  scene: Scene;
  // 마지막 음성 입힌 영상에서 이 씬이 대본 시각을 넘쳤으면 그 내용 (stale 이면 지난 결과 기준)
  overrun?: DubOverrun;
  overrunStale?: boolean;
  projectId: string;
  voices: Voice[];
  canClone: boolean;
  busy: boolean;
  isFirst: boolean;
  isLast: boolean;
  onPatch: (patch: Record<string, unknown>) => Promise<unknown> | void;
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
  canClone,
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
  // 칸을 벗어나며 보낸 저장 — 곧바로 '다시 생성'을 누르면 이 저장이 끝난 뒤에 합성한다
  const inflight = useRef<Promise<unknown> | null>(null);

  // 서버가 새 값을 주면(재파싱·재정렬 등) 편집 중이 아닌 한 따라간다
  useEffect(() => setText(scene.text), [scene.id, scene.text]);
  useEffect(() => setReading(scene.reading ?? ""), [scene.id, scene.reading]);

  useEffect(() => {
    const onFocus = (event: Event) => {
      if ((event as CustomEvent<string>).detail === scene.id) setOpen(true);
    };
    window.addEventListener(FOCUS_SCENE_EVENT, onFocus);
    return () => window.removeEventListener(FOCUS_SCENE_EVENT, onFocus);
  }, [scene.id]);

  function save(patch: Record<string, unknown>) {
    const pending = Promise.resolve(onPatch(patch));
    inflight.current = pending;
    return pending;
  }

  // 읽는 법에 쌍 하나를 덧붙인다 — 이미 적어 둔 것은 지우지 않는다
  function addReading(pair: string) {
    const next = reading.trim() ? `${reading.trim()} · ${pair}` : pair;
    setReading(next);
    save({ reading: next });
  }

  async function synthesize() {
    if (inflight.current) await inflight.current;
    const patch: Record<string, unknown> = {};
    if (text !== scene.text) patch.text = text;
    if (reading !== (scene.reading ?? "")) patch.reading = reading;
    if (Object.keys(patch).length) await save(patch);
    onSynthesize();
  }

  function remove() {
    const hasAudio = scene.status === "ready" || scene.status === "stale";
    if (window.confirm(hasAudio ? "이 씬과 만든 음성을 지웁니다. 계속할까요?" : "이 씬을 지웁니다. 계속할까요?")) {
      onDelete();
    }
  }

  const drift = formatDrift(scene.drift_sec);
  const fit = suggestSpeed(scene.raw_duration_sec, scene.target_duration_sec);
  const label = String(scene.number ?? scene.position + 1).padStart(2, "0");
  const overrunFix = overrun ? speedToFit(overrun, scene.effective_speed) : null;

  return (
    <div className="scene" id={`scene-${scene.id}`}>
      <div className="scene-head">
        <span className="scene-num mono">{label}</span>
        {scene.title && <span className="scene-title">{scene.title}</span>}
        <span className={`badge ${scene.status}`}>{statusLabel(scene.status)}</span>
        {scene.target_start_sec !== null && (
          <span className="scene-meta mono" title="대본에 적힌 시각">
            대본 {formatRange(scene.target_start_sec, scene.target_end_sec)}
          </span>
        )}
        <span className="spacer" />
        {scene.duration_sec !== null && (
          <span className="scene-meta">
            {formatSeconds(scene.duration_sec)}
            {scene.target_duration_sec !== null && ` / 목표 ${formatSeconds(scene.target_duration_sec)}`}
          </span>
        )}
        {drift.text && <span className={drift.className}>{drift.text}</span>}
      </div>

      <AutoTextarea
        aria-label={`씬 ${label} 내레이션 (자막에도 쓰입니다)`}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onBlur={() => text !== scene.text && save({ text })}
      />

      <div className="reading-row">
        <label className="reading-label" htmlFor={`reading-${scene.id}`}>
          읽는 법
        </label>
        <input
          id={`reading-${scene.id}`}
          type="text"
          value={reading}
          placeholder="예: AI → 에이아이 · 응력 = 응녁 (→ 와 = 둘 다 됩니다 · 자막은 그대로, 소리만 바뀝니다)"
          onChange={(event) => setReading(event.target.value)}
          onBlur={() => reading !== (scene.reading ?? "") && save({ reading })}
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
              「{hint.word}」 — [{hint.heard}]로 들린 적 있음
              {hint.suggest ? (
                <button
                  className="btn small"
                  title="읽는 법에 이 우회 표기를 넣습니다 (자막은 그대로)"
                  onClick={() => addReading(`${hint.word} → ${hint.suggest}`)}
                >
                  「{hint.suggest}」{withRo(hint.suggest).slice(hint.suggest.length)} 읽기
                  {hint.confirmed ? "" : " (확인 필요)"}
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
          <div>
            ⚠ 음성 입힌 영상에서 {overrunMessage(overrun)}
            {overrunStale ? " (지난 결과 기준)" : ""}.
          </div>
          <div className="scene-meta mono">
            대본 {formatRange(overrun.target_start_sec, overrun.target_end_sec)} → 실제{" "}
            {formatRange(overrun.start_sec, overrun.end_sec)}
          </div>
          <div className="btn-row" style={{ marginTop: 4 }}>
            {overrunFix !== null && (
              <button className="btn small" disabled={busy} onClick={() => save({ speed: overrunFix })}>
                이 씬 속도 {overrunFix.toFixed(2)}×로 올려 맞추기
              </button>
            )}
            <span className="scene-meta">{overrunAdvice(overrun, overrunFix)}</span>
          </div>
        </div>
      )}

      {scene.error && <div className="scene-error">{scene.error}</div>}

      <div className="scene-actions">
        {scene.status === "ready" ? (
          <audio
            controls
            preload="none"
            aria-label={`씬 ${label} 듣기`}
            src={`${urls.sceneAudio(projectId, scene.id)}?v=${scene.duration_sec}`}
          />
        ) : (
          <span className="scene-meta">아직 생성되지 않았습니다</span>
        )}
        <span className="spacer" />
        <button className="btn small" onClick={synthesize} disabled={busy}>
          {scene.status === "ready" ? "다시 생성" : "음성 생성"}
        </button>
        <button className="btn icon" onClick={() => setOpen(!open)} title="씬 설정" aria-expanded={open}>
          {open ? "▲ 설정" : "▼ 설정"}
        </button>
        <button className="btn icon" onClick={() => onMove(-1)} disabled={isFirst || busy} title="위로" aria-label="위로">
          ↑
        </button>
        <button className="btn icon" onClick={() => onMove(1)} disabled={isLast || busy} title="아래로" aria-label="아래로">
          ↓
        </button>
        <button className="btn icon danger" onClick={remove} disabled={busy} title="씬 삭제" aria-label="씬 삭제">
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
                disabled={!canClone}
                onChange={(e) =>
                  e.target.value ? save({ voice_id: e.target.value }) : save({ reset: ["voice_id"] })
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
            <CommitRange
              value={scene.speed ?? scene.effective_speed}
              min={0.5}
              max={2}
              step={0.05}
              disabled={busy}
              label={(v) => `속도 (${v.toFixed(2)}×)`}
              onCommit={(v) => save({ speed: v })}
            />
            <CommitNumber
              label="앞 무음 (ms)"
              value={scene.gap_before_ms}
              min={0}
              max={5000}
              step={50}
              disabled={busy}
              onCommit={(v) => save({ gap_before_ms: v })}
            />
            <CommitNumber
              label="뒤 무음 (ms)"
              value={scene.gap_after_ms}
              min={0}
              max={5000}
              step={50}
              disabled={busy}
              onCommit={(v) => save({ gap_after_ms: v })}
            />
          </div>

          {fit !== null && Math.abs(fit - scene.effective_speed) > 0.02 && (
            <div className="btn-row" style={{ marginTop: 10 }}>
              <button className="btn small" disabled={busy} onClick={() => save({ speed: fit })}>
                목표 {formatSeconds(scene.target_duration_sec)}에 맞추기 (속도 {fit.toFixed(2)}×)
              </button>
            </div>
          )}

          <details style={{ marginTop: 12 }}>
            <summary style={{ cursor: "pointer", color: "var(--text-dim)", fontSize: 12.5 }}>
              고급 — 감정 강도 · 억양 안정성 · 무작위성 (Chatterbox 전용 · 바꾸면 음성을 다시 생성해야 합니다)
            </summary>
            <div className="grid cols-4" style={{ marginTop: 10 }}>
              <CommitRange
                value={scene.exaggeration ?? scene.effective_exaggeration}
                min={0}
                max={1.5}
                step={0.05}
                disabled={busy}
                label={(v) => `감정 강도 (${v.toFixed(2)})`}
                onCommit={(v) => save({ exaggeration: v })}
              />
              <CommitRange
                value={scene.cfg_weight ?? scene.effective_cfg_weight}
                min={0}
                max={1}
                step={0.05}
                disabled={busy}
                label={(v) => `억양 안정성 (${v.toFixed(2)})`}
                onCommit={(v) => save({ cfg_weight: v })}
              />
              <CommitRange
                value={scene.temperature ?? scene.effective_temperature}
                min={0.05}
                max={1.5}
                step={0.05}
                disabled={busy}
                label={(v) => `무작위성 (${v.toFixed(2)})`}
                onCommit={(v) => save({ temperature: v })}
              />
              <div style={{ display: "flex", alignItems: "flex-end" }}>
                <button
                  className="btn small"
                  disabled={busy}
                  onClick={() =>
                    save({ reset: ["speed", "exaggeration", "cfg_weight", "temperature", "voice_id"] })
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

function overrunMessage(overrun: DubOverrun): string {
  const parts: string[] = [];
  if (overrun.pushed_sec > 0) parts.push(`앞 씬이 길어 ${overrun.pushed_sec.toFixed(1)}초 늦게 시작했습니다`);
  if (overrun.over_sec > 0) parts.push(`끝이 대본보다 ${overrun.over_sec.toFixed(1)}초 넘쳤습니다`);
  return parts.join(" · ");
}

/** 넘친 까닭에 맞는 고칠 거리 — 앞 씬에 밀렸으면 앞 씬을, 속도로 못 맞추면 원고를 고치라고 알린다. */
function overrunAdvice(overrun: DubOverrun, fix: number | null): string {
  const cause =
    overrun.pushed_sec > 0
      ? "앞 씬의 원고를 줄이거나 앞 씬 속도를 올리면 제때 시작합니다. "
      : overrun.over_sec > 0 && fix === null
        ? "속도만으로는 맞추기 어렵습니다 — 원고를 줄여 주세요. "
        : "";
  return `${cause}바꾼 뒤 음성 입힌 영상을 다시 만드세요.`;
}

/** 이 씬이 대본 끝을 넘칠 때, 실제 시작부터 대본 끝 안에 들어가려면 필요한 속도 (2.0 을 넘으면 없음). */
function speedToFit(overrun: DubOverrun, current: number): number | null {
  if (overrun.over_sec <= 0 || overrun.target_end_sec === null) return null;
  const allowed = overrun.target_end_sec - overrun.start_sec;
  const spoken = overrun.end_sec - overrun.start_sec;
  if (allowed <= 0.3 || spoken <= 0) return null;
  const needed = Math.ceil(((current * spoken) / allowed) * 20) / 20;
  return needed > current && needed <= 2 ? needed : null;
}
