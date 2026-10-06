from django.db import migrations, models


def liberar_espera(apps, schema_editor):
    Lead = apps.get_model("crm", "Lead")
    Lead.objects.using(schema_editor.connection.alias).filter(
        etapa_atendimento="espera", desfecho="",
    ).update(owner=None)


class Migration(migrations.Migration):
    dependencies = [("crm", "0030_fora_de_escopo_desqualificado")]
    operations = [
        migrations.AlterField(
            model_name="lead",
            name="etapa_atendimento",
            field=models.CharField(
                blank=True, max_length=20,
                choices=[("espera", "Atendimentos em espera"), ("negociacao", "Em negociação"), ("despacho", "Despacho")],
                help_text="Coluna do Kanban pós-classificação. Qualificados (vazio) e Em espera não têm responsável; negociação e despacho atribuem o atendente. Ver services.reivindicar_lead/mover_para_negociacao/preparar_despacho/liberar_lead.",
            ),
        ),
        migrations.RunPython(liberar_espera, migrations.RunPython.noop),
    ]
