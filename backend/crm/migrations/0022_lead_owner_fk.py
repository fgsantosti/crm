import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('crm', '0021_lead_owner_texto_para_usuario'),
    ]

    operations = [
        migrations.RemoveField(model_name='lead', name='owner'),
        migrations.RenameField(model_name='lead', old_name='owner_user', new_name='owner'),
        migrations.AlterField(
            model_name='lead',
            name='owner',
            field=models.ForeignKey(blank=True, help_text='Atendente responsável. FK (não texto): trocar o nome de exibição nunca faz o atendente perder os próprios leads.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='leads_atendidos', to=settings.AUTH_USER_MODEL),
        ),
    ]
