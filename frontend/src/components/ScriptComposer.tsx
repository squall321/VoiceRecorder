// 스크립트 붙여넣기 → 씬 분할 미리보기 → 프로젝트 생성 화면

import { useEffect, useState } from "react";
import { api } from "../api";
import { formatSeconds } from "../format";
import type { Engine, ParseResponse, ProjectPayload, Voice } from "../types";

const SAMPLE = `01 오프닝 (0:00–0:08) "질문 하나가 의사결정문이 되기까지 — HWAX 협업진단 플랫폼. 방열 난제를 맡은 B책임의 하루를 따라가 봅니다."

02 문제 배정 (0:08–0:19) "신제품 초기안의 최고 온도는 83.4도. 허용 기준을 넘겼습니다. 히트파이프, 베이퍼 챔버, 그라파이트 — 열, 기구, 재료, 배치, 신뢰성, 원가까지. 여섯 분야가 얽힌 문제가 B책임 한 사람에게 떨어졌습니다."`;

interface Props {
  engines: Engine[];
  voices: Voice[];
  onCreated: (payload: ProjectPayload) => void;
  onCancel: () => void;
}

export function ScriptComposer({ engines, voices, onCreated, onCancel }: Props) {
  const [title, setTitle] = useState("");
  const [raw, setRaw] = useState("");
  const [parsed, setParsed] = useState<ParseResponse | null>(null);
  const [engine, setEngine] = useState(engines.find((e) => e.available)?.id ?? "chatterbox");
  const [voiceId, setVoiceId] = useState("");
  const [gapMs, setGapMs] = useState(400);
  const [speed, setSpeed] = useState(1.0);
  const [readNumbers, setReadNumbers] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // 입력이 멈춘 뒤에만 파싱한다 — 타이핑 중 매 글자마다 서버를 때리지 않게.
  useEffect(() => {
    if (!raw.trim()) {
      setParsed(null);
      return;
    }
    const timer = window.setTimeout(() => {
      api
        .parse(raw)
        .then(setParsed)
        .catch((err) => setError(String(err.message ?? err)));
    }, 350);
    return () => window.clearTimeout(timer);
  }, [raw]);

  const languages = engines.find((e) => e.id === engine)?.languages ?? { ko: "Korean" };

  async function create() {
    setBusy(true);
    setError("");
    try {
      const payload = await api.createProject({
        title,
        raw_script: raw,
        engine,
        language: "ko" in languages ? "ko" : Object.keys(languages)[0],
        voice_id: voiceId || null,
        gap_ms: gapMs,
        speed,
        read_numbers: readNumbers,
      });
      onCreated(payload);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {error && <div className="error-banner">{error}</div>}

      <div className="split">
        <div className="card">
          <h2>1. 스크립트 붙여넣기</h2>
          <p className="hint">
            <code>01 오프닝 (0:00–0:08) "본문"</code> 형식을 그대로 인식합니다. 번호·타임코드가
            없으면 빈 줄 기준으로 씬을 나눕니다.
          </p>
          <label className="field" style={{ marginBottom: 12 }}>
            제목 (비우면 첫 씬 제목을 씁니다)
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="HWAX 협업진단 플랫폼 소개 영상"
            />
          </label>
          <textarea
            rows={20}
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            placeholder={SAMPLE}
          />
          <div className="btn-row" style={{ marginTop: 10 }}>
            <button className="btn small" onClick={() => setRaw(SAMPLE)}>
              예시 넣기
            </button>
            <button className="btn small" onClick={() => setRaw("")} disabled={!raw}>
              비우기
            </button>
          </div>
        </div>

        <div>
          <div className="card">
            <h2>
              2. 씬 미리보기{" "}
              {parsed && (
                <span className={`badge ${parsed.structured ? "info" : "pending"}`}>
                  {parsed.structured ? "번호·타임코드 인식됨" : "문단 분할"}
                </span>
              )}
            </h2>
            {!parsed && <p className="hint">스크립트를 붙여넣으면 여기에 씬이 나뉘어 보입니다.</p>}
            {parsed && (
              <>
                <p className="hint">
                  씬 {parsed.scenes.length}개 · 총 {parsed.scenes.reduce((n, s) => n + s.char_count, 0)}자
                </p>
                <ol className="list-plain">
                  {parsed.scenes.map((scene) => (
                    <li key={scene.index}>
                      <span className="scene-num mono">
                        {String(scene.number ?? scene.index + 1).padStart(2, "0")}
                      </span>
                      <span style={{ flex: 1, minWidth: 0 }}>
                        {scene.title && <strong>{scene.title} </strong>}
                        <span style={{ color: "var(--text-dim)" }}>
                          {scene.text.length > 60 ? `${scene.text.slice(0, 60)}…` : scene.text}
                        </span>
                      </span>
                      {scene.target_duration_sec !== null && (
                        <span className="scene-meta">{formatSeconds(scene.target_duration_sec)}</span>
                      )}
                    </li>
                  ))}
                </ol>
              </>
            )}
          </div>

          <div className="card">
            <h2>3. 기본 설정</h2>
            <p className="hint">씬마다 따로 바꿀 수 있습니다. 여기서는 전체 기본값만 정합니다.</p>
            <div className="grid cols-2">
              <label className="field">
                TTS 엔진
                <select value={engine} onChange={(e) => setEngine(e.target.value)}>
                  {engines.map((item) => (
                    <option key={item.id} value={item.id} disabled={!item.available}>
                      {item.name} {item.available ? "" : "(사용 불가)"}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                화자
                <select value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
                  <option value="">기본 목소리</option>
                  {voices.map((voice) => (
                    <option key={voice.id} value={voice.id}>
                      {voice.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                씬 사이 무음 (ms)
                <input
                  type="number"
                  min={0}
                  max={5000}
                  step={50}
                  value={gapMs}
                  onChange={(e) => setGapMs(Number(e.target.value))}
                />
              </label>
              <label className="field">
                말 속도 ({speed.toFixed(2)}×)
                <input
                  type="range"
                  min={0.5}
                  max={2}
                  step={0.05}
                  value={speed}
                  onChange={(e) => setSpeed(Number(e.target.value))}
                />
              </label>
            </div>
            <label className="field" style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <input
                type="checkbox"
                checked={readNumbers}
                onChange={(e) => setReadNumbers(e.target.checked)}
                style={{ width: "auto" }}
              />
              숫자를 한글로 읽기 (83.4도 → 팔십삼 점 사 도)
            </label>

            <div className="btn-row" style={{ marginTop: 16 }}>
              <button
                className="btn primary"
                onClick={create}
                disabled={busy || !parsed || parsed.scenes.length === 0}
              >
                {busy ? "만드는 중…" : "프로젝트 만들기"}
              </button>
              <button className="btn" onClick={onCancel}>
                취소
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
