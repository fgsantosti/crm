# Definições do projeto

Registro das decisões confirmadas em 02/10/2026. Este documento descreve o destino da implementação; a base atual ainda precisa ser adaptada.

## Empresas e acesso

O sistema atende várias empresas contratantes. Cada empresa possui seus próprios contatos, equipe, configuração de WhatsApp, roteiro, conversas e requisições.

Todo acesso deve validar o vínculo do usuário ou da integração com a empresa. O filtro enviado pelo navegador não substitui essa validação no backend. Relacionamentos entre registros também devem pertencer à mesma empresa.

Atendentes podem consultar todos os casos da sua empresa, inclusive casos atribuídos a outros atendentes. Área e responsável são filtros de organização. A área não restringe a visibilidade dos casos.

Cada empresa cadastrará suas próprias áreas de atendimento. O cadastro pertence à empresa e seus valores não são compartilhados automaticamente com outras empresas. A classificação de um caso deve usar uma área da mesma empresa.

Acesso de consulta não define automaticamente permissão para editar configurações, assumir casos de outra pessoa ou mudar responsáveis. A matriz de permissões de escrita será definida antes de implementar essas operações.

O telefone deve ser único dentro da empresa. O mesmo telefone pode existir em empresas diferentes, com registros independentes.

## Agente e qualificação

O agente OpenClaw é externo e acessa somente APIs autenticadas. O CRM é a fonte da verdade e valida as ações solicitadas pelo agente.

O agente usa exclusivamente o roteiro aprovado, conforme AGENTS.md e SOUL.md. Pode abrir requisições no CRM. Essa ação administrativa não autoriza texto livre, confirmação de abertura, novas perguntas ou alteração do roteiro.

Atendimento humano e encerramento continuam bloqueando respostas automáticas. Novas entradas nesses estados são apenas registradas. Abertura de requisição não pode reativar o bot nem voltar etapas.

A requisição será aberta somente ao concluir a qualificação pelo roteiro aprovado. Contatos com triagem incompleta ou transferidos para atendimento humano antes da conclusão não geram uma requisição automática por esse fluxo.

Concluir a qualificação deve registrar o resultado, encerrar o bot e abrir a requisição no CRM. A abertura não autoriza mensagem adicional ao contato. O serviço de abertura precisa ser idempotente para impedir que a repetição do mesmo evento crie requisições duplicadas.

A área da requisição será identificada pelo roteiro aprovado, conforme suas respostas e regras de classificação. O CRM deve validar que a área resultante pertence à mesma empresa. Os mapeamentos entre respostas e áreas fazem parte do roteiro e exigem aprovação da empresa; o agente não pode inventar áreas ou critérios.

A requisição será aberta sem responsável, na fila da área identificada pelo roteiro. Os atendentes atenderão os casos conforme a divisão interna da empresa, usando o filtro de área. Não haverá atribuição automática de atendente na abertura. Todos os casos continuam visíveis aos atendentes da mesma empresa.

Ao iniciar o atendimento, o atendente usará o botão “Assumir atendimento”. O CRM registrará o usuário autenticado como responsável pela requisição e colocará a conversa em atendimento humano, preservando o encerramento da qualificação e bloqueando respostas automáticas.

A operação deve validar o vínculo do atendente com a empresa, registrar quem assumiu e quando e executar a atribuição de forma atômica. Se dois atendentes tentarem assumir a mesma requisição sem responsável, somente um poderá concluir a atribuição. Repetir a ação pelo mesmo responsável não deve duplicar o registro de atribuição. A troca de um responsável existente dependerá de uma regra de permissão ainda a definir.

O comportamento quando o roteiro não identificar uma área válida ainda será definido antes da implementação. Também falta definir os dados mínimos exigidos para abrir a requisição.

## Entidades previstas

| Entidade | Finalidade |
| --- | --- |
| Company | Empresa contratante |
| Membership | Vínculo do usuário com a empresa e seu papel |
| Area | Área de atendimento pertencente à empresa |
| Customer | Contato pertencente à empresa, com telefone E.164 |
| Conversation | Conversa, etapa de qualificação e controle de atendimento |
| Message | Registro da mensagem segundo a política de armazenamento |
| OutboundMessage | Controle persistente de envio |
| ServiceRequest | Demanda com status, área, prioridade, responsável e SLA |

O estado de qualificação, o modo de atendimento e o status da requisição são controles separados. Resolver uma requisição não deve reiniciar a qualificação.

## Pontos ainda a definir

1. Necessidade de múltiplas áreas em uma requisição.
2. Informações mínimas exigidas para abrir a requisição após a qualificação e tratamento quando o roteiro não identificar uma área válida.
3. Permissões de escrita dos papéis admin, supervisor e atendente.
4. Política de armazenamento de texto e payload bruto. Não armazenar transcrições integrais de áudio, conforme as instruções atuais.
5. Contrato real do OpenClaw, após consulta à documentação do adaptador utilizado.

## Infraestrutura preparada

Foram adicionados Dockerfiles, Compose com PostgreSQL, Redis, setup, web, worker, beat, frontend e proxy, além das configurações ASGI, Celery e Channels. Os comandos e limites estão em infraestrutura.md. A disponibilidade do Docker e os resultados das verificações serão registrados ao concluir esta etapa.

## Próxima entrega

Implementar modelos e permissões em uma etapa separada, conforme as decisões deste documento.

Cada entrega deve informar o que foi implementado e os testes executados. A base atual possui compilação do frontend e verificação de sintaxe Python; os testes Django ainda não foram executados porque a instalação das dependências não foi autorizada na etapa anterior.
