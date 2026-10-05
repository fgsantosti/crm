from django.db import migrations
from django.utils import timezone


def corrigir(apps, schema_editor):
    """Idempotente: leads ATIVOS que caíram em atendimento humano por "fora de escopo" (ou com
    a área "Fora de escopo") viram Desqualificado/Baixa com desfecho automático, fora do Kanban
    -- mesma regra de services.desqualificar_fora_de_escopo. Também remove o agendamento antigo
    do beat (a task foi renomeada para apagar_triagens_abandonadas_task)."""
    Lead = apps.get_model("crm", "Lead")
    # A regra anterior promovia triagens abandonadas/encerradas cedo para
    # Remarketing ou Quente. Remove só as que ainda não foram assumidas.
    Lead.objects.filter(
        desfecho="", origem_manual=False, owner__isnull=True,
        urgencia_detalhe__motivo__in=["abandono", "encerramento_antecipado"],
    ).delete()
    afetados = Lead.objects.filter(desfecho="", origem_manual=False).filter(
        next_action__iexact="fora de escopo"
    ) | Lead.objects.filter(desfecho="", origem_manual=False, especialidade__iexact="fora de escopo")
    agora = timezone.now()
    for lead in afetados.distinct():
        lead.temperature = "Desqualificado"
        lead.priority = "Baixa"
        lead.mode = "AUTOMÁTICO"
        lead.bot_closed = True
        lead.state = "ENCERRADO_CLASSIFICADO"
        lead.funnel_stage = "Triagem concluída"
        lead.next_action = "Fora de escopo"
        lead.desfecho = "desqualificado"
        lead.concluido_em = agora
        lead.urgencia_detalhe = {**(lead.urgencia_detalhe or {}), "motivo": "fora_de_escopo"}
        lead.save()

    if "django_celery_beat_periodictask" in schema_editor.connection.introspection.table_names():
        try:
            PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
        except LookupError:
            return
        PeriodicTask.objects.filter(name="classificar-triagens-abandonadas").delete()


class Migration(migrations.Migration):
    dependencies = [("crm", "0029_blacklist_desfecho_bloqueado")]
    operations = [migrations.RunPython(corrigir, migrations.RunPython.noop)]
