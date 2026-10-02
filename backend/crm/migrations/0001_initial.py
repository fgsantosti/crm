import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='Company', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('name', models.CharField(max_length=160)),
            ('initial_state', models.CharField(default='INICIAL', max_length=80)),
            ('output_channel', models.CharField(choices=[('TEXTO', 'Texto'), ('AUDIO_GRAVADO', 'Áudio gravado')], default='TEXTO', max_length=20)),
            ('allow_transcription', models.BooleanField(default=False)),
            ('default_owner', models.CharField(blank=True, max_length=120)),
            ('members', models.ManyToManyField(related_name='companies', to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name='Step', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('state', models.CharField(max_length=80)),
            ('next_state', models.CharField(max_length=80)),
            ('question_id', models.CharField(max_length=80)),
            ('text', models.TextField(blank=True)),
            ('audio_asset', models.CharField(blank=True, max_length=250)),
            ('accepted_answers', models.JSONField(default=list, help_text='Respostas exatas aprovadas, normalizadas sem distinção de maiúsculas.')),
            ('terminal', models.BooleanField(default=False)),
            ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='crm.company')),
        ], options={'constraints': [models.UniqueConstraint(fields=('company', 'state'), name='unique_company_state')]}),
        migrations.CreateModel(name='Lead', fields=[
            ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ('name', models.CharField(blank=True, max_length=160)),
            ('contact', models.CharField(max_length=20)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('funnel_stage', models.CharField(default='Novo lead', max_length=40)),
            ('state', models.CharField(max_length=80)),
            ('demand', models.CharField(blank=True, max_length=300)),
            ('temperature', models.CharField(blank=True, max_length=30)),
            ('last_contact', models.DateTimeField(blank=True, null=True)),
            ('next_action', models.CharField(blank=True, max_length=250)),
            ('return_at', models.DateTimeField(blank=True, null=True)),
            ('priority', models.CharField(choices=[('Alta', 'Alta'), ('Média', 'Média'), ('Baixa', 'Baixa')], default='Média', max_length=10)),
            ('owner', models.CharField(blank=True, max_length=120)),
            ('mode', models.CharField(choices=[('AUTOMÁTICO', 'Automático'), ('HUMANO', 'Humano')], default='AUTOMÁTICO', max_length=10)),
            ('output_channel', models.CharField(choices=[('TEXTO', 'Texto'), ('AUDIO_GRAVADO', 'Áudio gravado')], default='TEXTO', max_length=20)),
            ('last_audio_id', models.CharField(blank=True, max_length=250)),
            ('bot_closed', models.BooleanField(default=False)),
            ('notes', models.TextField(blank=True)),
            ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='crm.company')),
        ], options={'ordering': ['-created_at'], 'constraints': [models.UniqueConstraint(fields=('company', 'contact'), name='unique_company_contact')]}),
        migrations.CreateModel(name='Event', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('message_id', models.CharField(max_length=160)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('summary', models.CharField(max_length=160)),
            ('result', models.JSONField(default=dict)),
            ('delivery', models.CharField(default='NOT_REQUIRED', max_length=15)),
            ('lead', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='events', to='crm.lead')),
        ], options={'ordering': ['created_at'], 'constraints': [models.UniqueConstraint(fields=('lead', 'message_id'), name='unique_lead_message')]}),
    ]
