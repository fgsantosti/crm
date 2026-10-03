export type Company = {
  id: number;
  name: string;
  initial_state: string;
  allow_transcription: boolean;
  default_owner: string;
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
};

export type CompanyInfoEntry = {
  id: number;
  company: number;
  title: string;
  content: string;
  updated_at: string;
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
  id: number;
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
