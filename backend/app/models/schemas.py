from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator


# --- Corpus ---

class CorpusStatus(str, Enum):
    RAW = "raw"
    PROCESSING = "processing"
    PROCESSED = "processed"
    ERROR = "error"


class ChapterMeta(BaseModel):
    chapter_id: str
    series_order: int
    sub_order: str | None = None
    volume_key: str
    volume_display_name: str
    chapter_order: int
    title: str
    word_count: int
    dialogue_ratio: float = 0.0
    source_file: str = ""
    content_hash: str = ""


class Chapter(ChapterMeta):
    content: str
    status: CorpusStatus = CorpusStatus.RAW
    created_at: datetime = Field(default_factory=datetime.now)


class CorpusStats(BaseModel):
    total_volumes: int = 0
    total_chapters: int = 0
    total_words: int = 0
    processed_chapters: int = 0


# --- Style Analysis ---

class AnalysisDimension(str, Enum):
    NARRATIVE_PERSPECTIVE = "narrative_perspective"
    SENTENCE_RHYTHM = "sentence_rhythm"
    DIALOGUE_RATIO = "dialogue_ratio"
    EMOTIONAL_ATMOSPHERE = "emotional_atmosphere"
    IMAGERY = "imagery"
    DESCRIPTION_RATIO = "description_ratio"
    CHAPTER_STRUCTURE = "chapter_structure"
    CONFLICT_ADVANCEMENT = "conflict_advancement"
    CHARACTER_VOICE = "character_voice"
    CLIFFHANGER_STYLE = "cliffhanger_style"
    STYLE_SENSIBILITY = "style_sensibility"


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class DimensionResult(BaseModel):
    dimension: AnalysisDimension
    summary: str
    details: dict = Field(default_factory=dict)
    examples: list[str] = Field(default_factory=list)

    @field_validator("examples", mode="before")
    @classmethod
    def normalize_examples(cls, value) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, dict):
            return [
                f"{key}：{item}"
                for key, item in value.items()
                if item is not None and str(item).strip()
            ]
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, (list, tuple, set)):
            return [
                str(item)
                for item in value
                if item is not None and str(item).strip()
            ]
        return [str(value)]


def _normalize_string_list(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        return [
            f"{key}：{item}"
            for key, item in value.items()
            if item is not None and str(item).strip()
        ]
    if isinstance(value, (list, tuple, set)):
        return [
            str(item)
            for item in value
            if item is not None and str(item).strip()
        ]
    return [str(value)]


class ChapterStyleJson(BaseModel):
    narrative_pov: str = ""
    language_style: str = ""
    sentence_rhythm: str = ""
    dialogue_style: str = ""
    description_focus: str = ""
    emotional_tone: str = ""
    pacing: str = ""
    character_portrayal: str = ""
    worldbuilding_style: str = ""
    recurring_motifs: list[str] = Field(default_factory=list)
    taboo_or_constraints: list[str] = Field(default_factory=list)
    continuation_rules: list[str] = Field(default_factory=list)

    @field_validator(
        "recurring_motifs",
        "taboo_or_constraints",
        "continuation_rules",
        mode="before",
    )
    @classmethod
    def normalize_lists(cls, value) -> list[str]:
        return _normalize_string_list(value)


class ChapterStyleCacheEntry(BaseModel):
    chapter_id: str
    chapter_title: str
    content_hash: str
    model_name: str
    analyzed_at: datetime = Field(default_factory=datetime.now)
    style_json: ChapterStyleJson


class GlobalStyleKnowledge(BaseModel):
    global_narrative_style: str = ""
    global_language_style: str = ""
    global_pacing_pattern: str = ""
    global_character_rules: list[str] = Field(default_factory=list)
    global_dialogue_rules: list[str] = Field(default_factory=list)
    global_worldbuilding_rules: list[str] = Field(default_factory=list)
    plot_continuity_rules: list[str] = Field(default_factory=list)
    do_not_write_list: list[str] = Field(default_factory=list)
    style_prompt_for_continuation: str = ""
    analyzed_chapter_count: int = 0
    skipped_chapter_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary_source: str = "model"

    @field_validator(
        "global_character_rules",
        "global_dialogue_rules",
        "global_worldbuilding_rules",
        "plot_continuity_rules",
        "do_not_write_list",
        "skipped_chapter_ids",
        "warnings",
        mode="before",
    )
    @classmethod
    def normalize_lists(cls, value) -> list[str]:
        return _normalize_string_list(value)


class StyleProfile(BaseModel):
    id: str = ""
    chapter_ids: list[str] = Field(default_factory=list)
    dimensions: list[DimensionResult] = Field(default_factory=list)
    global_summary: str = ""
    chapter_styles: list[ChapterStyleJson] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)


# --- Knowledge Base ---

class CharacterProfile(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    personality: str = ""
    speech_style: str = ""
    character_arc: str = ""
    key_quotes: list[str] = Field(default_factory=list)
    relationships: dict[str, str] = Field(default_factory=dict)


class WorldSetting(BaseModel):
    category: str
    name: str
    description: str
    related_characters: list[str] = Field(default_factory=list)


class PlotNode(BaseModel):
    volume: str
    chapter_range: str
    title: str
    summary: str
    is_foreshadowing: bool = False
    is_resolved: bool = True
    related_nodes: list[str] = Field(default_factory=list)


class Theme(BaseModel):
    name: str
    description: str
    typical_scenes: list[str] = Field(default_factory=list)
    key_passages: list[str] = Field(default_factory=list)


class KnowledgeBase(BaseModel):
    characters: list[CharacterProfile] = Field(default_factory=list)
    world_settings: list[WorldSetting] = Field(default_factory=list)
    plot_nodes: list[PlotNode] = Field(default_factory=list)
    themes: list[Theme] = Field(default_factory=list)
    style_knowledge: GlobalStyleKnowledge | None = None
    updated_at: datetime = Field(default_factory=datetime.now)


# --- Generation ---

class GenerationMode(str, Enum):
    SINGLE = "single"
    CHAPTER = "chapter"
    AUTO = "auto"


class GenerationRequest(BaseModel):
    start_chapter_id: str
    source_anchor_chapter_id: str = ""
    plot_direction: str = ""
    target_word_count: int = Field(default=500, ge=300, le=8000)
    mode: GenerationMode = GenerationMode.SINGLE
    draft_id: str = ""
    plan_id: str = ""
    append_to_draft: bool = False
    reference_chapter_ids: list[str] = Field(default_factory=list)
    pov_character: str = ""
    additional_instructions: str = ""
    generation_kind: str = "chapter_generation"

    @model_validator(mode="after")
    def normalize_anchor(self):
        if not self.source_anchor_chapter_id:
            self.source_anchor_chapter_id = self.start_chapter_id
        self.reference_chapter_ids = list(dict.fromkeys(self.reference_chapter_ids))[:6]
        if self.generation_kind not in {
            "chapter_generation",
            "continuation",
            "revision",
            "regeneration",
            "full_chapter",
        }:
            self.generation_kind = "chapter_generation"
        return self


class GenerationResult(BaseModel):
    id: str
    request: GenerationRequest
    content: str
    generated_text: str = ""
    word_count: int = 0
    suggested_title: str = ""
    can_append_to_draft: bool = True
    accepted: bool = False
    is_partial: bool = False
    ending_status: str = "ok"
    warning: str = ""
    can_repair: bool = False
    revision_mode: str = ""
    original_word_count: int = 0
    revision_change_ratio: float = 1.0
    revision_change_level: str = ""
    revision_requires_confirmation: bool = False
    revision_failed: bool = False
    system_prompt_used: str = ""
    generation_file_path: str = ""
    saved_draft_id: str = ""
    saved_draft_path: str = ""
    save_status: str = "temporary"
    created_at: datetime = Field(default_factory=datetime.now)

    @model_validator(mode="after")
    def normalize_content(self):
        if not self.generated_text:
            self.generated_text = self.content
        if not self.content:
            self.content = self.generated_text
        if not self.word_count:
            self.word_count = len("".join(self.content.split()))
        self.can_append_to_draft = bool(self.content.strip())
        return self


class IterateRequest(BaseModel):
    generation_id: str
    feedback: str
    target_section: str = ""
    current_text: str = ""
    revision_mode: str = "local_edit"

    @model_validator(mode="after")
    def normalize_revision_mode(self):
        if self.revision_mode not in {"local_edit", "full_rewrite"}:
            self.revision_mode = "local_edit"
        return self


# --- Projects ---

_PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


class ProjectType(str, Enum):
    CONTINUATION = "continuation"
    ORIGINAL = "original"
    ANALYSIS = "analysis"


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class CorpusConfig(BaseModel):
    mode: str = "managed"
    source_paths: list[str] = Field(default_factory=list)
    read_only: bool = True

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        if value not in {"managed", "external_readonly", "none"}:
            raise ValueError("语料模式必须是 managed、external_readonly 或 none")
        return value


class Project(BaseModel):
    schema_version: int = 1
    project_id: str
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    project_type: ProjectType = ProjectType.ORIGINAL
    status: ProjectStatus = ProjectStatus.ACTIVE
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    corpus_config: CorpusConfig = Field(default_factory=CorpusConfig)
    model_config_ref: dict = Field(default_factory=dict)
    current_book_plan_id: str | None = None
    current_chapter_id: str | None = None
    metadata: dict = Field(default_factory=dict)
    storage_mode: str = "managed"
    legacy: bool = False
    migration_state: str = "not_required"

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _PROJECT_ID_PATTERN.fullmatch(normalized):
            raise ValueError(
                "project_id 只能包含小写字母、数字、下划线和连字符，长度 3-64"
            )
        return normalized

    @field_validator("storage_mode")
    @classmethod
    def validate_storage_mode(cls, value: str) -> str:
        if value not in {"managed", "legacy"}:
            raise ValueError("storage_mode 必须是 managed 或 legacy")
        return value


class ProjectCreateRequest(BaseModel):
    project_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    project_type: ProjectType = ProjectType.ORIGINAL
    corpus_config: CorpusConfig = Field(default_factory=CorpusConfig)
    model_config_ref: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)

    @field_validator("project_id")
    @classmethod
    def validate_optional_project_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip().lower()
        if not _PROJECT_ID_PATTERN.fullmatch(normalized):
            raise ValueError(
                "project_id 只能包含小写字母、数字、下划线和连字符，长度 3-64"
            )
        return normalized


class ProjectUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    corpus_config: CorpusConfig | None = None
    model_config_ref: dict | None = None
    current_book_plan_id: str | None = None
    current_chapter_id: str | None = None
    metadata: dict | None = None


class ProjectSummary(BaseModel):
    project_id: str
    title: str
    status: ProjectStatus
    storage_mode: str
    corpus_chapter_count: int = 0
    corpus_word_count: int = 0
    temp_generation_count: int = 0
    official_chapter_count: int = 0
    active_task_count: int = 0
    current_chapter_id: str | None = None
    analysis_profile_count: int = 0
    knowledge_ready: bool = False
    book_plan_exists: bool = False
    book_plan_accepted: bool = False
    chapter_plans_complete: bool = False
    chapter_plan_count: int = 0
    planned_chapter_count: int = 0
    quality_checked_count: int = 0
    current_chapter_order: int | None = None
    current_chapter_title: str = ""
    current_chapter_status: str = ""
    recent_tasks: list[dict] = Field(default_factory=list)
    recent_official_chapters: list[dict] = Field(default_factory=list)
    recommended_step: str = "import_corpus"
    recommended_action: str = "导入语料"


class ProjectDeleteResult(BaseModel):
    project_id: str
    deleted: bool = True
    recoverable: bool = True
    backup_path: str = ""
    trash_path: str = ""


class LegacyMigrationPreview(BaseModel):
    source_project_id: str
    source_paths: list[str] = Field(default_factory=list)
    chapter_count: int = 0
    total_words: int = 0
    derived_file_count: int = 0
    writable_file_count: int = 0
    estimated_copy_bytes: int = 0
    source_corpus_bytes: int = 0
    source_corpus_will_be_copied: bool = False
    warnings: list[str] = Field(default_factory=list)


class LegacyMigrationRequest(BaseModel):
    title: str = Field(default="本地续写项目", min_length=1, max_length=200)
    target_project_id: str | None = None
    confirm_source_project_id: str
    corpus_mode: str = "reference"

    @field_validator("target_project_id")
    @classmethod
    def validate_target_project_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip().lower()
        if not _PROJECT_ID_PATTERN.fullmatch(normalized):
            raise ValueError("迁移目标 project_id 格式不安全")
        return normalized

    @field_validator("corpus_mode")
    @classmethod
    def validate_corpus_mode(cls, value: str) -> str:
        if value not in {"reference", "copy"}:
            raise ValueError("corpus_mode 必须是 reference 或 copy")
        return value


class LegacyMigrationResult(BaseModel):
    source_project_id: str
    target_project_id: str
    backup_path: str
    copied_files: int
    copied_bytes: int
    chapter_count_before: int
    chapter_count_after: int
    total_words_before: int
    total_words_after: int
    source_untouched: bool = True
    rollback_available: bool = True


# --- API Common ---

class TaskStatus(BaseModel):
    task_id: str
    status: AnalysisStatus
    progress: float = 0.0
    message: str = ""


# --- Long-running tasks ---

class TaskType(str, Enum):
    STYLE_ANALYSIS = "style_analysis"
    KNOWLEDGE_BUILD = "knowledge_build"
    GENERATION = "generation"
    REVISION = "revision"
    BOOK_PLAN = "book_plan"
    CHAPTER_REVIEW = "chapter_review"
    CHAPTER_REPAIR = "chapter_repair"


class LongTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskError(BaseModel):
    type: str
    message: str
    http_status: int | None = None
    is_timeout: bool = False
    is_api_key_error: bool = False
    is_json_parse_error: bool = False


class LongTask(BaseModel):
    task_id: str
    type: TaskType
    project_id: str = ""
    operation_type: str = ""
    target_id: str = ""
    user_visible_title: str = ""
    status: LongTaskStatus = LongTaskStatus.PENDING
    progress: float = 0.0
    stage: str = "已创建任务"
    message: str = "任务等待执行"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    input_summary: dict = Field(default_factory=dict)
    result: dict = Field(default_factory=dict)
    error: TaskError | None = None
    logs: list[str] = Field(default_factory=list)
    current_segment: int = 0
    total_segments: int = 0
    partial_text: str = ""
    partial_word_count: int = 0
    draft_id: str = ""
    can_accept: bool = False


class StyleAnalysisTaskRequest(BaseModel):
    chapter_id: str


class KnowledgeBuildTaskRequest(BaseModel):
    selected_chapter_id: str | None = None
    summary_only: bool = False


# --- Continuation drafts ---

class DraftCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    source_anchor_chapter_id: str
    notes: str = Field(default="", max_length=4000)


class DraftUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = ""
    notes: str = Field(default="", max_length=4000)


class DraftAppendRequest(BaseModel):
    generated_text: str = Field(min_length=1)
    generation_id: str = ""


class DraftExportRequest(BaseModel):
    format: str = "md"

    @field_validator("format")
    @classmethod
    def validate_format(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"md", "txt"}:
            raise ValueError("导出格式只支持 md 或 txt")
        return normalized


class DraftMeta(BaseModel):
    draft_id: str
    title: str
    source_anchor_chapter_id: str
    notes: str = ""
    word_count: int = 0
    status: str = "draft"
    file_path: str
    created_at: datetime
    updated_at: datetime


class DraftDetail(DraftMeta):
    content: str = ""


class DraftVersion(BaseModel):
    version_id: str
    draft_id: str
    file_path: str
    word_count: int
    created_at: datetime


# --- Continuation project planning ---

class ProjectOutlineUpdate(BaseModel):
    title: str = Field(default="写作项目", max_length=200)
    premise: str = Field(default="", max_length=8000)
    main_conflict: str = Field(default="", max_length=8000)
    tone: str = Field(default="", max_length=4000)
    ending_direction: str = Field(default="", max_length=8000)
    continuity_notes: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    character_arcs: list[str] = Field(default_factory=list)
    prohibitions: list[str] = Field(default_factory=list)


class ProjectOutline(ProjectOutlineUpdate):
    project_id: str = "default"
    updated_at: datetime = Field(default_factory=datetime.now)


class ChapterPlanInput(BaseModel):
    draft_id: str = ""
    book_plan_id: str = ""
    title: str = Field(default="未命名章节规划", max_length=200)
    order: int = Field(default=1, ge=1, le=10000)
    anchor_chapter_id: str
    target_words: int = Field(default=2000, ge=300, le=8000)
    chapter_summary: str = Field(default="", max_length=8000)
    chapter_goal: str = Field(default="", max_length=8000)
    opening_state: str = Field(default="", max_length=8000)
    ending_state: str = Field(default="", max_length=8000)
    previous_bridge: str = Field(default="", max_length=8000)
    next_bridge: str = Field(default="", max_length=8000)
    plot_beats: list[str] = Field(default_factory=list)
    chapter_function: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    conflict: str = Field(default="", max_length=8000)
    foreshadowing_to_plant: list[str] = Field(default_factory=list)
    foreshadowing_to_resolve: list[str] = Field(default_factory=list)
    emotional_tone: str = Field(default="", max_length=4000)
    word_count_reason: str = Field(default="", max_length=4000)
    ending_hook: str = Field(default="", max_length=4000)
    status: str = "unplanned"

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        legacy = {"drafting": "draft_review", "done": "official"}
        normalized = legacy.get(value, value)
        allowed = {
            "unplanned",
            "planned",
            "generating",
            "draft_review",
            "quality_checked",
            "official",
            "archived",
        }
        if normalized not in allowed:
            raise ValueError("章节状态无效")
        return normalized


class ChapterPlan(ChapterPlanInput):
    plan_id: str
    updated_at: datetime = Field(default_factory=datetime.now)


class BookPlanChapter(BaseModel):
    order: int = Field(ge=1, le=10000)
    title: str = Field(default="未命名章节", max_length=200)
    chapter_summary: str = Field(default="", max_length=8000)
    chapter_goal: str = Field(default="", max_length=8000)
    opening_state: str = Field(default="", max_length=8000)
    ending_state: str = Field(default="", max_length=8000)
    previous_bridge: str = Field(default="", max_length=8000)
    next_bridge: str = Field(default="", max_length=8000)
    plot_beats: list[str] = Field(default_factory=list)
    chapter_function: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    conflict: str = Field(default="", max_length=8000)
    foreshadowing_to_plant: list[str] = Field(default_factory=list)
    foreshadowing_to_resolve: list[str] = Field(default_factory=list)
    emotional_tone: str = Field(default="", max_length=4000)
    word_count_reason: str = Field(default="", max_length=4000)
    ending_hook: str = Field(default="", max_length=4000)
    target_words: int = Field(default=2000, ge=300, le=8000)


class BookPlanGenerateRequest(BaseModel):
    source_anchor_chapter_id: str
    rough_direction: str = Field(default="", max_length=8000)
    target_scale: str = "medium"
    target_chapter_count: int = Field(default=12, ge=3, le=60)
    automation_level: str = "plan_only"
    auto_create_chapter_plans: bool = True

    @field_validator("target_scale")
    @classmethod
    def validate_target_scale(cls, value: str) -> str:
        if value not in {"short", "medium", "long"}:
            raise ValueError("target_scale must be short, medium, or long")
        return value

    @field_validator("automation_level")
    @classmethod
    def validate_automation_level(cls, value: str) -> str:
        if value not in {"plan_only", "chapter_by_chapter", "continuous"}:
            raise ValueError(
                "automation_level must be plan_only, chapter_by_chapter, or continuous"
            )
        return value


class BookPlanUpdate(BaseModel):
    source_anchor_chapter_id: str
    rough_direction: str = Field(default="", max_length=8000)
    target_scale: str = "medium"
    target_chapter_count: int = Field(default=12, ge=1, le=60)
    automation_level: str = "plan_only"
    title: str = Field(default="续写全书规划", max_length=200)
    premise: str = Field(default="", max_length=8000)
    core_theme: str = Field(default="", max_length=4000)
    focus_characters: list[str] = Field(default_factory=list)
    main_conflict: str = Field(default="", max_length=8000)
    hidden_conflict: str = Field(default="", max_length=8000)
    central_mystery: str = Field(default="", max_length=8000)
    relation_to_previous_books: str = Field(default="", max_length=8000)
    old_foreshadowing_to_resolve: list[str] = Field(default_factory=list)
    new_foreshadowing_to_plant: list[str] = Field(default_factory=list)
    main_locations: list[str] = Field(default_factory=list)
    tone: str = Field(default="", max_length=4000)
    opening_setup: str = Field(default="", max_length=8000)
    midpoint_turn: str = Field(default="", max_length=8000)
    ending_direction: str = Field(default="", max_length=8000)
    continuity_notes: list[str] = Field(default_factory=list)
    character_arcs: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    prohibitions: list[str] = Field(default_factory=list)
    chapters: list[BookPlanChapter] = Field(default_factory=list)


class BookPlan(BookPlanUpdate):
    book_plan_id: str = "book_plan_main"
    project_id: str = "default"
    model_name: str = ""
    prompt_chars: int = 0
    generation_source: str = "model"
    accepted: bool = False
    accepted_at: datetime | None = None
    chapter_plans_complete: bool = False
    chapter_plans_completed_at: datetime | None = None
    file_path: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class BookPlanRevisionRequest(BaseModel):
    feedback: str = Field(min_length=1, max_length=8000)


class TempGenerationCreate(BaseModel):
    generation_id: str = ""
    chapter_order: int = Field(default=0, ge=0, le=10000)
    chapter_title: str = Field(default="", max_length=200)
    record_type: str = "chapter_generation"
    content: str = ""
    source_plan_id: str = ""
    generation_request: dict = Field(default_factory=dict)
    generation_status: str = "success"
    warning: str = ""
    can_save: bool = True
    can_repair: bool = False


class TempGeneration(BaseModel):
    temp_id: str
    generation_id: str = ""
    chapter_order: int = 0
    chapter_title: str = ""
    record_type: str = "chapter_generation"
    content: str = ""
    word_count: int = 0
    accepted: bool = False
    saved_official: bool = False
    official_chapter_id: str = ""
    source_plan_id: str = ""
    generation_request: dict = Field(default_factory=dict)
    generation_status: str = "success"
    warning: str = ""
    can_save: bool = True
    can_repair: bool = False
    file_path: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class OfficialChapterSaveRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    chapter_order: int = Field(default=0, ge=0, le=10000)
    source_generation_id: str = ""
    source_temp_id: str = ""
    source_plan_id: str = ""
    official_chapter_id: str = ""
    completeness_check: dict = Field(default_factory=dict)
    chapter_plan_snapshot: dict = Field(default_factory=dict)


class OfficialChapterUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)


class OfficialChapter(BaseModel):
    chapter_id: str
    order: int
    title: str
    content: str = ""
    word_count: int = 0
    file_path: str
    source_generation_id: str = ""
    source_plan_id: str = ""
    completeness_passed: bool = True
    saved_with_warnings: bool = False
    warnings: list[str] = Field(default_factory=list)
    chapter_plan_snapshot: dict = Field(default_factory=dict)
    revision_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class WritingProjectManifest(BaseModel):
    project_id: str = "default"
    title: str = "本地写作项目"
    book_plan_accepted: bool = False
    book_plan_file_path: str = ""
    official_chapter_count: int = 0
    temp_generation_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ContinuityIssue(BaseModel):
    level: str
    code: str
    message: str


class ContinuityCheckResult(BaseModel):
    draft_id: str
    passed: bool
    word_count: int
    issues: list[ContinuityIssue] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=datetime.now)


class ChapterCompletenessRequest(BaseModel):
    plan_id: str
    content: str


class ChapterCompletenessResult(BaseModel):
    plan_id: str
    passed: bool
    can_save_official: bool
    word_count: int
    target_word_count: int
    minimum_word_count: int
    maximum_word_count: int
    sentence_complete: bool
    blocking_errors: list[ContinuityIssue] = Field(default_factory=list)
    warnings: list[ContinuityIssue] = Field(default_factory=list)
    info: list[ContinuityIssue] = Field(default_factory=list)
    issues: list[ContinuityIssue] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=datetime.now)


class PlotBeatReview(BaseModel):
    beat: str = ""
    covered: bool = False
    evidence: str = ""
    comment: str = ""


class AIChapterReviewRequest(BaseModel):
    generation_id: str = ""
    plan_id: str
    content: str = Field(min_length=1)


class AIChapterReviewResult(BaseModel):
    plan_id: str
    generation_id: str = ""
    overall_pass: bool = False
    score: int = Field(default=0, ge=0, le=100)
    summary_alignment: str = ""
    summary_aligned: bool = False
    plot_beats_coverage: list[PlotBeatReview] = Field(default_factory=list)
    ending_state_alignment: str = ""
    ending_state_aligned: bool = False
    continuity_with_previous: str = ""
    continuity_previous_pass: bool = False
    continuity_with_next: str = ""
    continuity_next_pass: bool = False
    character_consistency: str = ""
    character_consistent: bool = False
    style_consistency: str = ""
    style_consistent: bool = False
    problems: list[str] = Field(default_factory=list)
    repair_suggestions: list[str] = Field(default_factory=list)
    need_repair: bool = False
    semantic_overrides: list[str] = Field(default_factory=list)
    report_format: str = "structured"
    readable_report: str = ""
    raw_response: str = ""
    parse_warning: str = ""
    model_name: str = ""
    prompt_chars: int = 0
    reviewed_at: datetime = Field(default_factory=datetime.now)


class AIChapterRepairRequest(BaseModel):
    generation_id: str = ""
    plan_id: str
    content: str = Field(min_length=1)
    review_report: AIChapterReviewResult


# --- Import ---

class ImportDetail(BaseModel):
    file: str
    status: str = "ok"  # "ok" | "empty" | "error"
    chapters_found: int = 0
    chapters_added: int = 0
    chapters_skipped: int = 0
    error_message: str = ""


class ImportReport(BaseModel):
    scanned_files: int = 0
    new_chapters: int = 0
    skipped_duplicates: int = 0
    failed_files: int = 0
    total_chapters_after: int = 0
    details: list[ImportDetail] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)
