from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Area, Company, Event, Lead, Question, Variavel, VariavelRoteiro
from .services import contexto_agente, seed_roteiro_padrao


class AgentOptionsTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Empresa SPIN")
        seed_roteiro_padrao(self.company)
        self.area = Area.objects.create(company=self.company, name="Consumidor")
        self.other_area = Area.objects.create(company=self.company, name="Trabalhista")
        self.variable = VariavelRoteiro.objects.create(company=self.company, name="Renda", slug="renda")
        self.spin = []
        for index, stage in enumerate(["situacao", "problema", "implicacao", "necessidade"]):
            weight = Variavel.objects.create(company=self.company, name=stage, peso=(index + 1) * 2)
            self.spin.append(Question.objects.create(
                company=self.company, question_id=f"spin_{stage}", area=self.area,
                etapa_spin=stage, ordem=4 - index, text=f"Pergunta de {stage}?",
                variavel=weight, variavel_roteiro=self.variable if stage == "implicacao" else None,
            ))
        Question.objects.create(company=self.company, question_id="outro_spin", area=self.other_area, text="Outra SPIN?", variavel=weight)
        Question.objects.filter(company=self.company, question_id="nome").update(text="Qual seu nome?")
        Question.objects.filter(company=self.company, question_id="apresentacao").update(text="Olá!")
        Question.objects.filter(company=self.company, question_id="empresa").update(text="Sobre a empresa")
        Question.objects.filter(company=self.company, question_id="validar").update(text="Confirma?")
        Question.objects.filter(company=self.company, question_id="encerramento").update(text="Até logo!")
        self.company.spin_inicial = self.area
        self.company.etapa_inicial = True
        self.company.save()
        self.user = get_user_model().objects.create_user(username="empresa-spin", is_staff=True)
        self.company.members.add(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.counter = 0
        self.contact = "+5585999999999"

    def send(self, marker="Q", **extra):
        self.counter += 1
        body = {"contact": self.contact, "message_id": f"msg-{self.counter}", "marker": marker, **extra}
        response = self.client.post(f"/api/companies/{self.company.pk}/incoming/", body, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()
        if result.get("action") == "TEXTO":
            Event.objects.filter(pk=result["event_id"]).update(delivery="SENT")
        return result

    def finish_questions(self):
        self.send(question_id="apresentacao", contact_name="Joana WhatsApp")
        for question in self.spin[1:]:
            self.send("ATUALIZAR", fields={"proxima": question.question_id})

    def test_primeira_mensagem_inicia_spin_e_preserva_variaveis_reconhecidas(self):
        result = self.send("ATUALIZAR", fields={"proxima": "nome", "tema": "Desconto indevido", "variaveis_roteiro": {"renda": "R$ 2.000", "inventada": "x"}}, contact_name="Joana WhatsApp")
        self.assertEqual(result["question_id"], "spin_situacao")
        self.assertEqual(result["content"], self.spin[0].text)
        lead = Lead.objects.get(contact=self.contact)
        self.assertEqual((lead.especialidade, lead.name, lead.contact_name), ("Consumidor", "", "Joana WhatsApp"))
        self.assertEqual((lead.demand, lead.variaveis_roteiro), ("Desconto indevido", {"renda": "R$ 2.000"}))
        status = self.client.get(f"/api/companies/{self.company.pk}/agente/contato/", {"contact": self.contact}).json()
        self.assertEqual(status["campos"]["tema"], "Desconto indevido")
        self.assertEqual(status["variaveis_roteiro"], {"renda": "R$ 2.000"})

    def test_contexto_expoe_apenas_spin_selecionada_na_ordem_das_etapas(self):
        context = contexto_agente(self.company)
        self.assertEqual(context["perguntas"], [])
        self.assertEqual(context["fora_do_fluxo"], [])
        self.assertEqual(list(context["spin"]), ["Consumidor"])
        self.assertEqual([q["question_id"] for q in context["spin"]["Consumidor"]], [q.question_id for q in self.spin])
        self.assertEqual(context["pergunta_inicial"], "spin_situacao")
        self.assertFalse(context["validar_habilitado"])

    def test_bloqueia_textos_fixas_outra_spin_pulos_e_regressoes(self):
        self.send(question_id="apresentacao")
        for question_id in ["apresentacao", "empresa", "nome", "outro_spin", "spin_necessidade"]:
            result = self.send("ATUALIZAR", fields={"proxima": question_id})
            self.assertEqual(result["action"], "NO_REPLY", question_id)
            self.assertEqual(Lead.objects.get(contact=self.contact).state, "spin_situacao")
        self.send("ATUALIZAR", fields={"proxima": "spin_problema"})
        result = self.send(question_id="spin_situacao")
        self.assertEqual(result["action"], "NO_REPLY")
        self.assertEqual(Lead.objects.get(contact=self.contact).state, "spin_problema")

    def test_repeticao_mantem_texto_literal_e_classificacao_antecipada_nao_fecha(self):
        self.send(question_id="apresentacao")
        result = self.send("REPETIR")
        self.assertEqual(result["content"], self.spin[0].text)
        result = self.send("CLASSIFICADO", fields={"notas": {"spin_situacao": 8}})
        self.assertEqual(result["action"], "NO_REPLY")
        self.assertFalse(Lead.objects.get(contact=self.contact).bot_closed)

    def test_classifica_sem_validacao_pelos_pesos_e_nome_do_perfil(self):
        self.finish_questions()
        self.assertEqual(self.send("VALIDAR", fields={"tema": "Desconto"})["action"], "NO_REPLY")
        result = self.send("CLASSIFICADO", fields={"notas": {**{q.question_id: 8 for q in self.spin}, "outro_spin": 0, "nome": 0}, "variaveis_roteiro": {"renda": "2.000"}})
        self.assertEqual(result["action"], "NO_REPLY")
        lead = Lead.objects.get(contact=self.contact)
        self.assertTrue(lead.bot_closed)
        self.assertEqual((lead.name, lead.temperature), ("Joana WhatsApp", "Qualificado"))
        self.assertEqual(lead.urgencia_detalhe["score"], 8)
        self.assertEqual(set(lead.urgencia_detalhe["notas"]), {q.question_id for q in self.spin})
        self.assertEqual(lead.variaveis_roteiro, {"renda": "2.000"})
        self.assertEqual(self.send(question_id="apresentacao")["action"], "NO_REPLY")

    def test_nome_informado_prevalece_sobre_nome_do_perfil(self):
        self.finish_questions()
        self.send("CLASSIFICADO", contact_name="Outro nome do perfil", fields={"nome": "Joana Silva", "notas": {q.question_id: 8 for q in self.spin}})
        self.assertEqual(Lead.objects.get(contact=self.contact).name, "Joana Silva")

    def test_notas_omitidas_recebem_zero_na_media_spin(self):
        self.finish_questions()
        self.send("CLASSIFICADO", fields={"notas": {"spin_necessidade": 10}})
        lead = Lead.objects.get(contact=self.contact)
        self.assertEqual(lead.urgencia_detalhe["score"], 4)
        self.assertEqual(lead.temperature, "Desconfiado")

    def test_checkbox_envio_e_pulo_da_apresentacao_persistem_pela_api(self):
        self.company.etapa_inicial = False
        self.company.save()
        for qid in ["apresentacao", "empresa", "validar", "encerramento"]:
            question = Question.objects.get(company=self.company, question_id=qid)
            response = self.client.patch(f"/api/questions/{question.pk}/?company={self.company.pk}", {"habilitada": False}, format="json")
            self.assertEqual(response.status_code, 200, response.content)
            self.assertFalse(response.json()["habilitada"])
        self.assertEqual(self.send(question_id="apresentacao")["question_id"], "nome")
        self.assertEqual(self.send(question_id="empresa")["action"], "NO_REPLY")
        self.assertEqual(Lead.objects.get(contact=self.contact).state, "nome")
        self.send("CLASSIFICADO", fields={"nome": "Joana", "temperatura": "Qualificado", "prioridade": "Média"})
        self.assertTrue(Lead.objects.get(contact=self.contact).bot_closed)
        self.assertEqual(contexto_agente(self.company)["fora_do_fluxo"][0]["question_id"], "necessidade_humana")

    def test_checkbox_humana_desabilitada_preserva_coleta_obrigatoria(self):
        self.company.etapa_inicial = False
        self.company.save()
        human = Question.objects.get(company=self.company, question_id="necessidade_humana")
        human.habilitada = False
        human.save()
        human.variaveis_obrigatorias.add(VariavelRoteiro.objects.get(company=self.company, slug="nome"))
        result = self.send("ATUALIZAR", human_required=True, reason="pedido humano")
        self.assertEqual(result["question_id"], "nome")
        self.send("ATUALIZAR", fields={"nome": "Joana"})
        self.assertEqual(Lead.objects.get(contact=self.contact).mode, "HUMANO")

    def test_configuracao_inicial_valida_empresa_e_perguntas(self):
        url = f"/api/companies/{self.company.pk}/"
        other = Company.objects.create(name="Outra empresa")
        foreign = Area.objects.create(company=other, name="Outra área")
        empty = Area.objects.create(company=self.company, name="Sem perguntas")
        for area in [foreign, empty]:
            self.assertEqual(self.client.patch(url, {"spin_inicial": area.pk}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"etapa_inicial": True, "spin_inicial": self.area.pk}, format="json").status_code, 200)
        saved = self.client.get(url).json()
        self.assertEqual((saved["etapa_inicial"], saved["spin_inicial"]), (True, self.area.pk))
        self.assertEqual(self.client.patch(url, {"etapa_inicial": False}, format="json").status_code, 200)

    def test_nome_do_perfil_tambem_e_fallback_no_fluxo_normal(self):
        self.company.etapa_inicial = False
        self.company.save()
        self.send(question_id="apresentacao", contact_name="Joana WhatsApp")
        self.send("VALIDAR")
        self.send("CLASSIFICADO", fields={"temperatura": "Qualificado", "prioridade": "Média"})
        self.assertEqual(Lead.objects.get(contact=self.contact).name, "Joana WhatsApp")
