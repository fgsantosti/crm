export type Company = {
  id: number;
  name: string;
  initial_state: string;
  allow_transcription: boolean;
  /** Número de WhatsApp (E.164) conectado ao agente; mensagens dele mesmo nunca abrem lead. */
  numero_agente: string;
  /** Marcado: agente conversa livremente sobre a empresa antes do funil. Desmarcado: vai direto pro funil com texto próprio. */
  agente_conversacional: boolean;
  /** Portão do Admin: o CRM guarda o histórico de conversa dos leads (botão "Histórico de conversa"). */
  coletar_historico_conversa: boolean;
  etapa_inicial: boolean;
  /** SPIN única quando só uma está habilitada na Etapa Inicial (derivado de spins_iniciais). */
  spin_inicial: number | null;
  /** Etapa Inicial: SPINs (áreas) que o cliente pode acessar; com várias o agente escolhe a área pela mensagem inicial. */
  spins_iniciais: number[];
  /** Agente envia as mensagens como áudio (só vale com allow_transcription ligado pelo Admin). */
  mensagens_audio: boolean;
  /** Voz do TTS automático (Edge, pt-BR). */
  voz_tts: string;
};

export type Lead = {
  id: string;
  company: number;
  name: string;
  contact: string;
  created_at: string;
  funnel_stage: string;
  /** question_id atual do protocolo Axioma (apresentacao, nome, situacao, ... ou ENCERRADO_CLASSIFICADO). */
  state: string;
  /** Campo "tema" do protocolo Axioma. */
  demand: string;
  /** Nome de uma Area cadastrada pela empresa (tela Equipe) — texto livre, não é mais um enum fixo. */
  especialidade: string;
  impacto: string;
  interesse: 'sim' | 'nao' | 'depois' | '';
  /** Campo "temperatura" do protocolo Axioma. */
  temperature: 'Qualificado' | 'Quente' | 'Desconfiado' | 'Frio' | 'Desqualificado' | '';
  urgencia_rank: number;
  last_contact: string | null;
  next_action: string;
  return_at: string | null;
  priority: 'Alta' | 'Média' | 'Baixa';
  /** Auditoria do CLASSIFICADO por notas (vazio quando o agente mandou a temperatura direto). */
  urgencia_detalhe: { notas?: Record<string, number>; pesos?: Record<string, number>; score?: number; temperatura_calculada?: string };
  /** id do usuário responsável -- compare com Me.id, nunca por nome. */
  owner: number | null;
  /** Só pra exibição. */
  owner_nome: string;
  mode: 'AUTOMÁTICO' | 'HUMANO';
  last_audio_id: string;
  bot_closed: boolean;
  notes: string;
  /** Fora do fluxo de leads novos (ex.: 'acompanhamento' = cliente com processo no escritório). Vazio = lead normal. */
  situacao_especial: '' | 'acompanhamento';
  /** 'desqualificado' é automático (classificado Desqualificado/Desconfiado), nunca escolhido no Despacho. */
  desfecho: 'encerrado' | 'comprometido' | 'falha' | 'desqualificado' | 'bloqueado' | '';
  concluido_em: string | null;
  /** Coluna pós-classificação. Qualificados (vazio) e Em espera não têm responsável. */
  etapa_atendimento: 'espera' | 'negociacao' | 'despacho' | '';
  /** Desfecho escolhido ao entrar em "Despacho", ainda não definitivo até "Enviar Despachos". */
  desfecho_pendente: 'encerrado' | 'comprometido' | 'falha' | '';
  /** Cadastrado manualmente pelo atendente (tela Atendimento Humano) -- não vem do agente, não aparece no Kanban. */
  origem_manual: boolean;
};

export type BlacklistEntry = {
  id: number;
  contact: string;
  motivo: string;
  adicionado_por: number | null;
  adicionado_por_nome: string;
  created_at: string;
};

export type LeadEvent = {
  id: number;
  message_id: string;
  created_at: string;
  summary: string;
  delivery: string;
};

export type Question = {
  id: number;
  company: number;
  question_id: string;
  text: string;
  habilitada: boolean;
  /** URL da gravação própria (OGG), que substitui o TTS; null sem gravação. */
  audio_gravado: string | null;
  /** Variável (peso 1-10) que esta pergunta alimenta na classificação de urgência. */
  variavel: number;
  /** nome/situacao/demanda — fixas em todo roteiro, não podem ser excluídas. */
  obrigatoria: boolean;
  /** Enviar a pergunta SPIN mesmo quando todos os dados de classificação já foram capturados. */
  envio_obrigatorio: boolean;
  ordem: number;
  /** Opcional: guarda a resposta desta pergunta pra reusar como placeholder ({slug}) em outro texto. */
  variavel_roteiro: number | null;
  /** Dados que o cliente deve informar antes do encaminhamento para humano. */
  variaveis_obrigatorias: number[];
  /** null = pergunta fixa (antes de o agente definir a área); com área = lista "{Área}-SPIN". */
  area: number | null;
  etapa_spin: '' | 'situacao' | 'problema' | 'implicacao' | 'necessidade';
};

export type Variavel = {
  id: number;
  name: string;
  /** 1-10, usado na média ponderada que sugere a urgência (ver services.calcular_urgencia). */
  peso: number;
};

export type VariavelRoteiro = {
  id: number;
  name: string;
  /** Token usado como {slug} no texto; gerado a partir do nome. */
  slug: string;
  /** Cor do marcador na tela Roteiro, pra confirmação visual de uso. */
  cor: string;
  /** Nome/Área da Lead/Demanda — fixas em toda empresa, não podem ser excluídas. */
  builtin: boolean;
};

export type CompanyInfoEntry = {
  id: number;
  company: number;
  title: string;
  content: string;
  updated_at: string;
  /** Nome da empresa / Áreas de atendimento / Disponibilidade de horários — fixas, não podem ser excluídas. */
  obrigatorio: boolean;
};

export type Paginated<T> = { count: number; next: string | null; previous: string | null; results: T[] };

export type Role = 'atendente' | 'empresa' | 'admin';

export type Me = {
  id: number;
  username: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
  is_staff: boolean;
  is_superuser: boolean;
  is_agent: boolean;
  must_change_password: boolean;
};

export type Area = {
  id: number;
  name: string;
  /** Etapa Inicial com várias SPINs: palavras-chave (separadas por vírgula) que ajudam o agente a reconhecer a área. */
  palavras_chave: string;
};

export type AtendenteInvite = {
  id: string;
  name: string;
  email: string;
  created_at: string;
  expires_at: string;
  verified_at: string | null;
  attempts: number;
  status: 'pendente' | 'expirado' | 'verificado';
};

export type EquipeMembro = {
  id: number;
  username: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
  is_staff: boolean;
  is_superuser: boolean;
  date_joined: string;
};

export type AdminCompany = {
  id: number;
  name: string;
  initial_state: string;
  allow_transcription: boolean;
  coletar_historico_conversa: boolean;
  numero_agente: string;
  member_count: number;
  tem_agente_ativo: boolean;
};

export type AgentStatus = {
  existe: boolean;
  id: number | null;
  username: string;
  /** Conta ligada à empresa (membro). Desvinculada = chave válida, mas o agente recebe 404 do CRM. */
  vinculada: boolean;
  ativa: boolean;
  masked_key: string | null;
  validade: { expires_at: string; expirado: boolean } | null;
};

export type ContaEmpresa = {
  id: number;
  username: string;
  email: string;
  display_name: string;
  is_active: boolean;
  date_joined: string;
  last_login: string | null;
  must_change_password: boolean;
};

export type ContasDaEmpresa = {
  agente: AgentStatus;
  agentes_extras: AgentStatus[];
  empresa: ContaEmpresa[];
};

export type AdminOverview = {
  empresas_total: number;
  empresas_com_agente_ativo: number;
  empresas_sem_agente_ativo: number;
  usuarios_ativos: number;
};

export type AdminContaEmpresa = {
  id: number;
  username: string;
  email: string;
  display_name: string;
  is_active: boolean;
  date_joined: string;
  companies: string[];
};
