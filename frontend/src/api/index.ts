const BASE = import.meta.env.VITE_API_BASE_URL || '/api';
export const ACTIVE_PROJECT_STORAGE_KEY = 'noval.active-project-id';

export function getActiveProjectId(): string {
  return localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY) || '';
}

export function setActiveProjectId(projectId: string): void {
  if (projectId) localStorage.setItem(ACTIVE_PROJECT_STORAGE_KEY, projectId);
  else localStorage.removeItem(ACTIVE_PROJECT_STORAGE_KEY);
}

export function getProjectStorageKey(baseKey: string): string {
  const projectId = getActiveProjectId();
  return projectId ? `${baseKey}.${projectId}` : `${baseKey}.unselected`;
}

function projectHeaders(): Record<string, string> {
  const projectId = getActiveProjectId();
  return projectId ? { 'X-Project-ID': projectId } : {};
}

export type ApiErrorKind = 'not_found' | 'http';

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.kind = status === 404 ? 'not_found' : 'http';
  }
}

export function isApiNotFoundError(error: unknown): error is ApiError {
  return error instanceof ApiError && error.kind === 'not_found';
}
const DEFAULT_TIMEOUT_MS = 60_000; // 60秒超时

async function request<T>(
  url: string,
  options?: RequestInit,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  includeProject = true,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const isFormData = options?.body instanceof FormData;
    const res = await fetch(`${BASE}${url}`, {
      ...options,
      headers: {
        ...(includeProject ? projectHeaders() : {}),
        ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
        ...options?.headers,
      },
      signal: controller.signal,
    });
    if (!res.ok) {
      const text = await res.text();
      let message = text || res.statusText;
      try {
        const parsed = JSON.parse(text) as { detail?: string };
        message = parsed.detail || message;
      } catch {
        // Keep the plain-text response.
      }
      throw new ApiError(message, res.status);
    }
    if (res.status === 204) return undefined as T;
    return res.json() as Promise<T>;
  } catch (e: unknown) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new Error('请求超时，请检查后端或模型 API。', { cause: e });
    }
    if (e instanceof TypeError) {
      throw new Error(`无法连接后端：${e.message}`, { cause: e });
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// ── Projects ──

export type ProjectType = 'continuation' | 'original' | 'analysis';
export type ProjectStatus = 'active' | 'archived';

export interface Project {
  schema_version: number;
  project_id: string;
  title: string;
  description: string;
  project_type: ProjectType;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  corpus_config: {
    mode: 'managed' | 'external_readonly' | 'none';
    source_paths: string[];
    read_only: boolean;
  };
  model_config_ref: Record<string, unknown>;
  current_book_plan_id: string | null;
  current_chapter_id: string | null;
  metadata: Record<string, unknown>;
  storage_mode: 'managed' | 'legacy';
  legacy: boolean;
  migration_state: string;
}

export interface ProjectSummary {
  project_id: string;
  title: string;
  status: ProjectStatus;
  storage_mode: 'managed' | 'legacy';
  corpus_chapter_count: number;
  corpus_word_count: number;
  temp_generation_count: number;
  official_chapter_count: number;
  active_task_count: number;
  current_chapter_id: string | null;
  analysis_profile_count: number;
  knowledge_ready: boolean;
  book_plan_exists: boolean;
  book_plan_accepted: boolean;
  chapter_plans_complete: boolean;
  chapter_plan_count: number;
  planned_chapter_count: number;
  quality_checked_count: number;
  current_chapter_order: number | null;
  current_chapter_title: string;
  current_chapter_status: ChapterWorkflowStatus | '';
  recent_tasks: Array<{
    task_id: string;
    title: string;
    status: LongTaskState;
    progress: number;
    stage: string;
    updated_at: string;
  }>;
  recent_official_chapters: Array<{
    chapter_id: string;
    order: number;
    title: string;
    word_count: number;
    updated_at: string;
  }>;
  recommended_step: string;
  recommended_action: string;
}

export function listProjects() {
  return request<Project[]>('/projects', undefined, DEFAULT_TIMEOUT_MS, false);
}

export function createProject(value: {
  title: string;
  description?: string;
  project_type: ProjectType;
}) {
  return request<Project>(
    '/projects',
    { method: 'POST', body: JSON.stringify(value) },
    DEFAULT_TIMEOUT_MS,
    false,
  );
}

export function getProjectSummary(projectId: string) {
  return request<ProjectSummary>(
    `/projects/${encodeURIComponent(projectId)}/summary`,
    undefined,
    DEFAULT_TIMEOUT_MS,
    false,
  );
}

// ── Corpus ──

export interface CorpusStats {
  total_volumes: number;
  total_chapters: number;
  total_words: number;
  processed_chapters: number;
}

export interface ChapterMeta {
  chapter_id: string;
  series_order: number;
  sub_order: string | null;
  volume_key: string;
  volume_display_name: string;
  chapter_order: number;
  title: string;
  word_count: number;
  dialogue_ratio: number;
  source_file: string;
  content_hash: string;
}

export interface Chapter extends ChapterMeta {
  content: string;
  status: string;
  created_at: string;
}

export function getCorpusStats() { return request<CorpusStats>('/corpus/stats'); }
export function listChapters(volume?: string) {
  const q = volume ? `?volume=${encodeURIComponent(volume)}` : '';
  return request<ChapterMeta[]>(`/corpus/chapters${q}`);
}
export function getChapter(id: string) { return request<Chapter>(`/corpus/chapters/${id}`); }
export async function uploadChapter(file: File) {
  const form = new FormData();
  form.append('file', file);
  return request<{ chapter_id: string; word_count: number }>(
    '/corpus/chapters/upload',
    { method: 'POST', body: form },
  );
}
export function deleteChapter(id: string) {
  return request<{deleted: string}>(`/corpus/chapters/${id}`, { method: 'DELETE' });
}

// ── Import ──

export interface ImportDetail {
  file: string;
  status: string;
  chapters_found: number;
  chapters_added: number;
  chapters_skipped: number;
  error_message: string;
}

export interface ImportReport {
  scanned_files: number;
  new_chapters: number;
  skipped_duplicates: number;
  failed_files: number;
  total_chapters_after: number;
  details: ImportDetail[];
  timestamp: string;
}

export function scanLocal() {
  return request<ImportReport>('/corpus/scan-local', { method: 'POST' }, 120_000);
}
export function getImportReport() {
  return request<ImportReport | null>('/corpus/import-report');
}

// ── Analysis ──

export interface DimensionResult {
  dimension: string;
  summary: string;
  details: Record<string, unknown>;
  examples: string[];
}

export interface StyleProfile {
  id: string;
  chapter_ids: string[];
  dimensions: DimensionResult[];
  global_summary: string;
  chapter_styles?: ChapterStyleJson[];
  warnings?: string[];
  created_at: string;
}

export interface ChapterStyleJson {
  narrative_pov: string;
  language_style: string;
  sentence_rhythm: string;
  dialogue_style: string;
  description_focus: string;
  emotional_tone: string;
  pacing: string;
  character_portrayal: string;
  worldbuilding_style: string;
  recurring_motifs: string[];
  taboo_or_constraints: string[];
  continuation_rules: string[];
}

export interface TaskStatus {
  task_id: string;
  status: string;
  progress: number;
  message: string;
}

export function listProfiles() { return request<StyleProfile[]>('/analysis/profiles'); }
export function getProfile(id: string) { return request<StyleProfile>(`/analysis/profiles/${id}`); }
export function startAnalysis(chapterId: string) {
  return request<TaskStatus>(`/analysis/analyze/${chapterId}`, { method: 'POST' });
}
export function getTaskStatus(taskId: string) { return request<TaskStatus>(`/analysis/tasks/${taskId}`); }

// ── Long-running tasks ──

export type LongTaskType = 'style_analysis' | 'knowledge_build' | 'generation' | 'revision' | 'book_plan' | 'chapter_review' | 'chapter_repair';
export type LongTaskState = 'pending' | 'running' | 'success' | 'partial_success' | 'failed' | 'cancelled';

export interface TaskError {
  type: string;
  message: string;
  http_status: number | null;
  is_timeout: boolean;
  is_api_key_error: boolean;
  is_json_parse_error: boolean;
}

export interface LongTask {
  task_id: string;
  type: LongTaskType;
  project_id: string;
  operation_type: string;
  target_id: string;
  user_visible_title: string;
  status: LongTaskState;
  progress: number;
  stage: string;
  message: string;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  input_summary: Record<string, unknown>;
  result: Record<string, unknown>;
  error: TaskError | null;
  logs: string[];
  current_segment: number;
  total_segments: number;
  partial_text: string;
  partial_word_count: number;
  draft_id: string;
  can_accept: boolean;
}

export function listTasks(limit = 50) {
  return request<LongTask[]>(`/tasks?limit=${limit}`);
}
export function getLongTask(taskId: string) {
  return request<LongTask>(`/tasks/${taskId}`);
}
export function cancelLongTask(taskId: string) {
  return request<LongTask>(`/tasks/${taskId}/cancel`, { method: 'POST' });
}
export function startStyleAnalysisTask(chapterId: string) {
  return request<LongTask>('/tasks/style-analysis/start', {
    method: 'POST',
    body: JSON.stringify({ chapter_id: chapterId }),
  });
}

// ── Generation ──

export interface CharacterProfile {
  name: string;
  aliases: string[];
  personality: string;
  speech_style: string;
  character_arc: string;
  key_quotes: string[];
  relationships: Record<string, string>;
}

export interface WorldSetting {
  category: string;
  name: string;
  description: string;
  related_characters: string[];
}

export interface PlotNode {
  volume: string;
  chapter_range: string;
  title: string;
  summary: string;
  is_foreshadowing: boolean;
  is_resolved: boolean;
  related_nodes: string[];
}

export interface Theme {
  name: string;
  description: string;
  typical_scenes: string[];
  key_passages: string[];
}

export interface KnowledgeBase {
  characters: CharacterProfile[];
  world_settings: WorldSetting[];
  plot_nodes: PlotNode[];
  themes: Theme[];
  style_knowledge?: GlobalStyleKnowledge | null;
  updated_at: string;
}

export interface GlobalStyleKnowledge {
  global_narrative_style: string;
  global_language_style: string;
  global_pacing_pattern: string;
  global_character_rules: string[];
  global_dialogue_rules: string[];
  global_worldbuilding_rules: string[];
  plot_continuity_rules: string[];
  do_not_write_list: string[];
  style_prompt_for_continuation: string;
  analyzed_chapter_count: number;
  skipped_chapter_ids: string[];
  warnings: string[];
  summary_source: string;
}

export interface GenerationRequest {
  start_chapter_id: string;
  source_anchor_chapter_id: string;
  plot_direction: string;
  target_word_count: number;
  mode: 'single' | 'chapter' | 'auto';
  draft_id: string;
  plan_id: string;
  append_to_draft: boolean;
  reference_chapter_ids: string[];
  pov_character: string;
  additional_instructions: string;
  generation_kind: 'chapter_generation' | 'continuation' | 'revision' | 'regeneration' | 'full_chapter';
}

export interface GenerationResult {
  id: string;
  request: GenerationRequest;
  content: string;
  generated_text: string;
  word_count: number;
  suggested_title: string;
  can_append_to_draft: boolean;
  accepted: boolean;
  is_partial: boolean;
  ending_status: 'ok' | 'repaired' | 'truncated' | 'partial' | 'failed';
  warning: string;
  can_repair: boolean;
  revision_mode: RevisionMode | '';
  original_word_count: number;
  revision_change_ratio: number;
  revision_change_level: string;
  revision_requires_confirmation: boolean;
  revision_failed: boolean;
  system_prompt_used: string;
  generation_file_path: string;
  saved_draft_id: string;
  saved_draft_path: string;
  save_status: string;
  created_at: string;
}

export type RevisionMode = 'local_edit' | 'full_rewrite';

export interface DraftMeta {
  draft_id: string;
  title: string;
  source_anchor_chapter_id: string;
  notes: string;
  word_count: number;
  status: string;
  file_path: string;
  created_at: string;
  updated_at: string;
}

export interface DraftDetail extends DraftMeta {
  content: string;
}

export interface DraftVersion {
  version_id: string;
  draft_id: string;
  file_path: string;
  word_count: number;
  created_at: string;
}

export interface ProjectOutline {
  project_id: string;
  title: string;
  premise: string;
  main_conflict: string;
  tone: string;
  ending_direction: string;
  continuity_notes: string[];
  foreshadowing: string[];
  character_arcs: string[];
  prohibitions: string[];
  updated_at: string;
}

export interface ChapterPlanInput {
  draft_id: string;
  book_plan_id: string;
  title: string;
  order: number;
  anchor_chapter_id: string;
  target_words: number;
  chapter_summary: string;
  chapter_goal: string;
  opening_state: string;
  ending_state: string;
  previous_bridge: string;
  next_bridge: string;
  plot_beats: string[];
  chapter_function: string[];
  characters: string[];
  conflict: string;
  foreshadowing_to_plant: string[];
  foreshadowing_to_resolve: string[];
  emotional_tone: string;
  word_count_reason: string;
  ending_hook: string;
  status: ChapterWorkflowStatus;
}

export type ChapterWorkflowStatus =
  | 'unplanned'
  | 'planned'
  | 'generating'
  | 'draft_review'
  | 'quality_checked'
  | 'official'
  | 'archived';

export interface ChapterPlan extends ChapterPlanInput {
  plan_id: string;
  updated_at: string;
}

export interface BookPlanChapter {
  order: number;
  title: string;
  chapter_summary: string;
  chapter_goal: string;
  opening_state: string;
  ending_state: string;
  previous_bridge: string;
  next_bridge: string;
  plot_beats: string[];
  chapter_function: string[];
  characters: string[];
  conflict: string;
  foreshadowing_to_plant: string[];
  foreshadowing_to_resolve: string[];
  emotional_tone: string;
  word_count_reason: string;
  ending_hook: string;
  target_words: number;
}

export interface BookPlanGenerateRequest {
  source_anchor_chapter_id: string;
  rough_direction: string;
  target_scale: 'short' | 'medium' | 'long';
  target_chapter_count: number;
  automation_level: 'plan_only' | 'chapter_by_chapter' | 'continuous';
  auto_create_chapter_plans: boolean;
}

export interface BookPlan {
  book_plan_id: string;
  project_id: string;
  source_anchor_chapter_id: string;
  rough_direction: string;
  target_scale: 'short' | 'medium' | 'long';
  target_chapter_count: number;
  automation_level: 'plan_only' | 'chapter_by_chapter' | 'continuous';
  title: string;
  premise: string;
  core_theme: string;
  focus_characters: string[];
  main_conflict: string;
  hidden_conflict: string;
  central_mystery: string;
  relation_to_previous_books: string;
  old_foreshadowing_to_resolve: string[];
  new_foreshadowing_to_plant: string[];
  main_locations: string[];
  tone: string;
  opening_setup: string;
  midpoint_turn: string;
  ending_direction: string;
  continuity_notes: string[];
  character_arcs: string[];
  foreshadowing: string[];
  prohibitions: string[];
  chapters: BookPlanChapter[];
  model_name: string;
  prompt_chars: number;
  generation_source: string;
  accepted: boolean;
  accepted_at: string | null;
  chapter_plans_complete: boolean;
  chapter_plans_completed_at: string | null;
  file_path: string;
  created_at: string;
  updated_at: string;
}

export interface TempGeneration {
  temp_id: string;
  generation_id: string;
  chapter_order: number;
  chapter_title: string;
  record_type: string;
  content: string;
  word_count: number;
  accepted: boolean;
  saved_official: boolean;
  official_chapter_id: string;
  source_plan_id: string;
  generation_request: Record<string, unknown>;
  generation_status: string;
  warning: string;
  can_save: boolean;
  can_repair: boolean;
  file_path: string;
  created_at: string;
  updated_at: string;
}

export interface OfficialChapter {
  chapter_id: string;
  order: number;
  title: string;
  content: string;
  word_count: number;
  file_path: string;
  source_generation_id: string;
  source_plan_id: string;
  completeness_passed: boolean;
  saved_with_warnings: boolean;
  warnings: string[];
  chapter_plan_snapshot: Record<string, unknown>;
  revision_count: number;
  created_at: string;
  updated_at: string;
}

export interface WritingProjectManifest {
  project_id: string;
  title: string;
  book_plan_accepted: boolean;
  book_plan_file_path: string;
  official_chapter_count: number;
  temp_generation_count: number;
  created_at: string;
  updated_at: string;
}

export interface ContinuityIssue {
  level: 'error' | 'warning' | 'info';
  code: string;
  message: string;
}

export interface ContinuityCheckResult {
  draft_id: string;
  passed: boolean;
  word_count: number;
  issues: ContinuityIssue[];
  checked_at: string;
}

export function getKnowledgeBase() { return request<KnowledgeBase>('/generation/knowledge-base'); }
export function buildKnowledgeBase() {
  return request<KnowledgeBase>('/generation/knowledge-base/build', { method: 'POST' }, 90_000);
}
export function generateChapter(req: GenerationRequest) {
  return request<GenerationResult>(
    '/generation/generate',
    { method: 'POST', body: JSON.stringify(req) },
    120_000,
  );
}
export function startKnowledgeBuildTask(selectedChapterId?: string, summaryOnly = false) {
  return request<LongTask>('/tasks/knowledge-build/start', {
    method: 'POST',
    body: JSON.stringify({
      selected_chapter_id: selectedChapterId || null,
      summary_only: summaryOnly,
    }),
  });
}
export function startGenerationTask(req: GenerationRequest) {
  return request<LongTask>('/tasks/generation/start', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}
export function startChapterGeneration(req: GenerationRequest) {
  return request<LongTask>('/chapter-generation/start', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}
export function startFullChapterGeneration(req: GenerationRequest) {
  return request<LongTask>('/chapter-generation/full-chapter/start', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export interface ChapterCompletenessResult {
  plan_id: string;
  passed: boolean;
  can_save_official: boolean;
  word_count: number;
  target_word_count: number;
  minimum_word_count: number;
  maximum_word_count: number;
  sentence_complete: boolean;
  blocking_errors: ContinuityIssue[];
  warnings: ContinuityIssue[];
  info: ContinuityIssue[];
  issues: ContinuityIssue[];
  checked_at: string;
}

export function checkChapterCompleteness(planId: string, content: string) {
  return request<ChapterCompletenessResult>('/chapter-generation/check-completeness', {
    method: 'POST',
    body: JSON.stringify({ plan_id: planId, content }),
  });
}
export interface PlotBeatReview {
  beat: string;
  covered: boolean;
  evidence: string;
  comment: string;
}
export interface AIChapterReviewResult {
  plan_id: string;
  generation_id: string;
  overall_pass: boolean;
  score: number;
  summary_alignment: string;
  summary_aligned: boolean;
  plot_beats_coverage: PlotBeatReview[];
  ending_state_alignment: string;
  ending_state_aligned: boolean;
  continuity_with_previous: string;
  continuity_previous_pass: boolean;
  continuity_with_next: string;
  continuity_next_pass: boolean;
  character_consistency: string;
  character_consistent: boolean;
  style_consistency: string;
  style_consistent: boolean;
  problems: string[];
  repair_suggestions: string[];
  need_repair: boolean;
  semantic_overrides: string[];
  report_format: 'structured' | 'text';
  readable_report: string;
  raw_response: string;
  parse_warning: string;
  model_name: string;
  prompt_chars: number;
  reviewed_at: string;
}
export function startAIChapterReview(generationId: string, planId: string, content: string) {
  return request<LongTask>('/chapter-generation/ai-review/start', {
    method: 'POST',
    body: JSON.stringify({
      generation_id: generationId,
      plan_id: planId,
      content,
    }),
  });
}
export function startAIChapterRepair(
  generationId: string,
  planId: string,
  content: string,
  reviewReport: AIChapterReviewResult,
) {
  return request<LongTask>('/chapter-generation/ai-repair/start', {
    method: 'POST',
    body: JSON.stringify({
      generation_id: generationId,
      plan_id: planId,
      content,
      review_report: reviewReport,
    }),
  });
}
export function startRevisionTask(
  genId: string,
  feedback: string,
  targetSection: string,
  currentText: string,
  revisionMode: RevisionMode = 'local_edit',
) {
  return request<LongTask>('/tasks/revision/start', {
    method: 'POST',
    body: JSON.stringify({
      generation_id: genId,
      feedback,
      target_section: targetSection,
      current_text: currentText,
      revision_mode: revisionMode,
    }),
  });
}
export function listResults() { return request<GenerationResult[]>('/generation/results'); }
export function getResult(id: string) { return request<GenerationResult>(`/generation/results/${id}`); }
export function deleteResult(id: string) {
  return request<{ deleted: string }>(`/generation/results/${id}`, { method: 'DELETE' });
}
export function iterateChapter(
  genId: string,
  feedback: string,
  targetSection: string,
  currentText = '',
  revisionMode: RevisionMode = 'local_edit',
) {
  return request<GenerationResult>('/generation/iterate', {
    method: 'POST',
    body: JSON.stringify({
      generation_id: genId,
      feedback,
      target_section: targetSection,
      current_text: currentText,
      revision_mode: revisionMode,
    }),
  });
}

// ── Draft workspace ──

export function listDrafts() { return request<DraftMeta[]>('/drafts'); }
export function createDraft(title: string, sourceAnchorChapterId: string, notes = '') {
  return request<DraftDetail>('/drafts', {
    method: 'POST',
    body: JSON.stringify({
      title,
      source_anchor_chapter_id: sourceAnchorChapterId,
      notes,
    }),
  });
}
export function getDraft(id: string) { return request<DraftDetail>(`/drafts/${id}`); }
export function saveDraft(id: string, title: string, content: string, notes = '') {
  return request<DraftDetail>(`/drafts/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ title, content, notes }),
  });
}
export function appendDraft(id: string, generatedText: string, generationId = '') {
  return request<DraftDetail>(`/drafts/${id}/append`, {
    method: 'POST',
    body: JSON.stringify({
      generated_text: generatedText,
      generation_id: generationId,
    }),
  });
}
export function createDraftVersion(id: string) {
  return request<DraftVersion>(`/drafts/${id}/version`, { method: 'POST' });
}
export function listDraftVersions(id: string) {
  return request<DraftVersion[]>(`/drafts/${id}/versions`);
}
export function checkDraftContinuity(id: string) {
  return request<ContinuityCheckResult>(`/drafts/${id}/continuity-check`, {
    method: 'POST',
  });
}
export async function exportDraft(id: string, format: 'md' | 'txt') {
  const res = await fetch(`${BASE}/drafts/${encodeURIComponent(id)}/export`, {
    method: 'POST',
    headers: { ...projectHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ format }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(text || '导出失败', res.status);
  }
  return res.blob();
}

// ── Project planning ──

export function getProjectOutline() { return request<ProjectOutline>('/outline'); }
export function getBookPlan() { return request<BookPlan | null>('/book-plan'); }
export function generateBookPlan(value: BookPlanGenerateRequest) {
  return request<LongTask>('/book-plan/generate', {
    method: 'POST',
    body: JSON.stringify(value),
  });
}
export function reviseBookPlan(feedback: string) {
  return request<LongTask>('/book-plan/revise', {
    method: 'POST',
    body: JSON.stringify({ feedback }),
  });
}
export function acceptBookPlan() {
  return request<BookPlan>('/book-plan/accept', { method: 'POST' });
}
export function completeChapterPlans() {
  return request<LongTask>('/book-plan/complete-chapter-plans', {
    method: 'POST',
  });
}
export function reparseRawBookPlan(tempId: string) {
  return request<BookPlan>(`/book-plan/reparse-raw/${encodeURIComponent(tempId)}`, {
    method: 'POST',
  });
}
export function regenerateBookPlan(value: BookPlanGenerateRequest) {
  return request<LongTask>('/book-plan/regenerate', {
    method: 'POST',
    body: JSON.stringify(value),
  });
}
export function saveBookPlan(value: Omit<BookPlan, 'book_plan_id' | 'project_id' | 'model_name' | 'prompt_chars' | 'generation_source' | 'accepted' | 'accepted_at' | 'chapter_plans_complete' | 'chapter_plans_completed_at' | 'file_path' | 'created_at' | 'updated_at'>) {
  return request<BookPlan>('/book-plan', {
    method: 'PUT',
    body: JSON.stringify(value),
  });
}
export function applyBookPlanToChapterPlans() {
  return request<ChapterPlan[]>('/book-plan/apply-to-chapter-plans', {
    method: 'POST',
  });
}

export function getWritingProject() {
  return request<WritingProjectManifest>('/writing-project');
}
export function listTempGenerations() {
  return request<TempGeneration[]>('/temp-generations');
}
export function getTempGeneration(id: string) {
  return request<TempGeneration>(`/temp-generations/${id}`);
}
export function loadTempToEditor(id: string) {
  return request<TempGeneration>(`/temp-generations/${id}/load-to-editor`, {
    method: 'POST',
  });
}
export function deleteTempGeneration(id: string) {
  return request<{ deleted: string }>(`/temp-generations/${id}`, {
    method: 'DELETE',
  });
}
export function saveTempGeneration(value: {
  generation_id?: string;
  chapter_order: number;
  chapter_title: string;
  record_type: string;
  content: string;
  source_plan_id: string;
  generation_request?: Record<string, unknown>;
}) {
  return request<TempGeneration>('/chapter-generation/save-temp', {
    method: 'POST',
    body: JSON.stringify(value),
  });
}
export function listOfficialChapters() {
  return request<OfficialChapter[]>('/official-chapters');
}
export function getOfficialChapter(id: string) {
  return request<OfficialChapter>(`/official-chapters/${id}`);
}
export function saveOfficialChapter(value: {
  title: string;
  content: string;
  chapter_order?: number;
  source_generation_id?: string;
  source_temp_id?: string;
  source_plan_id?: string;
  official_chapter_id?: string;
  completeness_check?: Record<string, unknown>;
  chapter_plan_snapshot?: Record<string, unknown>;
}) {
  return request<OfficialChapter>('/chapter-generation/save-official', {
    method: 'POST',
    body: JSON.stringify(value),
  });
}
export function updateOfficialChapter(id: string, title: string, content: string) {
  return request<OfficialChapter>(`/official-chapters/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ title, content }),
  });
}
export function loadOfficialToEditor(id: string) {
  return request<TempGeneration>(`/official-chapters/${id}/load-to-editor`, {
    method: 'POST',
  });
}
export function deleteOfficialChapter(id: string) {
  return request<{ deleted: string }>(`/official-chapters/${id}`, {
    method: 'DELETE',
  });
}
export async function exportOfficialChapter(id: string, format: 'md' | 'txt') {
  const res = await fetch(`${BASE}/official-chapters/${encodeURIComponent(id)}/export`, {
    method: 'POST',
    headers: { ...projectHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ format }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(text || '导出失败', res.status);
  }
  return res.blob();
}
export function saveProjectOutline(value: Omit<ProjectOutline, 'project_id' | 'updated_at'>) {
  return request<ProjectOutline>('/outline', {
    method: 'PUT',
    body: JSON.stringify(value),
  });
}
export function listChapterPlans() { return request<ChapterPlan[]>('/chapter-plans'); }
export function createChapterPlan(value: ChapterPlanInput) {
  return request<ChapterPlan>('/chapter-plans', {
    method: 'POST',
    body: JSON.stringify(value),
  });
}
export function saveChapterPlan(id: string, value: ChapterPlanInput) {
  return request<ChapterPlan>(`/chapter-plans/${id}`, {
    method: 'PUT',
    body: JSON.stringify(value),
  });
}
export function deleteChapterPlan(id: string) {
  return request<{ deleted: string }>(`/chapter-plans/${id}`, {
    method: 'DELETE',
  });
}

// ── System ──

export interface ConfigStatus {
  has_api_key: boolean;
  base_url_configured: boolean;
  provider: string;
  model: string;
  env_loaded: boolean;
}

export function getConfigStatus() { return request<ConfigStatus>('/system/config-status'); }
