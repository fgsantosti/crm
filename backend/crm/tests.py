from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from .models import Company, Step, Lead, Event
from .services import receive

class QualificationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Empresa A")
        self.other = Company.objects.create(name="Empresa B")
        self.user = get_user_model().objects.create_user(username="operador")
        self.company.members.add(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        Step.objects.create(company=self.company, state="INICIAL", next_state="RESPOSTA", question_id="q1", text="Qual sua demanda?")
        Step.objects.create(company=self.company, state="RESPOSTA", next_state="FIM", question_id="fim", terminal=True, accepted_answers=["consultoria"])
    def send(self, mid="1", **kwargs):
        data = {"contact": "+5585999999999", "message_id": mid, "answer": "olá", "kind": "text", "human_required": False, "reason": "pedido humano", **kwargs}
        return receive(self.company, data)
    def delivered(self, result):
        Event.objects.filter(pk=result["event_id"]).update(delivery="SENT")
    def test_duplicate_does_not_send_or_create_twice(self):
        first = self.send()
        self.assertEqual(first["action"], "TEXTO")
        self.assertEqual(self.send()["action"], "NO_REPLY")
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(Event.objects.count(), 1)
    def test_terminal_and_late_messages(self):
        self.delivered(self.send())
        self.assertEqual(self.send("2", answer="consultoria")["action"], "NO_REPLY")
        lead = Lead.objects.get()
        self.assertTrue(lead.bot_closed)
        self.assertEqual(self.send("3")["action"], "NO_REPLY")
    def test_ambiguous_does_not_advance(self):
        self.delivered(self.send())
        self.send("2", answer="talvez")
        self.assertEqual(Lead.objects.get().state, "RESPOSTA")
    def test_human_request(self):
        self.send(human_required=True)
        self.assertEqual(Lead.objects.get().mode, "HUMANO")
    def test_missing_audio(self):
        self.company.output_channel = "AUDIO_GRAVADO"
        self.company.save()
        self.assertEqual(self.send()["action"], "NO_REPLY")
        self.assertEqual(Lead.objects.get().mode, "HUMANO")
    def test_pending_delivery_blocks_progress(self):
        self.send()
        self.send("2", answer="consultoria")
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
        self.assertEqual(self.client.post(f"/api/steps/?company={self.company.pk}", {}).status_code, 403)
