import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ExpensesPage } from './features/expenses/ExpensesPage.js';
import { api } from './api/client.js';
import './styles.css';

function App() {
  const [dark, setDark] = useState(false);
  function toggleTheme() {
    document.documentElement.dataset.theme = dark ? 'light' : 'dark';
    setDark(!dark);
  }
  return <>
    <header className="dashboard-header">
      <h1>Multica 费用大盘</h1>
      <button type="button" onClick={toggleTheme}>{dark ? '浅色' : '深色'}</button>
    </header>
    <main><ExpensesPage api={api} /></main>
  </>;
}

createRoot(document.getElementById('root')!).render(<App />);
