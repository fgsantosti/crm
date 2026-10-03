from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from .models import Company, Question, Lead, Event
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
