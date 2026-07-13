import { useEffect, useState } from 'react';
import Layout, { type AppPage } from './components/Layout';
import { Alert, Button, EmptyState, Field, Modal, Select, Textarea, Input } from './components/ui';
import Dashboard from './pages/Dashboard';
import CorpusManage from './pages/CorpusManage';
import StyleAnalysis from './pages/StyleAnalysis';
import Generator from './pages/Generator';
import Projects from './pages/Projects';
import Settings from './pages/Settings';
import { createProject, getActiveProjectId, listProjects, setActiveProjectId, type Project, type ProjectType } from './api';

export default function App() {
  const [page, setPage] = useState<AppPage>('home');
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsLoaded, setProjectsLoaded] = useState(false);
  const [activeProjectId, setActiveProjectState] = useState(getActiveProjectId());
  const [projectError, setProjectError] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [projectType, setProjectType] = useState<ProjectType>('original');

  useEffect(() => {
    let disposed = false;
    listProjects().then((items) => {
      if (disposed) return;
      setProjects(items);
      const current = items.find((item) => item.project_id === getActiveProjectId());
      const fallback = current || items.find((item) => item.status === 'active') || items[0];
      setActiveProjectId(fallback?.project_id || '');
      setActiveProjectState(fallback?.project_id || '');
      setProjectsLoaded(true);
    }).catch((error) => { if (!disposed) { setProjectError(error instanceof Error ? error.message : '无法读取项目列表'); setProjectsLoaded(true); } });
    return () => { disposed = true; };
  }, []);

  const selectProject = (projectId: string, destination: AppPage = 'home') => { setActiveProjectId(projectId); setActiveProjectState(projectId); setPage(destination); setProjectError(''); };
  const submitProject = async () => {
    if (!title.trim()) return;
    setCreating(true); setProjectError('');
    try {
      const project = await createProject({ title: title.trim(), description: description.trim(), project_type: projectType });
      setProjects((items) => [...items, project]);
      setTitle(''); setDescription(''); setProjectType('original'); setCreateOpen(false); selectProject(project.project_id);
    } catch (error) { setProjectError(error instanceof Error ? error.message : '创建项目失败'); } finally { setCreating(false); }
  };

  const activeProject = projects.find((item) => item.project_id === activeProjectId);
  const projectPage = !projectsLoaded ? <div className="ui-state">正在加载项目...</div> : !activeProject ? <EmptyState title="尚未选择项目" description="创建或选择项目后，可以进入语料、分析和创作工作区。" actions={<><Button variant="primary" onClick={() => setCreateOpen(true)}>新建项目</Button>{projects.length > 0 && <Button onClick={() => setPage('projects')}>选择项目</Button>}</>} /> : null;

  const renderPage = () => {
    if (page === 'projects') return <Projects projects={projects} activeProjectId={activeProjectId} onSelect={(id) => selectProject(id)} onCreate={() => setCreateOpen(true)} />;
    if (page === 'settings') return <Settings />;
    if (projectPage) return projectPage;
    switch (page) {
      case 'home': return <Dashboard project={activeProject!} onNavigate={setPage} />;
      case 'corpus': return <CorpusManage />;
      case 'analysis': return <StyleAnalysis />;
      case 'creation': return <Generator />;
      case 'library': return <Generator initialTab="official" />;
      default: return null;
    }
  };

  return <><Layout currentPage={page} onNavigate={setPage} projects={projects} activeProjectId={activeProjectId} onProjectChange={(id) => selectProject(id)} onProjectCreate={() => setCreateOpen(true)} projectError={projectError}><div key={`${activeProjectId}:${page}`}>{renderPage()}</div></Layout><Modal open={createOpen} title="新建项目" onClose={() => setCreateOpen(false)} footer={<><Button onClick={() => setCreateOpen(false)}>取消</Button><Button variant="primary" loading={creating} disabled={!title.trim()} onClick={() => void submitProject()}>创建项目</Button></>}><div className="page-stack">{projectError && <Alert tone="danger">{projectError}</Alert>}<Field label="项目名称"><Input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} maxLength={120} placeholder="例如：新长篇计划" /></Field><Field label="项目类型"><Select value={projectType} onChange={(event) => setProjectType(event.target.value as ProjectType)}><option value="original">原创长篇</option><option value="continuation">续写项目</option><option value="analysis">语料分析</option></Select></Field><Field label="项目说明" help="可选，后续可以完善。"><Textarea rows={4} value={description} onChange={(event) => setDescription(event.target.value)} maxLength={1000} /></Field></div></Modal></>;
}
