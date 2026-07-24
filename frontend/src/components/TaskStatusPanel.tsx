import { RotateCcw, Square } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { LongTask } from '../api';
import { Alert, Badge, Button, Progress } from './ui';

interface Props { task: LongTask; onCancel?: () => void; onRetry?: () => void; retryLabel?: string; }
const TYPE_LABELS: Record<LongTask['type'], string> = { style_analysis: '风格分析', knowledge_build: '知识库构建', generation: '章节生成', revision: '迭代修改', book_plan: '总体构想', chapter_review: 'AI 深度质检', chapter_repair: 'AI 质检修复' };
const STATUS_LABELS: Record<LongTask['status'], string> = { pending: '等待中', running: '运行中', success: '已完成', partial_success: '已生成，需确认', failed: '未完成', cancelled: '已取消', interrupted: '已中断' };

export default function TaskStatusPanel({ task, onCancel, onRetry, retryLabel = '重试' }: Props) {
  const [, setClock] = useState(0);
  const active = task.status === 'pending' || task.status === 'running';
  useEffect(() => { if (!active) return; const timer = window.setInterval(() => setClock((value) => value + 1), 1000); return () => window.clearInterval(timer); }, [active]);
  const callingModel = task.stage.includes('调用模型') || task.message.includes('API');
  const phaseLabel = active ? (callingModel ? '正在等待模型响应' : task.stage || '后台处理中') : STATUS_LABELS[task.status];
  const tone = task.status === 'failed' ? 'danger' : task.status === 'partial_success' || task.status === 'interrupted' ? 'warning' : task.status === 'success' ? 'success' : 'info';

  return <section className="task-panel" aria-live="polite">
    <div className="task-panel__header"><div><div className="task-panel__title">{TYPE_LABELS[task.type]}</div><div className="task-panel__meta">{phaseLabel} · 已用时 {formatElapsed(task.started_at || task.created_at, task.finished_at)}</div></div><Badge tone={tone}>{STATUS_LABELS[task.status]}</Badge></div>
    <Progress value={task.progress} label={`${TYPE_LABELS[task.type]}进度`} />
    <div className="task-panel__progress"><span>{Math.round(task.progress)}%</span><span>{task.message}</span></div>
    {task.type === 'generation' && task.total_segments > 0 && <div className="task-panel__meta">分段 {task.current_segment}/{task.total_segments} · 已生成 {task.partial_word_count.toLocaleString()} 字</div>}
    {task.error && <Alert tone="danger" title="任务未完成">{task.error.message}{task.error.http_status ? `（HTTP ${task.error.http_status}）` : ''}</Alert>}
    {task.status === 'partial_success' && <Alert tone="warning">{String(task.result.warning || task.message || '正文已保留，可继续人工编辑或修复。')}</Alert>}
    {task.status === 'failed' && task.type === 'generation' && task.partial_word_count > 0 && <Alert tone="warning">已生成的 {task.partial_word_count.toLocaleString()} 字仍然保留。</Alert>}
    {(active || ((task.status === 'failed' || task.status === 'cancelled' || task.status === 'interrupted') && onRetry)) && <div className="task-panel__actions">{active && onCancel && <Button size="sm" variant="danger" icon={<Square size={13} />} onClick={onCancel}>停止</Button>}{(task.status === 'failed' || task.status === 'cancelled' || task.status === 'interrupted') && onRetry && <Button size="sm" variant="primary" icon={<RotateCcw size={14} />} onClick={onRetry}>{retryLabel}</Button>}</div>}
    {task.logs.length > 0 && <details className="task-panel__details"><summary>技术详情</summary><div className="task-panel__logs">{task.logs.slice(-8).reverse().map((log, index) => <div key={`${log}-${index}`}>{log}</div>)}</div><div className="task-panel__id">任务编号：{task.task_id}</div></details>}
  </section>;
}

function formatElapsed(start: string, finish: string | null): string { const startMs = new Date(start).getTime(); const endMs = finish ? new Date(finish).getTime() : Date.now(); if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return '-'; const seconds = Math.max(0, Math.floor((endMs - startMs) / 1000)); const minutes = Math.floor(seconds / 60); return minutes > 0 ? `${minutes}分${seconds % 60}秒` : `${seconds}秒`; }
