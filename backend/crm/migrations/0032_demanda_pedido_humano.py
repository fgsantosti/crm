from django.db import migrations


def registrar_pedido_humano(apps, schema_editor):
    Lead = apps.get_model("crm", "Lead")
    motivo = "Cliente pediu contato direto com atendente humano"
    leads = Lead.objects.using(schema_editor.connection.alias).filter(
        mode="HUMANO", next_action="pedido humano",
    ).exclude(demand__contains=motivo)
    for lead in leads.iterator():
        demanda = lead.demand.strip()
        lead.demand = f"{demanda[:300 - len(motivo) - 3]} | {motivo}" if demanda else motivo
        lead.save(update_fields=["demand"])


class Migration(migrations.Migration):
    dependencies = [("crm", "0031_espera_sem_responsavel")]
    operations = [migrations.RunPython(registrar_pedido_humano, migrations.RunPython.noop)]
