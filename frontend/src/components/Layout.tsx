import { type ReactNode } from 'react';

type Page = 'dashboard' | 'corpus' | 'analysis' | 'generator';

interface Props {
  currentPage: Page;
  onNavigate: (p: Page) => void;
  children: ReactNode;
}

const NAV: { key: Page; label: string }[] = [
  { key: 'dashboard', label: '总览' },
  { key: 'corpus', label: '语料管理' },
  { key: 'analysis', label: '风格分析' },
  { key: 'generator', label: '续写工作台' },
];

export default function Layout({ currentPage, onNavigate, children }: Props) {
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
          <p style={{ fontSize: 11, color: '#6a6a7a', margin: '4px 0 0' }}>龙族风格档案系统</p>
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
