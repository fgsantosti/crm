# Integração de um agent com o Conecta CRM

Este documento é **genérico**: serve para integrar **qualquer agent**
(qualquer nome, qualquer plataforma/runtime de agent — OpenClaw ou outro) e
seu Gateway WhatsApp ao Conecta CRM via API, em vez de planilha ou qualquer
outro armazenamento local. Não é específico de nenhuma instância de agent
nem de nenhum plugin — se você está montando um Gateway do zero, ver também
`BUILD_PROMPT.md`.

**Nota sobre o prefixo `AXIOMA` nos marcadores:** `[[AXIOMA:...]]` é uma
constante fixa do protocolo desta API (definida pelo backend do Conecta
CRM), não o nome do agent que você está integrando — mantenha-a como está,
independente de como o seu agent se chama.

## Como funciona

O Gateway nunca guarda estado de roteiro/lead localmente. Ele faz **uma
chamada HTTP por marcador emitido pelo agent** para
`POST /api/companies/{id}/incoming/`, e usa a resposta para saber o que
enviar ao contato. O CRM é sempre quem resolve `question_id → texto/áudio
aprovado` — o Gateway nunca mantém esse mapeamento sozinho, em planilha, em
arquivo local ou em qualquer outro cache de longo prazo.

Depois de efetivamente enviar a mensagem ao WhatsApp, o Gateway confirma com
`POST /api/companies/{id}/delivery/`. Enquanto essa confirmação não chega, o
CRM não libera avanço na conversa — se a entrega falhar, o caso é transferido
automaticamente para atendimento humano.

## 1. Credenciais

Cada empresa tem sua própria conta de serviço (usuário Django vinculado só
àquela empresa) e um token fixo. Já criei a conta de exemplo para validar o
contrato neste ambiente de desenvolvimento local:

| Campo | Valor |
| --- | --- |
| Empresa | Rufus Advocacia (`company_id = 1`) |
| Usuário | `agente.rufus-advocacia` |
| Token | `<TOKEN_DO_AGENTE>` |

Esse token vai em todo request como header:

```
Authorization: Token <TOKEN_DO_AGENTE>
```

**Importante:** este token é do ambiente local (`http://localhost:8080`), só
para validar o contrato. Quando o backend for implantado num domínio real,
gere um token novo nesse ambiente (mesmo procedimento, outro host) e nunca
reaproveite o de dev. O token não deve ser salvo em código ou planilha — só em
variável de ambiente/cofre do lado do plugin.

**Validade:** por padrão o token não expira (igual sempre foi). Opcionalmente,
na tela `Tokens` do Django Admin dá pra definir uma validade por tempo — a
empresa recebe um campo "Validade" no token (inline `AgentTokenExpiry`),
padrão sugerido de 6 meses, teto de 2 anos a partir de hoje. Passado esse
prazo, o token para de autenticar (`401 Token expirado.`) e precisa ser
renovado manualmente no Admin — não há renovação automática.

Para gerar um token de verdade mais pra frente (quando a empresa real for
cadastrada em produção), o fluxo é:

```python
# manage.py shell, no ambiente de produção
from django.contrib.auth.models import User
from crm.models import Company
from rest_framework.authtoken.models import Token

company = Company.objects.get(name="<nome da empresa real>")
user = User.objects.create_user(username="agente.<slug-da-empresa>")
company.members.add(user)
token = Token.objects.create(user=user)
print(token.key)

# Opcional: validade por tempo (sem isso, o token nunca expira)
from datetime import timedelta
from django.utils import timezone
from crm.models import AgentTokenExpiry
AgentTokenExpiry.objects.create(token=token, expires_at=timezone.now() + timedelta(days=183))  # 6 meses
```

Alternativa sem shell: criar o usuário pelo Django Admin (`/admin/`), vincular
à empresa em `Companies → members`, e gerar o token na própria tela do Admin
(`Tokens`). **`POST /api/login/` não serve mais para isso** — esse endpoint
agora é exclusivo do frontend humano e devolve um par de tokens JWT de curta
duração (`access`/`refresh`), não o token fixo que o agente usa.

**Confirmar que um token é de produção:** não existe uma marcação especial
no token pra isso — a distinção é só o host que você chama (`api_base_url`
de dev vs. de produção) e qual banco de dados aquele token foi gerado em
(dev e produção são bancos completamente separados; um token de dev nunca
autentica em produção e vice-versa, porque o `Token`/usuário simplesmente
não existe no outro banco). Pra confirmar com certeza antes de ativar
tráfego real, use o preflight (`GET /api/companies/{id}/` — ver seção 2)
contra o `api_base_url` de produção: um `401` significa token/host errado,
`200` com o `company_id` esperado confirma que está correto.

**Revogação e rotação:** revogar de verdade é **apagar o `Token`** no Django
Admin (não existe "desativar temporariamente" — ou o token existe e
autentica, ou não existe e dá `401` imediatamente, sem período de carência).
Pra rotacionar sem downtime: gere o token novo primeiro, atualize o
SecretRef do Gateway pro valor novo, confirme com o preflight, e só então
apague o token antigo — nessa ordem, nunca o contrário.

## 2. Contrato de `/incoming/`

```
POST /api/companies/{company_id}/incoming/
Authorization: Token <token>
Content-Type: application/json
```

Corpo da requisição — um por marcador emitido pelo agent:

```jsonc
{
  "contact": "+5585999887766",       // E.164, obrigatório
  "message_id": "id-unico-do-provedor", // idempotência: repetir o mesmo id nunca gera efeito duas vezes
  "kind": "text",                    // "text" ou "audio" — o tipo da ENTRADA do contato, não da saída
  "marker": "Q",                     // "Q" | "REPETIR" | "ATUALIZAR" | "VALIDAR" | "CLASSIFICADO"
  "question_id": "apresentacao",     // obrigatório só quando marker="Q"
  "fields": {},                      // obrigatório (pode ser {}) para ATUALIZAR/VALIDAR/CLASSIFICADO
  "human_required": false,           // true trata reason antes do marcador (exceções abaixo)
  "reason": "pedido humano"          // só relevante quando human_required=true
}
```

Resposta (sempre 200, mesmo em `NO_REPLY`):

```jsonc
{
  "action": "TEXTO",            // "NO_REPLY" | "TEXTO" | "AUDIO" (ver seção 5)
  "content": "texto aprovado já renderizado",  // ausente quando action="NO_REPLY"
  "question_id": "apresentacao",               // ausente quando action="NO_REPLY"
  "lead_id": "uuid-do-lead",
  "event_id": 123,                              // use este id para confirmar a entrega
  "lead_novo": false                            // true quando o lead foi criado nesta chamada
}
```

**Lead novo sempre começa pela apresentação:** quando a chamada cria o lead
(`lead_novo: true`) e o marcador não é `Q` do estado inicial da empresa
(`apresentacao`), o CRM ignora o marcador recebido e devolve o texto da
apresentação. Isso cobre o agente que "lembra" de uma triagem cujo lead foi
fechado/apagado no painel: o contato recomeça do zero, nunca no meio do
roteiro. `human_required: true` continua valendo: `fora de escopo` desqualifica
com prioridade Baixa; `falha de integração` remove a triagem; os outros motivos
transferem para humano. Números na BlackList sempre retornam `NO_REPLY`, sem lead/evento.

**Pedido explícito de atendimento humano:** `human_required=true` com
`reason="pedido humano"` transfere o lead e devolve uma única saída de
`question_id="necessidade_humana"`. Essa mensagem obrigatória fica em
Roteiro → Textos fora do fluxo e pode exigir variáveis de roteiro via o campo
`variaveis_obrigatorias` de `/questions/` (lista de IDs da mesma empresa).
O texto só é aceito se incluir os placeholders selecionados. No envio, todos
eles precisam ter valor coletado; caso contrário, o CRM transfere o contato
e retorna `NO_REPLY`, registrando o dado ausente no evento. Campos de dados
coletados podem acompanhar o pedido em `fields`; isso não classifica o lead.
Envie a saída e confirme a entrega normalmente; mensagens seguintes ficam
bloqueadas pelo modo HUMANO. Não use `Q:necessidade_humana` nem essa ID como
`proxima`: ela é exclusiva desse encaminhamento.

- `action="NO_REPLY"` → **não envie nada ao contato**, nem literalmente a
  palavra NO_REPLY. Acontece em mensagem duplicada, lead já encerrado/em
  atendimento humano, entrega anterior ainda pendente, ou falta de
  `question_id`/`Question` cadastrado. Erros de marcador e triagem travada removem
  o lead (`lead_apagado=true`, sem `event_id`); falta de conteúdo aprovado no
  Roteiro continua encaminhando para revisão humana. BlackList devolve
  `{"action":"NO_REPLY","blacklist":true}` sem criar lead ou evento.
- `action="TEXTO"` → envie `content` literalmente (texto já com os
  placeholders resolvidos — ver seção de placeholders abaixo).
- `action="AUDIO"` → só com **Mensagens via áudio** ligado (ver seção 5).
  Envie o arquivo de `audio_url` como **nota de voz** (OGG/Opus), sem legenda.
  `content` traz o mesmo texto que iria no `TEXTO` (para log/transcrição),
  nunca para enviar junto. Confirme a entrega em `/delivery/` igual ao TEXTO.
- O antigo `action="AUDIO_GRAVADO"` (identificador opaco em
  `Question.audio_asset`, só com `kind="audio"`) **foi removido**: não era usado
  por nenhuma empresa nem pela ponte. O campo `audio_asset` ficou no banco só
  por compatibilidade e não tem mais efeito.

### Idempotência e retentativas

- **Chave de idempotência de `/incoming/`** é `(lead ativo, message_id)` —
  reenviar o mesmo `message_id` pro mesmo contato nunca duplica efeito;
  a resposta vira `{"action": "NO_REPLY", "duplicate": true, "lead_id":
  "..."}`, **sem `event_id`** (nenhum evento novo é criado) — não chame
  `/delivery/` para esse caso, não há nada pra confirmar. Não há TTL: a
  deduplicação vale para sempre dentro do histórico daquele lead.
- **`/delivery/` também é idempotente por `event_id`**: se o evento já não
  está `PENDING` (já foi confirmado `SENT` ou `FAILED` antes), chamar de
  novo não tem efeito — só devolve o status atual. Seguro reenviar.
- Eventos de resposta `NO_REPLY` (fora do caso de duplicata) **não exigem
  confirmação de entrega** — nada foi enviado ao contato, então não há
  `/delivery/` a fazer para esses `event_id`.
- **Quando o Gateway pode retentar** `/incoming/`: só em falha de rede/timeout
  **antes** de receber qualquer resposta — e sempre com o **mesmo**
  `message_id` original (nunca gere um `message_id` novo para reenviar o
  mesmo marcador; isso criaria um evento novo e duplicaria efeito). Se a
  resposta já chegou (mesmo um erro HTTP do CRM), não retente automaticamente
  — trate como erro e fail-closed (ver `BUILD_PROMPT.md`).

### Erros e códigos HTTP

Este contrato usa só estes códigos — não espere `403` nem `409` de nenhuma
rota abaixo:

| Código | Quando acontece | O que o Gateway deve fazer |
| --- | --- | --- |
| `401` | Token ausente, inválido ou expirado (`AgentTokenExpiry`) | Fail-closed, alertar, nunca tentar de novo sem token novo |
| `404` | `company_id` não existe ou não pertence ao token usado (nunca `403` — o CRM não distingue "existe mas não é seu" de "não existe") | Fail-closed, revisar configuração (token trocado de empresa?) |
| `400` | Payload fora do schema (`IncomingSerializer`/`DeliverySerializer`) — inclui `CLASSIFICADO` sem `temperatura`/`prioridade`, `contact` fora do padrão E.164, `status` fora de `SENT`/`FAILED` em `/delivery/` | Fail-closed, é bug de integração do Gateway, não reenviar sem corrigir o payload |
| `429` | Mais de 300 chamadas/minuto por conta de serviço (`throttle_scope="agent-incoming"`, somando `incoming`, `delivery`, `agente/contato` e `agente/contexto`) | Esperar e reenviar depois — seguro, já que `/incoming/` é idempotente pelo mesmo `message_id` |
| `5xx` | Erro interno do CRM | Fail-closed, alertar; retentar depois é seguro (mesma idempotência), não há retry automático do lado do CRM |

### Preflight seguro (validar credencial sem efeito de negócio)

Não existe uma rota dedicada de "ping" — use `GET /api/companies/{company_id}/`
(já existe, sem side-effect, mesma autenticação) antes de qualquer tráfego
real: `200` confirma token válido e vinculado àquela empresa; `401`/`404`
apontam exatamente o problema (token vs. empresa errada), sem nunca criar
lead ou evento. Não há endpoint de "whoami" separado — este serve.

### Versão do contrato

Não há negociação de versão em runtime (sem header/campo de versão na API).
Este documento é a única fonte de verdade do contrato vigente — qualquer
mudança futura incompatível será um anúncio explícito aqui, nunca algo que
o Gateway deva detectar ou negociar automaticamente.

### Identidade/correlação do contato no WhatsApp

De onde vêm o E.164, o id da mensagem inbound e a chave de sessão é decisão
de **qual runtime/plataforma** está hospedando o Gateway, não do CRM — ver
`BUILD_PROMPT.md` → "Sessão por contato". O CRM só exige que `contact` já
chegue normalizado em E.164 e que `message_id` seja estável e único por
mensagem real (não reaproveitável entre mensagens diferentes).

### Mapeamento por marcador

| Marcador | O que mandar em `fields` | O que o CRM faz |
| --- | --- | --- |
| `[[AXIOMA:Q:<id>]]` | nada (`question_id` vai fora de `fields`) | marca o lead nesse `question_id` e devolve o conteúdo aprovado dele |
| `[[AXIOMA:REPETIR]]` | nada | reenvia o conteúdo da pergunta atual com o prefixo "Por favor, responda novamente. " (sem avançar) |
| `[[AXIOMA:ATUALIZAR:{...}]]` | os campos conhecidos + **`proxima`** (obrigatório, um `question_id` cadastrado pela empresa na tela Roteiro) | grava os campos, avança o lead para `proxima`, devolve o conteúdo dela |
| `[[AXIOMA:VALIDAR:{...}]]` | os campos conhecidos (sem `proxima`) | grava os campos, devolve a pergunta de confirmação fixa (`question_id="validar"`) |
| `[[AXIOMA:CLASSIFICADO:{...}]]` | **`notas`** (recomendado) **ou** `temperatura` + `prioridade` (sem `proxima`). Com `"encerramento_antecipado": true`, pode vir antes do `VALIDAR`, com notas parciais ou nenhuma | Após `VALIDAR`, grava os campos finais, encerra o bot e devolve `question_id="encerramento"`. Desqualificado/Desconfiado recebem desfecho automático, ficam fora do Kanban e liberam o número imediatamente. Encerramento antecipado ou ausência de `VALIDAR` remove a triagem e retorna `NO_REPLY` com `lead_apagado=true`, sem promover notas parciais a Qualificados. |

Campos aceitos dentro de `fields` (nomes exatamente como o agent emite):

| Campo em `fields` | Vai para o quê no Lead | Valores aceitos |
| --- | --- | --- |
| `nome` | Nome do lead | texto livre |
| `especialidade` | Área/especialidade (isso é o que o dashboard chama de "área") | Precisa bater exatamente com uma área cadastrada em Equipe. Área desconhecida remove a triagem. A exceção `Fora de escopo` desqualifica com prioridade Baixa, sem entrar no Kanban, inclusive antes de concluir o roteiro. |
| `tema` | Resumo da demanda | texto livre |
| `impacto` | Impacto relatado | texto livre |
| `interesse` | Interesse em seguir | `sim` \| `nao` \| `depois` |
| `temperatura` | Classificação comercial | `Qualificado` \| `Quente` \| `Desconfiado` \| `Remarketing` \| `Desqualificado` |
| `prioridade` | Prioridade de atendimento | `Alta` \| `Média` \| `Baixa` |
| `notas` | **não é campo do lead** — só em `CLASSIFICADO`: dict `{"<question_id>": nota}` com nota de 0 a 10 para cada pergunta respondida (quão urgente/relevante foi a resposta) | O CRM calcula `score = Σ(nota × peso) / Σ(peso)` e converte pelas `faixas_urgencia`. Prevalece sobre a temperatura enviada junto; prioridade ausente sai da temperatura (Quente→Alta, Qualificado→Média, demais→Baixa). Pergunta desconhecida ou sem variável é ignorada; se nenhuma sobrar, a triagem é removida. O detalhe fica em `Lead.urgencia_detalhe`. |
| `proxima` | **não é campo do lead** — só em `ATUALIZAR`, diz qual é o próximo `question_id` | **desde a tela Roteiro customizável**: qualquer `question_id` cadastrado pela empresa (3 sempre existem: `nome`, `situacao`, `demanda`; o resto é livre). Nunca `validar` nem `encerramento` — reservados. Um `question_id` que a empresa não cadastrou transfere o lead pra atendimento humano em vez de travar. |
| `variaveis_roteiro` | **opcional**, dict `{"<slug>": "<texto>"}` — não é um campo fixo do lead, grava em `Lead.variaveis_roteiro` | só aceita slugs de Variáveis de roteiro **customizadas** já cadastradas pela empresa (tela Roteiro → aba Variáveis; `GET /api/variaveis-roteiro/?company={id}` lista as válidas, com `builtin=false`). Slug desconhecido, builtin ou valor não-texto é simplesmente ignorado (nunca trava o fluxo). Serve pra responder uma pergunta adicional do roteiro (fora das 3 obrigatórias) e reusar esse texto depois via `{slug}` em outra pergunta. |

### Placeholders no texto aprovado

O texto de qualquer `Question` pode usar placeholders entre chaves, que o CRM
substitui antes de devolver `content`. Nunca precisa pedir isso ao agent —
é resolvido automaticamente pelo backend:

| Placeholder | Resolvido a partir de |
| --- | --- |
| `{empresa}` | `Company.name` — sempre o nome real da empresa daquele `question_id`. Use isso em vez de escrever o nome da empresa direto no texto: se a empresa for renomeada, ou se o mesmo texto for reaproveitado como modelo para uma empresa nova, continua certo sem precisar editar nada. |
| `{nome}`, `{especialidade}`, `{tema}`, `{impacto}`, `{interesse}`, `{temperatura}`, `{prioridade}` | O mesmo campo já coletado do lead (ver tabela acima). Usado sobretudo no texto de `validar`, para mostrar o resumo que o lead confirma. `{nome}`/`{especialidade}`/`{tema}` são também as 3 Variáveis de roteiro builtin (Nome/Área da Lead/Demanda). |
| `{<slug>}` de uma Variável de roteiro customizada | `Lead.variaveis_roteiro["<slug>"]` — o que foi gravado via `fields.variaveis_roteiro` numa pergunta anterior (ver tabela acima) | Sem valor coletado ainda, vira string vazia como qualquer outro placeholder. |

Um placeholder sem valor ainda (ex.: `{tema}` antes de o lead informar o tema)
vira string vazia — nunca aparece `{tema}` literal na mensagem.

Envie só os campos que a resposta atual esclareceu — o CRM mantém os que já
tinha. Isso já é como o `AGENTS.md` do agent descreve o preenchimento.

## 2.1 Contexto do agente (roteiro, áreas e faixas de urgência)

```
GET /api/companies/{company_id}/agente/contexto/
Authorization: Token <token>
```

Leitura pura (não cria lead nem evento), liberada para a conta de serviço do
agente e para membros humanos da empresa; empresa de outro token → `404`.
Use para conduzir o roteiro **na ordem configurada pela empresa** na tela
"Perguntas de Roteiro" e para dar as `notas` do `CLASSIFICADO`:

```jsonc
{
  "empresa": "Rufus Advocacia",
  "agente_conversacional": false,
  "mensagens_audio": false,                   // true: as respostas podem vir como action="AUDIO" (seção 5)
  "numero_agente": "+558694238125",          // mensagens vindas dele mesmo nunca abrem lead
  "areas": ["Consumidor", "Previdenciário", "Trabalhista"],
  "perguntas": [                              // só o fluxo, por ordem; sem textos vazios
    {"question_id": "nome", "ordem": 0, "texto": "Qual é o seu nome completo?", "obrigatoria": true,
     "variavel": {"nome": "Geral", "peso": 5}, "variavel_roteiro": "nome"}
  ],
  "fora_do_fluxo": [
    {"question_id": "apresentacao", "texto": "Olá! ..."},
    {"question_id": "necessidade_humana", "texto": "{nome}, vou chamar um atendente.", "variaveis_obrigatorias": ["nome"]}
  ],  // apresentacao, empresa, validar, encerramento, necessidade_humana
  "faixas_urgencia": [
    {"min": 0, "max_exclusivo": 3, "temperatura": "Desqualificado"},
    {"min": 3, "max_exclusivo": 5, "temperatura": "Desconfiado"},
    {"min": 5, "max_exclusivo": 7, "temperatura": "Remarketing"},
    {"min": 7, "max_exclusivo": 9, "temperatura": "Qualificado"},
    {"min": 9, "max_exclusivo": null, "temperatura": "Quente"}
  ]
}
```

`texto` vem cru (com placeholders): serve para o agente entender o que cada
etapa pergunta — o que o contato recebe continua sendo sempre o `content`
devolvido por `/incoming/`. Mensagem cujo `contact` é o próprio
`numero_agente` volta `{"action": "NO_REPLY", "proprio_numero": true}` sem
`lead_id`/`event_id` (não há entrega a confirmar).

Perguntas repetidas usam o prefixo também em áudio. Quando há gravação própria,
o CRM usa TTS do conteúdo completo na repetição. O mesmo vale para Necessidade
humana com placeholders, para que a fala inclua os dados reais do contato.

### 2.1.1 Perguntas fixas e SPIN por área

O roteiro tem duas camadas:

- **Perguntas fixas** (`perguntas`): feitas para todo contato, na ordem, antes
  de o agente definir a área. `nome` e `situacao` são sempre fixas.
- **SPIN por área** (`spin`): depois que o agente grava `especialidade` (uma
  das `areas`), ele segue a lista daquela área. `spin` tem **uma chave para
  cada área cadastrada** (lista vazia se a área não tiver SPIN); cada item tem
  o mesmo formato de `perguntas` mais `etapa_spin`
  (`"situacao" | "problema" | "implicacao" | "necessidade" | ""`), ordenado
  por `ordem`.

```jsonc
"spin": {
  "Trabalhista": [
    {"question_id": "trab_situacao", "ordem": 0, "texto": "Você ainda trabalha na empresa…?", "obrigatoria": false,
     "variavel": {"nome": "Geral", "peso": 5}, "variavel_roteiro": null, "etapa_spin": "situacao"},
    {"question_id": "demanda", "ordem": 1, "texto": "A situação envolve horas extras…?", "obrigatoria": true,
     "variavel": {"nome": "Geral", "peso": 5}, "variavel_roteiro": "tema", "etapa_spin": "problema"}
  ],
  "Consumidor": [],
  "Previdenciário": []
}
```

A pergunta obrigatória `demanda` pode estar dentro de uma lista SPIN. Fora
dela, no máximo **uma** pergunta por lista de área guarda a Variável de roteiro
builtin `tema` (a de "Problema", que registra a demanda daquela área).

Em `/incoming/`, `Q` ou `ATUALIZAR` com `"proxima"` de uma pergunta SPIN só é
aceito se o lead já estiver classificado **naquela** área (vale a
`especialidade` enviada no mesmo `ATUALIZAR`). SPIN de outra área, ou SPIN
antes de existir `especialidade`, leva o lead para atendimento humano com o
motivo "Pergunta SPIN de área diferente da classificada". Perguntas fixas
continuam livres.

## 2.2 Status do contato (o agente pode atender este número agora?)

```
GET /api/companies/{company_id}/agente/contato/?contact=+5586999999999
Authorization: Token <token>
```

Leitura pura, mesma permissão de `agente/contexto` (404 para outra empresa;
`contact` fora de E.164 → `400`). Use **antes de chamar o modelo**: se
`aceita_agente` for `false`, não processe a mensagem (não gaste o modelo nem
chame `/incoming/`). É exatamente a regra que `/incoming/` usa para decidir
`NO_REPLY` — as duas nunca divergem.

```jsonc
{
  "contact": "+5586999999999",
  "lead_id": "uuid-do-lead" | null,
  "aceita_agente": true,
  "motivo": "em_triagem",       // ver tabela
  "ultima_pergunta": "nome",    // só em "em_triagem"; null nos demais
  "repeticoes": 2,              // REPETIR consecutivos na etapa atual; 0 sem lead/fora da triagem
  "especialidade": "Trabalhista" // área já gravada no lead ativo ("" se ainda não classificada) — define a lista SPIN
}
```

`repeticoes` existe para o agente não ficar preso repetindo a mesma pergunta:
com 2 ou mais, avance (ou encerre antecipadamente) em vez de mandar outro
`REPETIR`. O CRM é o último recurso: o **4º `REPETIR` seguido** não é
reenviado — o CRM remove a triagem travada e libera o número para recomeçar na próxima mensagem.

| `motivo` | `aceita_agente` | Quando |
| --- | --- | --- |
| `sem_lead` | `true` | Nenhum lead ativo para o número (primeiro contato, ou o anterior já foi despachado/fechado) — a próxima chamada a `/incoming/` cria lead novo e começa pela apresentação |
| `em_triagem` | `true` | Lead ativo ainda na triagem automática; `ultima_pergunta` = etapa atual |
| `classificado` | `false` | Triagem concluída (`CLASSIFICADO`); o número fica com a equipe até o despacho registrar o desfecho |
| `humano` | `false` | Lead transferido para atendimento humano |
| `blacklist` | `false` | Número bloqueado pela empresa ou por atendente; não criar lead nem processar mídia |
| `proprio_numero` | `false` | `contact` é o próprio `numero_agente` da empresa |

## 3. Confirmação de entrega

```
POST /api/companies/{company_id}/delivery/
Authorization: Token <token>
Content-Type: application/json

{"event_id": 123, "status": "SENT"}   // ou "FAILED"
```

Chame isso **depois** de efetivamente enviar a mensagem/áudio ao WhatsApp.
`"FAILED"` durante a triagem remove o lead e libera o número (`lead_apagado=true`).
Após classificação, mantém o histórico e encaminha a falha para revisão humana.
Não há retry automático. Enquanto uma entrega está `PENDING`:

- **menos de 90s:** um marcador novo do mesmo lead volta `NO_REPLY` e é
  ignorado, **sem** transferir para humano (o contato mandou várias mensagens
  seguidas enquanto a resposta anterior saía);
- **90s ou mais:** a pendência é marcada `EXPIRADO` (a confirmação se perdeu) e
  o marcador novo é processado normalmente — a triagem nunca trava por isso.
  Uma confirmação que chegue depois para um evento `EXPIRADO` não muda nada.

### Triagem abandonada

A cada 30 minutos o CRM remove leads em triagem automática sem mensagem do contato
há mais de 24h. Leads manuais, classificados e em modo HUMANO são preservados.
Triagens removidas não entram em Qualificados; a próxima mensagem cria um lead zerado.
Desqualificado/Desconfiado permanecem só nas estatísticas e liberam o número sem quarentena.

### BlackList no painel

Empresa e atendentes usam `GET/POST /api/blacklist/?company={id}` e
`DELETE /api/blacklist/{id}/?company={id}` para listar, adicionar e remover números.
O contato é normalizado em E.164; a lista é isolada por empresa. A conta do agente
não acessa essas rotas. O dono de um atendimento em Meus Atendimentos pode usar
`POST /api/leads/{id}/despachar-bloquear/?company={id}`: conclui com desfecho
`bloqueado` e adiciona o número à lista numa transação. Remover o bloqueio libera
o bot, preservando o atendimento concluído no histórico.

## 4. Exemplo de conversa completa (testado de ponta a ponta)

```bash
TOKEN=<TOKEN_DO_AGENTE>
BASE=http://localhost:8080/api/companies/1

# 1) primeira mensagem
curl -s -X POST -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
  -d '{"contact":"+5585999110033","message_id":"m1","kind":"text","marker":"Q","question_id":"apresentacao","fields":{}}' \
  $BASE/incoming/
# confirmar entrega
curl -s -X POST -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
  -d '{"event_id": 1, "status": "SENT"}' $BASE/delivery/

# 2) agente extraiu o nome e decide ir para "situacao"
curl -s -X POST -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
  -d '{"contact":"+5585999110033","message_id":"m2","kind":"text","marker":"ATUALIZAR","fields":{"nome":"Carlos Pereira","proxima":"situacao"}}' \
  $BASE/incoming/

# ... (ATUALIZAR se repete até a última pergunta) ...

# N) confirmação
curl -s -X POST -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
  -d '{"contact":"+5585999110033","message_id":"mN","kind":"text","marker":"VALIDAR","fields":{"impacto":"Ficou sem renda","interesse":"sim"}}' \
  $BASE/incoming/

# N+1) classificação final, encerra o bot
curl -s -X POST -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
  -d '{"contact":"+5585999110033","message_id":"mN1","kind":"text","marker":"CLASSIFICADO","fields":{"temperatura":"Quente","prioridade":"Alta"}}' \
  $BASE/incoming/
```

## 5. Mensagens via áudio (TTS e gravações)

**Habilitação em 2 níveis:**

1. **Admin** (superuser) → empresa → "Habilitar áudio (transcrição/voz)"
   (`Company.allow_transcription`). É o portão da feature.
2. **Empresa** → Roteiro → "Opções do Agente" → "Mensagens via áudio"
   (`Company.mensagens_audio`) e "Voz" (`Company.voz_tts`:
   `pt-BR-FranciscaNeural` (padrão), `pt-BR-AntonioNeural`,
   `pt-BR-ThalitaMultilingualNeural`). O CRM recusa ligar sem o portão
   (`400 "Habilite o áudio no painel Admin."`) e, se o Admin desligar depois, a
   opção da empresa deixa de valer sozinha.

**Resposta de `/incoming/` com a feature ligada** (no lugar de um `TEXTO`):

```jsonc
{
  "action": "AUDIO",
  "content": "Olá! Você está falando com a Rufus Advocacia...",  // mesmo texto do TEXTO
  "audio_url": "http://web:8000/media/tts/<sha256>.ogg",           // mesma origem da requisição
  "audio_origem": "tts",                                           // ou "gravado"
  "question_id": "apresentacao", "lead_id": "...", "event_id": 123, "lead_novo": true
}
```

- **Gravação própria** da pergunta (tela Roteiro → "Gravar" ou "Enviar arquivo")
  → `audio_origem: "gravado"`. Sempre OGG/Opus mono 48 kHz (convertida no
  upload; máx. 2 min / 5 MB). A gravação é fixa: não inclui dados variáveis
  como `{nome}`.
- **Sem gravação** → TTS automático (Microsoft Edge neural, via `edge-tts`) do
  texto já renderizado, na voz da empresa, convertido para OGG/Opus. Fica em
  cache por voz + texto (`media/tts/<sha256>.ogg`), então perguntas sem
  placeholder só são sintetizadas uma vez. Limite de 12 s.
- **Falha de áudio** (TTS fora do ar, timeout, ffmpeg) → o CRM devolve o
  `TEXTO` normal (com `audio_erro` informativo) — nunca `NO_REPLY` por causa do
  áudio. A entrega pendente funciona igual nos dois casos.
- `audio_url` usa o host da própria requisição. Pela rede interna
  (`http://web:8000`) o Django serve `/media/tts/` e `/media/roteiro_audio/`;
  pelo domínio público o Caddy serve o mesmo volume.
- `GET /agente/contexto/` inclui `"mensagens_audio": true|false` (já
  considerando o portão do Admin).

Gravar/remover a gravação de uma pergunta (Empresa/admin da empresa; atendente
e conta do agente recebem `403`):

```
POST   /api/questions/{id}/audio/?company={company_id}   (multipart, campo "arquivo")
DELETE /api/questions/{id}/audio/?company={company_id}
```

## 6. O que falta cadastrar antes de ligar ao agente real

O catálogo de `question_id → texto/áudio` ainda está com conteúdo de teste.
Antes de apontar o agente real da Rufus Advocacia (ou qualquer empresa)
para este endpoint, cadastre o texto/áudio aprovado de cada um dos 10
`question_id` pela tela "Roteiro aprovado" do CRM (ou direto no Django
Admin, modelo `Question`):

`apresentacao`, `empresa`, `nome`, `situacao`, `ainda_na_empresa`,
`tipo_de_situacao`, `afetou_renda`, `equipe_avaliar_situacao`, `validar`,
`encerramento`.

Se o agent pedir um `question_id` sem `Question` cadastrada para aquela
empresa, o CRM devolve `NO_REPLY` e transfere o lead para atendimento humano
— não inventa texto.
