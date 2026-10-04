from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("crm", "0024_company_numero_agente")]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="urgencia_detalhe",
            field=models.JSONField(
                blank=True, default=dict,
                help_text="Auditoria do CLASSIFICADO por notas: {notas, pesos, score, temperatura_calculada} (ver services.calcular_urgencia).",
            ),
        ),
    ]
