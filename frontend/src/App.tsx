import { useEffect, useState } from 'react';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import CorpusManage from './pages/CorpusManage';
import StyleAnalysis from './pages/StyleAnalysis';
import Generator from './pages/Generator';
import {
  createProject,
  getActiveProjectId,
  listProjects,
  setActiveProjectId,
  type Project,
} from './api';

type Page = 'dashboard' | 'corpus' | 'analysis' | 'generator';

export default function App() {
  const [page, setPage] = useState<Page>('dashboard');
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsLoaded, setProjectsLoaded] = useState(false);
  const [activeProjectId, setActiveProjectState] = useState(getActiveProjectId());
  const [projectError, setProjectError] = useState('');

  useEffect(() => {
    let disposed = false;
    listProjects()
      .then((items) => {
        if (disposed) return;
        setProjects(items);
        const current = items.find((item) => item.project_id === getActiveProjectId());
        const fallback = current || items.find((item) => item.status === 'active') || items[0];
        if (fallback && fallback.project_id !== getActiveProjectId()) {
          setActiveProjectId(fallback.project_id);
          setActiveProjectState(fallback.project_id);
        }
        if (!fallback) {
          setActiveProjectId('');
          setActiveProjectState('');
        }
        setProjectsLoaded(true);
      })
      .catch((error) => {
        if (!disposed) {
          setProjectError(error instanceof Error ? error.message : '无法读取项目列表');
          setProjectsLoaded(true);
        }
      });
    return () => { disposed = true; };
  }, []);

  const selectProject = (projectId: string) => {
    setActiveProjectId(projectId);
    setActiveProjectState(projectId);
    setPage('dashboard');
    setProjectError('');
  };

  const addProject = async () => {
    const title = window.prompt('项目名称');
    if (!title?.trim()) return;
    try {
      const project = await createProject({ title: title.trim(), project_type: 'original' });
      setProjects((items) => [...items, project]);
      selectProject(project.project_id);
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : '创建项目失败');
    }
  };

  const renderPage = () => {
    if (!projectsLoaded || !projects.some((item) => item.project_id === activeProjectId)) {
      return null;
    }
    switch (page) {
      case 'dashboard': return <Dashboard />;
      case 'corpus': return <CorpusManage />;
      case 'analysis': return <StyleAnalysis />;
      case 'generator': return <Generator />;
    }
  };

  return (
    <Layout
      currentPage={page}
      onNavigate={setPage}
      projects={projects}
      activeProjectId={activeProjectId}
      onProjectChange={selectProject}
      onProjectCreate={addProject}
      projectError={projectError}
    >
      <div key={activeProjectId}>{renderPage()}</div>
    </Layout>
  );
}
