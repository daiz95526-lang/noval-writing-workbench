import { useEffect, useState } from 'react';
import { getCorpusStats, listChapters, type CorpusStats, type ChapterMeta } from '../api';

export default function Dashboard() {
  const [stats, setStats] = useState<CorpusStats | null>(null);
  const [chapters, setChapters] = useState<ChapterMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const pageSize = 50;

  useEffect(() => {
    Promise.all([getCorpusStats(), listChapters()])
      .then(([s, c]) => { setStats(s); setChapters(c); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div style={{ color: '#6a6a7a' }}>加载中...</div>;
  if (error) return <div style={{ color: '#c86e6e' }}>加载失败: {error}</div>;
  const totalPages = Math.max(1, Math.ceil(chapters.length / pageSize));
  const visibleChapters = chapters.slice((page - 1) * pageSize, page * pageSize);

  return (
    <div>
      <h2 style={{ fontSize: 22, fontWeight: 600, marginBottom: 24 }}>系统总览</h2>

      {/* Stats cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 32 }}>
        <StatCard label="总卷数" value={stats?.total_volumes ?? 0} />
        <StatCard label="总章节" value={stats?.total_chapters ?? 0} />
        <StatCard label="总字数" value={formatNum(stats?.total_words ?? 0)} />
        <StatCard label="已处理" value={`${stats?.processed_chapters ?? 0}/${stats?.total_chapters ?? 0}`} />
      </div>

      {/* Chapter list */}
      <div className="bg-panel" style={{ padding: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>章节列表</h3>
          <span style={{ fontSize: 12, color: '#8a8a9a' }}>
            共 {chapters.length} 章，当前显示 {visibleChapters.length} 章
          </span>
        </div>
        {chapters.length === 0 ? (
          <p style={{ color: '#6a6a7a' }}>暂无章节。请在"语料管理"中上传文本。</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e1e2e', textAlign: 'left' }}>
                <th style={{ padding: '8px 12px', color: '#6a6a7a', fontSize: 12, fontWeight: 500 }}>卷</th>
                <th style={{ padding: '8px 12px', color: '#6a6a7a', fontSize: 12, fontWeight: 500 }}>序号</th>
                <th style={{ padding: '8px 12px', color: '#6a6a7a', fontSize: 12, fontWeight: 500 }}>标题</th>
                <th style={{ padding: '8px 12px', color: '#6a6a7a', fontSize: 12, fontWeight: 500 }}>字数</th>
                <th style={{ padding: '8px 12px', color: '#6a6a7a', fontSize: 12, fontWeight: 500 }}>对话比</th>
              </tr>
            </thead>
            <tbody>
              {visibleChapters.map((ch) => (
                <tr key={ch.chapter_id} style={{ borderBottom: '1px solid #1a1a28' }}>
                  <td style={{ padding: '8px 12px', fontSize: 13 }}>{ch.volume_display_name || ch.volume_key || '-'}</td>
                  <td style={{ padding: '8px 12px', fontSize: 13 }}>{ch.chapter_order}</td>
                  <td style={{ padding: '8px 12px', fontSize: 13 }}>{ch.title}</td>
                  <td style={{ padding: '8px 12px', fontSize: 13, color: '#8a8a9a' }}>{formatNum(ch.word_count)}</td>
                  <td style={{ padding: '8px 12px', fontSize: 13, color: '#8a8a9a' }}>{formatPercent(ch.dialogue_ratio)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
        {chapters.length > pageSize && (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, marginTop: 14 }}>
            <button className="btn-primary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)} style={{ padding: '4px 12px', fontSize: 12 }}>上一页</button>
            <span style={{ fontSize: 12, color: '#8a8a9a' }}>{page}/{totalPages}</span>
            <button className="btn-primary" disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)} style={{ padding: '4px 12px', fontSize: 12 }}>下一页</button>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-panel" style={{ padding: '16px 20px' }}>
      <div style={{ fontSize: 12, color: '#6a6a7a', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: '#c8a86e' }}>{value}</div>
    </div>
  );
}

function formatNum(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
  return n.toLocaleString();
}

function formatPercent(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}
