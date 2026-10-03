from django.conf import settings
from django.core.mail import send_mail

def send_invite_email(invite, code):
    link = f"{settings.FRONTEND_BASE_URL}/validar-atendente/{invite.pk}"
    send_mail(
        subject=f"Convite para a equipe de {invite.company.name} — Conecta CRM",
        message=(
            f"Olá, {invite.name}!\n\n"
            f"Você foi convidado(a) para integrar a equipe de {invite.company.name} no Conecta CRM.\n\n"
            f"Código de verificação: {code}\n\n"
            f"Acesse o link abaixo e informe esse código para confirmar seu cadastro:\n{link}\n\n"
            f"Esse código expira em 15 minutos. Se você não esperava este convite, ignore este e-mail."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[invite.email],
    )

def send_email_change_code(new_email, code):
    send_mail(
        subject="Confirme a troca de e-mail — Conecta CRM",
        message=(
            f"Recebemos um pedido para trocar o e-mail da sua conta no Conecta CRM para este endereço.\n\n"
            f"Código de confirmação: {code}\n\n"
            f"Informe esse código na tela de perfil para concluir a troca. Se você não pediu essa troca, ignore este e-mail."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[new_email],
    )

def send_credentials_email(email, name, password):
    send_mail(
        subject="Suas credenciais de acesso — Conecta CRM",
        message=(
            f"Olá, {name}!\n\n"
            f"Seu cadastro foi confirmado. Use as credenciais abaixo para acessar o CRM:\n\n"
            f"E-mail: {email}\n"
            f"Senha provisória: {password}\n\n"
            f"Por segurança, você vai precisar definir uma nova senha no primeiro acesso."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
    )
