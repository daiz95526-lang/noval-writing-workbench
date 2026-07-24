import { ArrowRight, BookOpenText, Check, Circle, Clock3, FileText, PenLine, ScanSearch } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import type { AppPage } from '../components/Layout';
import { Badge, Button, EmptyState, ErrorState, LoadingState, PageHeader, Panel, SectionHeader } from '../components/ui';
import { getCorpusStats, getProjectSummary, listChapters, type ChapterMeta, type CorpusStats, type Project, type ProjectSummary } from '../api';

export default function Dashboard({ project, onNavigate }: { project: Project; onNavigate: (page: AppPage) => void }) {
  const [stats, setStats] = useState<CorpusStats | null>(null);
  const [chapters, setChapters] = useState<ChapterMeta[]>([]);
  const [summary, setSummary] = useState<ProjectSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const pageSize = 30;

  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [nextStats, nextChapters, nextSummary] = await Promise.all([getCorpusStats(), listChapters(), getProjectSummary(project.project_id)]);
      setStats(nextStats); setChapters(nextChapters); setSummary(nextSummary);
    }
    catch (value) { setError(value instanceof Error ? value.message : '无法读取项目概览'); }
    finally { setLoading(false); }
  }, [project.project_id]);
  useEffect(() => { const timer = window.setTimeout(() => { void refresh(); }, 0); return () => window.clearTimeout(timer); }, [refresh]);

  if (loading) return <LoadingState label="正在加载项目概览" />;
  if (error) return <ErrorState title="项目概览加载失败" description={error} actions={<Button onClick={() => void refresh()}>重试</Button>} />;

  const totalPages = Math.max(1, Math.ceil(chapters.length / pageSize));
  const visibleChapters = chapters.slice((page - 1) * pageSize, page * pageSize);
  const hasCorpus = chapters.length > 0;
  const recommendedPage = recommendedDestination(summary?.recommended_step);
  const workflow = [
    { label: '导入语料', done: (summary?.corpus_chapter_count ?? 0) > 0 },
    { label: '完成分析', done: (summary?.analysis_profile_count ?? 0) > 0 },
    { label: '总体构想', done: summary?.book_plan_accepted ?? false },
    { label: '章节规划', done: summary?.chapter_plans_complete ?? false },
    { label: '正式章节', done: (summary?.official_chapter_count ?? 0) > 0 },
  ];

  return <div className="page-stack">
    <PageHeader title={project.title} description={project.description || '从语料分析、作品规划到章节写作，所有内容都保存在当前本地项目中。'} breadcrumbs="工作区 / 首页" actions={<Button variant="primary" icon={<PenLine size={16} />} onClick={() => onNavigate('creation')}>进入创作工作台</Button>} />
    {summary && <Panel className="workflow-overview">
      <SectionHeader title="创作进度" description="按当前项目数据生成，完成一项后会自动推荐下一步。" />
      <div className="workflow-steps" aria-label="创作流程进度">
        {workflow.map((item, index) => <div className={`workflow-step${item.done ? ' workflow-step--done' : ''}`} key={item.label}>{item.done ? <Check size={15} /> : <Circle size={13} />}<span>{index + 1}. {item.label}</span></div>)}
      </div>
      <div className="workflow-recommendation">
        <div><div className="workflow-recommendation__label">推荐下一步</div><strong>{summary.recommended_action}</strong>{summary.current_chapter_order !== null && <small>当前第 {summary.current_chapter_order} 章{summary.current_chapter_title ? `：${summary.current_chapter_title}` : ''}</small>}</div>
        <Button variant="primary" onClick={() => onNavigate(recommendedPage)}>继续 <ArrowRight size={15} /></Button>
      </div>
    </Panel>}
    <div className="metric-grid">
      <Metric label="语料章节" value={stats?.total_chapters ?? 0} accent />
      <Metric label="语料字数" value={formatNum(stats?.total_words ?? 0)} />
      <Metric label="分卷数量" value={stats?.total_volumes ?? 0} />
      <Metric label="已处理章节" value={`${stats?.processed_chapters ?? 0}/${stats?.total_chapters ?? 0}`} />
    </div>
    {!hasCorpus ? <Panel><EmptyState icon={<BookOpenText size={20} />} title="当前项目还没有语料" description="导入合法的本地文本并扫描章节后，即可进行风格分析和辅助创作。" actions={<Button variant="primary" onClick={() => onNavigate('corpus')}>导入语料</Button>} /></Panel> : <>
      <div className="project-grid">
        <QuickAction icon={<BookOpenText size={18} />} title="整理语料" description="查看导入报告和章节内容。" onClick={() => onNavigate('corpus')} />
        <QuickAction icon={<ScanSearch size={18} />} title="分析作品" description="提取风格特征，构建创作参考。" onClick={() => onNavigate('analysis')} />
        <QuickAction icon={<FileText size={18} />} title="继续写作" description="打开规划、生成和编辑流程。" onClick={() => onNavigate('creation')} />
      </div>
      {summary && <div className="responsive-two-column">
        <Panel><SectionHeader title="当前创作" description="临时内容与正式章节分开统计。" />
          <div className="status-list">
            <StatusRow label="总体构想" value={summary.book_plan_accepted ? '已接受' : summary.book_plan_exists ? '待审核' : '未生成'} done={summary.book_plan_accepted} />
            <StatusRow label="章节规划" value={summary.chapter_plans_complete ? `已完成 ${summary.chapter_plan_count} 章` : `${summary.planned_chapter_count}/${summary.chapter_plan_count || '-'} 已规划`} done={summary.chapter_plans_complete} />
            <StatusRow label="临时生成" value={`${summary.temp_generation_count} 条`} />
            <StatusRow label="正式章节" value={`${summary.official_chapter_count} 章`} done={summary.official_chapter_count > 0} />
          </div>
        </Panel>
        <Panel><SectionHeader title="最近活动" description={summary.active_task_count > 0 ? `${summary.active_task_count} 个任务正在运行` : '当前没有运行中的任务'} />
          {summary.recent_tasks.length > 0 ? <div className="activity-list">{summary.recent_tasks.slice(0, 3).map((task) => <div className="activity-row" key={task.task_id}><Clock3 size={15} /><span><strong>{task.title}</strong><small>{task.stage}</small></span><Badge tone={task.status === 'failed' ? 'danger' : task.status === 'success' ? 'success' : 'info'}>{taskStatusText(task.status)}</Badge></div>)}</div> : summary.recent_official_chapters.length > 0 ? <div className="activity-list">{summary.recent_official_chapters.slice(0, 3).map((chapter) => <div className="activity-row" key={chapter.chapter_id}><FileText size={15} /><span><strong>第 {chapter.order} 章 · {chapter.title}</strong><small>{formatNum(chapter.word_count)} 字</small></span><Badge tone="success">正式</Badge></div>)}</div> : <p className="ui-section-description">完成一次分析、构想或章节保存后，最近活动会显示在这里。</p>}
        </Panel>
      </div>}
      <Panel><SectionHeader title="语料章节" description={`共 ${chapters.length} 章，当前显示 ${visibleChapters.length} 章。`} actions={<Button size="sm" variant="ghost" onClick={() => onNavigate('corpus')}>管理语料 <ArrowRight size={14} /></Button>} />
        <div className="table-scroll"><table className="data-table"><thead><tr><th>分卷</th><th>序号</th><th>标题</th><th>字数</th><th>对话占比</th></tr></thead><tbody>{visibleChapters.map((chapter) => <tr key={chapter.chapter_id}><td>{chapter.volume_display_name || chapter.volume_key || '-'}</td><td>{chapter.chapter_order}</td><td>{chapter.title}</td><td>{formatNum(chapter.word_count)}</td><td>{formatPercent(chapter.dialogue_ratio)}</td></tr>)}</tbody></table></div>
        {chapters.length > pageSize && <div className="table-pagination"><Button size="sm" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</Button><span>{page} / {totalPages}</span><Button size="sm" disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}>下一页</Button></div>}
      </Panel>
    </>}
  </div>;
}

function Metric({ label, value, accent }: { label: string; value: string | number; accent?: boolean }) {
  return <div className={`metric ui-panel${accent ? ' metric--accent' : ''}`}><div className="metric__label">{label}</div><div className="metric__value">{value}</div></div>;
}

function QuickAction({ icon, title, description, onClick }: { icon: React.ReactNode; title: string; description: string; onClick: () => void }) {
  return <button className="quick-action" onClick={onClick}><span className="quick-action__icon">{icon}</span><span><strong>{title}</strong><small>{description}</small></span><ArrowRight size={16} aria-hidden="true" /></button>;
}

function StatusRow({ label, value, done = false }: { label: string; value: string; done?: boolean }) {
  return <div className="status-row"><span>{label}</span><Badge tone={done ? 'success' : 'neutral'}>{value}</Badge></div>;
}

function recommendedDestination(step?: string): AppPage {
  if (step === 'import_corpus') return 'corpus';
  if (step === 'analyze') return 'analysis';
  if (step === 'export') return 'library';
  return 'creation';
}

function taskStatusText(status: ProjectSummary['recent_tasks'][number]['status']): string {
  return ({ pending: '等待', running: '执行中', success: '完成', partial_success: '部分完成', failed: '失败', cancelled: '已取消', interrupted: '已中断' })[status];
}

function formatNum(value: number): string { return value >= 10000 ? `${(value / 10000).toFixed(1)} 万` : value.toLocaleString(); }
function formatPercent(value: number): string { return `${(value * 100).toFixed(1)}%`; }
