from django.db import migrations

MANDATORY_OFFFLOW_QUESTION_IDS = ["apresentacao", "empresa", "validar", "encerramento"]


def seed_textos_fora_do_fluxo(apps, schema_editor):
    """Cria (se não existirem) os 4 textos fora do fluxo em toda empresa já
    cadastrada -- apresentacao (1ª mensagem), empresa (fallback sobre a
    empresa durante o fluxo), validar (confirmação dos dados coletados) e
    encerramento (CLASSIFICADO) -- sem Variavel (não são classificáveis), e
    atribui uma ordem sequencial (por id) às perguntas de fluxo que ainda
    estavam todas em ordem=0 (valor padrão da 0012).

    Migration de dados separada da 0012 (que só mexe em schema) seguindo o
    mesmo motivo da separação 0009/0010: evitar o erro real de Postgres
    "cannot CREATE INDEX ... because it has pending trigger events" quando
    uma escrita na tabela roda antes do índice do campo novo ser criado, na
    mesma transação.
    """
    Company = apps.get_model("crm", "Company")
    Question = apps.get_model("crm", "Question")

    for company in Company.objects.all():
        for question_id in MANDATORY_OFFFLOW_QUESTION_IDS:
            question, created = Question.objects.get_or_create(
                company=company, question_id=question_id,
                defaults={"text": "", "variavel": None, "obrigatoria": True},
            )
            if not created and (not question.obrigatoria or question.variavel_id is not None):
                # Já existia de antes da feature de Variaveis (0009/0010 chegou a
                # herdar a Variavel "Geral" pra esses 4 por terem variavel nulo
                # na época) -- corrige pra bater com a regra atual: textos fora
                # do fluxo são obrigatórios e nunca têm variável.
                question.obrigatoria = True
                question.variavel = None
                question.save(update_fields=["obrigatoria", "variavel"])
        fluxo = Question.objects.filter(company=company).exclude(question_id__in=MANDATORY_OFFFLOW_QUESTION_IDS).order_by("id")
        for ordem, question in enumerate(fluxo):
            Question.objects.filter(pk=question.pk).update(ordem=ordem)


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0012_question_ordem'),
    ]

    operations = [
        migrations.RunPython(seed_textos_fora_do_fluxo, migrations.RunPython.noop),
    ]
