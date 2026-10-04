# BUILD_PROMPT.md — Construção do Gateway WhatsApp ↔ Agent

> Este documento é um prompt de construção, não documentação de referência,
> e é **genérico**: serve pra qualquer agent (qualquer nome, qualquer
> plataforma/runtime — OpenClaw, outro framework, ou implementação própria)
> que vá operar segundo um `SOUL.md`+`AGENTS.md` deste padrão e precise de
> um Gateway WhatsApp próprio. Não assuma nome fixo de agent nem plataforma
> fixa em nada do que for construído a partir daqui.
>
> Antes de escrever qualquer código, leia os três documentos do agent em
> questão (`SOUL.md`, `AGENTS.md` dele, e `docs/integracao-agente.md` deste
> repositório) — o contrato com o CRM já está definido ali e não deve ser
> reinventado aqui.
>
> **Nota sobre o prefixo `AXIOMA` nos marcadores:** `[[AXIOMA:...]]` é uma
> constante fixa do protocolo da API do Conecta CRM (definida pelo backend,
> nunca muda), não o nome do agent. Um agent chamado de outro jeito (ex.:
> "Suporte Clínica X") ainda emite exatamente `[[AXIOMA:Q:...]]` etc. — não
> troque esse prefixo por conta própria, ele não tem relação com a
> identidade do agent.

## Papel do Gateway (o que ele é e o que ele não é)

O Gateway é a **única** peça que fala com a API do WhatsApp e com a API do
agent. Ele nunca decide conteúdo, nunca mantém roteiro, nunca guarda dados
da empresa — isso é 100% do CRM, por contrato (`docs/integracao-agente.md`).
O Gateway só:

1. Recebe mensagem inbound do WhatsApp.
2. Encaminha pro agent (sessão correta).
3. Intercepta a saída do agent (que é **sempre** um marcador `[[AXIOMA:...]]`,
   nunca texto livre — ver `AGENTS.md` do agent → "Saída externa controlada").
4. Resolve esse marcador chamando o CRM (`POST /incoming/`).
5. Envia ao WhatsApp **somente** o `content` que o CRM devolveu.
6. Confirma a entrega (`POST /delivery/`).

## Sessão por contato

**Cada novo contato do WhatsApp leva a uma sessão nova do agent.**
Isso significa:

- A chave de sessão é o número em E.164 (`+55...`) **por empresa**
  (`company_id` + `contact`), nunca o `message_id` isolado.
- "Novo contato" = primeira mensagem que o Gateway recebe desse par
  (`company_id`, `contact`) **sem sessão ativa aberta**. O Gateway não
  precisa (e não deve) tentar adivinhar no CRM se aquele contato já teve
  lead antes — o CRM já resolve isso sozinho em `/incoming/` (cria lead novo
  automaticamente se o anterior já foi despachado; reaproveita o lead ativo
  se ainda não foi). O Gateway só abre uma sessão nova quando não tem uma
  sessão já em memória para aquele par.
- Uma sessão fica aberta enquanto o Gateway estiver recebendo mensagens
  dela. Ela pode (e deve) ser fechada/descartada por timeout de inatividade
  (ex.: sem nenhuma mensagem nova por N horas — defina um valor razoável,
  algo entre 12h e 48h) — isso é só gestão de memória/custo do lado do
  Gateway, **nunca** é o que determina se o agent pode ou não responder.
  Quem decide isso é sempre o CRM via `Bot encerrado`/`NO_REPLY` (ver
  `SOUL.md` do agent → "Máquina de estados"). Uma sessão nova só repete o roteiro do
  zero se o CRM mandar (`action="TEXTO"` com `question_id="apresentacao"`
  de novo); se o CRM disser `NO_REPLY`, a sessão nova fica muda também,
  exatamente como uma sessão antiga ficaria.
- Dentro da mesma sessão, o Gateway deve preservar o contexto de conversa do
  LLM normalmente (histórico de turnos) — isso é memória de conversa, não
  memória de estado de negócio. Estado de negócio nunca vive na sessão.

## Regra inegociável: nunca enviar texto do agent direto ao cliente

O único texto que pode chegar ao WhatsApp do cliente é o `content` devolvido
por `POST /incoming/`. Nunca, em hipótese alguma, o texto que o LLM gerou
(a saída crua do turno do agent) é enviado ao cliente — mesmo que pareça um
marcador malformado, mesmo que a chamada ao CRM falhe, mesmo que a sessão
não seja reconhecida como válida.

Implemente isso assim, não como uma checagem isolada fácil de pular:

1. A função que envia mensagem ao WhatsApp **só aceita como entrada** o
   `content` de uma resposta 200 de `/incoming/` (ou um asset de áudio já
   resolvido do catálogo). Ela não tem um parâmetro de "texto livre" — não
   dá pra chamá-la com a saída do LLM por acidente, porque a assinatura da
   função não permite.
2. A saída do LLM nunca vai direto pra essa função de envio. Ela só pode ir
   para o parser de marcador. Se o parser não reconhecer um marcador válido
   (`Q`, `REPETIR`, `ATUALIZAR`, `VALIDAR`, `CLASSIFICADO`), **nada é
   enviado ao cliente** — registre erro, escale pra revisão humana (log de
   alerta/canal interno), e pare ali. Fail-closed, não fail-open.
3. Se a chamada a `POST /incoming/` falhar (timeout, 5xx, token inválido),
   mesma coisa: nada é enviado ao cliente, erro registrado, alerta disparado.
   Nunca "manda alguma coisa só pra não deixar o cliente sem resposta" — é
   melhor o cliente não receber nada do que receber lixo interno.
4. Identidade do agent/sessão: valide de forma simples e direta (ex.:
   comparar `company_id` da sessão com o `company_id` configurado no token
   daquela empresa) — e se a validação falhar, trate como erro (ponto 3),
   nunca como "deixa passar sem intercepção" (foi exatamente esse o bug do
   Gateway anterior).

## Contrato com o CRM (resumo — ver `docs/integracao-agente.md` para o detalhe completo)

- **Credenciais**: um token fixo por empresa (`Authorization: Token <token>`),
  vindo de variável de ambiente/cofre — nunca hardcoded, nunca em log.
- **`POST /api/companies/{company_id}/incoming/`**: uma chamada por marcador
  emitido pelo agent. Corpo: `contact`, `message_id` (idempotência — repetir
  o mesmo `message_id` nunca duplica efeito), `kind` (`text`/`audio`),
  `marker`, `question_id` (só em `Q`), `fields` (objeto, pode ser `{}`),
  `human_required`/`reason` quando aplicável. Resposta sempre 200:
  `action` (`NO_REPLY`/`TEXTO`/`AUDIO_GRAVADO`), `content`, `question_id`,
  `lead_id`, `event_id`.
  - `NO_REPLY` → não envie nada, nem a palavra "NO_REPLY".
  - `TEXTO` → envie `content` literalmente.
  - `AUDIO_GRAVADO` → `content` é o id do áudio pré-aprovado; resolva no
    catálogo de áudios e envie sem legenda/TTS.
- **`POST /api/companies/{company_id}/delivery/`**: chame só **depois** de
  efetivamente confirmar o envio ao WhatsApp, com `{"event_id": ..., "status":
  "SENT"}` ou `"FAILED"`. Sem essa confirmação, o próximo marcador desse lead
  volta `NO_REPLY` (trava de segurança do CRM contra duplicidade) — então
  **nunca pule essa chamada**, mesmo em caminho de erro (confirme `FAILED`
  explicitamente se o envio falhou).
- O Gateway nunca mantém roteiro, textos aprovados ou dados da empresa em
  cache de longo prazo — cada decisão de conteúdo é uma chamada nova.

## Entrada de áudio

Se a empresa permitir transcrição (`AGENTS.md` → "Áudio de saída e entrada"),
o Gateway transcreve a mensagem de voz recebida **uma única vez** antes de
passar pro agent, e nunca guarda a transcrição completa — só o necessário
pra aquele turno. Isso é responsabilidade do Gateway, não do CRM nem do LLM.

## Saída de áudio por TTS (futuro — não implementar ainda)

Vai existir uma opção futura na tela Roteiro → "Opções do Agente" (mesmo
lugar de `Agente conversacional`), algo como **"Agente envia áudio"**, que
quando marcada faz o Gateway enviar a resposta como áudio sintetizado (TTS)
em vez de texto — mesmo em `action="TEXTO"`. Isso ainda **não está
especificado nem implementado** (nem o campo no `Company`, nem o contrato
de `/incoming/`, nem o parser de ação) — é só um aviso pra quem for montar
o Gateway agora: não hardcode a suposição de que `action="TEXTO"` significa
"sempre manda texto puro ao WhatsApp" de um jeito que vá exigir reescrita
grande depois. Deixe o ponto de envio (texto vs. áudio) isolado numa função
única, fácil de estender com essa opção quando ela for desenhada. Isso é
trabalho futuro, não desta rodada.

## O que validar antes de apontar para um número real

Antes de ligar o Gateway a um número de produção, valide com números
internos, nesta ordem:

1. Primeira mensagem de um contato novo → sessão nova → `Q:apresentacao`
   resolvido e enviado corretamente (não o marcador bruto).
2. Fluxo completo até `CLASSIFICADO` → confirma `delivery` em cada etapa.
3. Reenvio do mesmo `message_id` → nenhum efeito duplicado.
4. Falha propositalmente a chamada de `/incoming/` (ex.: token errado) →
   confirme que **nada** é enviado ao cliente e que um alerta é registrado.
5. Mensagem de um contato cujo lead já foi despachado (`desfecho` setado)
   → confirme que uma sessão nova abre e o fluxo recomeça do zero (o CRM já
   garante um `lead_id` novo — o Gateway só precisa não travar nisso).
6. Áudio recebido, com e sem transcrição permitida pela empresa.
7. `human_required=true` manual → confirme transferência pra humano sem
   nenhuma resposta automática adicional.

Só depois desses 7 cenários passarem limpos é que o Gateway deve ser
apontado para tráfego real de cliente.
