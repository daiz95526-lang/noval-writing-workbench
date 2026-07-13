import { useEffect, useState } from 'react';
import type { LongTask } from '../api';

interface Props {
  task: LongTask;
  onCancel?: () => void;
  onRetry?: () => void;
  retryLabel?: string;
}

const TYPE_LABELS: Record<LongTask['type'], string> = {
  style_analysis: '风格分析',
  knowledge_build: '知识库构建',
  generation: '章节生成',
  revision: '迭代修改',
  book_plan: '全书自动构想',
  chapter_review: 'AI 深度质检',
  chapter_repair: 'AI 质检修复',
};

const STATUS_LABELS: Record<LongTask['status'], string> = {
  pending: '等待中',
  running: '运行中',
  success: '已完成',
  partial_success: '已生成，但有提醒',
  failed: '已失败',
  cancelled: '已取消',
};

export default function TaskStatusPanel({ task, onCancel, onRetry, retryLabel = '重试' }: Props) {
  const [, setClock] = useState(0);
  const active = task.status === 'pending' || task.status === 'running';

  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setClock((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [active]);

  const elapsed = formatElapsed(task.started_at || task.created_at, task.finished_at);
  const callingModel = task.stage.includes('调用模型') || task.message.includes('API');
  const activePhaseLabel = task.stage.includes('汇总')
    ? '汇总风格'
    : task.stage.includes('分析第')
      ? '分章分析'
      : task.stage.includes('缓存')
        ? '缓存处理中'
        : callingModel
          ? '正在调用模型'
          : '后台处理中';
  const phaseLabel = active
    ? activePhaseLabel
    : task.status === 'partial_success'
      ? '已生成，但有提醒'
      : STATUS_LABELS[task.status];

  return (
    <div className="bg-panel-alt" style={{ padding: 14, marginTop: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600 }}>
            {TYPE_LABELS[task.type]} · {STATUS_LABELS[task.status]}
          </div>
          <div style={{ fontSize: 11, color: '#6a6a7a', marginTop: 2 }}>任务 {task.task_id}</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {active && onCancel && (
            <button className="btn-danger" onClick={onCancel} style={{ padding: '4px 10px', fontSize: 12 }}>
              取消
            </button>
          )}
          {(task.status === 'failed' || task.status === 'cancelled') && onRetry && (
            <button className="btn-primary" onClick={onRetry} style={{ padding: '4px 10px', fontSize: 12 }}>
              {retryLabel}
            </button>
          )}
        </div>
      </div>

      <div style={{ fontSize: 13, marginBottom: 6 }}>{task.stage || '等待后台任务'}</div>
      <div className="progress-bar" style={{ marginBottom: 6 }}>
        <div className="progress-bar-fill" style={{ width: `${Math.max(0, Math.min(task.progress, 100))}%` }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', color: '#8a8a9a', fontSize: 12 }}>
        <span>{Math.round(task.progress)}% · 已耗时 {elapsed}</span>
        <span style={{ color: callingModel ? '#c8a86e' : '#6a6a7a' }}>
          {phaseLabel}
        </span>
      </div>
      <div style={{ fontSize: 12, color: '#aaa', marginTop: 8 }}>{task.message}</div>
      {task.type === 'generation' && task.total_segments > 0 && (
        <div style={{ marginTop: 8, color: '#8a8a9a', fontSize: 12 }}>
          分段进度：{task.current_segment}/{task.total_segments}
          {' · '}已生成 {task.partial_word_count.toLocaleString()} 字
          {task.can_accept && !['success', 'partial_success'].includes(task.status) ? ' · 当前部分可接受' : ''}
        </div>
      )}

      {task.error && (
        <div style={{ marginTop: 10, padding: 10, background: '#2e1a1a', color: '#c86e6e', borderRadius: 4, fontSize: 12 }}>
          {task.error.is_timeout ? task.error.message : `失败原因：${task.error.message}`}
          {task.error.http_status ? `（HTTP ${task.error.http_status}）` : ''}
        </div>
      )}

      {task.status === 'success' && (
        <div style={{ marginTop: 8, color: '#6ec86e', fontSize: 12 }}>
          结果已完成并载入当前页面。
        </div>
      )}
      {task.status === 'partial_success' && (
        <div style={{ marginTop: 8, color: '#c8a86e', fontSize: 12 }}>
          {String(task.result.warning || task.message || '正文已保留，可手动编辑、修复或保存。')}
        </div>
      )}
      {task.status === 'failed' && task.type === 'knowledge_build' && Object.keys(task.result).length > 0 && (
        <div style={{ marginTop: 8, color: '#c8a86e', fontSize: 12 }}>
          {task.result.summary_failed
            ? '章节级分析已完成，最终汇总失败；缓存和规则知识库已保留。'
            : '模型整理失败，但规则知识库已保留，可继续使用或重试。'}
        </div>
      )}
      {task.status === 'failed' && task.type === 'generation' && task.partial_word_count > 0 && (
        <div style={{ marginTop: 8, color: '#c8a86e', fontSize: 12 }}>
          生成未全部完成，但已保留 {task.partial_word_count.toLocaleString()} 字，不会丢失。
        </div>
      )}

      {task.logs.length > 0 && (
        <details style={{ marginTop: 10 }}>
          <summary style={{ cursor: 'pointer', color: '#8a8a9a', fontSize: 12 }}>最近日志</summary>
          <div style={{ maxHeight: 120, overflowY: 'auto', marginTop: 6 }}>
            {task.logs.slice(-6).reverse().map((log, index) => (
              <div key={`${log}-${index}`} style={{ fontSize: 11, color: '#6a6a7a', padding: '2px 0' }}>
                {log}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function formatElapsed(start: string, finish: string | null): string {
  const startMs = new Date(start).getTime();
  const endMs = finish ? new Date(finish).getTime() : Date.now();
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return '-';
  const seconds = Math.max(0, Math.floor((endMs - startMs) / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? `${minutes}分${seconds % 60}秒` : `${seconds}秒`;
}
