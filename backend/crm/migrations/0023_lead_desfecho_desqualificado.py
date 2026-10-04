from django.db import migrations, models

FORA_DO_KANBAN = ["Desqualificado", "Desconfiado"]


def encerrar_desqualificados_presos(apps, schema_editor):
    """Leads Desqualificado/Desconfiado já classificados e nunca assumidos por humano
    ficavam com desfecho vazio pra sempre -- e com isso o número nunca podia abrir
    lead novo. Fecha esses com o desfecho automático."""
    Lead = apps.get_model('crm', 'Lead')
    for lead in Lead.objects.filter(desfecho='', bot_closed=True, temperature__in=FORA_DO_KANBAN, origem_manual=False).exclude(mode='HUMANO'):
        lead.desfecho = 'desqualificado'
        lead.concluido_em = lead.last_contact or lead.created_at
        lead.save(update_fields=['desfecho', 'concluido_em'])


class Migration(migrations.Migration):
    dependencies = [('crm', '0022_lead_owner_fk')]

    operations = [
        migrations.AlterField(
            model_name='lead',
            name='desfecho',
            field=models.CharField(blank=True, choices=[('encerrado', 'Encerrado'), ('comprometido', 'Comprometido'), ('falha', 'Falha durante o atendimento'), ('desqualificado', 'Desqualificado na triagem')], help_text='Definitivo: setado ao despachar (services.enviar_despachos) ou automaticamente ao classificar como Desqualificado/Desconfiado. Lead some do Kanban quando preenchido.', max_length=20),
        ),
        migrations.AlterField(
            model_name='lead',
            name='desfecho_pendente',
            field=models.CharField(blank=True, choices=[('encerrado', 'Encerrado'), ('comprometido', 'Comprometido'), ('falha', 'Falha durante o atendimento'), ('desqualificado', 'Desqualificado na triagem')], help_text="Desfecho escolhido ao arrastar pra 'Despacho', mas ainda NÃO definitivo -- só vira Lead.desfecho (e some do Kanban) quando o owner clica 'Enviar Despachos' (services.enviar_despachos).", max_length=20),
        ),
        migrations.AddField(
            model_name='lead',
            name='concluido_em',
            field=models.DateTimeField(blank=True, help_text='Quando o desfecho virou definitivo.', null=True),
        ),
        migrations.RunPython(encerrar_desqualificados_presos, migrations.RunPython.noop),
    ]
