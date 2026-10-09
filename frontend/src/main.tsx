import React from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { App } from './App';
import { ValidarAtendente } from './views/ValidarAtendente';
import { ConfirmProvider } from './components/ConfirmDialog';

// Sem router de verdade: só esta única rota pública precisa existir fora do
// App autenticado, então basta checar o path na entrada.
const inviteMatch = window.location.pathname.match(/^\/validar-atendente\/([0-9a-f-]{36})$/i);

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfirmProvider>{inviteMatch ? <ValidarAtendente inviteId={inviteMatch[1]} /> : <App />}</ConfirmProvider>
  </React.StrictMode>
);
