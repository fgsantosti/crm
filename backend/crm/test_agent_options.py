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

    def test_classifica_na_primeira_mensagem_com_perfil_demanda_area_e_notas(self):
        result = self.send("CLASSIFICADO", contact_name="Joana WhatsApp", fields={"tema": "Desconto indevido", "notas": {"spin_situacao": 8}})
        self.assertEqual(result["action"], "NO_REPLY")
        lead = Lead.objects.get(contact=self.contact)
        self.assertEqual((lead.name, lead.demand, lead.especialidade), ("Joana WhatsApp", "Desconto indevido", "Consumidor"))
        self.assertTrue(lead.bot_closed)
        self.assertEqual(lead.temperature, "Qualificado")
        self.assertEqual(lead.urgencia_detalhe["score"], 8)
        self.assertEqual(lead.urgencia_detalhe["notas"], {"spin_situacao": 8})

    def test_classifica_no_meio_da_spin_quando_ultima_variavel_e_capturada(self):
        self.send(question_id="apresentacao", contact_name="Joana WhatsApp")
        result = self.send("ATUALIZAR", fields={"tema": "Desconto indevido", "proxima": "spin_problema", "notas": {"spin_situacao": 9}})
        self.assertEqual(result["action"], "NO_REPLY")
        lead = Lead.objects.get(contact=self.contact)
        self.assertTrue(lead.bot_closed)
        self.assertEqual(lead.temperature, "Quente")
        self.assertEqual(lead.events.latest("created_at").marker, "CLASSIFICADO")

    def test_classificacao_antecipada_sem_spin_tambem_aceita_dados_completos(self):
        self.company.etapa_inicial = False
        self.company.save()
        result = self.send("CLASSIFICADO", fields={"nome": "Joana", "tema": "Desconto", "especialidade": "Consumidor", "notas": {"spin_situacao": 8}})
        self.assertEqual(result["question_id"], "encerramento")
        self.assertTrue(Lead.objects.get(contact=self.contact).bot_closed)

    def test_pedido_humano_na_spin_nao_cria_coleta_paralela(self):
        human = Question.objects.get(company=self.company, question_id="necessidade_humana")
        human.variaveis_obrigatorias.add(VariavelRoteiro.objects.get(company=self.company, slug="nome"))
        result = self.send("ATUALIZAR", human_required=True, reason="pedido humano")
        self.assertEqual(result["question_id"], "spin_situacao")
        lead = Lead.objects.get(contact=self.contact)
        self.assertEqual(lead.mode, "AUTOMÁTICO")
        self.assertFalse(lead.pedido_humano_pendente)
        self.assertEqual(lead.demand, "")
        self.assertFalse(contexto_agente(self.company)["atendimento_humano_habilitado"])

    def test_pedidos_de_transferencia_no_meio_da_spin_preservam_triagem(self):
        self.send(question_id="apresentacao")
        for reason in ["pedido humano", "urgência ou risco", "decisão profissional"]:
            result = self.send("ATUALIZAR", human_required=True, reason=reason, fields={"proxima": "spin_problema", "tema": "Desconto"})
            lead = Lead.objects.get(contact=self.contact)
            self.assertEqual(lead.mode, "AUTOMÁTICO")
            self.assertFalse(lead.pedido_humano_pendente)
            self.assertEqual(result["question_id"], "spin_problema")

    def test_pendencia_humana_antiga_retorna_a_ultima_pergunta_spin(self):
        self.send(question_id="apresentacao")
        self.send("ATUALIZAR", fields={"proxima": "spin_problema"})
        Lead.objects.filter(contact=self.contact).update(state="necessidade_humana", pedido_humano_pendente=True, next_action="Coletar nome")
        status = self.client.get(f"/api/companies/{self.company.pk}/agente/contato/", {"contact": self.contact}).json()
        self.assertFalse(status["pedido_humano_pendente"])
        self.assertFalse(status["atendimento_humano_habilitado"])
        self.assertEqual(status["ultima_pergunta"], "spin_problema")
        self.send("ATUALIZAR", fields={"proxima": "spin_implicacao"})
        lead = Lead.objects.get(contact=self.contact)
        self.assertFalse(lead.pedido_humano_pendente)
        self.assertEqual(lead.state, "spin_implicacao")
        self.assertEqual(lead.next_action, "")

    def test_perfil_no_status_completa_nome_sem_sobrescrever_nome_informado(self):
        self.send(question_id="apresentacao", contact_name="Joana WhatsApp")
        Lead.objects.filter(contact=self.contact).update(demand="Desconto")
        url = f"/api/companies/{self.company.pk}/agente/contato/"
        status = self.client.get(url, {"contact": self.contact}).json()
        self.assertTrue(status["pode_classificar"])
        self.assertEqual(status["campos"]["nome"], "Joana WhatsApp")
        Lead.objects.filter(contact=self.contact).update(name="Joana Silva")
        status = self.client.get(url, {"contact": self.contact}).json()
        self.assertEqual(status["campos"]["nome"], "Joana Silva")

    def test_checkbox_de_envio_obrigatorio_persiste_e_so_vale_na_spin(self):
        question = self.spin[-1]
        url = f"/api/questions/{question.pk}/?company={self.company.pk}"
        response = self.client.patch(url, {"envio_obrigatorio": True}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["envio_obrigatorio"])
        item = contexto_agente(self.company)["spin"]["Consumidor"][-1]
        self.assertTrue(item["envio_obrigatorio"])
        self.assertEqual(self.client.patch(url, {"text": " "}, format="json").status_code, 400)
        fixed = Question.objects.get(company=self.company, question_id="nome")
        self.assertEqual(self.client.patch(f"/api/questions/{fixed.pk}/?company={self.company.pk}", {"envio_obrigatorio": True}, format="json").status_code, 400)
        response = self.client.patch(url, {"envio_obrigatorio": False}, format="json")
        self.assertFalse(response.json()["envio_obrigatorio"])

    def test_dados_completos_enviam_obrigatoria_antes_de_classificar_e_preservam_notas(self):
        Question.objects.filter(pk=self.spin[-1].pk).update(envio_obrigatorio=True)
        result = self.send("CLASSIFICADO", contact_name="Joana Perfil", fields={"tema": "Desconto", "notas": {"spin_situacao": 8}})
        self.assertEqual(result["question_id"], "spin_necessidade")
        lead = Lead.objects.get(contact=self.contact)
        self.assertFalse(lead.bot_closed)
        self.assertEqual(lead.demand, "Desconto")
        self.assertEqual(lead.urgencia_detalhe["notas"], {"spin_situacao": 8})
        result = self.send("CLASSIFICADO", fields={"notas": {"spin_necessidade": 8}})
        self.assertEqual(result["action"], "NO_REPLY")
        lead.refresh_from_db()
        self.assertTrue(lead.bot_closed)
        self.assertEqual(lead.temperature, "Qualificado")
        self.assertEqual(lead.urgencia_detalhe["score"], 8)
        self.assertEqual(set(lead.urgencia_detalhe["notas"]), {"spin_situacao", "spin_necessidade"})

    def test_todas_obrigatorias_sao_enviadas_em_ordem_sem_repetir_as_ja_enviadas(self):
        Question.objects.filter(pk__in=[self.spin[1].pk, self.spin[3].pk]).update(envio_obrigatorio=True)
        result = self.send("ATUALIZAR", contact_name="Joana", fields={"tema": "Desconto", "proxima": "spin_implicacao", "notas": {"spin_situacao": 8}})
        self.assertEqual(result["question_id"], "spin_problema")
        result = self.send("CLASSIFICADO", fields={"notas": {"spin_problema": 8}})
        self.assertEqual(result["question_id"], "spin_necessidade")
        self.assertFalse(Lead.objects.get(contact=self.contact).bot_closed)
        result = self.send("CLASSIFICADO", fields={"notas": {"spin_necessidade": 8}})
        self.assertEqual(result["action"], "NO_REPLY")
        self.assertTrue(Lead.objects.get(contact=self.contact).bot_closed)

    def test_status_bloqueia_classificacao_ate_entrega_da_obrigatoria(self):
        Question.objects.filter(pk=self.spin[-1].pk).update(envio_obrigatorio=True)
        result = self.send("ATUALIZAR", contact_name="Joana", fields={"tema": "Desconto", "proxima": "spin_situacao"})
        self.assertEqual(result["question_id"], "spin_necessidade")
        Event.objects.filter(pk=result["event_id"]).update(delivery="FAILED")
        url = f"/api/companies/{self.company.pk}/agente/contato/"
        status = self.client.get(url, {"contact": self.contact}).json()
        self.assertFalse(status["pode_classificar"])
        self.assertEqual(status["perguntas_obrigatorias_pendentes"], ["spin_necessidade"])
        result = self.send("CLASSIFICADO", fields={"notas": {"spin_necessidade": 8}})
        self.assertEqual(result["question_id"], "spin_necessidade")
        status = self.client.get(url, {"contact": self.contact}).json()
        self.assertEqual(status["perguntas_obrigatorias_pendentes"], [])
        self.assertTrue(status["pode_classificar"])

    def test_obrigatoria_de_outra_area_nao_bloqueia_classificacao(self):
        Question.objects.filter(company=self.company, question_id="outro_spin").update(envio_obrigatorio=True)
        result = self.send("CLASSIFICADO", contact_name="Joana", fields={"tema": "Desconto", "notas": {"spin_situacao": 8}})
        self.assertEqual(result["action"], "NO_REPLY")
        self.assertTrue(Lead.objects.get(contact=self.contact).bot_closed)

    def test_spin_apos_perguntas_fixas_tambem_respeita_envio_obrigatorio(self):
        self.company.etapa_inicial = False
        self.company.save()
        Question.objects.filter(pk=self.spin[-1].pk).update(envio_obrigatorio=True)
        result = self.send("CLASSIFICADO", fields={"nome": "Joana", "tema": "Desconto", "especialidade": "Consumidor", "notas": {"spin_situacao": 8}})
        self.assertEqual(result["question_id"], "spin_necessidade")
        self.assertFalse(Lead.objects.get(contact=self.contact).bot_closed)
        self.send("CLASSIFICADO", fields={"notas": {"spin_necessidade": 8}})
        self.assertTrue(Lead.objects.get(contact=self.contact).bot_closed)


class VariasSpinsIniciaisTests(TestCase):
    """Etapa Inicial com várias SPINs: o agente escolhe a área pela mensagem inicial, com ajuda de palavras-chave."""
    def setUp(self):
        self.company = Company.objects.create(name="Empresa Multi SPIN")
        seed_roteiro_padrao(self.company)
        self.consumidor = Area.objects.create(company=self.company, name="Consumidor", palavras_chave="desconto, benefício, INSS; empréstimo consignado, desconto, ")
        self.trabalhista = Area.objects.create(company=self.company, name="Trabalhista", palavras_chave="demitido, rescisão, FGTS")
        self.sem_spin = Area.objects.create(company=self.company, name="Criminal")
        peso = Variavel.objects.create(company=self.company, name="Geral2", peso=5)
        for area, prefixo in ((self.consumidor, "cons"), (self.trabalhista, "trab")):
            for etapa in ("situacao", "problema"):
                Question.objects.create(company=self.company, question_id=f"{prefixo}_{etapa}", area=area, etapa_spin=etapa,
                                        ordem=0 if etapa == "situacao" else 1, text=f"{prefixo} {etapa}?", variavel=peso)
        self.company.spins_iniciais.set([self.consumidor, self.trabalhista])
        Company.objects.filter(pk=self.company.pk).update(etapa_inicial=True)
        self.company.refresh_from_db()
        self.user = get_user_model().objects.create_user(username="empresa-multi", is_staff=True)
        self.company.members.add(self.user)
        self.client = APIClient(); self.client.force_authenticate(self.user)
        self.counter = 0
        self.contact = "+5585999990111"

    def send(self, marker="ATUALIZAR", **extra):
        self.counter += 1
        body = {"contact": self.contact, "message_id": f"m-{self.counter}", "marker": marker, **extra}
        r = self.client.post(f"/api/companies/{self.company.pk}/incoming/", body, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        result = r.json()
        if result.get("action") == "TEXTO":
            Event.objects.filter(pk=result["event_id"]).update(delivery="SENT")
        return result

    def test_contexto_lista_as_spins_habilitadas_com_as_palavras_chave(self):
        ctx = contexto_agente(self.company)
        self.assertIsNone(ctx["spin_inicial"])
        self.assertIsNone(ctx["pergunta_inicial"])
        self.assertEqual(ctx["perguntas"], [])
        self.assertEqual(ctx["spins_iniciais"], [
            {"area": "Consumidor", "palavras_chave": ["desconto", "benefício", "INSS", "empréstimo consignado"], "pergunta_inicial": "cons_situacao"},
            {"area": "Trabalhista", "palavras_chave": ["demitido", "rescisão", "FGTS"], "pergunta_inicial": "trab_situacao"},
        ])
        self.assertEqual(set(ctx["spin"]), {"Consumidor", "Trabalhista"})  # a SPIN de Criminal não está habilitada

    def test_primeira_mensagem_escolhe_a_area_e_recebe_a_primeira_pergunta_dela(self):
        r = self.send(fields={"especialidade": "Trabalhista", "proxima": "trab_situacao"}, contact_name="Ana")
        self.assertEqual((r["action"], r["question_id"], r["lead_novo"]), ("TEXTO", "trab_situacao", True))
        lead = Lead.objects.get()
        self.assertEqual((lead.especialidade, lead.state), ("Trabalhista", "trab_situacao"))
        # A partir daí vale só a SPIN escolhida: a próxima pergunta e o bloqueio da outra.
        self.assertEqual(self.send(fields={"proxima": "trab_problema"})["question_id"], "trab_problema")
        bloqueada = self.send(fields={"proxima": "cons_problema"})
        self.assertNotEqual(bloqueada.get("question_id"), "cons_problema")

    def test_area_nao_habilitada_ou_ausente_nao_envia_nada_e_tenta_de_novo(self):
        for campos in ({}, {"especialidade": "Criminal"}, {"especialidade": "Inventada"}):
            r = self.send(fields={**campos, "proxima": "cons_situacao"})
            self.assertEqual(r["action"], "NO_REPLY", campos)
        lead = Lead.objects.get()
        self.assertEqual((lead.especialidade, lead.desfecho), ("", ""))
        ok = self.send(fields={"especialidade": "consumidor", "proxima": "cons_situacao"})  # sem diferenciar maiúsculas
        self.assertEqual(ok["question_id"], "cons_situacao")
        self.assertEqual(Lead.objects.get().especialidade, "Consumidor")

    def test_fora_de_escopo_na_primeira_mensagem_desqualifica(self):
        r = self.send(human_required=True, reason="fora de escopo")
        self.assertEqual(r["action"], "NO_REPLY")
        lead = Lead.objects.get()
        self.assertEqual((lead.temperature, lead.desfecho, lead.bot_closed), ("Desqualificado", "desqualificado", True))
        # Número livre: a próxima mensagem abre um lead novo.
        self.assertEqual(self.send(fields={"especialidade": "Consumidor", "proxima": "cons_situacao"})["question_id"], "cons_situacao")

    def test_uma_so_spin_continua_igual_ao_comportamento_antigo(self):
        self.company.spins_iniciais.set([self.consumidor])
        self.assertEqual(contexto_agente(self.company)["spin_inicial"], "Consumidor")
        self.assertEqual(contexto_agente(self.company)["spins_iniciais"], [])
        r = self.send(fields={"proxima": "nome"})  # sem escolher área: a única SPIN vale
        self.assertEqual((r["question_id"], Lead.objects.get().especialidade), ("cons_situacao", "Consumidor"))

    def test_api_da_empresa_salva_varias_spins_e_valida(self):
        url = f"/api/companies/{self.company.pk}/"
        # Com a Etapa Inicial ligada, SPIN sem perguntas com texto é recusada.
        self.assertEqual(self.client.patch(url, {"spins_iniciais": [self.sem_spin.pk]}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"spins_iniciais": []}, format="json").status_code, 400)
        r = self.client.patch(url, {"spins_iniciais": [self.consumidor.pk, self.trabalhista.pk]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.company.refresh_from_db()
        self.assertEqual((set(self.company.spins_iniciais.values_list("name", flat=True)), self.company.spin_inicial_id), ({"Consumidor", "Trabalhista"}, None))
        r = self.client.patch(url, {"spins_iniciais": [self.trabalhista.pk]}, format="json")
        self.company.refresh_from_db()
        self.assertEqual(self.company.spin_inicial_id, self.trabalhista.pk)
        outra = Company.objects.create(name="Outra")
        area_outra = Area.objects.create(company=outra, name="X")
        self.assertEqual(self.client.patch(url, {"spins_iniciais": [area_outra.pk]}, format="json").status_code, 400)

    def test_palavras_chave_editam_pela_area_e_nome_nao_muda(self):
        r = self.client.patch(f"/api/areas/{self.consumidor.pk}/?company={self.company.pk}", {"palavras_chave": "novas, palavras"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.consumidor.refresh_from_db()
        self.assertEqual(self.consumidor.palavras_chave, "novas, palavras")
        self.assertEqual(self.client.patch(f"/api/areas/{self.consumidor.pk}/?company={self.company.pk}", {"name": "Outro"}, format="json").status_code, 400)
