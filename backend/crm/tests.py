from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from .models import Company, Question, Lead, Event, Area, AtendenteInvite, PasswordChangeRequired, AgentTokenExpiry
from .services import receive

class QualificationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Empresa A")
        self.other = Company.objects.create(name="Empresa B")
        self.user = get_user_model().objects.create_user(username="operador")
        self.company.members.add(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        Question.objects.create(company=self.company, question_id="apresentacao", text="Olá! Como posso ajudar?")
        Question.objects.create(company=self.company, question_id="nome", text="Qual é o seu nome?")
        Question.objects.create(company=self.company, question_id="validar", text="Posso confirmar seus dados?")
        Question.objects.create(company=self.company, question_id="encerramento", text="Perfeito, nossa equipe entra em contato.")
        for area_name in ["Previdenciário", "Consumidor", "Trabalhista", "Fora de escopo"]:
            Area.objects.create(company=self.company, name=area_name)
    def send(self, mid="1", **kwargs):
        data = {"contact": "+5585999999999", "message_id": mid, "kind": "text", "marker": "Q", "question_id": "apresentacao",
                "fields": {}, "human_required": False, "reason": "pedido humano", **kwargs}
        return receive(self.company, data)
    def delivered(self, result):
        Event.objects.filter(pk=result["event_id"]).update(delivery="SENT")
    def test_empresa_placeholder_renders_company_name(self):
        Question.objects.filter(company=self.company, question_id="apresentacao").update(
            text="Olá! Você está falando com a {empresa}."
        )
        result = self.send()
        self.assertEqual(result["content"], "Olá! Você está falando com a Empresa A.")
    def test_validar_renders_placeholders_from_collected_fields(self):
        Question.objects.filter(company=self.company, question_id="validar").update(
            text="Nome: {nome} | Área: {especialidade} | Tema: {tema}"
        )
        self.delivered(self.send())
        self.delivered(self.send("2", marker="ATUALIZAR", fields={"nome": "Maria", "especialidade": "Trabalhista", "proxima": "nome"}))
        result = self.send("3", marker="VALIDAR", fields={"tema": "Rescisão"})
        self.assertEqual(result["content"], "Nome: Maria | Área: Trabalhista | Tema: Rescisão")
    def test_placeholder_substitution_is_single_pass_not_reexpanded(self):
        # Um lead não deve conseguir encadear campos de texto livre (nome="{tema}",
        # tema="SEGREDO...") para fazer o backend reexpandir, numa passada seguinte
        # do loop de substituição, o que já tinha sido substituído no lugar de
        # {nome} — ou seja, {nome} nunca deve acabar mostrando o valor de "tema".
        Question.objects.filter(company=self.company, question_id="validar").update(
            text="Nome: {nome} | Tema: {tema}"
        )
        self.delivered(self.send())
        self.delivered(self.send("2", marker="ATUALIZAR", fields={"nome": "{tema}", "proxima": "nome"}))
        self.delivered(self.send("3", marker="ATUALIZAR", fields={"tema": "SEGREDO_NAO_DEVERIA_APARECER", "proxima": "nome"}))
        result = self.send("4", marker="VALIDAR", fields={})
        # O valor cru armazenado em lead.name ({tema} literal) é o que deve aparecer
        # no lugar de {nome} -- nunca o valor de demand (SEGREDO...) reexpandido ali.
        nome_part, tema_part = result["content"].split(" | ")
        self.assertEqual(nome_part, "Nome: {tema}")
        self.assertNotIn("SEGREDO_NAO_DEVERIA_APARECER", nome_part)
        self.assertEqual(tema_part, "Tema: SEGREDO_NAO_DEVERIA_APARECER")
        self.assertEqual(result["content"], "Nome: {tema} | Tema: SEGREDO_NAO_DEVERIA_APARECER")
    def test_duplicate_does_not_send_or_create_twice(self):
        first = self.send()
        self.assertEqual(first["action"], "TEXTO")
        self.assertEqual(self.send()["action"], "NO_REPLY")
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(Event.objects.count(), 1)
    def test_classificado_closes_and_blocks_further_messages(self):
        self.delivered(self.send())
        self.delivered(self.send("2", marker="ATUALIZAR", fields={"nome": "Maria", "proxima": "nome"}))
        self.delivered(self.send("3", marker="VALIDAR"))
        result = self.send("4", marker="CLASSIFICADO", fields={"temperatura": "Quente", "prioridade": "Alta"})
        self.assertEqual(result["action"], "TEXTO")
        self.assertEqual(result["question_id"], "encerramento")
        lead = Lead.objects.get()
        self.assertTrue(lead.bot_closed)
        self.assertEqual(lead.temperature, "Quente")
        self.assertEqual(lead.priority, "Alta")
        self.assertEqual(self.send("5")["action"], "NO_REPLY")
    def test_classificado_without_validar_is_escalated_not_closed(self):
        self.delivered(self.send())
        self.send("2", marker="CLASSIFICADO", fields={"temperatura": "Quente", "prioridade": "Alta"})
        lead = Lead.objects.get()
        self.assertFalse(lead.bot_closed)
        self.assertEqual(lead.mode, "HUMANO")
    def test_q_without_question_id_is_escalated_and_returns_200_shaped_result(self):
        result = self.send(question_id="")
        self.assertNotEqual(result.get("action"), "ERROR")
        self.assertIn("action", result)
        lead = Lead.objects.get()
        self.assertEqual(lead.mode, "HUMANO")
    def test_repetir_resends_current_question(self):
        self.delivered(self.send())
        result = self.send("2", marker="REPETIR")
        self.assertEqual(result["question_id"], "apresentacao")
        self.assertEqual(Lead.objects.get().state, "apresentacao")
    def test_atualizar_requires_proxima(self):
        self.delivered(self.send())
        self.send("2", marker="ATUALIZAR", fields={"nome": "Maria"})
        lead = Lead.objects.get()
        self.assertEqual(lead.mode, "HUMANO")
        self.assertEqual(lead.name, "Maria")
    def test_human_request(self):
        self.send(human_required=True)
        self.assertEqual(Lead.objects.get().mode, "HUMANO")
    def test_audio_without_recorded_asset_falls_back_to_text(self):
        # AGENTS.md: áudio usa o OGG/Opus aprovado "quando existir"; sem ativo gravado, cai para o texto.
        result = self.send(kind="audio")
        self.assertEqual(result["action"], "TEXTO")
        self.assertEqual(Lead.objects.get().mode, "AUTOMÁTICO")
    def test_audio_with_recorded_asset_sends_audio(self):
        Question.objects.filter(company=self.company, question_id="apresentacao").update(audio_asset="apresentacao.ogg")
        result = self.send(kind="audio")
        self.assertEqual(result["action"], "AUDIO_GRAVADO")
        self.assertEqual(result["content"], "apresentacao.ogg")
        self.assertEqual(Lead.objects.get().last_audio_id, "apresentacao.ogg")
    def test_pending_delivery_blocks_progress(self):
        self.send()
        self.send("2", marker="ATUALIZAR", fields={"nome": "Maria", "proxima": "nome"})
        self.assertEqual(Lead.objects.get().mode, "HUMANO")
    def test_tenant_isolation(self):
        self.assertEqual(self.client.get(f"/api/leads/?company={self.other.pk}").status_code, 404)
        self.assertEqual(self.client.post(f"/api/companies/{self.other.pk}/incoming/", {}).status_code, 404)
        self.assertEqual(self.client.get("/api/leads/").status_code, 404)
    def test_failed_delivery_hands_off(self):
        result = self.send()
        response = self.client.post(f"/api/companies/{self.company.pk}/delivery/", {"event_id": result["event_id"], "status": "FAILED"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Lead.objects.get().mode, "HUMANO")
    def test_unauthenticated_denied(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/companies/").status_code, 401)
    def test_staff_required_for_script_edit(self):
        self.assertEqual(self.client.post(f"/api/questions/?company={self.company.pk}", {}).status_code, 403)
    def test_company_info_tenant_isolation_and_staff_required(self):
        from .models import CompanyInfo
        CompanyInfo.objects.create(company=self.company, title="Horário", content="Seg a sex, 9h às 18h.")
        CompanyInfo.objects.create(company=self.other, title="Horário", content="24h.")
        response = self.client.get(f"/api/company-info/?company={self.company.pk}")
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(self.client.get(f"/api/company-info/?company={self.other.pk}").status_code, 404)
        self.assertEqual(self.client.post(f"/api/company-info/?company={self.company.pk}", {"title": "Endereço", "content": "Rua X, 123"}, format="json").status_code, 403)
    def test_atualizar_rejects_especialidade_not_registered_as_area(self):
        self.delivered(self.send())
        result = self.send("2", marker="ATUALIZAR", fields={"especialidade": "Área Inventada", "proxima": "nome"})
        self.assertEqual(result["action"], "NO_REPLY")
        lead = Lead.objects.get()
        self.assertEqual(lead.mode, "HUMANO")
        self.assertIn("Área desconhecida", lead.next_action)
        self.assertEqual(lead.especialidade, "")
    def test_atualizar_accepts_especialidade_registered_as_area(self):
        self.delivered(self.send())
        result = self.send("2", marker="ATUALIZAR", fields={"especialidade": "Trabalhista", "proxima": "nome"})
        self.assertEqual(result["action"], "TEXTO")
        self.assertEqual(Lead.objects.get().especialidade, "Trabalhista")
    def test_area_crud_is_tenant_isolated_and_staff_required(self):
        Area.objects.create(company=self.other, name="Área da outra empresa")
        response = self.client.get(f"/api/areas/?company={self.company.pk}")
        self.assertEqual({a["name"] for a in response.json()["results"]}, {"Previdenciário", "Consumidor", "Trabalhista", "Fora de escopo"})
        self.assertEqual(self.client.get(f"/api/areas/?company={self.other.pk}").status_code, 404)
        self.assertEqual(self.client.post(f"/api/areas/?company={self.company.pk}", {"name": "Imobiliário"}, format="json").status_code, 403)
        staff = get_user_model().objects.create_user(username="empresa-staff", is_staff=True)
        self.company.members.add(staff)
        staff_client = APIClient()
        staff_client.force_authenticate(staff)
        created = staff_client.post(f"/api/areas/?company={self.company.pk}", {"name": "Imobiliário"}, format="json")
        self.assertEqual(created.status_code, 201)
        self.assertTrue(Area.objects.filter(company=self.company, name="Imobiliário").exists())
    def test_equipe_endpoint_only_lists_atendente_role(self):
        from django.contrib.auth.models import Group
        staff = get_user_model().objects.create_user(username="empresa-staff", is_staff=True)
        atendente = get_user_model().objects.create_user(username="atendente-real", is_staff=False)
        agent_group, _ = Group.objects.get_or_create(name="agente")
        agent_user = get_user_model().objects.create_user(username="agente.empresa-a")
        agent_user.groups.add(agent_group)
        for u in (staff, atendente, agent_user):
            self.company.members.add(u)
        response = self.client.get(f"/api/companies/{self.company.pk}/equipe/")
        self.assertEqual(response.status_code, 200)
        usernames = {m["username"] for m in response.json()}
        # self.user ("operador", setUp) também é atendente real (is_staff=False) -- esperado aparecer junto.
        self.assertEqual(usernames, {"operador", "atendente-real"})
        row = next(m for m in response.json() if m["username"] == "atendente-real")
        self.assertIn("display_name", row)
        self.assertIn("avatar_url", row)
    def test_redefinir_senha_atendente_requires_empresa_and_emails_new_password(self):
        atendente = get_user_model().objects.create_user(username="atendente-x", password="senha-velha-123", email="atendente-x@example.com")
        self.company.members.add(atendente)
        denied = self.client.post(f"/api/companies/{self.company.pk}/equipe/{atendente.pk}/redefinir-senha/")
        self.assertEqual(denied.status_code, 403)
        staff = get_user_model().objects.create_user(username="empresa-staff-2", is_staff=True)
        self.company.members.add(staff)
        staff_client = APIClient()
        staff_client.force_authenticate(staff)
        ok = staff_client.post(f"/api/companies/{self.company.pk}/equipe/{atendente.pk}/redefinir-senha/")
        self.assertEqual(ok.status_code, 200)
        atendente.refresh_from_db()
        self.assertFalse(atendente.check_password("senha-velha-123"))
        self.assertTrue(PasswordChangeRequired.objects.filter(user=atendente).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Sua senha foi redefinida", mail.outbox[0].subject)
    def test_redefinir_senha_only_targets_atendente_of_same_company(self):
        other_atendente = get_user_model().objects.create_user(username="atendente-outra-empresa")
        self.other.members.add(other_atendente)
        staff = get_user_model().objects.create_user(username="empresa-staff-3", is_staff=True)
        self.company.members.add(staff)
        staff_client = APIClient()
        staff_client.force_authenticate(staff)
        resp = staff_client.post(f"/api/companies/{self.company.pk}/equipe/{other_atendente.pk}/redefinir-senha/")
        self.assertEqual(resp.status_code, 404)
    def test_desligar_atendente_removes_account(self):
        atendente = get_user_model().objects.create_user(username="atendente-demitir")
        self.company.members.add(atendente)
        staff = get_user_model().objects.create_user(username="empresa-staff-4", is_staff=True)
        self.company.members.add(staff)
        staff_client = APIClient()
        staff_client.force_authenticate(staff)
        denied = self.client.delete(f"/api/companies/{self.company.pk}/equipe/{atendente.pk}/")
        self.assertEqual(denied.status_code, 403)
        ok = staff_client.delete(f"/api/companies/{self.company.pk}/equipe/{atendente.pk}/")
        self.assertEqual(ok.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(pk=atendente.pk).exists())
    def test_desligar_atendente_cannot_target_staff_account(self):
        other_staff = get_user_model().objects.create_user(username="outro-staff", is_staff=True)
        self.company.members.add(other_staff)
        staff = get_user_model().objects.create_user(username="empresa-staff-5", is_staff=True)
        self.company.members.add(staff)
        staff_client = APIClient()
        staff_client.force_authenticate(staff)
        resp = staff_client.delete(f"/api/companies/{self.company.pk}/equipe/{other_staff.pk}/")
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(get_user_model().objects.filter(pk=other_staff.pk).exists())
    def test_convite_flow_creates_account_and_sends_credentials_email(self):
        staff = get_user_model().objects.create_user(username="empresa-staff", is_staff=True)
        self.company.members.add(staff)
        staff_client = APIClient()
        staff_client.force_authenticate(staff)
        response = staff_client.post(f"/api/convites/?company={self.company.pk}", {"name": "Novo Atendente", "email": "novo@example.com"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "pendente")
        self.assertNotIn("code", response.json())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Código de verificação", mail.outbox[0].body)
        code = mail.outbox[0].body.split("Código de verificação: ")[1].split("\n")[0]
        invite = AtendenteInvite.objects.get(email="novo@example.com")

        wrong = self.client.post(f"/api/convites/{invite.pk}/validar/", {"code": "000000"}, format="json")
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(AtendenteInvite.objects.get(pk=invite.pk).attempts, 1)

        ok = self.client.post(f"/api/convites/{invite.pk}/validar/", {"code": code}, format="json")
        self.assertEqual(ok.status_code, 200)
        new_user = get_user_model().objects.get(username="novo@example.com")
        self.assertTrue(self.company.members.filter(pk=new_user.pk).exists())
        self.assertTrue(PasswordChangeRequired.objects.filter(user=new_user).exists())
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Senha provisória", mail.outbox[1].body)
        # Link de uso único: o convite some do banco assim que validado, não fica só marcado.
        self.assertFalse(AtendenteInvite.objects.filter(pk=invite.pk).exists())

        again = self.client.post(f"/api/convites/{invite.pk}/validar/", {"code": code}, format="json")
        self.assertEqual(again.status_code, 400)
    def test_convite_validar_blocks_after_max_attempts(self):
        staff = get_user_model().objects.create_user(username="empresa-staff", is_staff=True)
        self.company.members.add(staff)
        staff_client = APIClient()
        staff_client.force_authenticate(staff)
        staff_client.post(f"/api/convites/?company={self.company.pk}", {"name": "X", "email": "x@example.com"}, format="json")
        invite = AtendenteInvite.objects.get(email="x@example.com")
        for _ in range(5):
            self.client.post(f"/api/convites/{invite.pk}/validar/", {"code": "000000"}, format="json")
        blocked = self.client.post(f"/api/convites/{invite.pk}/validar/", {"code": "000000"}, format="json")
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("tentativas", blocked.json()["detail"])
    def test_me_reports_must_change_password_and_trocar_senha_clears_it(self):
        user = get_user_model().objects.create_user(username="pendente@example.com", password="provisoria-123")
        PasswordChangeRequired.objects.create(user=user)
        pending_client = APIClient()
        pending_client.force_authenticate(user)
        self.assertTrue(pending_client.get("/api/me/").json()["must_change_password"])
        wrong_current = pending_client.post("/api/trocar-senha/", {"current_password": "errada", "password": "nova-senha-forte-123"}, format="json")
        self.assertEqual(wrong_current.status_code, 400)
        resp = pending_client.post("/api/trocar-senha/", {"current_password": "provisoria-123", "password": "nova-senha-forte-123"}, format="json")
        self.assertEqual(resp.status_code, 200)
        # force_authenticate reaproveita o mesmo objeto Python entre chamadas do
        # teste, e o Django cacheia a relação reversa OneToOne no primeiro acesso
        # -- numa requisição real isso nunca acontece (TokenAuthentication busca
        # um User novo do banco a cada request). Buscamos de novo pra simular isso.
        user.refresh_from_db()
        self.assertTrue(user.check_password("nova-senha-forte-123"))
        pending_client.force_authenticate(user)
        self.assertFalse(pending_client.get("/api/me/").json()["must_change_password"])
    def test_me_patch_updates_display_name(self):
        resp = self.client.patch("/api/me/", {"display_name": "Operador Teste"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["display_name"], "Operador Teste")
        self.assertEqual(self.client.get("/api/me/").json()["display_name"], "Operador Teste")
    def test_trocar_email_requires_code_sent_to_new_address(self):
        user = get_user_model().objects.create_user(username="dono-conta", password="senha-atual-123", email="antigo@example.com")
        c = APIClient()
        c.force_authenticate(user)
        resp = c.post("/api/me/email/", {"email": "novo@example.com"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Código de confirmação", mail.outbox[0].body)
        code = mail.outbox[0].body.split("Código de confirmação: ")[1].split("\n")[0]

        wrong = c.post("/api/me/email/confirmar/", {"code": "000000"}, format="json")
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(get_user_model().objects.get(pk=user.pk).email, "antigo@example.com")

        ok = c.post("/api/me/email/confirmar/", {"code": code}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(get_user_model().objects.get(pk=user.pk).email, "novo@example.com")
    def test_trocar_email_rejects_address_already_in_use(self):
        get_user_model().objects.create_user(username="ja-existe", email="ocupado@example.com")
        user = get_user_model().objects.create_user(username="dono-conta-2", password="x", email="meu@example.com")
        c = APIClient()
        c.force_authenticate(user)
        resp = c.post("/api/me/email/", {"email": "ocupado@example.com"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)
    def test_excluir_conta_requires_correct_password(self):
        user = get_user_model().objects.create_user(username="quer-sair", password="senha-certa-123")
        c = APIClient()
        c.force_authenticate(user)
        denied = c.delete("/api/me/excluir/", {"password": "senha-errada"}, format="json")
        self.assertEqual(denied.status_code, 400)
        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
        ok = c.delete("/api/me/excluir/", {"password": "senha-certa-123"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(pk=user.pk).exists())
    def test_login_returns_access_in_body_and_refresh_only_as_httponly_cookie(self):
        get_user_model().objects.create_user(username="login-jwt", password="senha-forte-123")
        anon_client = APIClient()
        login_resp = anon_client.post("/api/login/", {"username": "login-jwt", "password": "senha-forte-123"}, format="json")
        self.assertEqual(login_resp.status_code, 200)
        body = login_resp.json()
        self.assertIn("access", body)
        self.assertNotIn("refresh", body)
        cookie = login_resp.cookies.get("refresh_token")
        self.assertIsNotNone(cookie)
        self.assertTrue(cookie["httponly"])
        self.assertTrue(cookie["secure"])
        # O cookie já fica no cookiejar do client; /login/refresh/ não recebe nada no corpo.
        refresh_resp = anon_client.post("/api/login/refresh/")
        self.assertEqual(refresh_resp.status_code, 200)
        self.assertIn("access", refresh_resp.json())
    def test_refresh_without_cookie_is_rejected(self):
        anon_client = APIClient()
        resp = anon_client.post("/api/login/refresh/")
        self.assertEqual(resp.status_code, 401)
    def test_logout_blacklists_refresh_token_and_clears_cookie(self):
        get_user_model().objects.create_user(username="logout-jwt", password="senha-forte-123")
        anon_client = APIClient()
        anon_client.force_authenticate(self.user)  # só pra satisfazer IsAuthenticated de /api/logout/
        login_resp = anon_client.post("/api/login/", {"username": "logout-jwt", "password": "senha-forte-123"}, format="json")
        self.assertIn("refresh_token", login_resp.cookies)
        logout_resp = anon_client.post("/api/logout/")
        self.assertEqual(logout_resp.status_code, 200)
        self.assertEqual(logout_resp.cookies["refresh_token"].value, "")
        blocked = anon_client.post("/api/login/refresh/")
        self.assertEqual(blocked.status_code, 401)
    def test_agent_token_without_expiry_row_never_expires(self):
        from rest_framework.authtoken.models import Token
        agent_user = get_user_model().objects.create_user(username="agente.sem-validade")
        self.company.members.add(agent_user)
        token = Token.objects.create(user=agent_user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = client.post(
            f"/api/companies/{self.company.pk}/incoming/",
            {"contact": "+5585999110022", "message_id": "m1", "kind": "text", "marker": "Q", "question_id": "apresentacao", "fields": {}, "human_required": False, "reason": "pedido humano"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
    def test_agent_token_with_future_expiry_works(self):
        from rest_framework.authtoken.models import Token
        agent_user = get_user_model().objects.create_user(username="agente.valido")
        self.company.members.add(agent_user)
        token = Token.objects.create(user=agent_user)
        AgentTokenExpiry.objects.create(token=token, expires_at=timezone.now() + timedelta(days=30))
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = client.post(
            f"/api/companies/{self.company.pk}/incoming/",
            {"contact": "+5585999110023", "message_id": "m1", "kind": "text", "marker": "Q", "question_id": "apresentacao", "fields": {}, "human_required": False, "reason": "pedido humano"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
    def test_agent_token_past_expiry_is_rejected(self):
        from rest_framework.authtoken.models import Token
        agent_user = get_user_model().objects.create_user(username="agente.expirado")
        self.company.members.add(agent_user)
        token = Token.objects.create(user=agent_user)
        AgentTokenExpiry.objects.create(token=token, expires_at=timezone.now() - timedelta(days=1))
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = client.post(
            f"/api/companies/{self.company.pk}/incoming/",
            {"contact": "+5585999110024", "message_id": "m1", "kind": "text", "marker": "Q", "question_id": "apresentacao", "fields": {}, "human_required": False, "reason": "pedido humano"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)
    def test_agent_service_account_is_restricted_to_incoming_and_delivery(self):
        from django.contrib.auth.models import Group
        agent_group, _ = Group.objects.get_or_create(name="agente")
        agent_user = get_user_model().objects.create_user(username="agente.empresa-a")
        agent_user.groups.add(agent_group)
        self.company.members.add(agent_user)
        agent_client = APIClient()
        agent_client.force_authenticate(agent_user)
        self.assertEqual(agent_client.get(f"/api/leads/?company={self.company.pk}").status_code, 403)
        self.assertEqual(agent_client.post(f"/api/questions/?company={self.company.pk}", {}).status_code, 403)
        incoming_response = agent_client.post(
            f"/api/companies/{self.company.pk}/incoming/",
            {"contact": "+5585999999998", "message_id": "agent-1", "kind": "text", "marker": "Q", "question_id": "apresentacao", "fields": {}, "human_required": False, "reason": "pedido humano"},
            format="json",
        )
        self.assertEqual(incoming_response.status_code, 200)
        self.assertEqual(incoming_response.json()["action"], "TEXTO")
    def test_api_login_does_not_403_with_active_django_session(self):
        # Reproduz o bug real de produção: um usuário logado no /admin/ (sessão
        # Django ativa no navegador) que também chama /api/login/ não pode ser
        # bloqueado por exigência de CSRF -- o frontend só usa token, nunca
        # sessão, então SessionAuthentication nunca deveria entrar em jogo aqui.
        user = get_user_model().objects.create_user(username="empresa-teste", password="senha-123", is_staff=True)
        client = Client(enforce_csrf_checks=True)
        self.assertTrue(client.login(username="empresa-teste", password="senha-123"))
        response = client.post("/api/login/", {"username": "empresa-teste", "password": "senha-123"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
    def test_me_reflects_real_staff_flag(self):
        response = self.client.get("/api/me/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["username"], "operador")
        self.assertFalse(body["is_staff"])
        self.assertFalse(body["is_superuser"])
        self.assertFalse(body["is_agent"])
        self.user.is_staff = True
        self.user.save()
        self.assertTrue(self.client.get("/api/me/").json()["is_staff"])
    def test_me_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/me/").status_code, 401)
    def test_agent_service_account_can_read_but_not_write_company_info(self):
        from django.contrib.auth.models import Group
        from .models import CompanyInfo
        CompanyInfo.objects.create(company=self.company, title="Horário", content="Seg a sex, 9h às 18h.")
        agent_group, _ = Group.objects.get_or_create(name="agente")
        agent_user = get_user_model().objects.create_user(username="agente.empresa-b")
        agent_user.groups.add(agent_group)
        self.company.members.add(agent_user)
        agent_client = APIClient()
        agent_client.force_authenticate(agent_user)
        read_response = agent_client.get(f"/api/company-info/?company={self.company.pk}")
        self.assertEqual(read_response.status_code, 200)
        self.assertEqual(len(read_response.json()["results"]), 1)
        self.assertEqual(
            agent_client.post(f"/api/company-info/?company={self.company.pk}", {"title": "x", "content": "y"}, format="json").status_code,
            403,
        )
