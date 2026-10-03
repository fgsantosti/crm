# Integração do agente Axioma com o CRM

Este documento é para quem for adaptar o agente Axioma (OpenClaw, hospedado na
Hostinger) e o plugin `ephemeral-whatsapp-gate` para gravar leads no CRM via
API, em vez de na planilha "Funil de Atendimentos".

## O que muda em relação à planilha

Hoje o plugin escreve diretamente numa aba de planilha. A partir daqui, ele
deve fazer **uma chamada HTTP por marcador emitido pelo Axioma** para
`POST /api/companies/{id}/incoming/`, e usar a resposta para saber o que
enviar ao contato. O CRM passa a ser quem resolve `question_id → texto/áudio
aprovado` — o plugin não precisa mais manter esse mapeamento sozinho (isso é
o que antes vivia nas colunas da planilha ou em `axioma-audios/`).

Depois de efetivamente enviar a mensagem ao WhatsApp, o plugin confirma com
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
reaproveite o de dev. O token não expira e não deve ser salvo em código ou
planilha — só em variável de ambiente/cofre do lado do plugin.

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
```

Alternativa sem shell: criar o usuário pelo Django Admin (`/admin/`), vincular
à empresa em `Companies → members`, e pegar o token chamando
`POST /api/login/` com usuário/senha (o token retornado é o mesmo de sempre,
DRF Token não expira sozinho).

## 2. Contrato de `/incoming/`

```
POST /api/companies/{company_id}/incoming/
Authorization: Token <token>
Content-Type: application/json
```

Corpo da requisição — um por marcador emitido pelo Axioma:

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
- `action="TEXTO"` → envie `content` literalmente.
- `action="AUDIO_GRAVADO"` → `content` é o identificador do OGG/Opus aprovado
  (resolva no seu catálogo de áudios e envie sem legenda/TTS).

### Mapeamento por marcador

| Marcador do Axioma | O que mandar em `fields` | O que o CRM faz |
| --- | --- | --- |
| `[[AXIOMA:Q:<id>]]` | nada (`question_id` vai fora de `fields`) | marca o lead nesse `question_id` e devolve o conteúdo aprovado dele |
| `[[AXIOMA:REPETIR]]` | nada | reenvia o conteúdo da pergunta atual do lead (sem avançar) |
| `[[AXIOMA:ATUALIZAR:{...}]]` | os campos conhecidos + **`proxima`** (obrigatório, um dos 8 `question_id` dos Códigos permitidos) | grava os campos, avança o lead para `proxima`, devolve o conteúdo dela |
| `[[AXIOMA:VALIDAR:{...}]]` | os campos conhecidos (sem `proxima`) | grava os campos, devolve a pergunta de confirmação fixa (`question_id="validar"`) |
| `[[AXIOMA:CLASSIFICADO:{...}]]` | ao menos `temperatura` e `prioridade` (sem `proxima`) | grava os campos finais, **encerra o bot** (`bot_closed=true`), devolve a mensagem de encerramento (`question_id="encerramento"`) |

Campos aceitos dentro de `fields` (nomes exatamente como o Axioma emite):

| Campo em `fields` | Vai para o quê no Lead | Valores aceitos |
| --- | --- | --- |
| `nome` | Nome do lead | texto livre |
| `especialidade` | Área/especialidade (isso é o que o dashboard chama de "área") | `Previdenciário` \| `Consumidor` \| `Trabalhista` \| `Fora de escopo` |
| `tema` | Resumo da demanda | texto livre |
| `impacto` | Impacto relatado | texto livre |
| `interesse` | Interesse em seguir | `sim` \| `nao` \| `depois` |
| `temperatura` | Classificação comercial | `Qualificado` \| `Quente` \| `Desconfiado` \| `Remarketing` \| `Desqualificado` |
| `prioridade` | Prioridade de atendimento | `Alta` \| `Média` \| `Baixa` |
| `proxima` | **não é campo do lead** — só em `ATUALIZAR`, diz qual é o próximo `question_id` | um dos 8 códigos de pergunta (nunca `validar` nem `encerramento`) |

### Placeholders no texto aprovado

O texto de qualquer `Question` pode usar placeholders entre chaves, que o CRM
substitui antes de devolver `content`. Nunca precisa pedir isso ao Axioma —
é resolvido automaticamente pelo backend:

| Placeholder | Resolvido a partir de |
| --- | --- |
| `{empresa}` | `Company.name` — sempre o nome real da empresa daquele `question_id`. Use isso em vez de escrever o nome da empresa direto no texto: se a empresa for renomeada, ou se o mesmo texto for reaproveitado como modelo para uma empresa nova, continua certo sem precisar editar nada. |
| `{nome}`, `{especialidade}`, `{tema}`, `{impacto}`, `{interesse}`, `{temperatura}`, `{prioridade}` | O mesmo campo já coletado do lead (ver tabela acima). Usado sobretudo no texto de `validar`, para mostrar o resumo que o lead confirma. |

Um placeholder sem valor ainda (ex.: `{tema}` antes de o lead informar o tema)
vira string vazia — nunca aparece `{tema}` literal na mensagem.

Envie só os campos que a resposta atual esclareceu — o CRM mantém os que já
tinha. Isso já é como o `AGENTS.md` do Axioma descreve o preenchimento.

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

## 5. O que falta cadastrar antes de ligar ao agente real

O catálogo de `question_id → texto/áudio` ainda está com conteúdo de teste.
Antes de apontar o agente real da Rufus Advocacia (ou qualquer empresa)
para este endpoint, cadastre o texto/áudio aprovado de cada um dos 10
`question_id` pela tela "Roteiro aprovado" do CRM (ou direto no Django
Admin, modelo `Question`):

`apresentacao`, `empresa`, `nome`, `situacao`, `ainda_na_empresa`,
`tipo_de_situacao`, `afetou_renda`, `equipe_avaliar_situacao`, `validar`,
`encerramento`.

Se o Axioma pedir um `question_id` sem `Question` cadastrada para aquela
empresa, o CRM devolve `NO_REPLY` e transfere o lead para atendimento humano
— não inventa texto.
