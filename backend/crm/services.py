import re
from django.db import transaction
from django.utils import timezone
from .models import Lead, Question, Event, Company

NO_REPLY = {"action": "NO_REPLY"}

# Mapa dos campos que o agente Axioma envia em ATUALIZAR/VALIDAR/CLASSIFICADO
# para os campos reais do Lead. 'proxima' nunca é um campo do Lead: é o
# question_id da próxima pergunta, tratado separadamente.
FIELD_MAP = {
    "nome": "name",
    "especialidade": "especialidade",
    "tema": "demand",
    "impacto": "impacto",
    "interesse": "interesse",
    "temperatura": "temperature",
    "prioridade": "priority",
}

def escalate(lead, reason):
    lead.mode = "HUMANO"
    lead.priority = "Alta"
    lead.next_action = reason
    lead.save()

def apply_fields(lead, fields):
    for key, model_field in FIELD_MAP.items():
        if key in fields and fields[key]:
            setattr(lead, model_field, fields[key])

PLACEHOLDER_RE = re.compile(r"\{(" + "|".join(re.escape(p) for p in ["empresa", *FIELD_MAP.keys()]) + r")\}")

def render_text(text, lead, company):
    """Substitui placeholders no texto aprovado pelos dados já coletados do lead e pela empresa.

    {empresa} vem de Company.name: o roteiro nunca precisa citar o nome da empresa
    na mão, e continua correto automaticamente se a empresa for renomeada ou se o
    mesmo texto for reaproveitado como modelo para uma empresa nova.
    {nome}, {especialidade}, {tema}... vêm dos dados já coletados do lead (usado
    sobretudo no texto aprovado de 'validar', que mostra um resumo para confirmação).
    Placeholder sem valor ainda vira string vazia, nunca quebra ou expõe '{campo}' literal.

    Todos os valores de substituição são resolvidos ANTES de rodar o regex, e a
    troca é feita em uma única passada sobre o texto original: um valor de campo
    (texto livre vindo do lead via o agente de IA) nunca é reprocessado como se
    fosse ele próprio um novo placeholder. Isso evita que um lead encadeie campos
    (ex.: nome="{tema}", tema="{impacto}", impacto="<texto arbitrário>") para fazer
    o backend reexpandir e enviar conteúdo que não é do roteiro aprovado da empresa.
    """
    values = {"empresa": company.name}
    for placeholder, model_field in FIELD_MAP.items():
        values[placeholder] = getattr(lead, model_field) or ""

    def substitute(match):
        return values[match.group(1)]

    return PLACEHOLDER_RE.sub(substitute, text)

@transaction.atomic
def receive(company, data):
    # Serialize per company: protege a criação do primeiro contato e mensagens concorrentes.
    company = Company.objects.select_for_update().get(pk=company.pk)
    lead, created = Lead.objects.get_or_create(company=company, contact=data["contact"], defaults={"state": company.initial_state, "owner": company.default_owner})
    previous = Event.objects.filter(lead=lead, message_id=data["message_id"]).first()
    if previous:
        return {**NO_REPLY, "duplicate": True, "lead_id": str(lead.pk)}
    lead.last_contact = timezone.now()
    lead.save()
    event = Event.objects.create(lead=lead, message_id=data["message_id"], summary=f"Marcador recebido: {data['marker']}")
    result = dict(NO_REPLY)

    if lead.mode == "HUMANO" or lead.bot_closed or lead.state == "ENCERRADO_CLASSIFICADO":
        pass
    elif data["human_required"]:
        escalate(lead, data["reason"])
    elif Event.objects.filter(lead=lead, delivery="PENDING").exclude(pk=event.pk).exists():
        escalate(lead, "Entrega anterior pendente: verificar integração")
    else:
        marker = data["marker"]
        fields = data.get("fields") or {}
        if marker == "Q":
            question_id = data["question_id"]
            if not question_id:
                escalate(lead, "Marcador Q sem question_id: revisar integração do agente")
                question_id = None
            else:
                lead.state = question_id
        elif marker == "REPETIR":
            question_id = lead.state
            event.summary = "Entrada ambígua ou fora do roteiro; repetindo pergunta atual"
        elif marker == "ATUALIZAR":
            apply_fields(lead, fields)
            question_id = fields.get("proxima", "")
            if not question_id:
                escalate(lead, "ATUALIZAR sem 'proxima': configurar roteiro aprovado")
                question_id = None
            else:
                lead.state = question_id
                lead.funnel_stage = "Triagem"
        elif marker == "VALIDAR":
            apply_fields(lead, fields)
            question_id = "validar"
            lead.state = "VALIDANDO"
        elif marker == "CLASSIFICADO":
            if lead.state != "VALIDANDO":
                escalate(lead, "CLASSIFICADO recebido sem VALIDAR anterior: revisar fluxo do agente")
                question_id = None
            else:
                apply_fields(lead, fields)
                lead.bot_closed = True
                lead.state = "ENCERRADO_CLASSIFICADO"
                lead.funnel_stage = "Triagem concluída"
                lead.next_action = "Revisar classificação e dar continuidade humana"
                question_id = "encerramento"
        else:
            escalate(lead, f"Marcador desconhecido: {marker}")
            question_id = None

        if question_id:
            question = Question.objects.filter(company=company, question_id=question_id).first()
            if not question:
                escalate(lead, f"Configurar roteiro aprovado para question_id={question_id}")
            else:
                use_audio = data["kind"] == "audio" and question.audio_asset
                asset = question.audio_asset if use_audio else render_text(question.text, lead, company)
                if not asset:
                    escalate(lead, "Ativo aprovado ausente")
                else:
                    if use_audio:
                        lead.last_audio_id = question.audio_asset
                    result = {"action": "AUDIO_GRAVADO" if use_audio else "TEXTO", "content": asset, "question_id": question_id}
                    event.delivery = "PENDING"
        lead.save()

    result.update({"lead_id": str(lead.pk), "event_id": event.pk})
    event.result = result
    event.save()
    return result
