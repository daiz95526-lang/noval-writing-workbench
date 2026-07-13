import { CheckCircle2, RefreshCw, Settings2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { getConfigStatus, type ConfigStatus } from '../api';
import { Alert, Badge, Button, ErrorState, LoadingState, PageHeader, Panel, SectionHeader } from '../components/ui';

export default function Settings() {
  const [status, setStatus] = useState<ConfigStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const refresh = async () => {
    setLoading(true); setError('');
    try { setStatus(await getConfigStatus()); } catch (value) { setError(value instanceof Error ? value.message : '无法读取配置状态'); } finally { setLoading(false); }
  };
  useEffect(() => { const timer = window.setTimeout(() => { void refresh(); }, 0); return () => window.clearTimeout(timer); }, []);

  return <div className="page-stack"><PageHeader title="设置" description="查看本机模型连接状态。敏感配置不会显示在页面中。" breadcrumbs="工作区 / 设置" actions={<Button icon={<RefreshCw size={15} />} onClick={() => void refresh()} loading={loading}>重新检查</Button>} />{loading && !status ? <LoadingState label="正在检查本地配置" /> : error ? <ErrorState title="无法读取配置" description={error} actions={<Button onClick={() => void refresh()}>重试</Button>} /> : status && <><Alert tone={status.has_api_key ? 'success' : 'warning'} title={status.has_api_key ? '模型配置可用' : '模型尚未配置'}>{status.has_api_key ? '已检测到模型凭据。页面不会读取或展示凭据内容。' : '请按照配置文档设置本地环境变量后重新检查。'}</Alert><Panel><SectionHeader title="模型连接" description="这里只展示可安全公开的配置状态。" /><div className="settings-list"><SettingRow label="API 凭据" value={status.has_api_key ? '已配置' : '未配置'} ok={status.has_api_key} /><SettingRow label="服务地址" value={status.base_url_configured ? '已配置自定义地址' : '使用默认地址'} ok /><SettingRow label="服务提供方" value={status.provider || '未指定'} /><SettingRow label="默认模型" value={status.model || '未指定'} /><SettingRow label="环境配置" value={status.env_loaded ? '已加载' : '未检测到 .env'} ok={status.env_loaded} /></div></Panel><Panel><SectionHeader title="本地数据" description="项目数据路径由后端配置管理；本页面不修改或迁移任何文件。" /><div className="ui-alert ui-alert--info"><Settings2 size={17} /><div>需要调整数据目录或服务端口时，请修改本地 `.env` 并重启后端。路径和密钥不会保存到浏览器。</div></div></Panel></>}</div>;
}

function SettingRow({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return <div className="settings-row"><div className="settings-row__label">{label}</div><div className="settings-row__value">{ok === undefined ? value : <Badge tone={ok ? 'success' : 'warning'}>{ok && <CheckCircle2 size={11} />} {value}</Badge>}</div></div>;
}
