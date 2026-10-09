from django.db import migrations, models


def criar_detalhamento(apps, schema_editor):
    Company = apps.get_model("crm", "Company")
    Variavel = apps.get_model("crm", "Variavel")
    for company in Company.objects.all():
        Variavel.objects.get_or_create(company=company, name="Detalhamento", defaults={"peso": 3, "builtin": True})


class Migration(migrations.Migration):

    dependencies = [("crm", "0042_identidade_visual")]

    operations = [
        migrations.AddField(
            model_name="variavel",
            name="builtin",
            field=models.BooleanField(default=False, help_text="Variável do sistema (ex.: Detalhamento): existe em toda empresa, não tem pergunta própria, não pode ser renomeada nem excluída; só o peso é editável."),
        ),
        migrations.RunPython(criar_detalhamento, migrations.RunPython.noop),
    ]
