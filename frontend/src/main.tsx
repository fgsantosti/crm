import React from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { App } from './App';
import { ValidarAtendente } from './views/ValidarAtendente';

// Sem router de verdade: só esta única rota pública precisa existir fora do
// App autenticado, então basta checar o path na entrada.
const inviteMatch = window.location.pathname.match(/^\/validar-atendente\/(\d+)$/);

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {inviteMatch ? <ValidarAtendente inviteId={Number(inviteMatch[1])} /> : <App />}
  </React.StrictMode>
);
