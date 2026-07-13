import { Archive, ArrowRight, FolderKanban, Plus } from 'lucide-react';
import type { Project } from '../api';
import { Badge, Button, Card, EmptyState, PageHeader } from '../components/ui';

const TYPE_LABELS: Record<Project['project_type'], string> = { continuation: '续写', original: '原创', analysis: '分析' };

export default function Projects({ projects, activeProjectId, onSelect, onCreate }: {
  projects: Project[];
  activeProjectId: string;
  onSelect: (projectId: string) => void;
  onCreate: () => void;
}) {
  return (
    <div className="page-stack">
      <PageHeader title="项目" description="每个项目独立保存语料、分析、规划、草稿、正式章节和导出。" breadcrumbs="工作区 / 项目" actions={<Button variant="primary" icon={<Plus size={16} />} onClick={onCreate}>新建项目</Button>} />
      {!projects.length ? <EmptyState icon={<FolderKanban size={20} />} title="创建第一个写作项目" description="项目用于隔离语料、创作过程和正式章节。创建后可以导入本地文本。" actions={<Button variant="primary" onClick={onCreate}>新建项目</Button>} /> : <div className="project-grid">{projects.map((project) => <Card className="project-card" key={project.project_id}><div><div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}><h2 className="project-card__title">{project.title}</h2>{project.project_id === activeProjectId && <Badge tone="info">当前</Badge>}</div><div className="project-card__meta"><Badge>{TYPE_LABELS[project.project_type]}</Badge>{project.status === 'archived' ? <Badge tone="warning"><Archive size={11} /> 已归档</Badge> : <Badge tone="success">使用中</Badge>}{project.legacy && <Badge tone="warning">兼容项目</Badge>}</div><p className="project-card__description">{project.description || '尚未填写项目说明。'}</p></div><Button variant={project.project_id === activeProjectId ? 'secondary' : 'primary'} icon={<ArrowRight size={15} />} onClick={() => onSelect(project.project_id)}>{project.project_id === activeProjectId ? '进入当前项目' : '切换并进入'}</Button></Card>)}</div>}
    </div>
  );
}
