"""Converte Lead.owner (texto: nome de exibição / nome completo / username) no
usuário correspondente da MESMA empresa. Só aceita match único; texto que não
bate com ninguém (ou bate com mais de um) vira null e é logado -- o lead volta
pra 'sem responsável' em vez de cair no atendente errado."""
from django.db import migrations


def _chaves(user, display_names):
    full = f"{user.first_name} {user.last_name}".strip()
    return {k.strip().lower() for k in (display_names.get(user.pk, ""), full, user.first_name, user.username) if k and k.strip()}


def texto_para_usuario(apps, schema_editor):
    Lead = apps.get_model('crm', 'Lead')
    Company = apps.get_model('crm', 'Company')
    Profile = apps.get_model('crm', 'Profile')
    display_names = dict(Profile.objects.values_list('user_id', 'display_name'))
    nao_mapeados = []
    for company in Company.objects.all():
        membros = list(company.members.all())
        indice = {}
        for u in membros:
            for chave in _chaves(u, display_names):
                indice.setdefault(chave, set()).add(u.pk)
        for lead in Lead.objects.filter(company=company).exclude(owner=''):
            candidatos = indice.get(lead.owner.strip().lower(), set())
            if len(candidatos) == 1:
                lead.owner_user_id = next(iter(candidatos))
                lead.save(update_fields=['owner_user'])
            else:
                nao_mapeados.append((company.pk, str(lead.pk), lead.owner, len(candidatos)))
    for company_id, lead_id, texto, n in nao_mapeados:
        print(f"[0021] lead {lead_id} (empresa {company_id}): owner '{texto}' sem match único ({n} candidatos) -> sem responsável")


def usuario_para_texto(apps, schema_editor):
    Lead = apps.get_model('crm', 'Lead')
    Profile = apps.get_model('crm', 'Profile')
    display_names = dict(Profile.objects.values_list('user_id', 'display_name'))
    for lead in Lead.objects.exclude(owner_user=None).select_related('owner_user'):
        u = lead.owner_user
        lead.owner = display_names.get(u.pk) or f"{u.first_name} {u.last_name}".strip() or u.username
        lead.save(update_fields=['owner'])


class Migration(migrations.Migration):
    dependencies = [('crm', '0020_lead_owner_user')]
    operations = [migrations.RunPython(texto_para_usuario, usuario_para_texto)]
