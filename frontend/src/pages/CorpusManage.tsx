import { useEffect, useState, useRef } from 'react';
import {
  getCorpusStats, listChapters, getChapter, uploadChapter, deleteChapter,
  scanLocal, getImportReport,
  type CorpusStats, type ChapterMeta, type Chapter, type ImportReport,
} from '../api';
import { Alert, EmptyState, LoadingState, PageHeader } from '../components/ui';

export default function CorpusManage() {
  const [stats, setStats] = useState<CorpusStats | null>(null);
  const [chapters, setChapters] = useState<ChapterMeta[]>([]);
  const [selected, setSelected] = useState<Chapter | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [importReport, setImportReport] = useState<ImportReport | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = async () => {
    setLoading(true);
    setError('');
    try {
      const [s, c, r] = await Promise.all([
        getCorpusStats(), listChapters(), getImportReport(),
      ]);
      setStats(s);
      setChapters(c);
      if (r) setImportReport(r);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载语料失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => { void refresh(); }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const handleUpload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setError('');
    try {
      await uploadChapter(file);
      setMessage(`已上传: ${file.name}`);
      if (fileRef.current) fileRef.current.value = '';
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '上传失败');
    } finally {
      setUploading(false);
    }
  };

  const handleScan = async () => {
    setScanning(true);
    setError('');
    setMessage('');
    try {
      const report = await scanLocal();
      setImportReport(report);
      const parts: string[] = [];
      if (report.new_chapters > 0) parts.push(`新增 ${report.new_chapters} 章`);
      if (report.skipped_duplicates > 0) parts.push(`跳过 ${report.skipped_duplicates} 重复章`);
      if (report.failed_files > 0) parts.push(`${report.failed_files} 文件失败`);
      setMessage(parts.length > 0 ? `扫描完成：${parts.join('，')}` : '扫描完成，未发现新章节');
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '扫描失败');
    } finally {
      setScanning(false);
    }
  };

  const handleView = async (chapterId: string) => {
    try {
      const ch = await getChapter(chapterId);
      setSelected(ch);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm(`确定删除章节 "${id}"？`)) return;
    try {
      await deleteChapter(id);
      setSelected(null);
      setMessage(`已删除: ${id}`);
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '删除失败');
    }
  };

  if (loading) return <LoadingState label="正在加载语料库" />;

  return (
    <div className="page-stack corpus-page">
      <PageHeader title="语料库" description="导入合法的本地文本、扫描章节并查看只读语料内容。" breadcrumbs="当前项目 / 语料库" />

      {error && <Alert tone="danger">{error}</Alert>}
      {message && <Alert tone="success">{message}</Alert>}

      <div className="metric-grid">
        <StatBadge label="总章节" value={stats?.total_chapters ?? 0} />
        <StatBadge label="总字数" value={stats ? formatNum(stats.total_words) : '0'} />
        <StatBadge label="已处理" value={`${stats?.processed_chapters ?? 0}/${stats?.total_chapters ?? 0}`} />
        {importReport && <StatBadge label="上次导入" value={`+${importReport.new_chapters}`} />}
      </div>

      {/* Scan + Upload */}
      <div className="bg-panel" style={{ padding: 20, marginBottom: 24 }}>
        <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>语料导入</h3>

        {/* Scan local */}
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, color: 'var(--text-primary)', marginBottom: 4 }}>自动扫描导入</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              扫描当前项目配置的只读语料目录，自动分章、去重后导入
            </div>
          </div>
          <button className="btn-primary" onClick={handleScan} disabled={scanning} style={{ whiteSpace: 'nowrap' }}>
            {scanning ? '扫描中...' : '扫描本地语料'}
          </button>
        </div>

        <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
          <div style={{ fontSize: 13, color: 'var(--text-primary)', marginBottom: 4 }}>手动上传文件</div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <input ref={fileRef} type="file" accept=".txt,.md" style={{ flex: 1 }} />
            <button className="btn-primary" onClick={handleUpload} disabled={uploading} style={{ whiteSpace: 'nowrap' }}>
              {uploading ? '上传中...' : '上传'}
            </button>
          </div>
        </div>
      </div>

      {/* Import report detail */}
      {importReport && importReport.details.length > 0 && (
        <div className="bg-panel" style={{ padding: 20, marginBottom: 24 }}>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>最近导入报告</h3>
          <div className="report-metrics">
            <MiniBadge label="扫描文件" value={importReport.scanned_files} />
            <MiniBadge label="新增章节" value={importReport.new_chapters} color="var(--success)" />
            <MiniBadge label="跳过重复" value={importReport.skipped_duplicates} color="var(--warning)" />
            <MiniBadge label="失败" value={importReport.failed_files} color={importReport.failed_files > 0 ? 'var(--danger)' : undefined} />
            <MiniBadge label="当前总章节" value={importReport.total_chapters_after} />
          </div>
          <div style={{ maxHeight: 320, overflow: 'auto' }}>
          <table style={{ width: '100%', minWidth: 760, borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)', textAlign: 'left' }}>
                <th style={{ padding: '6px 10px', color: 'var(--text-muted)', fontSize: 12, fontWeight: 500 }}>文件</th>
                <th style={{ padding: '6px 10px', color: 'var(--text-muted)', fontSize: 12, fontWeight: 500 }}>状态</th>
                <th style={{ padding: '6px 10px', color: 'var(--text-muted)', fontSize: 12, fontWeight: 500 }}>发现章节</th>
                <th style={{ padding: '6px 10px', color: 'var(--text-muted)', fontSize: 12, fontWeight: 500 }}>新增</th>
                <th style={{ padding: '6px 10px', color: 'var(--text-muted)', fontSize: 12, fontWeight: 500 }}>跳过</th>
                <th style={{ padding: '6px 10px', color: 'var(--text-muted)', fontSize: 12, fontWeight: 500 }}>备注</th>
              </tr>
            </thead>
            <tbody>
              {importReport.details.map((d, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '6px 10px' }}>{d.file}</td>
                  <td style={{ padding: '6px 10px' }}>
                    <span style={{
                      fontSize: 11, padding: '2px 8px', borderRadius: 4,
                      background: d.status === 'ok' ? 'var(--success-soft)' : d.status === 'empty' ? 'var(--surface-hover)' : 'var(--danger-soft)',
                      color: d.status === 'ok' ? 'var(--success)' : d.status === 'empty' ? 'var(--text-muted)' : 'var(--danger)',
                    }}>
                      {d.status === 'ok' ? '成功' : d.status === 'empty' ? '空文件' : '错误'}
                    </span>
                  </td>
                  <td style={{ padding: '6px 10px' }}>{d.chapters_found}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--success)' }}>{d.chapters_added}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--warning)' }}>{d.chapters_skipped}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--text-muted)', fontSize: 12, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {d.error_message || '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
            {importReport.timestamp ? new Date(importReport.timestamp).toLocaleString('zh-CN') : ''}
          </div>
        </div>
      )}

      <div className="responsive-two-column">
        {/* Chapter list */}
        <div className="bg-panel" style={{ padding: 20, maxHeight: 500, overflowY: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
            <h3 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>章节列表</h3>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>共 {chapters.length} 章，全部已加载</span>
          </div>
          {chapters.length === 0 ? (
            <EmptyState title="暂无语料章节" description="扫描当前项目的语料目录，或上传 TXT、Markdown 文件。" />
          ) : (
            chapters.map((ch) => {
              const chapterId = ch.chapter_id;
              return (
                <div
                  key={chapterId}
                  onClick={() => handleView(chapterId)}
                  style={{
                    padding: '8px 12px',
                    cursor: 'pointer',
                    borderBottom: '1px solid var(--border-subtle)',
                    fontSize: 13,
                    display: 'flex',
                    justifyContent: 'space-between',
                  }}
                  title={chapterId}
                >
                  <span>[{ch.volume_display_name}] {ch.chapter_order}. {ch.title || chapterId}</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{formatNum(ch.word_count)}字</span>
                </div>
              );
            })
          )}
        </div>

        {/* Detail */}
        <div className="bg-panel" style={{ padding: 20, maxHeight: 500, overflowY: 'auto' }}>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>章节详情</h3>
          {!selected ? (
            <EmptyState title="选择一个章节" description="章节正文只用于本地阅读和分析。" />
          ) : (
            <div>
              <div style={{ marginBottom: 12 }}>
                <span style={{ fontSize: 14, fontWeight: 600 }}>{selected.title}</span>
                <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 12 }}>{formatNum(selected.word_count)}字</span>
                <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>对话比 {(selected.dialogue_ratio * 100).toFixed(1)}%</span>
              </div>
              <button className="btn-danger" style={{ marginBottom: 12, fontSize: 12, padding: '4px 12px' }} onClick={() => handleDelete(selected.chapter_id)}>
                删除此章节
              </button>
              <div style={{ whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.8, maxHeight: 340, overflowY: 'auto', color: 'var(--text-secondary)' }}>
                {selected.content}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatBadge({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric ui-panel">
      <div className="metric__label">{label}</div>
      <div className="metric__value">{value}</div>
    </div>
  );
}

function MiniBadge({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="bg-panel-alt" style={{ padding: '10px 14px', textAlign: 'center' }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: color || 'var(--text-primary)' }}>{value}</div>
    </div>
  );
}

function formatNum(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
  return n.toLocaleString();
}
