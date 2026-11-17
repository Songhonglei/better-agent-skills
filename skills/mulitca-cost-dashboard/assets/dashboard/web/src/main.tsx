import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Moon, Sun } from 'lucide-react';
import { ExpensesPage } from './features/expenses/ExpensesPage.js';
import { api } from './api/client.js';
import './styles.css';

function App() {
  const [dark, setDark] = useState(false);
  const themeLabel = dark ? '切换到亮色模式' : '切换到暗色模式';
  function toggleTheme() {
    document.documentElement.dataset.theme = dark ? 'light' : 'dark';
    setDark(!dark);
  }
  return <>
    <header className="dashboard-header">
      <h1>Multica 费用大盘</h1>
      <button className="theme-toggle" type="button" aria-label={themeLabel} title={themeLabel} aria-pressed={dark} onClick={toggleTheme}>
        {dark ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
      </button>
    </header>
    <main><ExpensesPage api={api} /></main>
  </>;
}

createRoot(document.getElementById('root')!).render(<App />);
