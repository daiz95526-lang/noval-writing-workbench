import { ArrowRight, BookOpenText, FileText, PenLine, ScanSearch } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { AppPage } from '../components/Layout';
import { Button, EmptyState, ErrorState, LoadingState, PageHeader, Panel, SectionHeader } from '../components/ui';
import { getCorpusStats, listChapters, type ChapterMeta, type CorpusStats, type Project } from '../api';

export default function Dashboard({ project, onNavigate }: { project: Project; onNavigate: (page: AppPage) => void }) {
  const [stats, setStats] = useState<CorpusStats | null>(null);
  const [chapters, setChapters] = useState<ChapterMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const pageSize = 30;

  const refresh = async () => {
    setLoading(true); setError('');
    try { const [nextStats, nextChapters] = await Promise.all([getCorpusStats(), listChapters()]); setStats(nextStats); setChapters(nextChapters); }
    catch (value) { setError(value instanceof Error ? value.message : '无法读取项目概览'); }
    finally { setLoading(false); }
  };
  useEffect(() => { const timer = window.setTimeout(() => { void refresh(); }, 0); return () => window.clearTimeout(timer); }, []);

  if (loading) return <LoadingState label="正在加载项目概览" />;
  if (error) return <ErrorState title="项目概览加载失败" description={error} actions={<Button onClick={() => void refresh()}>重试</Button>} />;

  const totalPages = Math.max(1, Math.ceil(chapters.length / pageSize));
  const visibleChapters = chapters.slice((page - 1) * pageSize, page * pageSize);
  const hasCorpus = chapters.length > 0;

  return <div className="page-stack">
    <PageHeader title={project.title} description={project.description || '从语料分析、作品规划到章节写作，所有内容都保存在当前本地项目中。'} breadcrumbs="工作区 / 首页" actions={<Button variant="primary" icon={<PenLine size={16} />} onClick={() => onNavigate('creation')}>进入创作工作台</Button>} />
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

function formatNum(value: number): string { return value >= 10000 ? `${(value / 10000).toFixed(1)} 万` : value.toLocaleString(); }
function formatPercent(value: number): string { return `${(value * 100).toFixed(1)}%`; }
