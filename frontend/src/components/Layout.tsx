import { type ReactNode } from 'react';
import { type Project } from '../api';

type Page = 'dashboard' | 'corpus' | 'analysis' | 'generator';

interface Props {
  currentPage: Page;
  onNavigate: (p: Page) => void;
  projects: Project[];
  activeProjectId: string;
  onProjectChange: (projectId: string) => void;
  onProjectCreate: () => void;
  projectError: string;
  children: ReactNode;
}

const NAV: { key: Page; label: string }[] = [
  { key: 'dashboard', label: '总览' },
  { key: 'corpus', label: '语料管理' },
  { key: 'analysis', label: '风格分析' },
  { key: 'generator', label: '创作' },
];

export default function Layout({
  currentPage,
  onNavigate,
  projects,
  activeProjectId,
  onProjectChange,
  onProjectCreate,
  projectError,
  children,
}: Props) {
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      {/* Sidebar */}
      <aside style={{
        width: 200,
        backgroundColor: '#0d0d14',
        borderRight: '1px solid #1e1e2e',
        padding: '24px 0',
        flexShrink: 0,
      }}>
        <div style={{ padding: '0 20px', marginBottom: 32 }}>
          <h1 style={{ fontSize: 18, fontWeight: 700, color: '#c8a86e', margin: 0, letterSpacing: 2 }}>
            NOVAL
          </h1>
          <p style={{ fontSize: 11, color: '#6a6a7a', margin: '4px 0 0' }}>本地 AI 长篇写作工作台</p>
          <label style={{ display: 'block', fontSize: 11, color: '#8a8a9a', marginTop: 18 }}>
            当前项目
            <select
              value={activeProjectId}
              onChange={(event) => onProjectChange(event.target.value)}
              style={{ width: '100%', marginTop: 6, padding: '7px 8px' }}
              aria-label="当前项目"
            >
              {!projects.length && <option value="">暂无项目</option>}
              {projects.map((project) => (
                <option key={project.project_id} value={project.project_id}>
                  {project.title}{project.status === 'archived' ? '（已归档）' : ''}
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={onProjectCreate}
            style={{ width: '100%', marginTop: 8, padding: '7px 8px', cursor: 'pointer' }}
          >
            新建项目
          </button>
          {projectError && (
            <p style={{ fontSize: 11, color: '#d78484', lineHeight: 1.5 }}>
              {projectError}
            </p>
          )}
        </div>
        <nav>
          {NAV.map((item) => (
            <button
              key={item.key}
              onClick={() => onNavigate(item.key)}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                padding: '10px 20px',
                border: 'none',
                background: currentPage === item.key ? '#1a1a2e' : 'transparent',
                color: currentPage === item.key ? '#c8a86e' : '#8a8a9a',
                cursor: 'pointer',
                fontSize: 14,
                borderLeft: currentPage === item.key ? '2px solid #c8a86e' : '2px solid transparent',
                transition: 'all 0.15s',
              }}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </aside>

      {/* Main content */}
      <main style={{ flex: 1, padding: '24px 32px', overflowY: 'auto', maxHeight: '100vh' }}>
        {children}
      </main>
    </div>
  );
}
