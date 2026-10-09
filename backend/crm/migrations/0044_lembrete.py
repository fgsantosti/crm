from django.db import migrations, models

TEXTO = "Olá, {nome}! Nossa conversa com {empresa} ficou parada. Quando puder, é só responder aqui que continuamos de onde paramos."


def criar_texto_lembrete(apps, schema_editor):
    Company = apps.get_model("crm", "Company")
    Question = apps.get_model("crm", "Question")
    for company in Company.objects.all():
        # Empresas que já operam começam com o lembrete DESLIGADO: a empresa revisa o texto e liga.
        Question.objects.get_or_create(company=company, question_id="lembrete", defaults={"text": TEXTO, "obrigatoria": True, "habilitada": False})


class Migration(migrations.Migration):

    dependencies = [("crm", "0043_variavel_detalhamento")]

    operations = [
        migrations.AddField(model_name="question", name="horario_envio", field=models.TimeField(blank=True, null=True, help_text="Só no texto 'lembrete': horário exato (fuso do CRM) em que o lembrete é enviado depois de 24h sem resposta; vazio = assim que completar 24h.")),
        migrations.AddField(model_name="lead", name="lembrete_enviado_em", field=models.DateTimeField(blank=True, null=True, help_text="Confirmação (SENT) do lembrete de 24h sem resposta; depois dele o lead sem retorno é apagado em mais 24h.")),
        migrations.RunPython(criar_texto_lembrete, migrations.RunPython.noop),
    ]
