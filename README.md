# Conecta CRM

Base de CRM multiempresa para qualificação de leads de WhatsApp. Backend Django REST Framework, PostgreSQL e frontend React + TypeScript + Vite.

## Funcionalidades

- Login, empresas vinculadas ao usuário e isolamento de leads por empresa.
- Central de leads, pesquisa, pendências e atendimento humano.
- Edição de nome, responsável, demanda, prioridade e próxima ação; histórico operacional.
- Roteiros aprovados por empresa, texto ou referência a áudio pré-gravado.
- Recepção idempotente por ID de mensagem; estado persistido antes de devolver uma saída.
- Encerramento bloqueia respostas; ambiguidade não avança; ausência de ativo e falha de entrega transferem para humano.
- Pendências automáticas e atendimento humano em visões separadas.

## Executar com Docker Compose

A infraestrutura inclui PostgreSQL, Redis, Django com Uvicorn, worker e beat Celery, frontend e proxy Caddy. O container do backend usa Python 3.12.

Injete `DJANGO_SECRET_KEY` e `POSTGRES_PASSWORD` por ambiente protegido e execute:

```bash
docker compose config --quiet
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
```

Abra http://localhost:8080. O frontend, API e admin usam o mesmo domínio.
Consulte [infraestrutura](docs/infraestrutura.md) para serviços, validações e limites desta etapa. Credenciais não devem ser salvas em arquivos do projeto.

O token da interface permanece somente em memória; recarregar exige novo login. A migração para autenticação por sessão e CSRF ainda será implementada.

## Configurar empresas e roteiro

1. No Django Admin, crie a empresa e vincule usuários em `members`. Administradores também precisam ser vinculados para acessar a empresa pela API.
2. Defina responsável, canal de saída e estado inicial.
3. Cadastre as etapas em Steps após aprovação da empresa. `state` é o estado ao receber a mensagem; `text`/`audio_asset` é a próxima pergunta a enviar; `next_state` é o estado que aguardará sua resposta.
4. Na etapa seguinte, `accepted_answers` contém as respostas exatas aprovadas para a pergunta anterior. Respostas que não correspondem permanecem no mesmo estado com `NO_REPLY`.
5. A etapa final usa `terminal=true` e as respostas aprovadas da última pergunta. Encerra o bot e cria uma ação de revisão humana. Critérios comerciais de temperatura ainda não estão implementados.

Exemplo: `INICIAL` envia pergunta e avança para `RESPOSTA`; `RESPOSTA` aceita uma lista aprovada e encerra com `terminal=true`. Não há roteiro comercial fictício pré-aprovado no banco.
Somente usuários staff vinculados à empresa podem editar roteiros via API. Operadores podem editar dados de atendimento, mas não reabrir a automação.

## Contrato do agente WhatsApp

O conector externo autentica com `Authorization: Token <token>` e um usuário de serviço vinculado apenas à empresa atendida. Obtenha o token pelo endpoint `POST /api/login/` usando credenciais de ambiente protegido. Cada empresa deve preferencialmente ter sua própria conta de serviço.

`POST /api/companies/{id}/incoming/`:

```json
{
  "contact": "+5585999999999",
  "message_id": "identificador-unico-do-provedor",
  "kind": "text",
  "answer": "resposta da etapa",
  "human_required": false
}
```

Telefone deve estar no formato E.164. O conector valida a assinatura do provedor antes de chamar esta API. Não envie o webhook público diretamente para este endpoint.

Respostas:

- `action=NO_REPLY`: não envie nada, nem o texto literal NO_REPLY.
- `action=TEXTO`: envie somente `content`.
- `action=AUDIO_GRAVADO`: resolva `content` como identificador de ativo aprovado e envie o arquivo sem legenda ou TTS. Verifique previamente a existência dos ativos no provedor.

Após enviar, confirme `POST /api/companies/{id}/delivery/` com `{"event_id": 1, "status": "SENT"}`; em falha use `FAILED`. Uma entrega pendente impede novo avanço e transfere o caso para humano. Reenvio da mesma entrada não gera outra saída. Não há retry automático: entregas incertas precisam de revisão humana para evitar duplicação.

Se o agente detectar urgência, risco, conflito, reclamação, assunto fora de escopo ou decisão profissional, envie `human_required=true` e `reason` com um dos valores: `pedido humano`, `urgência ou risco`, `fora de escopo`, `decisão profissional`, `falha de integração`. Há uma proteção adicional por palavras-chave, que não substitui a classificação do agente.

Áudios de entrada são registrados sem transcrição nesta versão, mesmo se a configuração permitir. Não envie transcrições integrais. Histórico guarda metadados, sem texto integral recebido. Áudios e contatos encerrados não são processados.

## Validação

```bash
docker compose exec web python manage.py test crm
cd frontend
npm run build
```

SQLite é somente uma opção de teste; produção usa PostgreSQL. Testes de concorrência e integração com PostgreSQL e provedor devem ser feitos com números internos antes de produção, conforme AGENTS.md.

## Escopo e próximos passos

Esta base não envia WhatsApp, não integra um provedor específico, não gera respostas livres por IA e não faz transcrição. O agente/conector é externo e usa o contrato acima. Ainda requer implantação com HTTPS, política de retenção, rate limiting, gerenciamento de tokens e integração real validada. A lista mostra os primeiros 100 leads; a API retorna paginação, mas a navegação entre páginas ainda não está na interface. Não use o servidor de desenvolvimento em produção.
