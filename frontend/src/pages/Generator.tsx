import { useCallback, useEffect, useRef, useState } from 'react';
import {
  acceptBookPlan,
  cancelLongTask,
  checkChapterCompleteness,
  completeChapterPlans,
  deleteOfficialChapter,
  deleteTempGeneration,
  exportOfficialChapter,
  generateBookPlan,
  getBookPlan,
  getConfigStatus,
  getProjectStorageKey,
  getLongTask,
  getOfficialChapter,
  getWritingProject,
  isApiNotFoundError,
  listChapterPlans,
  listChapters,
  listOfficialChapters,
  listTempGenerations,
  loadOfficialToEditor,
  loadTempToEditor,
  reparseRawBookPlan,
  reviseBookPlan,
  saveBookPlan,
  saveChapterPlan,
  saveDraft,
  saveOfficialChapter,
  saveTempGeneration,
  startAIChapterRepair,
  startAIChapterReview,
  startChapterGeneration,
  startFullChapterGeneration,
  startRevisionTask,
  type BookPlan,
  type BookPlanGenerateRequest,
  type AIChapterReviewResult,
  type ChapterMeta,
  type ChapterCompletenessResult,
  type ChapterPlan,
  type GenerationRequest,
  type GenerationResult,
  type LongTask,
  type OfficialChapter,
  type RevisionMode,
  type TempGeneration,
  type WritingProjectManifest,
} from '../api';
import TaskStatusPanel from '../components/TaskStatusPanel';

type WorkspaceTab = 'plan' | 'chapter' | 'temp' | 'official';
type GenerationAction = 'chapter_generation' | 'continuation' | 'regeneration';

const STORAGE_KEY = 'noval.continuation-workspace-v2';
const PROJECT_ROOT = '当前项目';

interface StoredState {
  activeTab: WorkspaceTab;
  bookPlanTaskId: string;
  generationTaskId: string;
  revisionTaskId: string;
  reviewTaskId: string;
  repairTaskId: string;
  selectedPlanId: string;
}

function loadStoredState(storageKey: string): StoredState {
  const fallback: StoredState = {
    activeTab: 'plan',
    bookPlanTaskId: '',
    generationTaskId: '',
    revisionTaskId: '',
    reviewTaskId: '',
    repairTaskId: '',
    selectedPlanId: '',
  };
  try {
    const raw = localStorage.getItem(storageKey);
    return raw ? { ...fallback, ...JSON.parse(raw) as Partial<StoredState> } : fallback;
  } catch {
    return fallback;
  }
}

function useLongTask(
  taskId: string,
  onUpdate: (task: LongTask) => void,
  onNotFound: () => void,
  onError: (message: string) => void,
) {
  const [task, setTask] = useState<LongTask | null>(null);

  useEffect(() => {
    if (!taskId) return;
    let disposed = false;
    let timer = 0;
    const refresh = async () => {
      try {
        const next = await getLongTask(taskId);
        if (disposed) return;
        setTask(next);
        onUpdate(next);
        if (['success', 'partial_success', 'failed', 'cancelled'].includes(next.status)) {
          window.clearInterval(timer);
        }
      } catch (error: unknown) {
        if (disposed) return;
        window.clearInterval(timer);
        if (isApiNotFoundError(error)) {
          setTask(null);
          onNotFound();
        } else {
          onError(error instanceof Error ? error.message : '任务状态读取失败');
        }
      }
    };
    void refresh();
    timer = window.setInterval(() => { void refresh(); }, 1500);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [taskId, onUpdate, onNotFound, onError]);

  return [task, setTask] as const;
}

export default function Generator() {
  const [storageKey] = useState(() => getProjectStorageKey(STORAGE_KEY));
  const [stored] = useState(() => loadStoredState(storageKey));
  const [activeTab, setActiveTab] = useState<WorkspaceTab>(stored.activeTab);
  const [chapters, setChapters] = useState<ChapterMeta[]>([]);
  const [bookPlan, setBookPlan] = useState<BookPlan | null>(null);
  const [plans, setPlans] = useState<ChapterPlan[]>([]);
  const [manifest, setManifest] = useState<WritingProjectManifest | null>(null);
  const [tempRecords, setTempRecords] = useState<TempGeneration[]>([]);
  const [officialChapters, setOfficialChapters] = useState<OfficialChapter[]>([]);
  const [selectedTemp, setSelectedTemp] = useState<TempGeneration | null>(null);
  const [selectedOfficial, setSelectedOfficial] = useState<OfficialChapter | null>(null);
  const [selectedPlanId, setSelectedPlanId] = useState(stored.selectedPlanId);

  const [roughDirection, setRoughDirection] = useState('');
  const [targetScale, setTargetScale] = useState<BookPlanGenerateRequest['target_scale']>('medium');
  const [targetChapterCount, setTargetChapterCount] = useState(18);
  const [planFeedback, setPlanFeedback] = useState('');

  const [editorTitle, setEditorTitle] = useState('');
  const [editorContent, setEditorContent] = useState('');
  const [editorGenerationId, setEditorGenerationId] = useState('');
  const [editorTempId, setEditorTempId] = useState('');
  const [editingOfficialId, setEditingOfficialId] = useState('');
  const [editorOfficialPath, setEditorOfficialPath] = useState('');
  const [revisionFeedback, setRevisionFeedback] = useState('');
  const [revisionTarget, setRevisionTarget] = useState('');
  const [revisionMode, setRevisionMode] = useState<RevisionMode>('local_edit');
  const [completeness, setCompleteness] = useState<ChapterCompletenessResult | null>(null);
  const [aiReview, setAIReview] = useState<AIChapterReviewResult | null>(null);
  const [repairCandidate, setRepairCandidate] = useState<{
    result: GenerationResult;
    temp: TempGeneration | null;
    completeness: ChapterCompletenessResult | null;
  } | null>(null);
  const [revisionCandidate, setRevisionCandidate] = useState<{
    result: GenerationResult;
    temp: TempGeneration | null;
    sourceSnapshot: TempGeneration | null;
    completeness: ChapterCompletenessResult | null;
    originalContent: string;
  } | null>(null);
  const [targetWords, setTargetWords] = useState(0);
  const [editingChapterPlan, setEditingChapterPlan] = useState(false);
  const editorContentRef = useRef('');

  const [bookPlanTaskId, setBookPlanTaskId] = useState(stored.bookPlanTaskId);
  const [generationTaskId, setGenerationTaskId] = useState(stored.generationTaskId);
  const [revisionTaskId, setRevisionTaskId] = useState(stored.revisionTaskId);
  const [reviewTaskId, setReviewTaskId] = useState(stored.reviewTaskId);
  const [repairTaskId, setRepairTaskId] = useState(stored.repairTaskId);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [notice, setNotice] = useState('');
  const [modelLabel, setModelLabel] = useState('');

  useEffect(() => {
    editorContentRef.current = editorContent;
  }, [editorContent]);

  const clearFeedback = useCallback(() => {
    setError('');
    setMessage('');
    setNotice('');
  }, []);

  const refreshWritingData = useCallback(async () => {
    const [nextManifest, nextTemps, nextOfficial, nextPlans] = await Promise.all([
      getWritingProject(),
      listTempGenerations(),
      listOfficialChapters(),
      listChapterPlans(),
    ]);
    setManifest(nextManifest);
    setTempRecords(nextTemps);
    setOfficialChapters(nextOfficial);
    setPlans(nextPlans);
  }, []);

  const runAction = useCallback(async <T,>(
    key: string,
    action: () => Promise<T>,
  ): Promise<T | undefined> => {
    if (busy) {
      setNotice('已有操作正在执行，请稍候。');
      return undefined;
    }
    setBusy(key);
    clearFeedback();
    try {
      return await action();
    } catch (actionError: unknown) {
      setError(actionError instanceof Error ? actionError.message : '操作失败');
      return undefined;
    } finally {
      setBusy('');
    }
  }, [busy, clearFeedback]);

  const handleBookPlanTask = useCallback((task: LongTask) => {
    if (task.status === 'success') {
      const nextPlan = task.result.book_plan as BookPlan | undefined;
      if (nextPlan) setBookPlan(nextPlan);
      setBookPlanTaskId('');
      setMessage(task.input_summary.operation === 'revise'
        ? '总体构想已按要求修改，请重新审核。'
        : task.input_summary.operation === 'complete_chapter_plans'
          ? `完整章节规划已生成，共 ${nextPlan?.chapters.length || 0} 章。`
          : '总体构想已生成，请先生成完整章节规划。');
      void refreshWritingData();
    } else if (task.status === 'failed' || task.status === 'cancelled') {
      setBookPlanTaskId('');
      if (task.status === 'failed' && task.result.raw_book_plan_text) {
        setNotice('结构化解析失败，但模型已返回原始构想文本并保存到临时记录。');
        void refreshWritingData();
      }
    }
  }, [refreshWritingData]);

  const handleGenerationTask = useCallback((task: LongTask) => {
    const partial = task.partial_text || String(task.result.partial_text || '');
    if (partial) setEditorContent(partial);
    if (task.status === 'success' || task.status === 'partial_success') {
      const result = task.result.generation_result as GenerationResult | undefined;
      if (result?.content) {
        const tempRecord = task.result.temp_generation as TempGeneration | undefined;
        const combined = result.request.generation_kind === 'continuation'
          ? [editorContentRef.current.trim(), result.content.trim()].filter(Boolean).join('\n\n')
          : result.content;
        setEditorContent(combined);
        setEditorGenerationId(result.id);
        setEditorTempId(tempRecord?.temp_id || '');
        setEditingOfficialId('');
        setEditorOfficialPath('');
          setCompleteness(
            task.result.completeness_check as ChapterCompletenessResult | null,
          );
          setAIReview(null);
          setRepairCandidate(null);
        const plan = plans.find((item) => item.plan_id === result.request.plan_id);
        if (plan) {
          setEditorTitle(plan.title);
          if (plan.draft_id) {
            void saveDraft(plan.draft_id, plan.title, combined).catch(() => undefined);
          }
        }
        if (task.status === 'partial_success') {
          setNotice(
            result.warning
            || String(task.result.warning || '')
            || '生成未完全通过末句检查，但正文已保留，可手动编辑或保存。',
          );
          setMessage('正文已载入编辑器并保存为临时记录。');
        } else {
          setMessage('本章草稿生成完成，当前仍是临时内容，尚未写入正式章节。');
        }
      }
      setGenerationTaskId('');
      void refreshWritingData();
    } else if (task.status === 'failed') {
      const result = task.result.generation_result as GenerationResult | undefined;
      const tempRecord = task.result.temp_generation as TempGeneration | undefined;
      if (result?.content) {
        setEditorContent(result.content);
        setEditorGenerationId(result.id);
        setEditorTempId(tempRecord?.temp_id || '');
        setCompleteness(
          (task.result.completeness_check as ChapterCompletenessResult | undefined)
          || null,
        );
        setNotice('生成未完全通过检查，但正文已保留，可手动编辑、保存临时记录或重新生成。');
      }
      setGenerationTaskId('');
      setError(task.error?.message || '章节生成失败，已生成的部分仍保留在编辑器中。');
      void refreshWritingData();
    } else if (task.status === 'cancelled') {
      setGenerationTaskId('');
      setNotice('生成已停止，已完成的部分仍保留在编辑器中。');
      void refreshWritingData();
    }
  }, [plans, refreshWritingData]);

  const handleRevisionTask = useCallback((task: LongTask) => {
    if (task.status === 'success' || task.status === 'partial_success') {
      const result = task.result.generation_result as GenerationResult | undefined;
      if (result?.content) {
        const tempRecord = task.result.temp_generation as TempGeneration | undefined;
        setRevisionCandidate({
          result,
          temp: tempRecord || null,
          sourceSnapshot: (
            task.result.source_snapshot as TempGeneration | undefined
          ) || null,
          completeness: (
            task.result.completeness_check as ChapterCompletenessResult | undefined
          ) || null,
          originalContent: String(task.result.original_text || editorContentRef.current),
        });
        if (task.status === 'partial_success') {
          setNotice(
            String(task.result.revision_warning || '')
            || result.warning
            || '修改候选版存在提醒，原文没有被覆盖。',
          );
          setMessage('修改候选版已保存，请对比原文后决定是否接受。');
        } else {
          setMessage('修改候选版已生成，原文保持不变。');
        }
      }
      setRevisionTaskId('');
      void refreshWritingData();
    } else if (task.status === 'failed' || task.status === 'cancelled') {
      const result = task.result.generation_result as GenerationResult | undefined;
      const tempRecord = task.result.temp_generation as TempGeneration | undefined;
      if (result?.content) {
        setRevisionCandidate({
          result,
          temp: tempRecord || null,
          sourceSnapshot: (
            task.result.source_snapshot as TempGeneration | undefined
          ) || null,
          completeness: null,
          originalContent: String(task.result.original_text || editorContentRef.current),
        });
        setNotice('修改未完全通过检查，候选版已保留，原文没有被覆盖。');
      }
      setRevisionTaskId('');
      if (task.status === 'failed') setError(task.error?.message || '修改失败');
    }
    }, [refreshWritingData]);

  const handleReviewTask = useCallback((task: LongTask) => {
    if (task.status === 'success' || task.status === 'partial_success') {
      const review = task.result.ai_review as AIChapterReviewResult;
      setAIReview(review);
      const latestRules = task.result.completeness_check as ChapterCompletenessResult | undefined;
      if (latestRules) setCompleteness(latestRules);
      setReviewTaskId('');
      setError('');
      if (review?.parse_warning || task.status === 'partial_success') {
        setNotice(review?.parse_warning || 'AI 深度质检完成，但报告为非结构化文本。');
        setMessage('AI 深度质检完成，文本报告已保留。报告只供审核，不会影响正式保存。');
      } else {
        setNotice('');
        setMessage('AI 深度质检完成。报告只供审核，不会自动修改正文。');
      }
      void refreshWritingData();
    } else if (task.status === 'failed' || task.status === 'cancelled') {
      setReviewTaskId('');
      if (task.status === 'failed') setError(task.error?.message || 'AI 深度质检失败');
    }
  }, [refreshWritingData]);

  const handleRepairTask = useCallback((task: LongTask) => {
    if (task.status === 'success') {
      const result = task.result.generation_result as GenerationResult | undefined;
      if (result?.content) {
        setRepairCandidate({
          result,
          temp: (task.result.temp_generation as TempGeneration | undefined) || null,
          completeness: (
            task.result.completeness_check as ChapterCompletenessResult | undefined
          ) || null,
        });
        setMessage('AI 修复候选版本已生成。原文尚未替换，请审核后决定是否采用。');
      }
      setRepairTaskId('');
      void refreshWritingData();
    } else if (task.status === 'failed' || task.status === 'cancelled') {
      setRepairTaskId('');
      if (task.status === 'failed') {
        setError(task.error?.message || 'AI 修复失败，原文保持不变');
      }
    }
  }, [refreshWritingData]);

  const handleTaskNotFound = useCallback((setter: (value: string) => void) => {
    setter('');
    setNotice('上次任务已随后端重启失效，本地已保存的构想、临时记录和正式章节不受影响。');
  }, []);

  const reportTaskError = useCallback((value: string) => setError(value), []);

  const [bookPlanTask, setBookPlanTask] = useLongTask(
    bookPlanTaskId,
    handleBookPlanTask,
    useCallback(() => handleTaskNotFound(setBookPlanTaskId), [handleTaskNotFound]),
    reportTaskError,
  );
  const [generationTask, setGenerationTask] = useLongTask(
    generationTaskId,
    handleGenerationTask,
    useCallback(() => handleTaskNotFound(setGenerationTaskId), [handleTaskNotFound]),
    reportTaskError,
  );
  const [revisionTask, setRevisionTask] = useLongTask(
    revisionTaskId,
    handleRevisionTask,
    useCallback(() => handleTaskNotFound(setRevisionTaskId), [handleTaskNotFound]),
    reportTaskError,
  );
  const [reviewTask, setReviewTask] = useLongTask(
    reviewTaskId,
    handleReviewTask,
    useCallback(() => handleTaskNotFound(setReviewTaskId), [handleTaskNotFound]),
    reportTaskError,
  );
  const [repairTask, setRepairTask] = useLongTask(
    repairTaskId,
    handleRepairTask,
    useCallback(() => handleTaskNotFound(setRepairTaskId), [handleTaskNotFound]),
    reportTaskError,
  );

  useEffect(() => {
    void (async () => {
      const loaded = await Promise.allSettled([
        listChapters(),
        getBookPlan(),
        listChapterPlans(),
        getWritingProject(),
        listTempGenerations(),
        listOfficialChapters(),
        getConfigStatus(),
      ]);
      if (loaded[0].status === 'fulfilled') setChapters(loaded[0].value);
      if (loaded[1].status === 'fulfilled') setBookPlan(loaded[1].value);
      if (loaded[2].status === 'fulfilled') setPlans(loaded[2].value);
      if (loaded[3].status === 'fulfilled') setManifest(loaded[3].value);
      if (loaded[4].status === 'fulfilled') setTempRecords(loaded[4].value);
      if (loaded[5].status === 'fulfilled') setOfficialChapters(loaded[5].value);
      if (loaded[6].status === 'fulfilled') {
        setModelLabel(`${loaded[6].value.provider} / ${loaded[6].value.model}`);
      }
      const latestChapter = loaded[0].status === 'fulfilled'
        ? loaded[0].value[loaded[0].value.length - 1]
        : null;
      if (latestChapter && !roughDirection) setNotice(`默认从原作末章《${latestChapter.title}》承接。`);
    })();
    // Initial workspace hydration only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    localStorage.setItem(storageKey, JSON.stringify({
      activeTab,
      bookPlanTaskId,
      generationTaskId,
      revisionTaskId,
      reviewTaskId,
      repairTaskId,
      selectedPlanId,
    }));
  }, [
    storageKey,
    activeTab,
    bookPlanTaskId,
    generationTaskId,
    revisionTaskId,
    reviewTaskId,
    repairTaskId,
    selectedPlanId,
  ]);

  const orderedPlans = [...plans]
    .filter((item) => (
      bookPlan
        ? item.book_plan_id === bookPlan.book_plan_id
        : Boolean(item.book_plan_id)
    ))
    .sort((a, b) => a.order - b.order);
  const currentPlan = orderedPlans.find((item) => item.plan_id === selectedPlanId)
    || orderedPlans.find((item) => item.status !== 'done')
    || orderedPlans[0]
    || null;
  const nextPlan = currentPlan
    ? orderedPlans.find((item) => item.order > currentPlan.order && item.status !== 'done')
      || orderedPlans.find((item) => item.order > currentPlan.order)
      || null
    : null;
  const bookPlanActive = bookPlanTask?.status === 'pending' || bookPlanTask?.status === 'running';
  const generationActive = generationTask?.status === 'pending' || generationTask?.status === 'running';
  const revisionActive = revisionTask?.status === 'pending' || revisionTask?.status === 'running';
  const reviewActive = reviewTask?.status === 'pending' || reviewTask?.status === 'running';
  const repairActive = repairTask?.status === 'pending' || repairTask?.status === 'running';
  const completenessIssues = completeness
    ? uniqueCompletenessIssues([
      ...(completeness.issues || []),
      ...(completeness.blocking_errors || []),
      ...(completeness.warnings || []),
      ...(completeness.info || []),
    ])
    : [];
  const blockingCompletenessIssues = completenessIssues.filter(
    (item) => isBlockingCompletenessIssue(item, completeness),
  );
  const completenessWarnings = completenessIssues.filter(
    (item) => item.level === 'warning'
      || (item.level === 'error' && !isBlockingCompletenessIssue(item, completeness)),
  );
  const officialSaveBlockingReasons = [
    !editorContent.trim() ? '正文为空' : '',
    !editorTitle.trim() ? '章节标题为空' : '',
    !currentPlan ? '未选择章节规划' : '',
    ...blockingCompletenessIssues.map((item) => item.message),
  ].filter(Boolean);
  const latestSourceChapter = chapters[chapters.length - 1];

  const startBookPlan = async () => {
    if (!latestSourceChapter) return setError('语料库中没有可用章节');
    await runAction('book-plan', async () => {
      setBookPlanTask(null);
      const task = await generateBookPlan({
        source_anchor_chapter_id: latestSourceChapter.chapter_id,
        rough_direction: roughDirection,
        target_scale: targetScale,
        target_chapter_count: targetChapterCount,
        automation_level: 'chapter_by_chapter',
        auto_create_chapter_plans: false,
      });
      setBookPlanTask(task);
      setBookPlanTaskId(task.task_id);
      setMessage('正在分析项目语料、知识库、风格与已有草稿，生成总体构想。');
    });
  };

  const saveCurrentBookPlan = async () => {
    if (!bookPlan) return setError('尚无总体构想可保存');
    await runAction('save-plan', async () => {
      const {
        book_plan_id: _bookPlanId,
        project_id: _projectId,
        model_name: _modelName,
        prompt_chars: _promptChars,
        generation_source: _generationSource,
        accepted: _accepted,
        accepted_at: _acceptedAt,
        chapter_plans_complete: _chapterPlansComplete,
        chapter_plans_completed_at: _chapterPlansCompletedAt,
        file_path: _filePath,
        created_at: _createdAt,
        updated_at: _updatedAt,
        ...payload
      } = bookPlan;
      void _bookPlanId; void _projectId; void _modelName; void _promptChars;
      void _generationSource; void _accepted; void _acceptedAt; void _filePath;
      void _chapterPlansComplete; void _chapterPlansCompletedAt;
      void _createdAt; void _updatedAt;
      const saved = await saveBookPlan(payload);
      setBookPlan(saved);
      await refreshWritingData();
      setMessage(`总体构想已保存到：${saved.file_path}`);
    });
  };

  const acceptCurrentBookPlan = async () => {
    if (!bookPlan) return setError('尚无总体构想可接受');
    await runAction('accept-plan', async () => {
      const accepted = await acceptBookPlan();
      setBookPlan(accepted);
      await refreshWritingData();
      setActiveTab('chapter');
      setMessage('总体构想已接受。章节生成现已解锁。');
    });
  };

  const startCompleteChapterPlans = async () => {
    if (!bookPlan) return setError('请先生成总体构想');
    await runAction('complete-plans', async () => {
      setBookPlanTask(null);
      const task = await completeChapterPlans();
      setBookPlanTask(task);
      setBookPlanTaskId(task.task_id);
      setMessage(`正在分批生成 ${bookPlan.target_chapter_count} 章完整规划。`);
    });
  };

  const submitPlanRevision = async () => {
    if (!planFeedback.trim()) return setError('请先输入总体构想修改要求');
    await runAction('revise-plan', async () => {
      setBookPlanTask(null);
      const task = await reviseBookPlan(planFeedback.trim());
      setBookPlanTask(task);
      setBookPlanTaskId(task.task_id);
      setPlanFeedback('');
      setMessage('总体构想修改任务已启动。');
    });
  };

  const reparseRawPlan = async () => {
    const tempId = String(bookPlanTask?.result.raw_temp_id || '');
    if (!tempId) return setError('没有可重新结构化的原始构想记录');
    await runAction('reparse-plan', async () => {
      const parsed = await reparseRawBookPlan(tempId);
      setBookPlan(parsed);
      await refreshWritingData();
      setMessage(`原始构想已成功结构化并保存到：${parsed.file_path}`);
    });
  };

  const openRawPlanRecord = async () => {
    const tempId = String(bookPlanTask?.result.raw_temp_id || '');
    if (!tempId) return setError('原始构想尚未保存');
    await runAction('open-raw-plan', async () => {
      const records = await listTempGenerations();
      const record = records.find((item) => item.temp_id === tempId);
      if (!record) throw new Error('原始构想临时记录不存在');
      setTempRecords(records);
      setSelectedTemp(record);
      setActiveTab('temp');
      setMessage(`原始构想已保存到：${record.file_path}`);
    });
  };

  const copyRawPlan = async () => {
    const rawText = String(bookPlanTask?.result.raw_book_plan_text || '');
    if (!rawText) return setError('没有可复制的原始构想文本');
    await runAction('copy-raw-plan', async () => {
      await navigator.clipboard.writeText(rawText);
      setMessage('原始构想文本已复制。');
    });
  };

  const startChapter = async (kind: GenerationAction) => {
    if (!bookPlan?.accepted) return setError('请先在“总体构想”页接受总体构想');
    if (!bookPlan.chapter_plans_complete) return setError('章节规划未完成，不能开始正式正文生成');
    if (!currentPlan) return setError('没有可用的章节规划');
    await runAction('generate', async () => {
      if (kind === 'continuation' && editorContent.trim() && currentPlan.draft_id) {
        await saveDraft(currentPlan.draft_id, editorTitle || currentPlan.title, editorContent);
      }
      if (kind !== 'continuation') {
        setEditorContent('');
        setEditorGenerationId('');
        setEditorTempId('');
        setEditingOfficialId('');
        setEditorOfficialPath('');
        setCompleteness(null);
        setAIReview(null);
        setRepairCandidate(null);
      }
      setSelectedPlanId(currentPlan.plan_id);
      setEditorTitle(currentPlan.title);
      setGenerationTask(null);
      const request: GenerationRequest = {
        start_chapter_id: currentPlan.anchor_chapter_id,
        source_anchor_chapter_id: currentPlan.anchor_chapter_id,
        plot_direction: '',
        target_word_count: kind === 'continuation' ? 500 : (targetWords || currentPlan.target_words),
        mode: kind === 'continuation' ? 'single' : 'chapter',
        draft_id: currentPlan.draft_id,
        plan_id: currentPlan.plan_id,
        append_to_draft: false,
        reference_chapter_ids: previousChapterIds(chapters, currentPlan.anchor_chapter_id),
        pov_character: '',
        additional_instructions: '',
        generation_kind: kind === 'chapter_generation' ? 'full_chapter' : kind,
      };
      const task = kind === 'continuation'
        ? await startChapterGeneration(request)
        : await startFullChapterGeneration(request);
      setGenerationTask(task);
      setGenerationTaskId(task.task_id);
      setMessage(kind === 'continuation'
        ? '正在继续生成高级追加段落。'
        : `正在一键生成第 ${currentPlan.order} 章完整草稿，内部会自动分段和检查。`);
    });
  };

  const submitRevision = async () => {
    if (!editorGenerationId) return setError('当前内容没有可供模型修改的生成记录');
    if (!revisionFeedback.trim()) return setError('请先输入修改要求');
    await runAction('revision', async () => {
      setRevisionTask(null);
      setRevisionCandidate(null);
      const task = await startRevisionTask(
        editorGenerationId,
        revisionFeedback.trim(),
        revisionTarget.trim(),
        editorContent,
        revisionMode,
      );
      setRevisionTask(task);
      setRevisionTaskId(task.task_id);
      setMessage('修改任务已启动。');
    });
  };

  const autoRepairChapter = async () => {
    if (!editorGenerationId) return setError('当前内容没有可供自动修复的生成记录');
    await runAction('revision', async () => {
      setRevisionTask(null);
      const task = await startRevisionTask(
        editorGenerationId,
        '修复章节完整性问题：补足必要情节与字数，确保覆盖章节规划、承接上一章、引出下一章；只在必要处修改，并确保最后一句完整。',
        '全文及结尾',
        editorContent,
        'local_edit',
      );
      setRevisionTask(task);
      setRevisionTaskId(task.task_id);
      setMessage('正在自动修复本章完整性问题。');
    });
  };

  const acceptRevisionCandidate = () => {
    if (!revisionCandidate) return;
    if (revisionCandidate.result.revision_failed) {
      setNotice('该候选版异常缩短，系统已禁止直接覆盖原文。请重新修改。');
      return;
    }
    setEditorContent(revisionCandidate.result.content);
    setEditorGenerationId(revisionCandidate.result.id);
    setEditorTempId(revisionCandidate.temp?.temp_id || '');
    setCompleteness(revisionCandidate.completeness);
    setAIReview(null);
    setRepairCandidate(null);
    setRevisionCandidate(null);
    setRevisionFeedback('');
    setRevisionTarget('');
    setMessage('已接受修改候选版。原文快照仍保留在临时记录中。');
  };

  const saveRevisionCandidateVersion = () => {
    if (!revisionCandidate) return;
    const path = revisionCandidate.temp?.file_path;
    setMessage(path
      ? `修改候选版已作为新版本保存在：${path}`
      : '修改候选版已保留在当前任务结果中。');
  };

  const startDeepReview = async () => {
    if (!currentPlan) return setError('当前正文未绑定章节规划');
    if (!editorContent.trim()) return setError('当前没有可质检的正文');
    await runAction('ai-review', async () => {
      setReviewTask(null);
      setRepairCandidate(null);
      const task = await startAIChapterReview(
        editorGenerationId,
        currentPlan.plan_id,
        editorContent,
      );
      setReviewTask(task);
      setReviewTaskId(task.task_id);
      setMessage('AI 正在对照章节规划、前后章和全书构想进行语义级质检。');
    });
  };

  const startReviewRepair = async () => {
    if (!currentPlan || !aiReview) return setError('请先完成 AI 深度质检');
    if (!editorContent.trim()) return setError('当前没有可修复的正文');
    await runAction('ai-repair', async () => {
      setRepairTask(null);
      setRepairCandidate(null);
      const task = await startAIChapterRepair(
        editorGenerationId,
        currentPlan.plan_id,
        editorContent,
        aiReview,
      );
      setRepairTask(task);
      setRepairTaskId(task.task_id);
      setMessage('正在根据质检报告生成最小修改候选版，原文不会被覆盖。');
    });
  };

  const acceptRepairCandidate = () => {
    if (!repairCandidate) return;
    setEditorContent(repairCandidate.result.content);
    setEditorGenerationId(repairCandidate.result.id);
    setEditorTempId(repairCandidate.temp?.temp_id || '');
    setCompleteness(repairCandidate.completeness);
    setAIReview(null);
    setRepairCandidate(null);
    setMessage('已接受 AI 修复版。请重新运行 AI 深度质检或直接继续人工审核。');
  };

  const saveCurrentChapterPlan = async () => {
    if (!currentPlan) return setError('没有可修改的章节规划');
    await runAction('save-chapter-plan', async () => {
      const { plan_id: _planId, updated_at: _updatedAt, ...payload } = currentPlan;
      void _planId; void _updatedAt;
      const saved = await saveChapterPlan(currentPlan.plan_id, {
        ...payload,
        target_words: targetWords || currentPlan.target_words,
      });
      setPlans((current) => current.map((item) => (
        item.plan_id === saved.plan_id ? saved : item
      )));
      setEditingChapterPlan(false);
      setMessage('本章规划已保存。');
    });
  };

  const saveEditorAsTemp = async () => {
    if (!editorContent.trim()) return setError('当前没有可保存的正文');
    await runAction('save-temp', async () => {
      const record = await saveTempGeneration({
        generation_id: editorGenerationId,
        chapter_order: currentPlan?.order || 0,
        chapter_title: editorTitle || currentPlan?.title || '未命名章节',
        record_type: 'manual_snapshot',
        content: editorContent,
        source_plan_id: currentPlan?.plan_id || '',
        generation_request: currentPlan ? {
          start_chapter_id: currentPlan.anchor_chapter_id,
          source_anchor_chapter_id: currentPlan.anchor_chapter_id,
          target_word_count: currentPlan.target_words,
          mode: 'chapter',
          draft_id: currentPlan.draft_id,
          plan_id: currentPlan.plan_id,
          _completeness_check: completeness,
          _ai_review: aiReview,
          _chapter_plan_snapshot: currentPlan,
        } : {},
      });
      setEditorTempId(record.temp_id);
      await refreshWritingData();
      setMessage(`临时记录已保存到：${record.file_path}`);
    });
  };

  const confirmOfficial = async () => {
    if (!editorContent.trim()) return setError('当前没有可保存的正文');
    if (!editorTitle.trim()) return setError('章节标题不能为空');
    if (!currentPlan) return setError('当前正文未绑定章节规划');
    await runAction('save-official', async () => {
      const latestCheck = await checkChapterCompleteness(
        currentPlan.plan_id,
        editorContent,
      );
      setCompleteness(latestCheck);
      if (!latestCheck.can_save_official) {
        const reasons = (latestCheck.blocking_errors || [])
          .map((item) => item.message)
          .join('；');
        throw new Error(reasons || '章节存在阻断性问题，请先修复后再保存');
      }
      if (
        (latestCheck.warnings || []).length > 0
        && !window.confirm('本章存在若干提醒，但不影响保存。是否仍然保存为正式章节？')
      ) {
        setNotice('已取消正式保存，正文和临时记录均未改变。');
        return;
      }
      const chapter = await saveOfficialChapter({
        title: editorTitle.trim(),
        content: editorContent,
        chapter_order: currentPlan?.order || selectedOfficial?.order || 0,
        source_generation_id: editorGenerationId,
        source_temp_id: editorTempId,
        source_plan_id: currentPlan?.plan_id || '',
        official_chapter_id: editingOfficialId,
        completeness_check: latestCheck as unknown as Record<string, unknown>,
        chapter_plan_snapshot: currentPlan as unknown as Record<string, unknown>,
      });
      setEditingOfficialId(chapter.chapter_id);
      setEditorOfficialPath(chapter.file_path);
      setSelectedOfficial(chapter);
      await refreshWritingData();
      setMessage(`已保存到：${chapter.file_path}。可继续进入下一章。`);
    });
  };

  const moveToNextPlan = () => {
    if (!nextPlan) return setNotice('当前已没有后续章节规划。');
    setSelectedPlanId(nextPlan.plan_id);
    setTargetWords(nextPlan.target_words);
    setEditorTitle(nextPlan.title);
    setEditorContent('');
    setEditorGenerationId('');
    setEditorTempId('');
    setEditingOfficialId('');
    setEditorOfficialPath('');
    setSelectedOfficial(null);
    setCompleteness(null);
    setAIReview(null);
    setRepairCandidate(null);
    setMessage(`已进入第 ${nextPlan.order} 章：${nextPlan.title}`);
  };

  const openTempInEditor = async (record: TempGeneration) => {
    await runAction('load-temp', async () => {
      const loaded = await loadTempToEditor(record.temp_id);
      setSelectedTemp(loaded);
      setEditorTitle(loaded.chapter_title);
      setEditorContent(loaded.content);
      setEditorGenerationId(loaded.generation_id);
      setEditorTempId(loaded.temp_id);
      setEditingOfficialId(loaded.official_chapter_id);
      setEditorOfficialPath(loaded.official_chapter_id
        ? `${PROJECT_ROOT}/official_chapters/${loaded.official_chapter_id}.md`
        : '');
      setCompleteness(
        (loaded.generation_request._completeness_check as ChapterCompletenessResult | undefined)
        || null,
      );
      setAIReview(
        (loaded.generation_request._ai_review as AIChapterReviewResult | undefined)
        || null,
      );
      setRepairCandidate(null);
      if (loaded.source_plan_id) {
        setSelectedPlanId(loaded.source_plan_id);
        const loadedPlan = plans.find((item) => item.plan_id === loaded.source_plan_id);
        if (loadedPlan) setTargetWords(loadedPlan.target_words);
      }
      setActiveTab('chapter');
      setMessage('临时记录已恢复到章节编辑器。');
    });
  };

  const openOfficialInEditor = async (chapter: OfficialChapter) => {
    await runAction('load-official', async () => {
      const record = await loadOfficialToEditor(chapter.chapter_id);
      setEditorTitle(chapter.title);
      setEditorContent(record.content);
      setEditorGenerationId(record.generation_id);
      setEditorTempId(record.temp_id);
      setEditingOfficialId(chapter.chapter_id);
      setEditorOfficialPath(chapter.file_path);
      setCompleteness(null);
      setAIReview(null);
      setRepairCandidate(null);
      if (chapter.source_plan_id) {
        setSelectedPlanId(chapter.source_plan_id);
        const loadedPlan = plans.find((item) => item.plan_id === chapter.source_plan_id);
        if (loadedPlan) setTargetWords(loadedPlan.target_words);
      }
      setActiveTab('chapter');
      setMessage('正式章节已加载到编辑器；再次确认保存时会先创建版本快照。');
    });
  };

  const removeOfficial = async (chapter: OfficialChapter) => {
    if (!window.confirm(`确认删除正式章节《${chapter.title}》？`)) return;
    if (!window.confirm('这是第二次确认。删除后正式章节文件将被移除，是否继续？')) return;
    await runAction('delete-official', async () => {
      await deleteOfficialChapter(chapter.chapter_id);
      if (selectedOfficial?.chapter_id === chapter.chapter_id) setSelectedOfficial(null);
      await refreshWritingData();
      setMessage('正式章节已删除。临时生成记录未受影响。');
    });
  };

  const downloadOfficial = async (chapter: OfficialChapter, format: 'md' | 'txt') => {
    await runAction('export', async () => {
      const blob = await exportOfficialChapter(chapter.chapter_id, format);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${chapter.chapter_id}.${format}`;
      anchor.click();
      URL.revokeObjectURL(url);
      setMessage(`已导出到 ${PROJECT_ROOT}/exports/，并开始浏览器下载。`);
    });
  };

  const stopTask = async (task: LongTask, setter: (task: LongTask) => void) => {
    await runAction('cancel', async () => {
      setter(await cancelLongTask(task.task_id));
      setNotice('已请求停止任务，已经生成的部分会保留。');
    });
  };

  return (
    <div>
      <div style={headerStyle}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22 }}>创作</h2>
          <div style={subtleStyle}>
            写作项目：{PROJECT_ROOT} · 模型：{modelLabel || '读取中'}
          </div>
        </div>
        <div style={{ textAlign: 'right', fontSize: 12, color: '#8a8a9a' }}>
          正式章节 {manifest?.official_chapter_count || 0} · 临时记录 {manifest?.temp_generation_count || 0}
        </div>
      </div>

      <div style={{ position: 'sticky', top: 8, zIndex: 5 }}>
        {error && <Banner color="#d78484" background="#321c1c">{error}</Banner>}
        {message && <Banner color="#72cf83" background="#17301d">{message}</Banner>}
        {notice && <Banner color="#b5b5c5" background="#22222d">{notice}</Banner>}
      </div>

      <div style={tabBarStyle}>
        {([
          ['plan', '1 总体构想'],
          ['chapter', '2 章节生成'],
          ['temp', '3 临时生成记录'],
          ['official', '4 正式章节库'],
        ] as [WorkspaceTab, string][]).map(([key, label]) => (
          <button
            key={key}
            className={activeTab === key ? 'btn-primary' : ''}
            onClick={() => setActiveTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'plan' && (
        <div style={twoPanelStyle}>
          <section className="bg-panel" style={panelStyle}>
            <h3 style={headingStyle}>一键构想下一部</h3>
            <p style={helpStyle}>
              粗略方向可以留空。系统会结合当前项目语料、知识库、风格规则和已有草稿生成总体构想。
            </p>
            <Field label="粗略方向（可留空）">
              <textarea
                value={roughDirection}
                onChange={(event) => setRoughDirection(event.target.value)}
                rows={5}
                style={wideStyle}
                placeholder="可以留空，系统会自动构想。"
              />
            </Field>
            <div style={twoColumnStyle}>
              <Field label="篇幅规模">
                <select value={targetScale} onChange={(event) => setTargetScale(event.target.value as BookPlanGenerateRequest['target_scale'])} style={wideStyle}>
                  <option value="short">短篇</option>
                  <option value="medium">中篇</option>
                  <option value="long">长篇</option>
                </select>
              </Field>
              <Field label="预计章节数">
                <input type="number" min={3} max={60} value={targetChapterCount} onChange={(event) => setTargetChapterCount(Number(event.target.value))} style={wideStyle} />
              </Field>
            </div>
            <div style={buttonRowStyle}>
              <PrimaryButton busy={busy === 'book-plan' || bookPlanActive} disabled={Boolean(busy) || bookPlanActive} onClick={() => { void startBookPlan(); }}>
                生成总体构想
              </PrimaryButton>
              {bookPlan && (
                <PrimaryButton busy={busy === 'book-plan' || bookPlanActive} disabled={Boolean(busy) || bookPlanActive} onClick={() => { void startBookPlan(); }}>
                  重新生成总体构想
                </PrimaryButton>
              )}
            </div>
            {bookPlanTask && (
              <TaskStatusPanel
                task={bookPlanTask}
                onCancel={() => { void stopTask(bookPlanTask, setBookPlanTask); }}
                onRetry={() => { void startBookPlan(); }}
              />
            )}
            {Boolean(bookPlanTask?.result.raw_book_plan_text) && bookPlanTask && (
              <div className="bg-panel-alt" style={{ padding: 12, marginTop: 12 }}>
                <div style={{ color: '#c9a96e', fontSize: 13, fontWeight: 600 }}>
                  结构化解析失败，但模型已返回原始构想文本
                </div>
                <div style={{ ...pathBoxStyle, marginTop: 8 }}>
                  Markdown：{String(bookPlanTask.result.raw_markdown_path || '')}<br />
                  JSON：{String(bookPlanTask.result.raw_json_path || '')}
                </div>
                <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 320, overflowY: 'auto', fontSize: 12, lineHeight: 1.7 }}>
                  {String(bookPlanTask.result.raw_book_plan_text)}
                </pre>
                <div style={buttonRowStyle}>
                  <PrimaryButton busy={busy === 'open-raw-plan'} disabled={Boolean(busy)} onClick={() => { void openRawPlanRecord(); }}>
                    保存为临时构想
                  </PrimaryButton>
                  <PrimaryButton busy={busy === 'reparse-plan'} disabled={Boolean(busy)} onClick={() => { void reparseRawPlan(); }}>
                    重新尝试结构化
                  </PrimaryButton>
                  <PrimaryButton busy={busy === 'copy-raw-plan'} disabled={Boolean(busy)} onClick={() => { void copyRawPlan(); }}>
                    复制原文
                  </PrimaryButton>
                  <PrimaryButton busy={busy === 'book-plan' || bookPlanActive} disabled={Boolean(busy) || bookPlanActive} onClick={() => { void startBookPlan(); }}>
                    重新生成
                  </PrimaryButton>
                </div>
              </div>
            )}
            <div className="bg-panel-alt" style={pathBoxStyle}>
              总体构想保存位置：<br />
              {PROJECT_ROOT}/planning/book_plan.json<br />
              {PROJECT_ROOT}/planning/book_plan.md
            </div>
          </section>

          <section className="bg-panel" style={panelStyle}>
            <div style={sectionHeaderStyle}>
              <div>
                <h3 style={{ ...headingStyle, marginBottom: 2 }}>总体构想审核</h3>
                <span style={{ color: bookPlan?.accepted ? '#72cf83' : '#c9a96e', fontSize: 12 }}>
                  {bookPlan?.accepted ? '已接受，可生成章节' : bookPlan ? '待审核' : '尚未生成'}
                </span>
              </div>
              <div style={buttonRowStyle}>
                <PrimaryButton busy={busy === 'save-plan'} disabled={!bookPlan || Boolean(busy)} onClick={() => { void saveCurrentBookPlan(); }}>保存构想</PrimaryButton>
                <PrimaryButton busy={busy === 'complete-plans' || bookPlanActive} disabled={!bookPlan || Boolean(busy) || bookPlanActive} onClick={() => { void startCompleteChapterPlans(); }}>
                  生成完整章节规划
                </PrimaryButton>
                <PrimaryButton busy={busy === 'accept-plan'} disabled={!bookPlan || Boolean(busy) || Boolean(bookPlan?.accepted) || !bookPlan?.chapter_plans_complete} onClick={() => { void acceptCurrentBookPlan(); }}>接受总体构想</PrimaryButton>
              </div>
            </div>
            {bookPlan && (
              <div style={{ ...pathBoxStyle, color: bookPlan.chapter_plans_complete ? '#72cf83' : '#c86e6e' }}>
                {bookPlan.chapter_plans_complete
                  ? `章节规划完整：${bookPlan.chapters.length}/${bookPlan.target_chapter_count} 章，可以接受并生成正文。`
                  : `章节规划未完成：请先点击“生成完整章节规划”，完成前不能生成正式正文。`}
              </div>
            )}
            {!bookPlan ? <p style={emptyStyle}>生成总体构想后，完整方案会显示在这里。</p> : (
              <>
                <Field label="书名"><input value={bookPlan.title} onChange={(event) => setBookPlan({ ...bookPlan, title: event.target.value })} style={wideStyle} /></Field>
                <Field label="本部故事"><textarea value={bookPlan.premise} onChange={(event) => setBookPlan({ ...bookPlan, premise: event.target.value })} rows={4} style={wideStyle} /></Field>
                <Field label="核心主题"><textarea value={bookPlan.core_theme} onChange={(event) => setBookPlan({ ...bookPlan, core_theme: event.target.value })} rows={2} style={wideStyle} /></Field>
                <Field label="重点人物（每行一位）"><textarea value={bookPlan.focus_characters.join('\n')} onChange={(event) => setBookPlan({ ...bookPlan, focus_characters: splitLines(event.target.value) })} rows={3} style={wideStyle} /></Field>
                <div style={twoColumnStyle}>
                  <Field label="主线冲突"><textarea value={bookPlan.main_conflict} onChange={(event) => setBookPlan({ ...bookPlan, main_conflict: event.target.value })} rows={4} style={wideStyle} /></Field>
                  <Field label="暗线冲突"><textarea value={bookPlan.hidden_conflict} onChange={(event) => setBookPlan({ ...bookPlan, hidden_conflict: event.target.value })} rows={4} style={wideStyle} /></Field>
                </div>
                <Field label="核心谜团"><textarea value={bookPlan.central_mystery} onChange={(event) => setBookPlan({ ...bookPlan, central_mystery: event.target.value })} rows={3} style={wideStyle} /></Field>
                <Field label="与既有作品的关系及选择理由"><textarea value={bookPlan.relation_to_previous_books} onChange={(event) => setBookPlan({ ...bookPlan, relation_to_previous_books: event.target.value })} rows={4} style={wideStyle} /></Field>
                <div style={twoColumnStyle}>
                  <Field label="要回收的旧伏笔（每行一条）"><textarea value={bookPlan.old_foreshadowing_to_resolve.join('\n')} onChange={(event) => setBookPlan({ ...bookPlan, old_foreshadowing_to_resolve: splitLines(event.target.value) })} rows={4} style={wideStyle} /></Field>
                  <Field label="要埋下的新伏笔（每行一条）"><textarea value={bookPlan.new_foreshadowing_to_plant.join('\n')} onChange={(event) => setBookPlan({ ...bookPlan, new_foreshadowing_to_plant: splitLines(event.target.value) })} rows={4} style={wideStyle} /></Field>
                </div>
                <div style={twoColumnStyle}>
                  <Field label="主要地点（每行一个）"><textarea value={bookPlan.main_locations.join('\n')} onChange={(event) => setBookPlan({ ...bookPlan, main_locations: splitLines(event.target.value) })} rows={3} style={wideStyle} /></Field>
                  <Field label="整体基调"><textarea value={bookPlan.tone} onChange={(event) => setBookPlan({ ...bookPlan, tone: event.target.value })} rows={3} style={wideStyle} /></Field>
                </div>
                <div style={threeColumnStyle}>
                  <Field label="开局局面"><textarea value={bookPlan.opening_setup} onChange={(event) => setBookPlan({ ...bookPlan, opening_setup: event.target.value })} rows={4} style={wideStyle} /></Field>
                  <Field label="中段转折"><textarea value={bookPlan.midpoint_turn} onChange={(event) => setBookPlan({ ...bookPlan, midpoint_turn: event.target.value })} rows={4} style={wideStyle} /></Field>
                  <Field label="结尾方向"><textarea value={bookPlan.ending_direction} onChange={(event) => setBookPlan({ ...bookPlan, ending_direction: event.target.value })} rows={4} style={wideStyle} /></Field>
                </div>
                <details style={{ marginTop: 12 }}>
                  <summary style={{ cursor: 'pointer', color: '#c9a96e' }}>查看 {bookPlan.chapters.length} 章安排</summary>
                  <div style={{ maxHeight: 360, overflowY: 'auto', marginTop: 8 }}>
                    {bookPlan.chapters.map((chapter) => (
                      <div key={chapter.order} className="bg-panel-alt" style={{ padding: 10, marginBottom: 7, fontSize: 12, lineHeight: 1.6 }}>
                        <strong>第 {chapter.order} 章：{chapter.title}</strong><br />
                        {chapter.chapter_summary || chapter.chapter_goal}<br />
                        人物：{chapter.characters.join('、') || '由模型按剧情选择'} · 目标 {chapter.target_words} 字
                      </div>
                    ))}
                  </div>
                </details>
                <div style={{ marginTop: 14 }}>
                  <Field label="要求 AI 修改总体构想">
                    <textarea value={planFeedback} onChange={(event) => setPlanFeedback(event.target.value)} rows={3} style={wideStyle} placeholder="例如：增强楚子航线，保留结局方向但重写中段转折。" />
                  </Field>
                  <PrimaryButton busy={busy === 'revise-plan' || bookPlanActive} disabled={Boolean(busy) || bookPlanActive || !planFeedback.trim()} onClick={() => { void submitPlanRevision(); }}>
                    修改总体构想
                  </PrimaryButton>
                </div>
              </>
            )}
          </section>
        </div>
      )}

      {activeTab === 'chapter' && (
        <div style={twoPanelStyle}>
          <section className="bg-panel" style={panelStyle}>
            <div style={sectionHeaderStyle}>
              <h3 style={{ ...headingStyle, marginBottom: 0 }}>当前章节任务</h3>
              <span style={{ color: bookPlan?.accepted ? '#72cf83' : '#c86e6e', fontSize: 12 }}>
                {bookPlan?.accepted ? '总体构想已接受' : '总体构想未接受'}
              </span>
            </div>
            <Field label="章节">
              <select value={currentPlan?.plan_id || ''} onChange={(event) => {
                setSelectedPlanId(event.target.value);
                setAIReview(null);
                setRepairCandidate(null);
                const selected = orderedPlans.find((item) => item.plan_id === event.target.value);
                if (selected) setTargetWords(selected.target_words);
              }} style={wideStyle}>
                <option value="">-- 选择章节 --</option>
                {orderedPlans.map((plan) => (
                  <option key={plan.plan_id} value={plan.plan_id}>
                    第 {plan.order} 章 {plan.title} · {statusText(plan.status)}
                  </option>
                ))}
              </select>
            </Field>
            <div style={{ maxHeight: 220, overflowY: 'auto', marginBottom: 12 }}>
              {orderedPlans.map((plan) => (
                <button
                  key={plan.plan_id}
                  onClick={() => {
                    setSelectedPlanId(plan.plan_id);
                    setTargetWords(plan.target_words);
                    setAIReview(null);
                    setRepairCandidate(null);
                  }}
                  className="bg-panel-alt"
                  style={{ ...listTitleButtonStyle, width: '100%', padding: 9, marginBottom: 6 }}
                >
                  第 {plan.order} 章：{plan.title}<br />
                  <span style={subtleStyle}>
                    {(plan.chapter_summary || plan.chapter_goal).slice(0, 70)}
                    {' · '}{plan.target_words} 字
                    {' · '}{generationActive && currentPlan?.plan_id === plan.plan_id
                      ? '生成中'
                      : plan.status === 'done'
                        ? '已正式保存'
                        : plan.status === 'drafting'
                          ? '草稿待审核'
                          : '未生成'}
                  </span>
                </button>
              ))}
            </div>
            {!currentPlan ? <p style={emptyStyle}>接受总体构想后会自动建立逐章规划。</p> : (
              <div className="bg-panel-alt" style={{ padding: 12, fontSize: 12, lineHeight: 1.75, marginBottom: 12 }}>
                <strong>第 {currentPlan.order} 章：{currentPlan.title}</strong><br />
                本章摘要：{currentPlan.chapter_summary}<br />
                章节作用：{currentPlan.chapter_function.join('、') || '推进总体构想'}<br />
                剧情目标：{currentPlan.chapter_goal || '按总体构想推进'}<br />
                开头状态：{currentPlan.opening_state}<br />
                结尾状态：{currentPlan.ending_state}<br />
                承接上一章：{currentPlan.previous_bridge}<br />
                引出下一章：{currentPlan.next_bridge}<br />
                主要冲突：{currentPlan.conflict}<br />
                情节点：{currentPlan.plot_beats.join('；')}<br />
                涉及人物：{currentPlan.characters.join('、') || '由模型按剧情选择'}<br />
                埋伏笔：{currentPlan.foreshadowing_to_plant.join('、') || '无'}<br />
                回收伏笔：{currentPlan.foreshadowing_to_resolve.join('、') || '无'}<br />
                情绪节奏：{currentPlan.emotional_tone}<br />
                AI 建议字数：{currentPlan.target_words}；{currentPlan.word_count_reason}
              </div>
            )}
            {currentPlan && (
              <Field label="本次目标字数（默认使用 AI 建议，可调整）">
                <input type="number" min={1200} max={8000} value={targetWords || currentPlan.target_words} onChange={(event) => setTargetWords(Number(event.target.value))} style={wideStyle} />
              </Field>
            )}
            <div style={buttonRowStyle}>
              <PrimaryButton busy={busy === 'generate' || generationActive} disabled={Boolean(busy) || generationActive || !bookPlan?.accepted || !bookPlan?.chapter_plans_complete || !currentPlan} onClick={() => { void startChapter('chapter_generation'); }}>
                生成本章完整草稿
              </PrimaryButton>
              <PrimaryButton busy={busy === 'generate' || generationActive} disabled={Boolean(busy) || generationActive || !currentPlan} onClick={() => { void startChapter('regeneration'); }}>
                重新生成本章
              </PrimaryButton>
              <PrimaryButton busy={false} disabled={Boolean(busy) || !currentPlan} onClick={() => setEditingChapterPlan((value) => !value)}>
                修改本章规划
              </PrimaryButton>
            </div>
            <details style={{ marginTop: 10 }}>
              <summary style={{ cursor: 'pointer', color: '#8a8a9a', fontSize: 12 }}>高级选项</summary>
              <div style={{ marginTop: 8 }}>
                <PrimaryButton busy={busy === 'generate' || generationActive} disabled={Boolean(busy) || generationActive || !editorContent.trim() || !currentPlan} onClick={() => { void startChapter('continuation'); }}>
                  继续追加一段
                </PrimaryButton>
              </div>
            </details>
            {!bookPlan?.chapter_plans_complete && <p style={{ ...helpStyle, color: '#c86e6e' }}>按钮不可用：章节规划未完成，请先在“总体构想”页生成完整章节规划。</p>}
            {editingChapterPlan && currentPlan && (
              <div className="bg-panel-alt" style={{ padding: 12, marginTop: 12 }}>
                <Field label="本章摘要">
                  <textarea value={currentPlan.chapter_summary} onChange={(event) => setPlans((items) => items.map((item) => item.plan_id === currentPlan.plan_id ? { ...item, chapter_summary: event.target.value } : item))} rows={3} style={wideStyle} />
                </Field>
                <Field label="本章目标">
                  <textarea value={currentPlan.chapter_goal} onChange={(event) => setPlans((items) => items.map((item) => item.plan_id === currentPlan.plan_id ? { ...item, chapter_goal: event.target.value } : item))} rows={3} style={wideStyle} />
                </Field>
                <Field label="前后衔接">
                  <textarea value={`${currentPlan.previous_bridge}\n${currentPlan.next_bridge}`} onChange={(event) => {
                    const [previousBridge = '', ...nextParts] = event.target.value.split('\n');
                    setPlans((items) => items.map((item) => item.plan_id === currentPlan.plan_id ? { ...item, previous_bridge: previousBridge, next_bridge: nextParts.join('\n') } : item));
                  }} rows={4} style={wideStyle} />
                </Field>
                <PrimaryButton busy={busy === 'save-chapter-plan'} disabled={Boolean(busy)} onClick={() => { void saveCurrentChapterPlan(); }}>
                  保存本章规划
                </PrimaryButton>
              </div>
            )}
            {generationTask && (
              <TaskStatusPanel
                task={generationTask}
                onCancel={() => { void stopTask(generationTask, setGenerationTask); }}
                onRetry={() => { void startChapter('chapter_generation'); }}
              />
            )}
          </section>

          <section className="bg-panel" style={panelStyle}>
            <div style={sectionHeaderStyle}>
              <div>
                <h3 style={{ ...headingStyle, marginBottom: 2 }}>章节草稿与审核</h3>
                <span style={subtleStyle}>{countWords(editorContent)} 字</span>
              </div>
              <div style={buttonRowStyle}>
                <PrimaryButton busy={busy === 'save-temp'} disabled={Boolean(busy) || !editorContent.trim()} onClick={() => { void saveEditorAsTemp(); }}>保存为临时记录</PrimaryButton>
                <PrimaryButton busy={busy === 'save-official'} disabled={Boolean(busy) || officialSaveBlockingReasons.length > 0} onClick={() => { void confirmOfficial(); }}>
                  确认并保存为正式章节
                </PrimaryButton>
                <PrimaryButton busy={false} disabled={Boolean(busy) || !editingOfficialId || !nextPlan} onClick={moveToNextPlan}>
                  下一章
                </PrimaryButton>
              </div>
            </div>
            <input value={editorTitle} onChange={(event) => setEditorTitle(event.target.value)} style={{ ...wideStyle, marginBottom: 10, fontSize: 16 }} placeholder="章节标题" />
              <textarea value={editorContent} onChange={(event) => {
                setEditorContent(event.target.value);
                setAIReview(null);
                setRepairCandidate(null);
                setRevisionCandidate(null);
              }} style={{ ...wideStyle, minHeight: 520, resize: 'vertical', lineHeight: 1.9 }} placeholder="生成后的章节草稿会显示在这里，也可以直接手工编辑。" />
            <div className="bg-panel-alt" style={pathBoxStyle}>
              {editingOfficialId
                ? `已保存到：${editorOfficialPath || `${PROJECT_ROOT}/official_chapters/${editingOfficialId}.md`}。再次保存会先在 ${PROJECT_ROOT}/revisions/ 创建版本快照。`
                : `当前内容只是临时生成结果，尚未写入 ${PROJECT_ROOT}/official_chapters/。`}
            </div>
            {officialSaveBlockingReasons.length > 0 && editorContent.trim() && (
              <div style={{ marginTop: 7, color: '#c86e6e', fontSize: 12 }}>
                暂不可保存：{officialSaveBlockingReasons.join('；')}
              </div>
            )}
            {completeness && (
              <div className="bg-panel-alt" style={{ padding: 12, marginTop: 10, fontSize: 12 }}>
                <strong style={{ color: blockingCompletenessIssues.length > 0 ? '#c86e6e' : completenessWarnings.length > 0 ? '#c9a96e' : '#72cf83' }}>
                  规则完整性检查：{
                    blockingCompletenessIssues.length > 0
                      ? '未通过，暂不可保存'
                      : completenessWarnings.length > 0
                        ? '通过，有提醒；可保存但建议人工复核'
                        : '通过'
                  }
                </strong><br />
                字数 {completeness.word_count}，合理范围 {completeness.minimum_word_count}-{completeness.maximum_word_count}；
                末句{completeness.sentence_complete ? '完整' : '不完整'}
                {completenessIssues.map((issue) => {
                  const blocking = isBlockingCompletenessIssue(issue, completeness);
                  const level = issue.level === 'info' ? 'info' : blocking ? 'error' : 'warning';
                  return (
                  <div key={`${issue.code}-${issue.message}`} style={{ color: level === 'error' ? '#c86e6e' : level === 'warning' ? '#c9a96e' : '#8a8a9a', marginTop: 5 }}>
                    {level === 'error' ? '阻断' : level === 'warning' ? '提醒' : '信息'}：{issue.message}
                  </div>
                  );
                })}
                {blockingCompletenessIssues.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ color: '#c86e6e', marginBottom: 7 }}>
                      禁用保存原因：{blockingCompletenessIssues.map((item) => item.message).join('；')}
                    </div>
                    <PrimaryButton busy={busy === 'revision' || revisionActive} disabled={Boolean(busy) || revisionActive || !editorGenerationId} onClick={() => { void autoRepairChapter(); }}>
                      自动修复本章
                    </PrimaryButton>
                  </div>
                )}
              </div>
            )}
            <div style={{ marginTop: 10 }}>
              <PrimaryButton
                busy={busy === 'ai-review' || reviewActive}
                disabled={Boolean(busy) || reviewActive || repairActive || !editorContent.trim() || !currentPlan}
                onClick={() => { void startDeepReview(); }}
              >
                AI 深度质检
              </PrimaryButton>
              <span style={{ ...helpStyle, marginLeft: 10 }}>
                按语义、因果、人物与前后章衔接审稿，不会自动修改正文。
              </span>
            </div>
            {reviewTask && (
              <TaskStatusPanel
                task={reviewTask}
                onCancel={() => { void stopTask(reviewTask, setReviewTask); }}
                onRetry={() => { void startDeepReview(); }}
              />
            )}
            {aiReview && (
              <div className="bg-panel-alt" style={{ padding: 12, marginTop: 10, fontSize: 12, lineHeight: 1.7 }}>
                <div style={sectionHeaderStyle}>
                  <strong style={{ color: aiReview.report_format === 'text' ? '#c9a96e' : (aiReview.overall_pass ? '#72cf83' : '#c86e6e') }}>
                    {aiReview.report_format === 'text'
                      ? 'AI 深度质检完成 · 非结构化文本报告'
                      : `AI 深度质检：${aiReview.score} 分 · ${aiReview.overall_pass ? '语义审稿通过' : '建议修改'}`}
                  </strong>
                  <span style={subtleStyle}>{aiReview.model_name}</span>
                </div>
                {aiReview.parse_warning && (
                  <div style={{ marginTop: 8, padding: 9, border: '1px solid #8a6b2f', color: '#e3bd69', background: '#2b2518' }}>
                    {aiReview.parse_warning}
                  </div>
                )}
                {aiReview.readable_report && (
                  <div style={{ marginTop: 10 }}>
                    <strong>文本质检报告</strong>
                    <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 520, overflowY: 'auto', lineHeight: 1.75, fontFamily: 'inherit' }}>
                      {aiReview.readable_report}
                    </pre>
                  </div>
                )}
                {aiReview.report_format !== 'text' && (
                  <>
                    {aiReview.semantic_overrides.map((item) => (
                      <div key={item} style={{ color: '#72cf83', marginTop: 5 }}>{item}</div>
                    ))}
                    <p><strong>摘要符合度：</strong>{aiReview.summary_alignment}</p>
                    <p><strong>结尾状态：</strong>{aiReview.ending_state_alignment}</p>
                    <p><strong>承接上一章：</strong>{aiReview.continuity_with_previous}</p>
                    <p><strong>引出下一章：</strong>{aiReview.continuity_with_next}</p>
                    <p><strong>人物一致性：</strong>{aiReview.character_consistency}</p>
                    <p><strong>文风一致性：</strong>{aiReview.style_consistency}</p>
                    <details>
                      <summary style={{ cursor: 'pointer', color: '#c9a96e' }}>逐条查看情节点覆盖</summary>
                      {aiReview.plot_beats_coverage.map((item) => (
                        <div key={item.beat} style={{ marginTop: 7, color: item.covered ? '#72cf83' : '#c86e6e' }}>
                          {item.covered ? '已覆盖' : '未覆盖'}：{item.beat}<br />
                          <span style={{ color: '#aaa' }}>
                            {item.evidence ? `依据：${item.evidence}` : '未找到明确正文依据'}
                            {item.comment ? `；${item.comment}` : ''}
                          </span>
                        </div>
                      ))}
                    </details>
                    {aiReview.problems.length > 0 && (
                      <div style={{ marginTop: 9, color: '#c86e6e' }}>
                        <strong>发现的问题：</strong>
                        {aiReview.problems.map((item) => <div key={item}>- {item}</div>)}
                      </div>
                    )}
                    {aiReview.repair_suggestions.length > 0 && (
                      <div style={{ marginTop: 9, color: '#c9a96e' }}>
                        <strong>修复建议：</strong>
                        {aiReview.repair_suggestions.map((item) => <div key={item}>- {item}</div>)}
                      </div>
                    )}
                  </>
                )}
                {aiReview.raw_response && (
                  <details style={{ marginTop: 10 }}>
                    <summary style={{ cursor: 'pointer', color: '#aaa' }}>查看模型原始返回</summary>
                    <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 320, overflowY: 'auto', lineHeight: 1.65, fontFamily: 'inherit' }}>
                      {aiReview.raw_response}
                    </pre>
                  </details>
                )}
                {aiReview.report_format !== 'text' && aiReview.need_repair && (
                  <div style={{ marginTop: 10 }}>
                    <PrimaryButton
                      busy={busy === 'ai-repair' || repairActive}
                      disabled={Boolean(busy) || repairActive}
                      onClick={() => { void startReviewRepair(); }}
                    >
                      根据质检自动修复
                    </PrimaryButton>
                  </div>
                )}
              </div>
            )}
            {repairTask && (
              <TaskStatusPanel
                task={repairTask}
                onCancel={() => { void stopTask(repairTask, setRepairTask); }}
                onRetry={() => { void startReviewRepair(); }}
              />
            )}
            {repairCandidate && (
              <div className="bg-panel-alt" style={{ padding: 12, marginTop: 10, fontSize: 12 }}>
                <strong style={{ color: '#c9a96e' }}>AI 修复候选版尚未应用</strong>
                <p>
                  {repairCandidate.result.word_count} 字；
                  规则检查{repairCandidate.completeness?.passed ? '通过' : '仍有问题'}。
                  原文仍保留在编辑器和原临时记录中。
                </p>
                <details>
                  <summary style={{ cursor: 'pointer' }}>预览修复版正文</summary>
                  <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 360, overflowY: 'auto', lineHeight: 1.7 }}>
                    {repairCandidate.result.content}
                  </pre>
                </details>
                <div style={{ ...buttonRowStyle, marginTop: 9 }}>
                  <PrimaryButton busy={false} disabled={Boolean(busy)} onClick={acceptRepairCandidate}>
                    接受 AI 修复版
                  </PrimaryButton>
                  <button onClick={() => setRepairCandidate(null)}>保留原文</button>
                </div>
              </div>
            )}
            <div style={{ marginTop: 14 }}>
              <Field label="修改模式">
                <select
                  value={revisionMode}
                  onChange={(event) => setRevisionMode(event.target.value as RevisionMode)}
                  style={wideStyle}
                >
                  <option value="local_edit">局部修改（推荐）</option>
                  <option value="full_rewrite">整章重写（会大幅改动全文）</option>
                </select>
              </Field>
              {revisionMode === 'full_rewrite' && (
                <div style={{ color: '#c9a96e', fontSize: 12, marginBottom: 9 }}>
                  整章重写会消耗更多模型输出，并可能产生较大改动。结果仍会先作为候选版，不会直接覆盖原文。
                </div>
              )}
              <Field label="修改要求">
                <textarea value={revisionFeedback} onChange={(event) => setRevisionFeedback(event.target.value)} rows={3} style={wideStyle} placeholder="例如：节奏慢一点；增强冲突；保留结尾但重写中间。" />
              </Field>
              <Field label="指定修改部分（可留空）">
                <input value={revisionTarget} onChange={(event) => setRevisionTarget(event.target.value)} style={wideStyle} />
              </Field>
              <PrimaryButton busy={busy === 'revision' || revisionActive} disabled={Boolean(busy) || revisionActive || !editorGenerationId || !revisionFeedback.trim()} onClick={() => { void submitRevision(); }}>
                提交修改
              </PrimaryButton>
              {!editorGenerationId && <span style={{ ...helpStyle, marginLeft: 10 }}>先生成或恢复一条临时记录后可使用 AI 修改。</span>}
              {revisionTask && (
                <TaskStatusPanel
                  task={revisionTask}
                  onCancel={() => { void stopTask(revisionTask, setRevisionTask); }}
                  onRetry={() => { void submitRevision(); }}
                />
              )}
              {revisionCandidate && (
                <div className="bg-panel-alt" style={{ padding: 12, marginTop: 10, fontSize: 12 }}>
                  <div style={sectionHeaderStyle}>
                    <strong style={{ color: revisionCandidate.result.revision_failed ? '#c86e6e' : '#c9a96e' }}>
                      修改候选版 · {revisionCandidate.result.revision_change_level || '待审核'}
                    </strong>
                    <span style={subtleStyle}>
                      {revisionCandidate.result.revision_mode === 'full_rewrite' ? '整章重写' : '局部修改'}
                    </span>
                  </div>
                  <div style={{ marginTop: 7 }}>
                    原文：{countWords(revisionCandidate.originalContent)} 字；
                    修改后：{revisionCandidate.result.word_count} 字；
                    保留比例：{Math.round(revisionCandidate.result.revision_change_ratio * 100)}%
                  </div>
                  {(revisionCandidate.result.warning || revisionCandidate.result.revision_requires_confirmation) && (
                    <div style={{ color: revisionCandidate.result.revision_failed ? '#c86e6e' : '#c9a96e', marginTop: 7 }}>
                      {revisionCandidate.result.warning || '修改结果明显短于原文，请人工复核后再接受。'}
                    </div>
                  )}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 10 }}>
                    <details>
                      <summary style={{ cursor: 'pointer' }}>查看原文</summary>
                      <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 360, overflowY: 'auto', lineHeight: 1.7 }}>
                        {revisionCandidate.originalContent}
                      </pre>
                    </details>
                    <details open>
                      <summary style={{ cursor: 'pointer' }}>查看修改后版本</summary>
                      <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 360, overflowY: 'auto', lineHeight: 1.7 }}>
                        {revisionCandidate.result.content}
                      </pre>
                    </details>
                  </div>
                  <div style={{ ...buttonRowStyle, marginTop: 10 }}>
                    <PrimaryButton
                      busy={false}
                      disabled={Boolean(busy) || revisionCandidate.result.revision_failed}
                      onClick={acceptRevisionCandidate}
                    >
                      接受修改
                    </PrimaryButton>
                    <button onClick={() => {
                      setRevisionCandidate(null);
                      setMessage('已放弃修改候选版，原文保持不变。');
                    }}>放弃修改</button>
                    <button onClick={() => {
                      setRevisionCandidate(null);
                      setNotice('请调整修改要求后重新提交，原文保持不变。');
                    }}>重新修改</button>
                    <button onClick={saveRevisionCandidateVersion}>保存为新版本</button>
                  </div>
                  {revisionCandidate.sourceSnapshot?.file_path && (
                    <div style={{ ...pathBoxStyle, marginTop: 9 }}>
                      修改前原文快照：{revisionCandidate.sourceSnapshot.file_path}
                    </div>
                  )}
                </div>
              )}
            </div>
          </section>
        </div>
      )}

      {activeTab === 'temp' && (
        <div style={twoPanelStyle}>
          <section className="bg-panel" style={panelStyle}>
            <div style={sectionHeaderStyle}>
              <h3 style={{ ...headingStyle, marginBottom: 0 }}>临时生成记录</h3>
              <button onClick={() => { void refreshWritingData(); }}>刷新</button>
            </div>
            {tempRecords.length === 0 ? <p style={emptyStyle}>暂无临时记录。</p> : (
              <div style={{ maxHeight: 680, overflowY: 'auto' }}>
                {tempRecords.map((record) => (
                  <div key={record.temp_id} style={listItemStyle}>
                    <div style={{ ...listTitleButtonStyle, cursor: 'default' }}>
                      {record.chapter_order ? `第 ${record.chapter_order} 章 · ` : ''}{record.chapter_title || '未命名记录'}<br />
                      <span style={subtleStyle}>
                        {recordTypeText(record.record_type)} · {record.word_count} 字 · {new Date(record.created_at).toLocaleString('zh-CN')}<br />
                        {record.accepted ? '已接受' : '未接受'} · {record.saved_official ? `已保存正式章 ${record.official_chapter_id}` : '尚未保存为正式章节'}
                      </span>
                    </div>
                    <div style={buttonRowStyle}>
                      <button onClick={() => setSelectedTemp(record)}>查看</button>
                      <button disabled={record.record_type === 'book_plan'} onClick={() => { void openTempInEditor(record); }}>继续编辑</button>
                      <button className="btn-danger" onClick={() => {
                        if (!window.confirm('只删除这条临时记录？正式章节不会被删除。')) return;
                        void runAction('delete-temp', async () => {
                          await deleteTempGeneration(record.temp_id);
                          if (selectedTemp?.temp_id === record.temp_id) setSelectedTemp(null);
                          await refreshWritingData();
                          setMessage('临时记录已删除，正式章节未受影响。');
                        });
                      }}>删除</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
          <section className="bg-panel" style={panelStyle}>
            <h3 style={headingStyle}>记录详情</h3>
            {!selectedTemp ? <p style={emptyStyle}>选择一条记录查看。</p> : (
              <>
                <div style={{ marginBottom: 10, fontSize: 13 }}>
                  <strong>{selectedTemp.chapter_title}</strong> · {recordTypeText(selectedTemp.record_type)} · {selectedTemp.word_count} 字
                </div>
                <div className="bg-panel-alt" style={pathBoxStyle}>{selectedTemp.file_path}</div>
                <div style={{ whiteSpace: 'pre-wrap', maxHeight: 620, overflowY: 'auto', lineHeight: 1.8 }}>{selectedTemp.content}</div>
              </>
            )}
          </section>
        </div>
      )}

      {activeTab === 'official' && (
        <div style={twoPanelStyle}>
          <section className="bg-panel" style={panelStyle}>
            <div style={sectionHeaderStyle}>
              <h3 style={{ ...headingStyle, marginBottom: 0 }}>正式章节库</h3>
              <button onClick={() => { void refreshWritingData(); }}>刷新</button>
            </div>
            {officialChapters.length === 0 ? <p style={emptyStyle}>尚无正式章节。请在章节生成页审核后确认保存。</p> : (
              officialChapters.map((chapter) => (
                <div key={chapter.chapter_id} style={listItemStyle}>
                  <button onClick={() => {
                    void runAction('view-official', async () => {
                      setSelectedOfficial(await getOfficialChapter(chapter.chapter_id));
                    });
                  }} style={listTitleButtonStyle}>
                    第 {chapter.order} 章：{chapter.title}<br />
                    <span style={subtleStyle}>{chapter.word_count} 字 · {new Date(chapter.updated_at).toLocaleString('zh-CN')}</span>
                  </button>
                  <div style={buttonRowStyle}>
                    <button onClick={() => { void openOfficialInEditor(chapter); }}>修改此章</button>
                    <button onClick={() => { void downloadOfficial(chapter, 'md'); }}>导出</button>
                    <button className="btn-danger" onClick={() => { void removeOfficial(chapter); }}>删除</button>
                  </div>
                </div>
              ))
            )}
          </section>
          <section className="bg-panel" style={panelStyle}>
            <h3 style={headingStyle}>正式正文</h3>
            {!selectedOfficial ? <p style={emptyStyle}>选择正式章节查看正文。</p> : (
              <>
                <div style={sectionHeaderStyle}>
                  <div>
                    <strong>第 {selectedOfficial.order} 章：{selectedOfficial.title}</strong>
                    <div style={subtleStyle}>{selectedOfficial.word_count} 字 · 版本快照 {selectedOfficial.revision_count} 个</div>
                  </div>
                  <div style={buttonRowStyle}>
                    <button onClick={() => { void openOfficialInEditor(selectedOfficial); }}>修改此章</button>
                    <button onClick={() => { void downloadOfficial(selectedOfficial, 'txt'); }}>导出 TXT</button>
                  </div>
                </div>
                <div className="bg-panel-alt" style={pathBoxStyle}>{selectedOfficial.file_path}</div>
                <div style={{ whiteSpace: 'pre-wrap', maxHeight: 650, overflowY: 'auto', lineHeight: 1.9 }}>{selectedOfficial.content}</div>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function previousChapterIds(chapters: ChapterMeta[], currentId: string): string[] {
  const index = chapters.findIndex((chapter) => chapter.chapter_id === currentId);
  return index <= 0 ? [] : chapters.slice(Math.max(0, index - 2), index).map((chapter) => chapter.chapter_id);
}

function countWords(text: string): number {
  return text.replace(/\s/g, '').length;
}

function uniqueCompletenessIssues(
  issues: ChapterCompletenessResult['issues'],
): ChapterCompletenessResult['issues'] {
  const seen = new Set<string>();
  return issues.filter((issue) => {
    const key = `${issue.code}:${issue.message}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function isBlockingCompletenessIssue(
  issue: ChapterCompletenessResult['issues'][number],
  check: ChapterCompletenessResult | null,
): boolean {
  if (issue.level !== 'error' || !check) return false;
  if ([
    'chapter_too_long',
    'chapter_above_recommended',
    'chapter_strongly_above_recommended',
  ].includes(issue.code)) {
    return check.word_count > check.maximum_word_count * 2;
  }
  if (['chapter_too_short', 'chapter_below_recommended'].includes(issue.code)) {
    return check.word_count < 500;
  }
  if ([
    'summary_alignment',
    'ending_state',
    'next_bridge',
    'plot_beat_coverage',
    'duplicate_paragraphs',
  ].includes(issue.code)) {
    return false;
  }
  return true;
}

function splitLines(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function statusText(status: ChapterPlan['status']): string {
  return status === 'done' ? '已完成' : status === 'drafting' ? '写作中' : '待生成';
}

function recordTypeText(value: string): string {
  const labels: Record<string, string> = {
    book_plan: '总体构想生成',
    chapter_generation: '章节生成',
    full_chapter: '完整章节生成',
    continuation: '继续生成',
    revision: '修改结果',
    revision_source_snapshot: '修改前原文快照',
    ai_repair: 'AI 质检修复候选',
    regeneration: '重新生成',
    manual_snapshot: '手工临时快照',
    official_revision: '正式章节修改',
  };
  return labels[value] || value;
}

function PrimaryButton({ busy, disabled, onClick, children }: {
  busy: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button className="btn-primary" disabled={disabled} onClick={onClick}>
      {busy ? '处理中...' : children}
    </button>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <label style={{ display: 'block', marginBottom: 4, color: '#858596', fontSize: 12 }}>{label}</label>
      {children}
    </div>
  );
}

function Banner({ color, background, children }: { color: string; background: string; children: React.ReactNode }) {
  return <div style={{ color, background, padding: '9px 12px', borderRadius: 6, marginBottom: 10, fontSize: 12 }}>{children}</div>;
}

const headerStyle = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 };
const tabBarStyle = { display: 'flex', gap: 8, marginBottom: 16, overflowX: 'auto' as const };
const twoPanelStyle = { display: 'grid', gridTemplateColumns: 'minmax(320px, .8fr) minmax(540px, 1.2fr)', gap: 16, alignItems: 'start' };
const twoColumnStyle = { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 };
const threeColumnStyle = { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 };
const panelStyle = { padding: 18 };
const headingStyle = { fontSize: 16, fontWeight: 600, margin: '0 0 12px' };
const sectionHeaderStyle = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 12 };
const buttonRowStyle = { display: 'flex', gap: 8, flexWrap: 'wrap' as const };
const wideStyle = { width: '100%' };
const subtleStyle = { color: '#777788', fontSize: 12 };
const helpStyle = { color: '#858596', fontSize: 12, lineHeight: 1.6 };
const emptyStyle = { color: '#6f6f80', fontSize: 13 };
const pathBoxStyle = { padding: 10, marginTop: 12, fontSize: 12, lineHeight: 1.65, wordBreak: 'break-all' as const };
const listItemStyle = { display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', borderBottom: '1px solid #20202b' };
const listTitleButtonStyle = { flex: 1, textAlign: 'left' as const, border: 0, background: 'transparent', color: '#d0d0d8', cursor: 'pointer', lineHeight: 1.5 };
