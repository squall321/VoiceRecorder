# API 요청/응답 pydantic 스키마

from __future__ import annotations

from pydantic import BaseModel, Field


class ParseRequest(BaseModel):
    raw_script: str = Field(default="", max_length=200_000)


class ParsedSceneOut(BaseModel):
    index: int
    text: str
    number: int | None = None
    title: str | None = None
    target_start_sec: float | None = None
    target_end_sec: float | None = None
    target_duration_sec: float | None = None
    char_count: int


class ParseResponse(BaseModel):
    structured: bool
    scenes: list[ParsedSceneOut]


class ProjectCreate(BaseModel):
    title: str = Field(default="", max_length=200)
    raw_script: str = Field(default="", max_length=200_000)
    engine: str | None = None
    language: str | None = None
    voice_id: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    gap_ms: int = Field(default=400, ge=0, le=10_000)
    read_numbers: bool = True
    exaggeration: float = Field(default=0.5, ge=0.0, le=2.0)
    cfg_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    temperature: float = Field(default=0.8, ge=0.05, le=2.0)


class ProjectPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    engine: str | None = None
    language: str | None = None
    voice_id: str | None = None
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    gap_ms: int | None = Field(default=None, ge=0, le=10_000)
    read_numbers: bool | None = None
    exaggeration: float | None = Field(default=None, ge=0.0, le=2.0)
    cfg_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    temperature: float | None = Field(default=None, ge=0.05, le=2.0)


class ScriptReplace(BaseModel):
    raw_script: str = Field(max_length=200_000)


class ScenePatch(BaseModel):
    text: str | None = Field(default=None, max_length=20_000)
    title: str | None = Field(default=None, max_length=200)
    voice_id: str | None = None
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    gap_before_ms: int | None = Field(default=None, ge=0, le=10_000)
    gap_after_ms: int | None = Field(default=None, ge=0, le=10_000)
    exaggeration: float | None = Field(default=None, ge=0.0, le=2.0)
    cfg_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    temperature: float | None = Field(default=None, ge=0.05, le=2.0)
    # null 로 되돌려 프로젝트 기본값을 다시 따르게 하고 싶을 때 필드 이름을 넣는다
    reset: list[str] | None = None


class SceneCreate(BaseModel):
    text: str = Field(max_length=20_000)
    title: str | None = Field(default=None, max_length=200)
    after_scene_id: str | None = None


class ReorderRequest(BaseModel):
    scene_ids: list[str]


class ApplySpeedRequest(BaseModel):
    # 전 씬 속도를 이 값으로 통일한다 (씬별 override 를 지운다)
    speed: float = Field(ge=0.5, le=2.0)


class FitTimecodeRequest(BaseModel):
    # 슬롯을 넘치는 씬에 허용할 최대 배속. 이걸로도 안 되면 원고를 줄여야 한다.
    max_speed: float = Field(default=2.0, ge=1.0, le=2.0)


class SynthesizeRequest(BaseModel):
    # 비우면 합성이 필요한 씬(pending/stale/error)만 골라 돌린다
    scene_ids: list[str] | None = None
    force: bool = False


class DictionaryEntryIn(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=400)


class JobOut(BaseModel):
    id: str
    project_id: str
    kind: str
    status: str
    total: int
    done: int
    current: str | None = None
    error: str | None = None
    result: dict | None = None
