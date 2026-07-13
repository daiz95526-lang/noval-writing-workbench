import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  BookOpenText,
  FolderKanban,
  Home,
  LibraryBig,
  Menu,
  PenLine,
  ScanSearch,
  Settings,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import { listTasks, type LongTask, type Project } from '../api';
import ProjectSwitcher from './ProjectSwitcher';
import { Alert, IconButton } from './ui';

export type AppPage = 'home' | 'projects' | 'corpus' | 'analysis' | 'creation' | 'library' | 'settings';

interface Props {
  currentPage: AppPage;
  onNavigate: (page: AppPage) => void;
  projects: Project[];
  activeProjectId: string;
  onProjectChange: (projectId: string) => void;
  onProjectCreate: () => void;
  projectError: string;
  children: ReactNode;
}

const NAV_GROUPS = [
  { label: '工作区', items: [
    { key: 'home', label: '首页', icon: Home },
    { key: 'projects', label: '项目', icon: FolderKanban },
  ] },
  { label: '当前项目', items: [
    { key: 'corpus', label: '语料库', icon: BookOpenText },
    { key: 'analysis', label: '分析', icon: ScanSearch },
    { key: 'creation', label: '创作', icon: PenLine },
    { key: 'library', label: '章节库', icon: LibraryBig },
  ] },
] satisfies { label: string; items: { key: AppPage; label: string; icon: typeof Home }[] }[];

const PAGE_LABELS: Record<AppPage, string> = {
  home: '首页', projects: '项目', corpus: '语料库', analysis: '分析中心', creation: '创作工作台', library: '章节库', settings: '设置',
};

export default function Layout({ currentPage, onNavigate, projects, activeProjectId, onProjectChange, onProjectCreate, projectError, children }: Props) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [tasks, setTasks] = useState<LongTask[]>([]);
  const activeProject = useMemo(() => projects.find((project) => project.project_id === activeProjectId), [projects, activeProjectId]);

  useEffect(() => {
    if (!activeProjectId) return;
    let disposed = false;
    const refresh = () => { void listTasks(12).then((items) => { if (!disposed) setTasks(items); }).catch(() => { if (!disposed) setTasks([]); }); };
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [activeProjectId]);

  const activeTask = activeProjectId ? tasks.find((task) => task.status === 'pending' || task.status === 'running') : undefined;
  const navigate = (page: AppPage) => { onNavigate(page); setMobileOpen(false); };

  return (
    <div className="app-shell">
      {mobileOpen && <button className="app-sidebar-backdrop" aria-label="关闭导航" onClick={() => setMobileOpen(false)} />}
      <aside className="app-sidebar" data-open={mobileOpen} aria-label="主导航">
        <div className="app-brand">
          <div className="app-brand__mark" aria-hidden="true">N</div>
          <div className="app-brand__text"><div className="app-brand__name">NOVAL</div><div className="app-brand__tagline">本地 AI 长篇写作工作台</div></div>
          <IconButton className="app-mobile-menu" label="关闭导航" variant="ghost" onClick={() => setMobileOpen(false)}><X size={18} /></IconButton>
        </div>
        <ProjectSwitcher projects={projects} activeProjectId={activeProjectId} onChange={onProjectChange} onCreate={onProjectCreate} />
        <nav className="app-nav">
          {NAV_GROUPS.map((group) => <div className="app-nav__group" key={group.label}><div className="app-nav__label">{group.label}</div>{group.items.map(({ key, label, icon: Icon }) => <button key={key} className="app-nav__item" aria-current={currentPage === key ? 'page' : undefined} onClick={() => navigate(key)} disabled={!activeProjectId && !['home', 'projects'].includes(key)} title={label}><Icon size={17} aria-hidden="true" /><span>{label}</span></button>)}</div>)}
        </nav>
        <div className="app-sidebar__footer"><button className="app-nav__item" aria-current={currentPage === 'settings' ? 'page' : undefined} onClick={() => navigate('settings')}><Settings size={17} /><span>设置</span></button></div>
      </aside>

      <div className="app-workspace">
        <header className="app-topbar">
          <div className="app-topbar__actions">
            <IconButton className="app-mobile-menu" label="打开导航" variant="ghost" aria-expanded={mobileOpen} onClick={() => setMobileOpen(true)}><Menu size={18} /></IconButton>
            <div className="app-topbar__context"><div className="app-topbar__title">{PAGE_LABELS[currentPage]}</div><div className="app-topbar__project">{activeProject?.title || '尚未选择项目'}</div></div>
          </div>
          <div className="app-topbar__actions">
            <div className="app-task-indicator" title={activeTask ? activeTask.stage || activeTask.message : '当前没有运行中的任务'}><span className={`app-task-indicator__dot${activeTask ? ' app-task-indicator__dot--active' : ''}`} /><span>{activeTask ? '后台任务进行中' : '任务空闲'}</span></div>
            <IconButton label="设置" variant="ghost" onClick={() => navigate('settings')}><SlidersHorizontal size={18} /></IconButton>
          </div>
        </header>
        <main className="app-main">
          <div className="app-content">
            {projectError && <Alert tone="danger" title="项目操作失败" className="app-project-error">{projectError}</Alert>}
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
