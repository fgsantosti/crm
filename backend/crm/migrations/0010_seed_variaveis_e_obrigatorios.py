from django.db import migrations

MANDATORY_QUESTION_IDS = ["nome", "situacao", "demanda"]
MANDATORY_COMPANYINFO_TITLES = ["Nome da empresa", "Áreas de atendimento", "Disponibilidade de horários"]


def seed_variaveis_e_obrigatorios(apps, schema_editor):
    """Garante que toda empresa já cadastrada sai desta migration com:
    - uma Variavel padrão ("Geral", peso 5) para herdar as perguntas que
      ainda não tinham nenhuma (campo era inexistente até a 0009);
    - as 3 perguntas obrigatórias existindo e marcadas (cria "demanda" se a
      empresa não tiver -- ex.: Rufus Advocacia não tem esse question_id
      hoje, só "nome"/"situacao");
    - as 3 entradas obrigatórias de "Dados da empresa" existindo (cria vazias
      se não existirem, só marca obrigatorio=True se já existirem por título).
    Nada disso quebra o roteiro real já em produção -- só completa o que falta.

    Em migration separada da 0009 (que só mexe em schema) de propósito: Postgres
    recusa criar o índice do FK recém-adicionado se uma escrita nessa mesma
    tabela já rodou antes, na mesma transação (erro real visto ao testar:
    "cannot CREATE INDEX ... because it has pending trigger events").
    """
    Company = apps.get_model("crm", "Company")
    Question = apps.get_model("crm", "Question")
    Variavel = apps.get_model("crm", "Variavel")
    CompanyInfo = apps.get_model("crm", "CompanyInfo")

    for company in Company.objects.all():
        geral, _ = Variavel.objects.get_or_create(company=company, name="Geral", defaults={"peso": 5})
        Question.objects.filter(company=company, variavel__isnull=True).update(variavel=geral)
        for question_id in MANDATORY_QUESTION_IDS:
            question, created = Question.objects.get_or_create(
                company=company, question_id=question_id,
                defaults={"text": "", "variavel": geral},
            )
            if question.variavel_id is None:
                question.variavel = geral
            question.obrigatoria = True
            question.save()
        for title in MANDATORY_COMPANYINFO_TITLES:
            entry, created = CompanyInfo.objects.get_or_create(
                company=company, title=title, defaults={"content": "", "obrigatorio": True},
            )
            if not created and not entry.obrigatorio:
                entry.obrigatorio = True
                entry.save(update_fields=["obrigatorio"])


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0009_companyinfo_obrigatorio_question_obrigatoria_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_variaveis_e_obrigatorios, migrations.RunPython.noop),
    ]
