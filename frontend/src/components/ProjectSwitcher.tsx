import { Plus } from 'lucide-react';
import type { Project } from '../api';
import { IconButton } from './ui';

export default function ProjectSwitcher({ projects, activeProjectId, onChange, onCreate }: {
  projects: Project[];
  activeProjectId: string;
  onChange: (projectId: string) => void;
  onCreate: () => void;
}) {
  return (
    <div className="app-project-switcher">
      <label className="app-project-switcher__label" htmlFor="app-project-select">当前项目</label>
      <div className="app-project-switcher__row">
        <select id="app-project-select" className="app-project-switcher__select" value={activeProjectId} onChange={(event) => onChange(event.target.value)}>
          {!projects.length && <option value="">暂无项目</option>}
          {projects.map((project) => <option key={project.project_id} value={project.project_id}>{project.title}{project.status === 'archived' ? '（已归档）' : ''}</option>)}
        </select>
        <IconButton label="新建项目" variant="secondary" onClick={onCreate}><Plus size={17} /></IconButton>
      </div>
    </div>
  );
}
