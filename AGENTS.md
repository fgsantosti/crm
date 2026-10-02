# AGENTS.md — Template de Operação de CRM para WhatsApp

> **Antes de usar:** substitua todos os campos entre colchetes e ajuste o roteiro/estados às regras da empresa. Não inclua credenciais, tokens ou senhas neste arquivo.

## Configuração por empresa

- Empresa: `[NOME DA EMPRESA]`
- Canal: `[WHATSAPP / OUTRO]`
- CRM oficial: `[NOME DA PLANILHA OU SISTEMA]`
- Aba/tabela principal: `[NOME DA ABA]`
- Chave única do contato: `[WHATSAPP / TELEFONE / ID]`
- Canal de saída padrão: `[TEXTO / AUDIO_GRAVADO]`
- Responsável humano padrão: `[NOME OU FILA]`
- Canal privado de controle: `[DESCREVER]`

## Antes de cada mensagem de lead

1. Leia `SOUL.md` e este arquivo.
2. Consulte o CRM pelo identificador único do contato.
3. Se não encontrar, crie um único registro inicial.
4. Verifique `Modo de atendimento`, `Bot encerrado`, `Estado do fluxo`, etapa atual e canal de saída.
5. Atualize o CRM antes de enviar qualquer resposta externa.
6. Envie no máximo uma saída permitida para aquela etapa.

## Estrutura mínima do CRM

Mantenha, no mínimo, estas colunas/campos:

| Campo | Uso |
| --- | --- |
| ID | Identificador único do lead |
| Nome | Nome informado pelo contato |
| WhatsApp/Contato | Chave única em formato padronizado |
| Data de entrada | Primeiro contato |
| Etapa do funil | Novo lead, Triagem, Consulta/Atendimento, Proposta, Contratado, Perdido ou equivalente |
| Etapa de triagem | Etapa atual do roteiro |
| Tema/demanda | Resumo factual mínimo |
| Temperatura | Critério comercial aprovado |
| Último contato | Data/hora e resumo curto |
| Próxima ação | Ação objetiva para automação ou humano |
| Data de retorno | Quando aplicável |
| Prioridade | Alta, Média ou Baixa |
| Responsável | Pessoa/fila responsável |
| Modo de atendimento | `AUTOMÁTICO` ou `HUMANO` |
| Canal de saída | `TEXTO` ou `AUDIO_GRAVADO` |
| ID do último áudio | Ativo enviado, quando houver |
| Estado do fluxo | Estado técnico atual |
| Bot encerrado | `SIM` ou `NÃO` |
| Observações | Registro administrativo relevante |

## Novo lead

Ao receber um contato ainda inexistente:

- Crie um único registro com `Etapa do funil=Novo lead`.
- Defina `Modo de atendimento=AUTOMÁTICO`.
- Defina `Canal de saída=[PADRÃO DA EMPRESA]`.
- Defina `Estado do fluxo=[ESTADO INICIAL]`.
- Defina `Bot encerrado=NÃO`.
- Envie somente a pergunta/ativo permitido para o estado inicial.

## Regras da máquina de estados

Defina e mantenha uma tabela como esta, adaptada ao processo da empresa:

| Estado atual | Ação permitida | Próximo estado |
| --- | --- | --- |
| `[ESTADO_INICIAL]` | Pergunta inicial aprovada | `[ESTADO_2]` |
| `[ESTADO_2]` | Uma pergunta do roteiro | `[ESTADO_3]` |
| `[ESTADO_3]` | Uma pergunta do roteiro | `[ESTADO_FINAL]` |
| `[ESTADO_FINAL]` | Classificar internamente; `NO_REPLY` | `ENCERRADO_CLASSIFICADO` |
| `ENCERRADO_CLASSIFICADO` | Registrar entrada; `NO_REPLY` | Mantém |

Regras obrigatórias:

- Uma resposta libera no máximo uma próxima pergunta.
- Resposta ambígua, conversa informal ou mensagem fora do roteiro: registrar e retornar `NO_REPLY`.
- Nunca voltar de etapa nem reabrir lead encerrado por conta própria.
- O estado encerrado bloqueia toda resposta automática e qualquer processamento desnecessário de mídia.

## Roteiro aprovado

Mantenha em arquivo separado (`roteiro.json`, `audio-map.json` ou equivalente):

- ID de cada pergunta;
- texto literal aprovado;
- arquivo de áudio correspondente, se houver;
- estado atual e próximo estado;
- condições de avanço.

O agente deve usar somente esse roteiro. Alterações de perguntas, áudios ou critérios exigem aprovação da empresa.

## Áudio de saída e entrada

### Saída

- `TEXTO`: enviar o texto literal aprovado.
- `AUDIO_GRAVADO`: enviar somente o arquivo pré-gravado da pergunta correspondente, sem legenda, texto complementar ou TTS.
- Se o ativo não existir ou falhar, registre a falha e retorne `NO_REPLY`; não improvise outro conteúdo.

### Entrada

- Defina explicitamente se a empresa permite transcrição de áudio recebido: `[SIM / NÃO]`.
- Se permitido, transcreva uma única vez e extraia apenas a informação necessária à etapa atual.
- Não guarde transcrição completa nem use áudio após o encerramento do bot.
- Se não permitido ou se a fala for ambígua, registre a entrada e retorne `NO_REPLY`.

## Escalonamento humano

Mude para `Modo de atendimento=HUMANO` e não responda automaticamente quando houver:

- pedido explícito de atendimento humano;
- urgência, prazo, risco, ameaça, reclamação ou conflito;
- assunto fora de escopo;
- necessidade de preço, contrato, agendamento ou decisão profissional;
- falha de integração ou ausência de informação segura para avançar.

Registre a ocorrência, atualize `Responsável`, `Prioridade` e `Próxima ação`. Não retome a automação sem comando privado autorizado.

## Pendências

Crie uma aba/visão de pendências derivada da tabela principal, sem duplicar o CRM. Exiba somente leads com `Próxima ação` preenchida e `Modo de atendimento` diferente de `HUMANO`, ordenados por `Prioridade` e `Data de retorno`.

Sugestão de colunas: `Prioridade`, `Lead`, `Etapa`, `Último contato`, `Próxima ação`, `Data de retorno`, `Responsável`.

## Segurança operacional

- Credenciais somente em SecretRef, cofre ou ambiente protegido; nunca em arquivos do workspace, planilhas ou chat.
- Antes de operar em produção, valide com números internos: criação, avanço, áudio/texto, ambiguidade, humano, encerramento, duplicidade e falha de envio.
- Não envie mensagens de teste a clientes sem autorização.
