import type { IdentidadeVisual } from './identidade';

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
  /** Identidade visual da barra lateral (só a empresa e a equipe dela veem): sem as duas cores vale o padrão Conecta. */
  identidade_visual: IdentidadeVisual;
  etapa_inicial: boolean;
  /** SPIN única quando só uma está habilitada na Etapa Inicial (derivado de spins_iniciais). */
  spin_inicial: number | null;
  /** Etapa Inicial: SPINs (áreas) que o cliente pode acessar; com várias o agente escolhe a área pela mensagem inicial. */
  spins_iniciais: number[];
  /** Agente envia as mensagens como áudio (só vale com allow_transcription ligado pelo Admin). */
  mensagens_audio: boolean;
  /** Voz do TTS automático (Edge, pt-BR). */
  voz_tts: string;
  /** Notas (0-10, crescentes) onde terminam Desqualificado, Desconfiado, Frio e Qualificado; a partir da última é Quente. */
  classificacao_cortes?: number[];
  /** Índice (0 Desqualificado ... 4 Quente) da primeira classificação que vai ao Kanban; as anteriores concluem sozinhas. Padrão 2. */
  classificacao_kanban_a_partir_de?: number;
  /** Critério em texto que o agente lê antes de dar as notas. */
  classificacao_regra?: string;
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
  /** Lembrete de 24h sem resposta confirmado (SENT); null se não houve. */
  lembrete_enviado_em?: string | null;
  /** Acompanhamento despachado pela conta Empresa sem responsável. */
  despachado_pela_empresa?: boolean;
  next_action: string;
  return_at: string | null;
  priority: 'Alta' | 'Média' | 'Baixa';
  /** Auditoria do CLASSIFICADO por notas (vazio quando o agente mandou a temperatura direto). */
  urgencia_detalhe: { notas?: Record<string, number>; pesos?: Record<string, number>; nomes?: Record<string, string>; score?: number; temperatura_calculada?: string };
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
  /** Só no texto 'lembrete': HH:MM:SS do envio (vazio = ao completar 24h sem resposta). */
  horario_envio?: string | null;
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
  /** Variável do sistema (Detalhamento): obrigatória, só o peso é editável. */
  builtin?: boolean;
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
  /** Fora de escopo: existe em toda empresa e não pode ser removida nem renomeada. */
  fixa?: boolean;
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
  /** Situação do teste (piloto) da empresa. */
  teste?: TesteSituacao;
  gestor_id?: number | null;
  gestor_nome?: string;
};

export type TesteSituacao = { em_teste: boolean; inicio: string | null; dias: number; fim: string | null; restam: number | null; situacao: string; convertido_em: string | null };

export type PrecoItem = {
  item: 'implantacao' | 'base' | 'empresa_adicional' | 'agente_adicional' | 'piloto';
  nome: string;
  nota: string;
  tipo: string;
  valor: string | null;
  vigente_desde: string | null;
  proximo: { valor: string; vigente_desde: string } | null;
  em_uso: number | null;
};

export type PrecoHistorico = { id: number; item: string; nome: string; valor: string; vigente_desde: string; escopo: string; escopo_rotulo: string; nota: string; criado_em: string; por: string };

export type TabelaPrecos = { itens: PrecoItem[]; recorrente_atual: string; historico: PrecoHistorico[] };

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


export type GestorEmpresa = { id: number; name: string; em_teste: boolean };
export type Gestor = {
  id: number;
  nome: string;
  email: string;
  usuario: number | null;
  usuario_email: string;
  dia_vencimento: number;
  forma_pagamento: 'pix' | 'boleto' | 'cartao' | 'outro';
  openai_modo: 'chave' | 'plano';
  contrato_inicio: string | null;
  indice_reajuste: string;
  openai_projeto: string;
  openai_chave_final: string;
  openai_limite_mensal: string | null;
  notas: string;
  empresas: GestorEmpresa[];
  usuario_info: { username: string; email: string; ativo: boolean; criado_em: string; ultimo_acesso: string | null } | null;
  resumo_comercial: { linhas: { descricao: string; valor: string }[]; total: string };
};

export type CobrancaItem = {
  id: number; gestor_id: number; gestor: string; forma: string; tipo: 'mensalidade' | 'piloto' | 'implantacao'; tipo_rotulo: string;
  referencia: string; vencimento: string; valor: string; pago: string; saldo: string;
  status: 'recebido' | 'a_receber' | 'em_atraso' | 'sem_cobranca'; dias_atraso: number; faixa: number;
  linhas: { descricao: string; valor: string; empresa: string; agente: string }[]; recebido_em: string | null;
};
export type Faturamento = {
  mes: string;
  kpis: { previsto: string; recebido: string; a_receber: string; em_atraso: string };
  cobrancas: CobrancaItem[];
  por_empresa: { empresa: string; gestor: string; valor: string; linhas: string[] }[];
  por_agente: { agente: string; empresa: string; gestor: string; valor: string; linhas: string[] }[];
  inadimplencia: {
    faixas: { faixa: number; n: number; valor: string }[];
    atrasados: { cobranca_id: number; gestor: string; tipo_rotulo: string; saldo: string; vencimento: string; dias_atraso: number; faixa: number }[];
    limites: { curta: number; media: number; aviso_desligamento_dias: number };
  };
  pagamentos: { id: number; data: string; gestor: string; referencia: string; valor: string; forma: string; comprovante: string; comprovante_arquivo: string; por: string }[];
  contratos: { gestor_id: number; gestor: string; contrato_inicio: string | null; indice: string; proximo_reajuste: string | null; dias_para_reajuste: number | null; alerta_reajuste: boolean; desconto_por_tempo_pct: number; implantacao: string; em_teste: boolean }[];
  recorrente: { mes: string; valor: string; projecao: boolean }[];
};


export type ConfigNotificacao = {
  remetente: string; cc: string; lembrete_cobranca_ativo: boolean; lembrete_dias_antes: number; teste_ativo: boolean; teste_dias_avisos: number[];
  atraso_f1: boolean; atraso_f2: boolean; atraso_f3: boolean; chave_ativo: boolean; chave_dias_avisos: number[];
  texto_cobranca: string; texto_teste: string; texto_atraso: string; texto_desligamento: string; texto_chave: string;
};
export type NotificacaoItem = { id: number; quando: string; gestor: string; para: string; tipo: string; tipo_rotulo: string; assunto: string; estado: string; erro: string };
export type ChavesGestor = {
  gestor_id: number; gestor: string; email: string;
  agentes: { agente: string; empresa: string; chave: string | null; expira_em: string | null; dias: number | null; situacao: 'valida' | 'expira' | 'expirada' | 'sem_chave' | 'sem_validade' }[];
  openai: { modo: 'chave' | 'plano'; projeto: string; chave_final: string; limite_mensal: string | null };
};
export type RegraCobranca = {
  prorata_ativo: boolean; descontos: [number, number][]; abater_piloto: boolean; abatimento_pct: number; indice_padrao: string;
  alerta_reajuste_dias: number; faixa_atraso_curta: number; faixa_atraso_media: number; aviso_desligamento_dias: number;
};

export type AdminVisaoGeral = {
  kpis: { mensalidade_estimada: string; gestores: number; gestores_sem_acesso: number; empresas: number; empresas_sem_gestor: number; agentes: number; agentes_adicionais: number; leads_30_dias: number };
  alertas: { tipo: 'chave' | 'cobranca' | 'teste' | 'empresa' | 'gestor'; titulo: string; detalhe: string; gravidade: 'alta' | 'media' | 'baixa' }[];
  volume: { empresa_id: number; empresa: string; leads: number }[];
  faturamento: { gestor_id: number; gestor: string; empresas: number; extras: number; total: string | null }[];
  atividade: { quando: string; texto: string }[];
};

export type AdminLeadsResumo = {
  periodo: '30' | '90' | 'all';
  resumo: { atendimentos: number; classificados: number; quentes: number; nao_prosseguiram: number };
  tipos: { chave: string; rotulo: string; valor: number }[];
  mensal: { mes: string; valor: number }[];
  temperaturas: string[];
  empresas: { empresa_id: number; empresa: string; gestor: string; total: number; temperaturas: Record<string, number>; nao_prosseguiram: number }[];
  gestores: { id: number; nome: string }[];
};
