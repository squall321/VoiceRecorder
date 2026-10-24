// 서버에 저장하는 입력 부품 — 슬라이더는 손을 뗄 때, 숫자 칸은 칸을 벗어나거나 Enter 일 때 한 번만 저장한다

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { TextareaHTMLAttributes } from "react";

interface RangeProps {
  value: number;
  min: number;
  max: number;
  step: number;
  label: (value: number) => string;
  disabled?: boolean;
  onCommit: (value: number) => void;
}

/** 드래그하는 동안은 화면만 바꾸고, 손을 떼면(포인터·키보드·포커스 이탈) 바뀐 값을 한 번 저장한다.
 *  매 눈금마다 PATCH 하면 속도 하나 바꾸는 데 요청 여러 개가 나가고, 씬 wav 를 동시에 다시 렌더한다. */
export function CommitRange({ value, min, max, step, label, disabled, onCommit }: RangeProps) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    if (Math.abs(draft - value) > 1e-9) onCommit(draft);
  };
  return (
    <label className="field">
      {label(draft)}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(Number(event.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
      />
    </label>
  );
}

interface NumberProps {
  value: number;
  min: number;
  max: number;
  step: number;
  label: string;
  disabled?: boolean;
  onCommit: (value: number) => void;
}

/** 글자마다 저장하면 '1200' 을 치는 동안 1·12·120 이 차례로 저장된다 — 다 친 뒤에 한 번만 저장한다. */
export function CommitNumber({ value, min, max, step, label, disabled, onCommit }: NumberProps) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  const commit = () => {
    const parsed = Number(draft);
    if (draft.trim() === "" || Number.isNaN(parsed)) {
      setDraft(String(value));
      return;
    }
    const clamped = Math.min(max, Math.max(min, parsed));
    setDraft(String(clamped));
    if (clamped !== value) onCommit(clamped);
  };
  return (
    <label className="field">
      {label}
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
      />
    </label>
  );
}

/** 내용만큼 늘어나는 입력창 — 좁은 화면에서 글자 수로 줄 수를 어림하면 본문이 잘린다. */
export function AutoTextarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight + 2}px`;
  }, [props.value]);
  return <textarea ref={ref} rows={2} {...props} />;
}
