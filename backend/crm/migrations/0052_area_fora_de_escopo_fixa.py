from django.db import migrations


def criar(apps, schema_editor):
    Area = apps.get_model("crm", "Area")
    Company = apps.get_model("crm", "Company")
    for company in Company.objects.all():
        if not Area.objects.filter(company=company, name__iexact="Fora de escopo").exists():
            Area.objects.create(company=company, name="Fora de escopo")


class Migration(migrations.Migration):
    dependencies = [("crm", "0051_anexos_comprovante_e_plano_openai")]
    operations = [migrations.RunPython(criar, migrations.RunPython.noop)]
