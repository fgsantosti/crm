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
    def test_validar_renders_placeholders_from_collected_fields(self):
        Question.objects.filter(company=self.company, question_id="validar").update(
            text="Nome: {nome} | Área: {especialidade} | Tema: {tema}"
        )
        self.delivered(self.send())
        self.delivered(self.send("2", marker="ATUALIZAR", fields={"nome": "Maria", "especialidade": "Trabalhista", "proxima": "nome"}))
        result = self.send("3", marker="VALIDAR", fields={"tema": "Rescisão"})
        self.assertEqual(result["content"], "Nome: Maria | Área: Trabalhista | Tema: Rescisão")
    def test_duplicate_does_not_send_or_create_twice(self):
        first = self.send()
        self.assertEqual(first["action"], "TEXTO")
        self.assertEqual(self.send()["action"], "NO_REPLY")
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(Event.objects.count(), 1)
    def test_classificado_closes_and_blocks_further_messages(self):
        self.delivered(self.send())
        self.delivered(self.send("2", marker="ATUALIZAR", fields={"nome": "Maria", "proxima": "nome"}))
        result = self.send("3", marker="CLASSIFICADO", fields={"temperatura": "Quente", "prioridade": "Alta"})
        self.assertEqual(result["action"], "TEXTO")
        self.assertEqual(result["question_id"], "encerramento")
        lead = Lead.objects.get()
        self.assertTrue(lead.bot_closed)
        self.assertEqual(lead.temperature, "Quente")
        self.assertEqual(lead.priority, "Alta")
        self.assertEqual(self.send("4")["action"], "NO_REPLY")
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
