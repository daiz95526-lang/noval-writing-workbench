import { useState } from 'react';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import CorpusManage from './pages/CorpusManage';
import StyleAnalysis from './pages/StyleAnalysis';
import Generator from './pages/Generator';

type Page = 'dashboard' | 'corpus' | 'analysis' | 'generator';

export default function App() {
  const [page, setPage] = useState<Page>('dashboard');

  const renderPage = () => {
    switch (page) {
      case 'dashboard': return <Dashboard />;
      case 'corpus': return <CorpusManage />;
      case 'analysis': return <StyleAnalysis />;
      case 'generator': return <Generator />;
    }
  };

  return <Layout currentPage={page} onNavigate={setPage}>{renderPage()}</Layout>;
}
