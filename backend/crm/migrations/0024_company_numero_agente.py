import re

from django.db import migrations, models

E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalizar_numero_agente(apps, schema_editor):
    """O antigo 'Responsável padrão' era texto livre (nome de atendente/fila). Só
    sobrevive o que já for um número de telefone; o resto vira vazio."""
    Company = apps.get_model("crm", "Company")
    for company in Company.objects.all():
        bruto = (company.numero_agente or "").strip()
        digitos = re.sub(r"\D", "", bruto)
        candidato = f"+{digitos}" if digitos else ""
        novo = candidato if E164.match(candidato) and not re.search(r"[A-Za-z]", bruto) else ""
        if novo != company.numero_agente:
            company.numero_agente = novo
            company.save(update_fields=["numero_agente"])


class Migration(migrations.Migration):
    dependencies = [("crm", "0023_lead_desfecho_desqualificado")]

    operations = [
        migrations.RenameField(model_name="company", old_name="default_owner", new_name="numero_agente"),
        migrations.RunPython(normalizar_numero_agente, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="company",
            name="numero_agente",
            field=models.CharField(
                blank=True, max_length=16,
                help_text="Número de WhatsApp (E.164) conectado ao agente. Normalmente é o mesmo número em que a equipe faz os atendimentos; mensagens vindas dele mesmo nunca abrem lead.",
            ),
        ),
    ]
