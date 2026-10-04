from django.db import migrations

BUILTIN_VARIAVEL_ROTEIRO = {
    "nome": ("Nome", "nome"),
    "situacao": ("Área da Lead", "especialidade"),
    "demanda": ("Demanda", "tema"),
}


def seed_variaveis_roteiro_builtin(apps, schema_editor):
    """Cria (se não existirem) as 3 Variáveis de roteiro builtin -- Nome/Área da
    Lead/Demanda, reaproveitando os placeholders fixos já existentes (nome/
    especialidade/tema) -- em toda empresa já cadastrada, e atrela cada uma à
    sua pergunta obrigatória correspondente (nome/situacao/demanda).

    Migration de dados separada da 0014 (que só mexe em schema), mesmo motivo
    das separações anteriores (0009/0010, 0012/0013): evitar o erro real de
    Postgres "cannot CREATE INDEX ... because it has pending trigger events".
    """
    Company = apps.get_model("crm", "Company")
    Question = apps.get_model("crm", "Question")
    VariavelRoteiro = apps.get_model("crm", "VariavelRoteiro")

    for company in Company.objects.all():
        for question_id, (nome, slug) in BUILTIN_VARIAVEL_ROTEIRO.items():
            vr, _ = VariavelRoteiro.objects.get_or_create(company=company, slug=slug, defaults={"name": nome, "builtin": True})
            if not vr.builtin:
                vr.builtin = True
                vr.save(update_fields=["builtin"])
            Question.objects.filter(company=company, question_id=question_id, variavel_roteiro__isnull=True).update(variavel_roteiro=vr)


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0014_variavel_roteiro'),
    ]

    operations = [
        migrations.RunPython(seed_variaveis_roteiro_builtin, migrations.RunPython.noop),
    ]
