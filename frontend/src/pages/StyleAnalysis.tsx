import { useEffect, useState } from 'react';
import {
  listChapters, listProfiles, getProfile,
  startStyleAnalysisTask, getLongTask, cancelLongTask,
  isApiNotFoundError,
  type ChapterMeta, type StyleProfile, type LongTask, type DimensionResult,
} from '../api';
import TaskStatusPanel from '../components/TaskStatusPanel';

const STORAGE_KEY = 'noval.style-analysis';

interface StoredAnalysisState {
  selectedChapterId: string;
  currentAnalysisTaskId: string;
  lastAnalysisResult: StyleProfile | null;
}

function loadStoredState(): StoredAnalysisState {
  const fallback: StoredAnalysisState = {
    selectedChapterId: '',
    currentAnalysisTaskId: '',
    lastAnalysisResult: null,
  };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      return {
        ...fallback,
        ...JSON.parse(raw) as Partial<StoredAnalysisState>,
      };
    }
  } catch {
    // Ignore invalid local state.
  }
  return fallback;
}

export default function StyleAnalysis() {
  const [stored] = useState(loadStoredState);
  const [chapters, setChapters] = useState<ChapterMeta[]>([]);
  const [profiles, setProfiles] = useState<StyleProfile[]>([]);
  const [selectedChapterId, setSelectedChapterId] = useState(stored.selectedChapterId);
  const [selectedProfile, setSelectedProfile] = useState<StyleProfile | null>(stored.lastAnalysisResult);
  const [expandedDim, setExpandedDim] = useState<string | null>(null);
  const [currentTaskId, setCurrentTaskId] = useState(stored.currentAnalysisTaskId);
  const [task, setTask] = useState<LongTask | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [notice, setNotice] = useState('');

  const refreshChapters = async () => {
    try {
      const [chapterList, profileList] = await Promise.all([
        listChapters(),
        listProfiles(),
      ]);
      setChapters(chapterList);
      setProfiles(profileList);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载分析页面失败');
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => { void refreshChapters(); }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      selectedChapterId,
      currentAnalysisTaskId: currentTaskId,
      lastAnalysisResult: selectedProfile,
    }));
  }, [selectedChapterId, currentTaskId, selectedProfile]);

  useEffect(() => {
    if (!currentTaskId) return;
    let disposed = false;
    let timer = 0;

    const refreshTask = async () => {
      try {
        const next = await getLongTask(currentTaskId);
        if (disposed) return;
        setTask(next);
        if (next.status === 'success') {
          const profile = next.result.profile as StyleProfile | undefined;
          if (profile) {
            setSelectedProfile(profile);
          } else {
            const profileId = next.result.profile_id;
            if (typeof profileId === 'string') setSelectedProfile(await getProfile(profileId));
          }
          const warnings = next.result.warnings as string[] | undefined;
          if (warnings?.length) {
            setNotice('模型分析未完成，已使用规则结果生成报告。');
          } else {
            setMessage(next.result.cache_hit ? '已复用章节风格缓存' : '风格分析完成');
          }
          setCurrentTaskId('');
          await refreshChapters();
          window.clearInterval(timer);
        } else if (next.status === 'failed') {
          const profile = next.result.profile as StyleProfile | undefined;
          if (profile) setSelectedProfile(profile);
          setNotice('风格分析未完成，可在任务面板中查看原因并重新分析。');
          setCurrentTaskId('');
          window.clearInterval(timer);
        } else if (next.status === 'cancelled') {
          setMessage('风格分析任务已取消');
          setCurrentTaskId('');
          window.clearInterval(timer);
        }
      } catch (e: unknown) {
        if (disposed) return;
        window.clearInterval(timer);
        if (isApiNotFoundError(e)) {
          setCurrentTaskId('');
          setTask(null);
          setNotice('上次分析任务已过期，请重新分析。');
          return;
        }
        setError(e instanceof Error ? e.message : '查询分析任务失败');
      }
    };

    void refreshTask();
    timer = window.setInterval(() => { void refreshTask(); }, 1500);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [currentTaskId]);

  const handleAnalyze = async (chapterId = selectedChapterId) => {
    if (!chapterId) {
      setError('请先选择章节');
      return;
    }
    setError('');
    setMessage('');
    setNotice('');
    setTask(null);
    setCurrentTaskId('');
    setSelectedChapterId(chapterId);
    try {
      const next = await startStyleAnalysisTask(chapterId);
      setTask(next);
      setCurrentTaskId(next.task_id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '分析启动失败');
    }
  };

  const handleCancel = async () => {
    if (!currentTaskId) return;
    try {
      setTask(await cancelLongTask(currentTaskId));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '取消任务失败');
    }
  };

  const handleViewProfile = async (id: string) => {
    try {
      const p = await getProfile(id);
      setSelectedProfile(p);
      setExpandedDim(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    }
  };

  const clearTaskState = () => {
    setCurrentTaskId('');
    setTask(null);
    setError('');
    setMessage('');
    setNotice('已清除历史任务状态。');
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>风格分析</h2>
        <button onClick={clearTaskState} style={{ padding: '4px 10px', fontSize: 12 }}>
          清除任务状态
        </button>
      </div>

      {error && <div style={{ background: '#2e1a1a', color: '#c86e6e', padding: '8px 12px', borderRadius: 6, marginBottom: 16, fontSize: 13 }}>{error}</div>}
      {message && <div style={{ background: '#1a2e1a', color: '#6ec86e', padding: '8px 12px', borderRadius: 6, marginBottom: 16, fontSize: 13 }}>{message}</div>}
      {notice && <div style={{ background: '#20202a', color: '#a0a0b0', padding: '7px 11px', borderRadius: 6, marginBottom: 16, fontSize: 12 }}>{notice}</div>}
      {task && (
        <TaskStatusPanel
          task={task}
          onCancel={handleCancel}
          onRetry={() => { void handleAnalyze(); }}
        />
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginTop: task ? 16 : 0 }}>
        {/* Left: chapter list + analyze */}
        <div className="bg-panel" style={{ padding: 20, maxHeight: 600, overflowY: 'auto' }}>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>选择章节进行分析</h3>
          {chapters.length === 0 ? (
            <p style={{ color: '#6a6a7a', fontSize: 13 }}>暂无章节，请先上传文本。</p>
          ) : (
            chapters.map((ch) => (
              <div key={ch.chapter_id} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '8px 12px', borderBottom: '1px solid #1a1a28', fontSize: 13,
                background: selectedChapterId === ch.chapter_id ? '#161625' : 'transparent',
              }}>
                <span
                  onClick={() => setSelectedChapterId(ch.chapter_id)}
                  style={{ cursor: 'pointer', flex: 1 }}
                >
                  [{ch.volume_display_name || ch.volume_key}] {ch.chapter_order}. {ch.title || ch.chapter_id}
                </span>
                <button
                  className="btn-primary"
                  style={{ padding: '4px 12px', fontSize: 12 }}
                  onClick={() => handleAnalyze(ch.chapter_id)}
                  disabled={task?.status === 'pending' || task?.status === 'running'}
                >
                  分析
                </button>
              </div>
            ))
          )}

          {/* Existing profiles */}
          {profiles.length > 0 && (
            <div style={{ marginTop: 20 }}>
              <h4 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>已有分析结果</h4>
              {profiles.map((p) => (
                <div
                  key={p.id}
                  onClick={() => handleViewProfile(p.id)}
                  style={{
                    padding: '8px 12px', cursor: 'pointer', borderBottom: '1px solid #1a1a28', fontSize: 13,
                    color: selectedProfile?.id === p.id ? '#c8a86e' : '#c8c8d0',
                  }}
                >
                  {p.id} — {p.dimensions.length}维度 — {new Date(p.created_at).toLocaleDateString('zh-CN')}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right: profile detail */}
        <div className="bg-panel" style={{ padding: 20, maxHeight: 600, overflowY: 'auto' }}>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>分析报告</h3>
          {!selectedProfile ? (
            <p style={{ color: '#6a6a7a', fontSize: 13 }}>选择分析结果查看报告</p>
          ) : (
            <div>
              <div style={{ fontSize: 13, color: '#6a6a7a', marginBottom: 16 }}>
                {selectedProfile.chapter_ids.length} 个章节 · {selectedProfile.dimensions.length} 个分析维度
              </div>
              {selectedProfile.dimensions.map((dim) => (
                <DimensionCard
                  key={dim.dimension}
                  dim={dim}
                  expanded={expandedDim === dim.dimension}
                  onToggle={() => setExpandedDim(expandedDim === dim.dimension ? null : dim.dimension)}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DimensionCard({ dim, expanded, onToggle }: { dim: DimensionResult; expanded: boolean; onToggle: () => void }) {
  const labelMap: Record<string, string> = {
    narrative_perspective: '叙事视角',
    sentence_rhythm: '句子长度与节奏',
    dialogue_ratio: '对话比例与特征',
    emotional_atmosphere: '情绪氛围',
    imagery: '高频意象',
    description_ratio: '描写类型比例',
    chapter_structure: '章节结构',
    conflict_advancement: '冲突推进方式',
    character_voice: '人物对白特点',
    cliffhanger_style: '章节结尾悬念',
    style_sensibility: '风格感知',
  };

  return (
    <div style={{ marginBottom: 8, border: '1px solid #1e1e2e', borderRadius: 6, overflow: 'hidden' }}>
      <div
        onClick={onToggle}
        style={{
          padding: '10px 14px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between',
          alignItems: 'center', background: expanded ? '#1a1a2e' : 'transparent',
        }}
      >
        <span style={{ fontSize: 14, fontWeight: 500 }}>{labelMap[dim.dimension] || dim.dimension}</span>
        <span style={{ fontSize: 12, color: '#6a6a7a' }}>{expanded ? '收起' : '展开'}</span>
      </div>
      {expanded && (
        <div style={{ padding: '12px 14px', background: '#0a0a12' }}>
          <p style={{ fontSize: 13, lineHeight: 1.7, marginBottom: 12, color: '#aaa' }}>{dim.summary || '无摘要'}</p>
          {Object.keys(dim.details).length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 12, color: '#6a6a7a', marginBottom: 6 }}>详细数据</div>
              <pre style={{ fontSize: 11, background: '#0d0d14', padding: 10, borderRadius: 4, overflow: 'auto', maxHeight: 200, color: '#aaa' }}>
                {JSON.stringify(dim.details, null, 2)}
              </pre>
            </div>
          )}
          {dim.examples.length > 0 && (
            <div>
              <div style={{ fontSize: 12, color: '#6a6a7a', marginBottom: 6 }}>原文示例</div>
              {dim.examples.map((ex, i) => (
                <div key={i} style={{ fontSize: 12, fontStyle: 'italic', padding: '4px 0', color: '#8a8a9a', borderLeft: '2px solid #2a2a3a', paddingLeft: 10, marginBottom: 4 }}>
                  {ex.length > 150 ? ex.slice(0, 150) + '...' : ex}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
