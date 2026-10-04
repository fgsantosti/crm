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
  "human_required": false,           // true força transferência para humano, independente do marcador
  "reason": "pedido humano"          // só relevante quando human_required=true
}
```

Resposta (sempre 200, mesmo em `NO_REPLY`):

```jsonc
{
  "action": "TEXTO",            // "NO_REPLY" | "TEXTO" | "AUDIO_GRAVADO"
  "content": "texto ou id do áudio aprovado",  // ausente quando action="NO_REPLY"
  "question_id": "apresentacao",               // ausente quando action="NO_REPLY"
  "lead_id": "uuid-do-lead",
  "event_id": 123                               // use este id para confirmar a entrega
}
```

- `action="NO_REPLY"` → **não envie nada ao contato**, nem literalmente a
  palavra NO_REPLY. Acontece em mensagem duplicada, lead já encerrado/em
  atendimento humano, entrega anterior ainda pendente, ou falta de
  `question_id`/`Question` cadastrado (nesses casos o CRM já move o lead para
  atendimento humano sozinho).
- `action="TEXTO"` → envie `content` literalmente (texto já com os
  placeholders resolvidos — ver seção de placeholders abaixo).
- `action="AUDIO_GRAVADO"` → `content` é um **identificador opaco de texto
  livre** (`Question.audio_asset`, cadastrado pela própria empresa na tela
  Roteiro — não é uma URL nem um asset gerenciado pelo CRM). **O catálogo
  de verdade (identificador → arquivo/URL/MIME real) é responsabilidade do
  Gateway**, combinado com a empresa na implantação — o CRM só guarda a
  string que a empresa decidiu usar como referência. Se o Gateway receber
  um identificador que não existe no seu catálogo, trate como erro
  (fail-closed — ver `BUILD_PROMPT.md`), nunca envie algo sem ter certeza.

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
| `429` | Mais de 60 chamadas/minuto por conta de serviço (`throttle_scope="agent-incoming"`) | Esperar e reenviar depois — seguro, já que `/incoming/` é idempotente pelo mesmo `message_id` |
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
| `[[AXIOMA:REPETIR]]` | nada | reenvia o conteúdo da pergunta atual do lead (sem avançar) |
| `[[AXIOMA:ATUALIZAR:{...}]]` | os campos conhecidos + **`proxima`** (obrigatório, um `question_id` cadastrado pela empresa na tela Roteiro) | grava os campos, avança o lead para `proxima`, devolve o conteúdo dela |
| `[[AXIOMA:VALIDAR:{...}]]` | os campos conhecidos (sem `proxima`) | grava os campos, devolve a pergunta de confirmação fixa (`question_id="validar"`) |
| `[[AXIOMA:CLASSIFICADO:{...}]]` | ao menos `temperatura` e `prioridade` (sem `proxima`) | grava os campos finais, **encerra o bot** (`bot_closed=true`), devolve a mensagem de encerramento (`question_id="encerramento"`) |

Campos aceitos dentro de `fields` (nomes exatamente como o agent emite):

| Campo em `fields` | Vai para o quê no Lead | Valores aceitos |
| --- | --- | --- |
| `nome` | Nome do lead | texto livre |
| `especialidade` | Área/especialidade (isso é o que o dashboard chama de "área") | texto livre, mas precisa bater exatamente com uma área já cadastrada pela empresa na tela "Equipe" (`GET /api/areas/?company={id}`). Valor que não exista nas áreas da empresa transfere o lead para atendimento humano em vez de ser aceito — o agente nunca inventa área nova. |
| `tema` | Resumo da demanda | texto livre |
| `impacto` | Impacto relatado | texto livre |
| `interesse` | Interesse em seguir | `sim` \| `nao` \| `depois` |
| `temperatura` | Classificação comercial | `Qualificado` \| `Quente` \| `Desconfiado` \| `Remarketing` \| `Desqualificado` |
| `prioridade` | Prioridade de atendimento | `Alta` \| `Média` \| `Baixa` |
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

## 3. Confirmação de entrega

```
POST /api/companies/{company_id}/delivery/
Authorization: Token <token>
Content-Type: application/json

{"event_id": 123, "status": "SENT"}   // ou "FAILED"
```

Chame isso **depois** de efetivamente enviar a mensagem/áudio ao WhatsApp.
`"FAILED"` transfere o lead para atendimento humano automaticamente — não há
retry automático. Sem essa confirmação, o próximo marcador para esse lead
retorna `NO_REPLY` (trava de segurança contra duplicidade).

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

## 5. Futuro: envio de áudio por TTS (ainda não implementado)

Vai existir uma opção futura na tela Roteiro → "Opções do Agente" (mesmo
lugar de `Agente conversacional`), algo como **"Agente envia áudio"**, que
quando marcada faria o plugin enviar a resposta como áudio sintetizado (TTS)
ao WhatsApp mesmo em `action="TEXTO"`. Isso ainda **não existe** — nem o
campo em `Company`, nem um novo valor de `action`, nem a lógica de síntese.
Citado aqui só como aviso: quem for integrar agora não deve supor que
`action="TEXTO"` sempre significa "manda texto puro" de um jeito difícil de
estender depois. Trabalho futuro, fora do escopo deste contrato por ora.

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
