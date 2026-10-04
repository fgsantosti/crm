export type Company = {
  id: number;
  name: string;
  initial_state: string;
  allow_transcription: boolean;
  default_owner: string;
  /** Marcado: agente conversa livremente sobre a empresa antes do funil. Desmarcado: vai direto pro funil com texto próprio. */
  agente_conversacional: boolean;
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
  temperature: 'Qualificado' | 'Quente' | 'Desconfiado' | 'Remarketing' | 'Desqualificado' | '';
  last_contact: string | null;
  next_action: string;
  return_at: string | null;
  priority: 'Alta' | 'Média' | 'Baixa';
  owner: string;
  mode: 'AUTOMÁTICO' | 'HUMANO';
  last_audio_id: string;
  bot_closed: boolean;
  notes: string;
  desfecho: 'encerrado' | 'comprometido' | 'falha' | '';
  /** Coluna do Kanban pós-classificação em que esse owner já está. Vazio = ainda em "Qualificados". */
  etapa_atendimento: 'espera' | 'negociacao' | 'despacho' | '';
  /** Desfecho escolhido ao entrar em "Despacho", ainda não definitivo até "Enviar Despachos". */
  desfecho_pendente: 'encerrado' | 'comprometido' | 'falha' | '';
  /** Cadastrado manualmente pelo atendente (tela Atendimento Humano) -- não vem do agente, não aparece no Kanban. */
  origem_manual: boolean;
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
  audio_asset: string;
  /** Variável (peso 1-10) que esta pergunta alimenta na classificação de urgência. */
  variavel: number;
  /** nome/situacao/demanda — fixas em todo roteiro, não podem ser excluídas. */
  obrigatoria: boolean;
  ordem: number;
  /** Opcional: guarda a resposta desta pergunta pra reusar como placeholder ({slug}) em outro texto. */
  variavel_roteiro: number | null;
};

export type Variavel = {
  id: number;
  name: string;
  /** 1-10, usado na média ponderada que sugere a urgência (ver services.calcular_urgencia_sugerida). */
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
  default_owner: string;
  member_count: number;
  tem_agente_ativo: boolean;
};

export type AgentStatus = {
  existe: boolean;
  username: string;
  masked_key: string | null;
  validade: { expires_at: string; expirado: boolean } | null;
};
