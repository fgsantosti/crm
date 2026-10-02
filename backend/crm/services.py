from django.db import transaction
from django.utils import timezone
from .models import Lead, Step, Event, Company

NO_REPLY = {"action": "NO_REPLY"}

def escalate(lead, reason):
    lead.mode = "HUMANO"
    lead.priority = "Alta"
    lead.next_action = reason
    lead.save()

@transaction.atomic
def receive(company, data):
    # Serialize per company: protects first-contact creation and concurrent messages.
    company = Company.objects.select_for_update().get(pk=company.pk)
    lead, created = Lead.objects.get_or_create(company=company, contact=data["contact"], defaults={"state": company.initial_state, "output_channel": company.output_channel, "owner": company.default_owner})
    previous = Event.objects.filter(lead=lead, message_id=data["message_id"]).first()
    if previous:
        return {**NO_REPLY, "duplicate": True, "lead_id": str(lead.pk)}
    lead.last_contact = timezone.now()
    lead.save()
    event = Event.objects.create(lead=lead, message_id=data["message_id"], summary="Entrada recebida: " + data["kind"])
    result = dict(NO_REPLY)
    if lead.mode == "HUMANO" or lead.bot_closed or lead.state == "ENCERRADO_CLASSIFICADO":
        pass
    elif data["human_required"] or any(term in data["answer"].casefold() for term in ["atendente", "atendimento humano", "urgente", "urgência", "ameaça", "reclamação", "contrato", "agendar", "preço", "prazo"]):
        escalate(lead, data["reason"])
    elif data["kind"] == "audio":
        event.summary = "Áudio registrado sem processamento; transcrição não implementada"
    elif Event.objects.filter(lead=lead, delivery="PENDING").exclude(pk=event.pk).exists():
        escalate(lead, "Entrega anterior pendente: verificar integração")
    else:
        step = Step.objects.filter(company=company, state=lead.state).first()
        if not step:
            escalate(lead, "Configurar roteiro aprovado para o estado atual")
        elif not created and data["answer"].strip().casefold() not in [a.strip().casefold() for a in step.accepted_answers]:
            event.summary = "Entrada ambígua ou fora do roteiro"
        elif step.terminal:
            lead.bot_closed = True
            lead.state = "ENCERRADO_CLASSIFICADO"
            lead.funnel_stage = "Triagem concluída"
            lead.next_action = "Revisar classificação e dar continuidade humana"
            lead.save()
        else:
            asset = step.text if lead.output_channel == "TEXTO" else step.audio_asset
            if not asset:
                escalate(lead, "Ativo aprovado ausente")
            else:
                lead.state = step.next_state
                lead.funnel_stage = "Triagem"
                if lead.output_channel == "AUDIO_GRAVADO": lead.last_audio_id = step.audio_asset
                lead.save()
                result = {"action": lead.output_channel, "content": asset, "question_id": step.question_id}
                event.delivery = "PENDING"
    result.update({"lead_id": str(lead.pk), "event_id": event.pk})
    event.result = result
    event.save()
    return result
