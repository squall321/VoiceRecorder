# 오프라인 가중치 확인 — 캐시가 비면 엔진이 '준비됨' 대신 이유와 함께 사용 불가로 보고한다

from __future__ import annotations

from pathlib import Path

import pytest

from app.tts import weights


def _snapshot(root: Path, folder: str) -> None:
    snap = root / folder / "snapshots" / "rev1"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}", encoding="utf-8")


@pytest.fixture()
def caches(tmp_path, monkeypatch):
    hf = tmp_path / "hf"
    ms = tmp_path / "ms"
    monkeypatch.setenv("HF_HOME", str(hf))
    monkeypatch.setenv("MODELSCOPE_CACHE", str(ms))
    return hf / "hub", ms / "models"


def test_online_never_blocks(caches, monkeypatch):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    assert weights.missing(["myshell-ai/MeloTTS-Korean"]) == []


def test_offline_reports_only_missing_repos(caches, monkeypatch):
    hub, ms = caches
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    _snapshot(hub, "models--myshell-ai--MeloTTS-Korean")
    _snapshot(ms, "pengzhendong--wetext")

    assert weights.missing(["myshell-ai/MeloTTS-Korean", "kykim/bert-kor-base"]) == ["kykim/bert-kor-base"]
    assert weights.missing([], modelscope=["pengzhendong/wetext"]) == []
    assert weights.missing([], modelscope=["other/fst"]) == ["other/fst"]


def test_empty_snapshot_folder_counts_as_missing(caches, monkeypatch):
    hub, _ = caches
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    (hub / "models--ResembleAI--chatterbox" / "snapshots" / "rev1").mkdir(parents=True)
    assert weights.missing(["ResembleAI/chatterbox"]) == ["ResembleAI/chatterbox"]


def test_missing_detail_is_short_and_actionable():
    detail = weights.missing_detail(["a/one", "b/two", "c/three"])
    assert "a/one, b/two 외 1개" in detail
    assert "models-from-drive.sh" in detail


def test_melo_engine_reports_missing_weights_offline(caches, monkeypatch):
    from app.tts.melo_engine import MELO_PYTHON, MeloEngine, _melo_installed

    if not (MELO_PYTHON.exists() and _melo_installed()):
        pytest.skip("MeloTTS 사이드카 venv 가 없는 환경")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    status = MeloEngine().status()
    assert status.available is False
    assert "가중치 없음" in status.detail
