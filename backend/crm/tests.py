from datetime import datetime, timedelta
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from .models import Blacklist, Company, Question, Lead, Event, Area, AtendenteInvite, PasswordChangeRequired, AgentTokenExpiry, CompanyInfo, Variavel, VariavelRoteiro
from .services import receive, status_contato, contexto_agente, seed_roteiro_padrao

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
    def assertTriagemReiniciada(self, result):
        # Erro do agente / triagem travada: nunca vai pra equipe -- lead apagado, número livre.
        self.assertEqual(result["action"], "NO_REPLY")
        self.assertTrue(result.get("lead_apagado"))
        self.assertEqual(Lead.objects.filter(contact="+5585999999999").count(), 0)
    def test_classificado_without_validar_reinicia_triagem(self):
        self.delivered(self.send())
        r = self.send("2", marker="CLASSIFICADO", fields={"temperatura": "Quente", "prioridade": "Alta"})
        self.assertTriagemReiniciada(r)
    def test_q_without_question_id_reinicia_triagem(self):
        # Lead novo sempre começa pela apresentação; o Q sem id num lead já existente reinicia.
        self.delivered(self.send())
        result = self.send("2", question_id="")
        self.assertTriagemReiniciada(result)
    def test_repetir_resends_current_question(self):
        self.delivered(self.send())
        result = self.send("2", marker="REPETIR")
        self.assertEqual(result["question_id"], "apresentacao")
        self.assertEqual(result["content"], "Por favor, responda novamente. Olá! Como posso ajudar?")
        self.assertEqual(Lead.objects.get().state, "apresentacao")
    def test_q_repetido_tambem_inclui_prefixo(self):
        self.delivered(self.send())
        result = self.send("2", marker="Q", question_id="apresentacao")
        self.assertEqual(result["content"], "Por favor, responda novamente. Olá! Como posso ajudar?")
    def test_atualizar_requires_proxima(self):
        self.delivered(self.send())
        self.assertTriagemReiniciada(self.send("2", marker="ATUALIZAR", fields={"nome": "Maria"}))
    def test_human_request(self):
        self.send(human_required=True)
        self.assertEqual(Lead.objects.get().mode, "HUMANO")
    def test_audio_without_recorded_asset_falls_back_to_text(self):
        # AGENTS.md: áudio usa o OGG/Opus aprovado "quando existir"; sem ativo gravado, cai para o texto.
        result = self.send(kind="audio")
        self.assertEqual(result["action"], "TEXTO")
        self.assertEqual(Lead.objects.get().mode, "AUTOMÁTICO")
    def test_pending_delivery_recente_ignora_sem_escalar(self):
        # Contato manda várias mensagens seguidas enquanto a resposta anterior sai: ignora, não trava.
        self.send()
        result = self.send("2", marker="ATUALIZAR", fields={"nome": "Maria", "proxima": "nome"})
        self.assertEqual(result["action"], "NO_REPLY")
        lead = Lead.objects.get()
        self.assertEqual(lead.mode, "AUTOMÁTICO")
        self.assertEqual(lead.state, "apresentacao")
    def test_pending_delivery_antiga_expira_e_processa(self):
        first = self.send()
        Event.objects.filter(pk=first["event_id"]).update(created_at=timezone.now() - timedelta(seconds=120))
        result = self.send("2", marker="ATUALIZAR", fields={"nome": "Maria", "proxima": "nome"})
        self.assertEqual(result["action"], "TEXTO")
        self.assertEqual(result["question_id"], "nome")
        self.assertEqual(Event.objects.get(pk=first["event_id"]).delivery, "EXPIRADO")
        self.assertEqual(Lead.objects.get().mode, "AUTOMÁTICO")
    def test_repetir_conta_e_desqualifica_na_quarta(self):
        from .services import status_contato
        self.delivered(self.send())
        for i in range(3):
            r = self.send(f"r{i}", marker="REPETIR")
            self.assertEqual(r["action"], "TEXTO")
            self.assertEqual(r["content"].count("Por favor, responda novamente."), 1)
            self.delivered(r)
        self.assertEqual(status_contato(self.company, "+5585999999999")["repeticoes"], 3)
        r = self.send("r3", marker="REPETIR")
        self.assertEqual(r["action"], "NO_REPLY")
        self.assertFalse(r.get("lead_apagado"))
        lead = Lead.objects.get()
        self.assertEqual((lead.temperature, lead.desfecho, lead.bot_closed), ("Desqualificado", "desqualificado", True))
        self.assertEqual(lead.urgencia_detalhe["motivo"], "sem_resposta")
        # Número liberado: a próxima mensagem abre um lead novo, pela apresentação.
        r = self.send("r4", marker="REPETIR")
        self.assertEqual((r["action"], r["question_id"], r["lead_novo"]), ("TEXTO", "apresentacao", True))
        self.assertEqual(Lead.objects.filter(contact="+5585999999999").count(), 2)
    def test_repeticoes_por_pergunta_nao_acumulam(self):
        # 3 repetições na 1ª pergunta, avanço, 3 na seguinte: ninguém é desqualificado.
        self.delivered(self.send())
        for i in range(3):
            self.delivered(self.send(f"a{i}", marker="REPETIR"))
        self.delivered(self.send("av", marker="ATUALIZAR", fields={"proxima": "nome"}))
        for i in range(3):
            r = self.send(f"b{i}", marker="REPETIR")
            self.assertEqual(r["action"], "TEXTO")
            self.delivered(r)
        self.assertEqual(Lead.objects.get().desfecho, "")
    def test_repeticoes_zera_com_marcador_de_avanco(self):
        from .services import status_contato
        self.delivered(self.send())
        self.delivered(self.send("r1", marker="REPETIR"))
        self.delivered(self.send("a1", marker="ATUALIZAR", fields={"proxima": "nome"}))
        self.assertEqual(status_contato(self.company, "+5585999999999")["repeticoes"], 0)
        self.assertEqual(status_contato(self.company, "+5500000000001")["repeticoes"], 0)
    def test_atualizar_para_a_mesma_pergunta_conta_como_repeticao(self):
        from .services import status_contato
        self.delivered(self.send())
        self.delivered(self.send("a0", marker="ATUALIZAR", fields={"proxima": "nome"}))
        for i in range(3):
            r = self.send(f"a{i + 1}", marker="ATUALIZAR", fields={"proxima": "nome"})
            self.assertEqual(r["question_id"], "nome")
            self.assertEqual(r["content"], "Por favor, responda novamente. Qual é o seu nome?")
            self.delivered(r)
        self.assertEqual(status_contato(self.company, "+5585999999999")["repeticoes"], 3)
        r = self.send("a4", marker="ATUALIZAR", fields={"proxima": "nome"})
        self.assertEqual(r["action"], "NO_REPLY")
        self.assertEqual(Lead.objects.get().desfecho, "desqualificado")
    def test_repetir_na_validacao_reenvia_validar(self):
        self.delivered(self.send())
        self.delivered(self.send("v1", marker="VALIDAR", fields={"nome": "Ana"}))
        r = self.send("v2", marker="REPETIR")
        self.assertEqual(r["action"], "TEXTO")
        self.assertEqual(r["question_id"], "validar")
        self.assertEqual(r["content"], "Por favor, responda novamente. Posso confirmar seus dados?")
        self.assertEqual(Lead.objects.get().mode, "AUTOMÁTICO")
    def _peso_em_nome(self, peso=9):
        v = Variavel.objects.create(company=self.company, name="Urgência", peso=peso)
        Question.objects.filter(company=self.company, question_id="nome").update(variavel=v)
    def test_encerramento_antecipado_com_notas_parciais(self):
        self._peso_em_nome()
        self.delivered(self.send())
        self.delivered(self.send("2", marker="ATUALIZAR", fields={"proxima": "nome"}))
        r = self.send("3", marker="CLASSIFICADO", fields={"encerramento_antecipado": True, "notas": {"nome": 9.5, "inexistente": 2}})
        self.assertTriagemReiniciada(r)
    def test_encerramento_antecipado_sem_notas_remove_triagem(self):
        self.delivered(self.send())
        r = self.send("2", marker="CLASSIFICADO", fields={"encerramento_antecipado": True})
        self.assertTriagemReiniciada(r)
    def test_encerramento_antecipado_pela_api_aceita_sem_notas(self):
        token_user = get_user_model().objects.create_user(username="agente-x")
        self.company.members.add(token_user)
        c = APIClient(); c.force_authenticate(token_user)
        base = f"/api/companies/{self.company.pk}/incoming/"
        payload = {"contact": "+5585911112222", "message_id": "m1", "marker": "Q", "question_id": "apresentacao"}
        r1 = c.post(base, payload, format="json").json()
        Event.objects.filter(pk=r1["event_id"]).update(delivery="SENT")
        r2 = c.post(base, {**payload, "message_id": "m2", "marker": "CLASSIFICADO", "fields": {"encerramento_antecipado": True}}, format="json")
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json()["lead_apagado"])
        self.assertFalse(Lead.objects.filter(contact="+5585911112222").exists())
        r3 = c.post(base, {**payload, "message_id": "m3", "marker": "CLASSIFICADO", "fields": {}}, format="json")
        self.assertEqual(r3.status_code, 400)
    def test_triagem_abandonada_e_apagada_e_e_idempotente(self):
        from .services import apagar_triagens_abandonadas
        self.delivered(self.send())
        parado = Lead.objects.get()
        Lead.objects.filter(pk=parado.pk).update(last_contact=timezone.now() - timedelta(hours=25))
        recente = Lead.objects.create(company=self.company, contact="+5585900000002", state="nome", last_contact=timezone.now())
        humano = Lead.objects.create(company=self.company, contact="+5585900000003", mode="HUMANO", last_contact=timezone.now() - timedelta(days=3))
        manual = Lead.objects.create(company=self.company, contact="+5585900000004", origem_manual=True, last_contact=timezone.now() - timedelta(days=3))
        self.assertEqual(apagar_triagens_abandonadas(), 1)
        self.assertFalse(Lead.objects.filter(pk=parado.pk).exists())
        self.assertFalse(Event.objects.filter(lead_id=parado.pk).exists())
        for outro in (recente, humano, manual):
            self.assertTrue(Lead.objects.filter(pk=outro.pk).exists())
        self.assertEqual(apagar_triagens_abandonadas(), 0)
        # O número recomeça do zero.
        r = self.send("9")
        self.assertEqual((r["action"], r["lead_novo"]), ("TEXTO", True))
    def test_classificado_sempre_em_uma_das_cinco_temperaturas(self):
        from .services import calcular_urgencia
        cinco = {"Desqualificado", "Desconfiado", "Frio", "Qualificado", "Quente"}
        for decimos in range(0, 101):
            _, temperatura = calcular_urgencia({"q": decimos / 10}, {"q": 7})
            self.assertIn(temperatura, cinco)
        self._peso_em_nome(peso=4)
        for i, notas in enumerate([{"nome": 0}, {"nome": 4}, {"nome": 6}, {"nome": 8}, {"nome": 10}]):
            contato = f"+55859000001{i:02d}"
            base = {"contact": contato, "kind": "text", "question_id": "apresentacao", "fields": {}, "human_required": False, "reason": "pedido humano"}
            for mid, marker, fields in [("a", "Q", {}), ("b", "VALIDAR", {}), ("c", "CLASSIFICADO", {"notas": notas})]:
                r = receive(self.company, {**base, "message_id": f"{contato}{mid}", "marker": marker, "fields": fields})
                Event.objects.filter(pk=r["event_id"]).update(delivery="SENT")
            self.assertIn(Lead.objects.filter(contact=contato).latest("created_at").temperature, cinco)
    def test_tenant_isolation(self):
        self.assertEqual(self.client.get(f"/api/leads/?company={self.other.pk}").status_code, 404)
        self.assertEqual(self.client.post(f"/api/companies/{self.other.pk}/incoming/", {}).status_code, 404)
        self.assertEqual(self.client.get("/api/leads/").status_code, 404)
    def test_failed_delivery_na_triagem_reinicia(self):
        result = self.send()
        response = self.client.post(f"/api/companies/{self.company.pk}/delivery/", {"event_id": result["event_id"], "status": "FAILED"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["lead_apagado"])
        self.assertEqual(Lead.objects.count(), 0)
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
    def test_atualizar_rejects_reserved_proxima_values(self):
        self.delivered(self.send())
        for reservado in ["validar", "encerramento"]:
            self.delivered(self.send(f"q-{reservado}"))
            result = self.send(f"m-{reservado}", marker="ATUALIZAR", fields={"nome": "Carlos", "proxima": reservado})
            self.assertTriagemReiniciada(result)
    def test_question_create_requires_variavel_and_delete_blocks_mandatory(self):
        staff = get_user_model().objects.create_user(username="empresa-roteiro", is_staff=True)
        self.company.members.add(staff)
        c = APIClient()
        c.force_authenticate(staff)

        sem_variavel = c.post(f"/api/questions/?company={self.company.pk}", {"question_id": "nova", "text": "Oi"}, format="json")
        self.assertEqual(sem_variavel.status_code, 400)

        variavel = c.post(f"/api/variaveis/?company={self.company.pk}", {"name": "Urgência", "peso": 7}, format="json")
        self.assertEqual(variavel.status_code, 201)
        variavel_id = variavel.json()["id"]

        criada = c.post(f"/api/questions/?company={self.company.pk}", {"question_id": "extra", "text": "Pergunta extra", "variavel": variavel_id}, format="json")
        self.assertEqual(criada.status_code, 201)
        self.assertFalse(criada.json()["obrigatoria"])
        extra_id = criada.json()["id"]

        nome_pk = Question.objects.get(company=self.company, question_id="nome").pk
        bloqueado = c.delete(f"/api/questions/{nome_pk}/?company={self.company.pk}")
        self.assertEqual(bloqueado.status_code, 400)

        # variável ainda em uso pela pergunta "extra" -- não pode excluir
        protegida = c.delete(f"/api/variaveis/{variavel_id}/?company={self.company.pk}")
        self.assertEqual(protegida.status_code, 400)

        liberado = c.delete(f"/api/questions/{extra_id}/?company={self.company.pk}")
        self.assertEqual(liberado.status_code, 204)

        # agora sem nenhuma pergunta usando -- pode excluir
        agora_livre = c.delete(f"/api/variaveis/{variavel_id}/?company={self.company.pk}")
        self.assertEqual(agora_livre.status_code, 204)
    def test_offflow_questions_have_no_variavel_and_cannot_be_deleted(self):
        staff = get_user_model().objects.create_user(username="empresa-roteiro-2", is_staff=True)
        self.company.members.add(staff)
        c = APIClient()
        c.force_authenticate(staff)

        variavel = c.post(f"/api/variaveis/?company={self.company.pk}", {"name": "Urgência 2", "peso": 6}, format="json")
        variavel_id = variavel.json()["id"]

        # "apresentacao" já existe (criada em setUp) sem variável -- editar o texto
        # não deve exigir nem aceitar uma variável, porque é fora do fluxo.
        apresentacao_pk = Question.objects.get(company=self.company, question_id="apresentacao").pk
        com_variavel = c.patch(f"/api/questions/{apresentacao_pk}/?company={self.company.pk}", {"variavel": variavel_id}, format="json")
        self.assertEqual(com_variavel.status_code, 400)
        so_texto = c.patch(f"/api/questions/{apresentacao_pk}/?company={self.company.pk}", {"text": "Olá! Em que posso ajudar?"}, format="json")
        self.assertEqual(so_texto.status_code, 200)

        bloqueado = c.delete(f"/api/questions/{apresentacao_pk}/?company={self.company.pk}")
        self.assertEqual(bloqueado.status_code, 400)

        # criar um novo texto fora do fluxo (ex.: "empresa") não aceita variável
        com_variavel_nova = c.post(
            f"/api/questions/?company={self.company.pk}",
            {"question_id": "empresa", "text": "Somos uma empresa...", "variavel": variavel_id},
            format="json",
        )
        self.assertEqual(com_variavel_nova.status_code, 400)
        sem_variavel_offflow = c.post(
            f"/api/questions/?company={self.company.pk}", {"question_id": "empresa", "text": "Somos uma empresa..."}, format="json"
        )
        self.assertEqual(sem_variavel_offflow.status_code, 201)
        self.assertIsNone(sem_variavel_offflow.json()["variavel"])
    def test_question_ordem_can_be_updated_for_drag_and_drop(self):
        from .models import Variavel
        staff = get_user_model().objects.create_user(username="empresa-roteiro-3", is_staff=True)
        self.company.members.add(staff)
        c = APIClient()
        c.force_authenticate(staff)
        variavel = Variavel.objects.create(company=self.company, name="Geral 3", peso=5)
        nome = Question.objects.get(company=self.company, question_id="nome")
        nome.variavel = variavel
        nome.save(update_fields=["variavel"])
        resp = c.patch(f"/api/questions/{nome.pk}/?company={self.company.pk}", {"ordem": 3}, format="json")
        self.assertEqual(resp.status_code, 200)
        nome.refresh_from_db()
        self.assertEqual(nome.ordem, 3)
    def test_variavel_roteiro_checkbox_flow_and_slug_collision(self):
        staff = get_user_model().objects.create_user(username="empresa-roteiro-4", is_staff=True)
        self.company.members.add(staff)
        c = APIClient()
        c.force_authenticate(staff)
        variavel = Variavel.objects.create(company=self.company, name="Geral 4", peso=5)

        criada = c.post(f"/api/variaveis-roteiro/?company={self.company.pk}", {"name": "Idade"}, format="json")
        self.assertEqual(criada.status_code, 201)
        self.assertEqual(criada.json()["slug"], "idade")
        self.assertFalse(criada.json()["builtin"])
        self.assertTrue(criada.json()["cor"].startswith("#"))
        vr_id = criada.json()["id"]

        # colisão de slug: outro nome que normaliza pro mesmo token ganha sufixo
        colisao = c.post(f"/api/variaveis-roteiro/?company={self.company.pk}", {"name": "Idade!"}, format="json")
        self.assertEqual(colisao.status_code, 201)
        self.assertEqual(colisao.json()["slug"], "idade_2")

        # marcar o checkbox numa pergunta adicional -> liga a Variável de roteiro
        extra = c.post(
            f"/api/questions/?company={self.company.pk}",
            {"question_id": "idade_pergunta", "text": "Qual sua idade?", "variavel": variavel.pk, "variavel_roteiro": vr_id},
            format="json",
        )
        self.assertEqual(extra.status_code, 201)
        self.assertEqual(extra.json()["variavel_roteiro"], vr_id)

        # builtin não pode ser excluída; a customizada em uso também não (PROTECT)
        nome_vr = VariavelRoteiro.objects.create(company=self.company, name="Nome", slug="nome", builtin=True)
        bloqueada_builtin = c.delete(f"/api/variaveis-roteiro/{nome_vr.pk}/?company={self.company.pk}")
        self.assertEqual(bloqueada_builtin.status_code, 400)
        bloqueada_em_uso = c.delete(f"/api/variaveis-roteiro/{vr_id}/?company={self.company.pk}")
        self.assertEqual(bloqueada_em_uso.status_code, 400)

        # pergunta obrigatória não aceita trocar a variável de roteiro fixa
        nome_q = Question.objects.get(company=self.company, question_id="nome")
        tentativa = c.patch(f"/api/questions/{nome_q.pk}/?company={self.company.pk}", {"variavel_roteiro": vr_id}, format="json")
        self.assertEqual(tentativa.status_code, 400)

        # texto fora do fluxo não aceita variável de roteiro
        apresentacao = Question.objects.get(company=self.company, question_id="apresentacao")
        offflow_tentativa = c.patch(f"/api/questions/{apresentacao.pk}/?company={self.company.pk}", {"variavel_roteiro": vr_id}, format="json")
        self.assertEqual(offflow_tentativa.status_code, 400)
    def test_render_text_resolves_custom_variavel_roteiro_placeholder(self):
        from .services import render_text
        VariavelRoteiro.objects.create(company=self.company, name="Idade", slug="idade", builtin=False)
        lead = Lead.objects.create(company=self.company, contact="+5585911112222", state="apresentacao")
        lead.variaveis_roteiro = {"idade": "34 anos"}
        self.assertEqual(render_text("Você tem {idade}, confirma?", lead, self.company), "Você tem 34 anos, confirma?")
        # sem valor coletado ainda -- vira string vazia, nunca quebra nem expõe o placeholder
        lead2 = Lead.objects.create(company=self.company, contact="+5585933334444", state="apresentacao")
        self.assertEqual(render_text("Idade: {idade}", lead2, self.company), "Idade: ")
    def test_apply_fields_only_accepts_known_custom_variavel_roteiro_slugs(self):
        from .services import apply_fields
        VariavelRoteiro.objects.create(company=self.company, name="Idade", slug="idade", builtin=False)
        lead = Lead.objects.create(company=self.company, contact="+5585955556666", state="apresentacao")
        apply_fields(lead, self.company, {"variaveis_roteiro": {"idade": "40 anos", "slug_inexistente": "x", "nome": "tentativa de sobrescrever campo fixo"}})
        self.assertEqual(lead.variaveis_roteiro, {"idade": "40 anos"})
    def test_company_patch_only_allows_agente_conversacional_and_blocks_atendente(self):
        staff = get_user_model().objects.create_user(username="empresa-opcoes", is_staff=True)
        self.company.members.add(staff)
        c = APIClient()
        c.force_authenticate(staff)

        self.assertTrue(self.company.agente_conversacional)
        resp = c.patch(f"/api/companies/{self.company.pk}/", {"agente_conversacional": False, "name": "Hackeado"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["agente_conversacional"])
        self.company.refresh_from_db()
        self.assertFalse(self.company.agente_conversacional)
        self.assertEqual(self.company.name, "Empresa A")  # name é read-only por aqui

        atendente = get_user_model().objects.create_user(username="atendente-opcoes")
        self.company.members.add(atendente)
        atendente_client = APIClient()
        atendente_client.force_authenticate(atendente)
        negado = atendente_client.patch(f"/api/companies/{self.company.pk}/", {"agente_conversacional": True}, format="json")
        self.assertEqual(negado.status_code, 403)
    def test_companyinfo_create_accepts_blank_content(self):
        # Bug real: "+ Nova entrada" no frontend manda content="" (preenche
        # depois); content não tinha blank=True, então todo POST de uma
        # entrada nova dava 400 antes de o admin digitar qualquer coisa.
        staff = get_user_model().objects.create_user(username="empresa-dados-2", is_staff=True)
        self.company.members.add(staff)
        c = APIClient()
        c.force_authenticate(staff)
        resp = c.post(f"/api/company-info/?company={self.company.pk}", {"title": "Novo título", "content": ""}, format="json")
        self.assertEqual(resp.status_code, 201)
    def test_companyinfo_mandatory_entries_cannot_be_deleted(self):
        staff = get_user_model().objects.create_user(username="empresa-dados", is_staff=True)
        self.company.members.add(staff)
        c = APIClient()
        c.force_authenticate(staff)
        obrigatoria = CompanyInfo.objects.create(company=self.company, title="Nome da empresa", content="", obrigatorio=True)
        livre = CompanyInfo.objects.create(company=self.company, title="Promoção", content="10% off", obrigatorio=False)
        bloqueado = c.delete(f"/api/company-info/{obrigatoria.pk}/?company={self.company.pk}")
        self.assertEqual(bloqueado.status_code, 400)
        liberado = c.delete(f"/api/company-info/{livre.pk}/?company={self.company.pk}")
        self.assertEqual(liberado.status_code, 204)
    def test_calcular_urgencia_pondera_notas_pelos_pesos_em_cinco_faixas(self):
        from .services import calcular_urgencia
        self.assertEqual(calcular_urgencia({"a": 2.9}, {"a": 5})[1], "Desqualificado")
        self.assertEqual(calcular_urgencia({"a": 3}, {"a": 5})[1], "Desconfiado")
        self.assertEqual(calcular_urgencia({"a": 5}, {"a": 5})[1], "Frio")
        self.assertEqual(calcular_urgencia({"a": 7}, {"a": 5})[1], "Qualificado")
        self.assertEqual(calcular_urgencia({"a": 9}, {"a": 5})[1], "Quente")
        score, temp = calcular_urgencia({"situacao": 8, "renda": 10, "avaliar": 6}, {"situacao": 9, "renda": 7, "avaliar": 4})
        self.assertAlmostEqual(score, (9 * 8 + 7 * 10 + 4 * 6) / 20)
        self.assertEqual(temp, "Qualificado")
        self.assertIsNone(calcular_urgencia({"x": 10}, {}))
    def test_atualizar_rejects_especialidade_not_registered_as_area(self):
        self.delivered(self.send())
        result = self.send("2", marker="ATUALIZAR", fields={"especialidade": "Área Inventada", "proxima": "nome"})
        self.assertTriagemReiniciada(result)
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
        desativado = get_user_model().objects.create_user(username="atendente-desativado", is_staff=False, is_active=False)
        agent_group, _ = Group.objects.get_or_create(name="agente")
        agent_user = get_user_model().objects.create_user(username="agente.empresa-a")
        agent_user.groups.add(agent_group)
        for u in (staff, atendente, desativado, agent_user):
            self.company.members.add(u)
        response = self.client.get(f"/api/companies/{self.company.pk}/equipe/")
        self.assertEqual(response.status_code, 200)
        usernames = {m["username"] for m in response.json()}
        # self.user ("operador", setUp) também é atendente real (is_staff=False) -- esperado aparecer junto.
        # Conta desativada e conta de agente nunca aparecem aqui.
        self.assertEqual(usernames, {"operador", "atendente-real"})
        row = next(m for m in response.json() if m["username"] == "atendente-real")
        self.assertIn("display_name", row)
        self.assertIn("avatar_url", row)
    def test_admin_company_member_count_ignores_inactive_and_agent(self):
        from django.contrib.auth.models import Group
        superuser = get_user_model().objects.create_user(username="super-teste-count", is_staff=True, is_superuser=True)
        c = APIClient()
        c.force_authenticate(superuser)

        atendente = get_user_model().objects.create_user(username="atendente-count", is_staff=False)
        desativado = get_user_model().objects.create_user(username="atendente-count-off", is_staff=False, is_active=False)
        agent_group, _ = Group.objects.get_or_create(name="agente")
        agent_user = get_user_model().objects.create_user(username="agente.count")
        agent_user.groups.add(agent_group)
        for u in (atendente, desativado, agent_user):
            self.company.members.add(u)

        resp = c.get("/api/admin-companies/")
        row = next(r for r in resp.json()["results"] if r["id"] == self.company.pk)
        # self.user ("operador") + atendente-count ativos = 2; desativado e agente não contam.
        self.assertEqual(row["member_count"], 2)
    def test_admin_companies_requires_superuser_not_just_staff(self):
        staff = get_user_model().objects.create_user(username="empresa-staff-admin-test", is_staff=True)
        self.company.members.add(staff)
        staff_client = APIClient()
        staff_client.force_authenticate(staff)
        self.assertEqual(staff_client.get("/api/admin-companies/").status_code, 403)
        superuser = get_user_model().objects.create_user(username="super-teste", is_staff=True, is_superuser=True)
        super_client = APIClient()
        super_client.force_authenticate(superuser)
        resp = super_client.get("/api/admin-companies/")
        self.assertEqual(resp.status_code, 200)
        names = {c["name"] for c in resp.json()["results"]}
        self.assertIn(self.company.name, names)
        self.assertIn(self.other.name, names)  # cross-tenant por design: é a tela interna da Axioma
    def test_admin_companies_create_and_update(self):
        superuser = get_user_model().objects.create_user(username="super-teste-2", is_staff=True, is_superuser=True)
        c = APIClient()
        c.force_authenticate(superuser)
        created = c.post("/api/admin-companies/", {"name": "Nova Empresa Teste", "initial_state": "apresentacao"}, format="json")
        self.assertEqual(created.status_code, 201)
        company_id = created.json()["id"]
        invalido = c.patch(f"/api/admin-companies/{company_id}/", {"numero_agente": "Fila Nova"}, format="json")
        self.assertEqual(invalido.status_code, 400)
        updated = c.patch(f"/api/admin-companies/{company_id}/", {"numero_agente": "+5586994238125"}, format="json")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["numero_agente"], "+5586994238125")
        formatado = c.patch(f"/api/admin-companies/{company_id}/", {"numero_agente": "+55 (86) 9423-8125"}, format="json")
        self.assertEqual(formatado.status_code, 200)
        self.assertEqual(formatado.json()["numero_agente"], "+558694238125")
        vazio = c.patch(f"/api/admin-companies/{company_id}/", {"numero_agente": ""}, format="json")
        self.assertEqual(vazio.json()["numero_agente"], "")
        # seed_roteiro_padrao: empresa nova já nasce com o mínimo pro funil funcionar.
        nova = Company.objects.get(pk=company_id)
        ids = set(Question.objects.filter(company=nova).values_list("question_id", flat=True))
        self.assertEqual(ids, {"nome", "situacao", "demanda", "apresentacao", "empresa", "validar", "encerramento", "necessidade_humana", "lembrete", "especial_acompanhamento"})
        self.assertTrue(Question.objects.filter(company=nova, question_id="nome", obrigatoria=True, variavel__isnull=False).exists())
        self.assertTrue(Question.objects.filter(company=nova, question_id="apresentacao", obrigatoria=True, variavel__isnull=True).exists())
        self.assertEqual(CompanyInfo.objects.filter(company=nova, obrigatorio=True).count(), 3)
        self.assertEqual(
            set(VariavelRoteiro.objects.filter(company=nova, builtin=True).values_list("slug", flat=True)),
            {"nome", "especialidade", "tema"},
        )
        self.assertTrue(Question.objects.filter(company=nova, question_id="nome", variavel_roteiro__slug="nome").exists())
    def test_admin_overview_and_contas_empresa(self):
        superuser = get_user_model().objects.create_user(username="super-teste-overview", is_staff=True, is_superuser=True)
        c = APIClient()
        c.force_authenticate(superuser)

        empresa = get_user_model().objects.create_user(username="empresa-overview", is_staff=True)
        self.company.members.add(empresa)
        atendente = get_user_model().objects.create_user(username="atendente-overview")
        self.company.members.add(atendente)

        overview = c.get("/api/admin-companies/overview/")
        self.assertEqual(overview.status_code, 200)
        body = overview.json()
        self.assertEqual(body["empresas_total"], Company.objects.count())
        self.assertEqual(body["empresas_com_agente_ativo"] + body["empresas_sem_agente_ativo"], body["empresas_total"])
        self.assertIn("usuarios_ativos", body)

        contas = c.get("/api/admin-companies/contas-empresa/")
        self.assertEqual(contas.status_code, 200)
        usernames = {row["username"] for row in contas.json()}
        self.assertIn("empresa-overview", usernames)
        self.assertNotIn("atendente-overview", usernames)
        self.assertNotIn("super-teste-overview", usernames)

        atendente_client = APIClient()
        atendente_client.force_authenticate(atendente)
        self.assertEqual(atendente_client.get("/api/admin-companies/overview/").status_code, 403)
    def test_admin_agente_gerar_status_revogar_token(self):
        superuser = get_user_model().objects.create_user(username="super-teste-3", is_staff=True, is_superuser=True)
        c = APIClient()
        c.force_authenticate(superuser)
        status_antes = c.get(f"/api/admin-companies/{self.company.pk}/agente/")
        self.assertEqual(status_antes.status_code, 200)
        self.assertFalse(status_antes.json()["existe"])

        gerado = c.post(f"/api/admin-companies/{self.company.pk}/agente/", {"validade_dias": 30}, format="json")
        self.assertEqual(gerado.status_code, 200)
        self.assertIn("token", gerado.json())
        primeiro_token = gerado.json()["token"]

        status_depois = c.get(f"/api/admin-companies/{self.company.pk}/agente/")
        self.assertTrue(status_depois.json()["existe"])
        self.assertIsNotNone(status_depois.json()["masked_key"])
        self.assertFalse(status_depois.json()["validade"]["expirado"])

        # Gerar de novo = rotação: token antigo para de funcionar
        regerado = c.post(f"/api/admin-companies/{self.company.pk}/agente/", {"validade_dias": 180}, format="json")
        novo_token = regerado.json()["token"]
        self.assertNotEqual(primeiro_token, novo_token)
        agent_client = APIClient()
        agent_client.credentials(HTTP_AUTHORIZATION=f"Token {primeiro_token}")
        self.assertEqual(agent_client.get("/api/me/").status_code, 401)
        agent_client.credentials(HTTP_AUTHORIZATION=f"Token {novo_token}")
        self.assertEqual(agent_client.get("/api/me/").status_code, 200)

        revogado = c.delete(f"/api/admin-companies/{self.company.pk}/agente/")
        self.assertEqual(revogado.status_code, 200)
        agent_client.credentials(HTTP_AUTHORIZATION=f"Token {novo_token}")
        self.assertEqual(agent_client.get("/api/me/").status_code, 401)
    def test_admin_companies_destroy_sem_confirmacao_nao_exclui(self):
        superuser = get_user_model().objects.create_user(username="super-teste-5", is_staff=True, is_superuser=True)
        c = APIClient()
        c.force_authenticate(superuser)
        resp = c.delete(f"/api/admin-companies/{self.company.pk}/")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())
    def test_admin_agente_validade_dias_bounds(self):
        superuser = get_user_model().objects.create_user(username="super-teste-4", is_staff=True, is_superuser=True)
        c = APIClient()
        c.force_authenticate(superuser)
        muito_longo = c.post(f"/api/admin-companies/{self.company.pk}/agente/", {"validade_dias": 9999}, format="json")
        self.assertEqual(muito_longo.status_code, 400)
        muito_curto = c.post(f"/api/admin-companies/{self.company.pk}/agente/", {"validade_dias": 0}, format="json")
        self.assertEqual(muito_curto.status_code, 400)
    def test_reivindicar_lead_blocks_desqualificado_e_desconfiado(self):
        self.delivered(self.send())
        self.delivered(self.send("2", marker="ATUALIZAR", fields={"nome": "Carlos", "proxima": "nome"}))
        self.delivered(self.send("3", marker="VALIDAR"))
        self.send("4", marker="CLASSIFICADO", fields={"temperatura": "Desqualificado", "prioridade": "Baixa"})
        lead = Lead.objects.get()
        atendente = get_user_model().objects.create_user(username="atendente-urgencia")
        self.company.members.add(atendente)
        client = APIClient()
        client.force_authenticate(atendente)
        negado = client.post(f"/api/leads/{lead.pk}/reivindicar/?company={self.company.pk}")
        self.assertEqual(negado.status_code, 400)
        lead.refresh_from_db()
        self.assertIsNone(lead.owner)

        lead.temperature = "Frio"
        lead.desfecho = ""
        lead.save()
        ok = client.post(f"/api/leads/{lead.pk}/reivindicar/?company={self.company.pk}")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["etapa_atendimento"], "espera")
    def test_colocar_em_espera_nao_atribui_dono_e_bloqueia_staff(self):
        self.delivered(self.send())
        self.delivered(self.send("2", marker="ATUALIZAR", fields={"nome": "Carlos", "proxima": "nome"}))
        self.delivered(self.send("3", marker="VALIDAR"))
        self.send("4", marker="CLASSIFICADO", fields={"temperatura": "Quente", "prioridade": "Alta"})
        lead = Lead.objects.get()
        self.assertIsNone(lead.owner)

        staff = get_user_model().objects.create_user(username="empresa-assumir", is_staff=True)
        self.company.members.add(staff)
        staff_client = APIClient()
        staff_client.force_authenticate(staff)
        denied = staff_client.post(f"/api/leads/{lead.pk}/reivindicar/?company={self.company.pk}")
        self.assertEqual(denied.status_code, 403)

        atendente_a = get_user_model().objects.create_user(username="atendente-a")
        atendente_b = get_user_model().objects.create_user(username="atendente-b")
        self.company.members.add(atendente_a, atendente_b)
        client_a = APIClient()
        client_a.force_authenticate(atendente_a)
        client_b = APIClient()
        client_b.force_authenticate(atendente_b)

        ok = client_a.post(f"/api/leads/{lead.pk}/reivindicar/?company={self.company.pk}")
        self.assertEqual(ok.status_code, 200)
        lead.refresh_from_db()
        self.assertIsNone(lead.owner)
        self.assertEqual(lead.etapa_atendimento, "espera")
        self.assertEqual(lead.mode, "AUTOMÁTICO")  # só vira HUMANO ao entrar em negociação

        ja_assumido = client_b.post(f"/api/leads/{lead.pk}/reivindicar/?company={self.company.pk}")
        self.assertEqual(ja_assumido.status_code, 400)
        lead.refresh_from_db()
        self.assertIsNone(lead.owner)

        # Outro atendente pode assumir a pendência; só agora recebe owner.
        self.assertEqual(client_b.post(f"/api/leads/{lead.pk}/negociar/?company={self.company.pk}").status_code, 200)

        # owner/etapa_atendimento não podem mais ser trocados por PATCH livre
        bypass = client_b.patch(f"/api/leads/{lead.pk}/?company={self.company.pk}", {"owner": atendente_a.pk}, format="json")
        self.assertEqual(bypass.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.owner, atendente_b)
    def test_negociar_lead_from_qualificados_or_espera_and_blocks_other_owner(self):
        self.delivered(self.send())
        self.delivered(self.send("2", marker="ATUALIZAR", fields={"nome": "Carlos", "proxima": "nome"}))
        self.delivered(self.send("3", marker="VALIDAR"))
        self.send("4", marker="CLASSIFICADO", fields={"temperatura": "Quente", "prioridade": "Alta"})
        lead = Lead.objects.get()
        atendente_a = get_user_model().objects.create_user(username="atendente-neg-a")
        atendente_b = get_user_model().objects.create_user(username="atendente-neg-b")
        self.company.members.add(atendente_a, atendente_b)
        client_a = APIClient()
        client_a.force_authenticate(atendente_a)
        client_b = APIClient()
        client_b.force_authenticate(atendente_b)

        # direto de Qualificados (sem owner ainda) -- quem move se torna owner
        ok = client_a.post(f"/api/leads/{lead.pk}/negociar/?company={self.company.pk}")
        self.assertEqual(ok.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.owner, atendente_a)
        self.assertEqual(lead.mode, "HUMANO")
        self.assertEqual(lead.etapa_atendimento, "negociacao")

        # outro atendente não pode mover um lead que já tem owner
        bloqueado = client_b.post(f"/api/leads/{lead.pk}/negociar/?company={self.company.pk}")
        self.assertEqual(bloqueado.status_code, 400)
    def test_preparar_despacho_auto_falha_direto_de_qualificados(self):
        self.delivered(self.send())
        self.delivered(self.send("2", marker="ATUALIZAR", fields={"nome": "Carlos", "proxima": "nome"}))
        self.delivered(self.send("3", marker="VALIDAR"))
        self.send("4", marker="CLASSIFICADO", fields={"temperatura": "Quente", "prioridade": "Alta"})
        lead = Lead.objects.get()
        atendente = get_user_model().objects.create_user(username="atendente-auto-falha")
        self.company.members.add(atendente)
        client = APIClient()
        client.force_authenticate(atendente)

        resp = client.post(f"/api/leads/{lead.pk}/preparar-despacho/?company={self.company.pk}", {"auto_falha": True}, format="json")
        self.assertEqual(resp.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.owner, atendente)
        self.assertEqual(lead.etapa_atendimento, "despacho")
        self.assertEqual(lead.desfecho_pendente, "falha")
        self.assertEqual(lead.desfecho, "")  # ainda não é definitivo
    def test_enviar_despachos_finaliza_so_do_proprio_owner_e_desta_empresa(self):
        self.delivered(self.send())
        self.delivered(self.send("2", marker="ATUALIZAR", fields={"nome": "Carlos", "proxima": "nome"}))
        self.delivered(self.send("3", marker="VALIDAR"))
        self.send("4", marker="CLASSIFICADO", fields={"temperatura": "Quente", "prioridade": "Alta"})
        lead_a = Lead.objects.get()

        atendente = get_user_model().objects.create_user(username="atendente-envia")
        outro = get_user_model().objects.create_user(username="atendente-nao-envia")
        self.company.members.add(atendente, outro)
        client = APIClient()
        client.force_authenticate(atendente)
        outro_client = APIClient()
        outro_client.force_authenticate(outro)

        # só lead_a está classificado/despachável nesse teste
        client.post(f"/api/leads/{lead_a.pk}/preparar-despacho/?company={self.company.pk}", {"desfecho": "encerrado"}, format="json")

        enviado_por_outro = outro_client.post(f"/api/leads/enviar-despachos/?company={self.company.pk}")
        self.assertEqual(enviado_por_outro.json()["enviados"], 0)
        lead_a.refresh_from_db()
        self.assertEqual(lead_a.desfecho, "")  # não foi o owner que mandou, nada mudou

        enviado = client.post(f"/api/leads/enviar-despachos/?company={self.company.pk}")
        self.assertEqual(enviado.status_code, 200)
        self.assertEqual(enviado.json()["enviados"], 1)
        lead_a.refresh_from_db()
        self.assertEqual(lead_a.desfecho, "encerrado")
        self.assertEqual(lead_a.desfecho_pendente, "")
        self.assertEqual(lead_a.etapa_atendimento, "")
    def test_liberar_lead_devolve_para_qualificados(self):
        self.delivered(self.send())
        self.delivered(self.send("2", marker="ATUALIZAR", fields={"nome": "Carlos", "proxima": "nome"}))
        self.delivered(self.send("3", marker="VALIDAR"))
        self.send("4", marker="CLASSIFICADO", fields={"temperatura": "Quente", "prioridade": "Alta"})
        lead = Lead.objects.get()
        atendente_a = get_user_model().objects.create_user(username="atendente-libera-a")
        atendente_b = get_user_model().objects.create_user(username="atendente-libera-b")
        self.company.members.add(atendente_a, atendente_b)
        client_a = APIClient()
        client_a.force_authenticate(atendente_a)
        client_b = APIClient()
        client_b.force_authenticate(atendente_b)

        client_a.post(f"/api/leads/{lead.pk}/negociar/?company={self.company.pk}")

        bloqueado = client_b.post(f"/api/leads/{lead.pk}/liberar/?company={self.company.pk}")
        self.assertEqual(bloqueado.status_code, 400)

        ok = client_a.post(f"/api/leads/{lead.pk}/liberar/?company={self.company.pk}")
        self.assertEqual(ok.status_code, 200)
        lead.refresh_from_db()
        self.assertIsNone(lead.owner)
        self.assertEqual(lead.etapa_atendimento, "")

        # livre de novo -- outro atendente consegue reivindicar
        reivindicado_por_b = client_b.post(f"/api/leads/{lead.pk}/reivindicar/?company={self.company.pk}")
        self.assertEqual(reivindicado_por_b.status_code, 200)
    def test_mesmo_contato_fica_mudo_enquanto_ativo_e_reabre_so_depois_de_despachado(self):
        from .services import preparar_despacho, enviar_despachos
        self.delivered(self.send())
        self.delivered(self.send("2", marker="ATUALIZAR", fields={"nome": "Carlos", "proxima": "nome"}))
        self.delivered(self.send("3", marker="VALIDAR"))
        self.send("4", marker="CLASSIFICADO", fields={"temperatura": "Quente", "prioridade": "Alta"})
        lead = Lead.objects.get()
        self.assertTrue(lead.bot_closed)
        self.assertEqual(lead.desfecho, "")

        # Enquanto ativo (sem desfecho), QUALQUER marcador novo desse contato é NO_REPLY e
        # nunca cria lead novo nem mexe no existente -- é a mesma trava de sempre (bot_closed).
        resp = self.send("5", marker="Q", question_id="apresentacao")
        self.assertEqual(resp["action"], "NO_REPLY")
        self.assertEqual(Lead.objects.count(), 1)

        # Despacha (sai da lista de ativos).
        atendente = get_user_model().objects.create_user(username="atendente-reabre")
        self.company.members.add(atendente)
        erro = preparar_despacho(lead.pk, "encerrado", atendente)
        self.assertIsNone(erro)
        enviados = enviar_despachos(atendente, self.company)
        self.assertEqual(enviados, 1)
        lead.refresh_from_db()
        self.assertEqual(lead.desfecho, "encerrado")

        # Mesmo contato escreve de novo: agora cria um lead NOVO (o antigo, despachado,
        # continua intacto no histórico) -- o número não fica mudo pra sempre.
        resp2 = self.send("6", marker="Q", question_id="apresentacao")
        self.assertEqual(resp2["action"], "TEXTO")
        self.assertEqual(Lead.objects.filter(contact="+5585999999999").count(), 2)
        novo_lead = Lead.objects.exclude(pk=lead.pk).get(contact="+5585999999999")
        self.assertEqual(novo_lead.desfecho, "")
        self.assertFalse(novo_lead.bot_closed)
    def test_criar_lead_manual_nao_entra_no_kanban_e_bloqueia_contato_duplicado(self):
        atendente = get_user_model().objects.create_user(username="atendente-manual")
        self.company.members.add(atendente)
        c = APIClient()
        c.force_authenticate(atendente)

        criado = c.post(
            f"/api/leads/manual/?company={self.company.pk}",
            {"name": "Contato Manual", "contact": "+5585977778888", "demand": "Ligou perguntando sobre honorários"},
            format="json",
        )
        self.assertEqual(criado.status_code, 201)
        body = criado.json()
        self.assertTrue(body["origem_manual"])
        self.assertTrue(body["bot_closed"])
        self.assertEqual(body["owner"], atendente.pk)
        self.assertEqual(body["owner_nome"], "atendente-manual")
        self.assertEqual(body["etapa_atendimento"], "")

        duplicado = c.post(
            f"/api/leads/manual/?company={self.company.pk}", {"name": "Outro", "contact": "+5585977778888"}, format="json"
        )
        self.assertEqual(duplicado.status_code, 400)

        staff = get_user_model().objects.create_user(username="empresa-manual", is_staff=True)
        self.company.members.add(staff)
        staff_client = APIClient()
        staff_client.force_authenticate(staff)
        negado = staff_client.post(
            f"/api/leads/manual/?company={self.company.pk}", {"name": "X", "contact": "+5585900001111"}, format="json"
        )
        self.assertEqual(negado.status_code, 403)
    def test_excluir_lead_e_fallback_de_admin_preso_no_kanban(self):
        self.delivered(self.send())
        lead = Lead.objects.get()

        atendente = get_user_model().objects.create_user(username="atendente-exclui")
        staff = get_user_model().objects.create_user(username="empresa-exclui", is_staff=True)
        self.company.members.add(atendente, staff)

        atendente_client = APIClient()
        atendente_client.force_authenticate(atendente)
        negado = atendente_client.delete(f"/api/leads/{lead.pk}/?company={self.company.pk}")
        self.assertEqual(negado.status_code, 403)
        self.assertTrue(Lead.objects.filter(pk=lead.pk).exists())

        staff_client = APIClient()
        staff_client.force_authenticate(staff)
        ok = staff_client.delete(f"/api/leads/{lead.pk}/?company={self.company.pk}")
        self.assertEqual(ok.status_code, 204)
        self.assertFalse(Lead.objects.filter(pk=lead.pk).exists())
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
    def test_trocar_email_atualiza_o_login_de_conta_por_email(self):
        user = get_user_model().objects.create_user(username="ana@example.com", password="senha-atual-123", email="ana@example.com")
        c = APIClient()
        c.force_authenticate(user)
        c.post("/api/me/email/", {"email": "ana.nova@example.com"}, format="json")
        code = mail.outbox[-1].body.split("Código de confirmação: ")[1].split("\n")[0]
        self.assertEqual(c.post("/api/me/email/confirmar/", {"code": code}, format="json").status_code, 200)
        user.refresh_from_db()
        self.assertEqual((user.username, user.email), ("ana.nova@example.com", "ana.nova@example.com"))
        login = Client().post("/api/login/", {"username": "ana.nova@example.com", "password": "senha-atual-123"}, content_type="application/json")
        self.assertEqual(login.status_code, 200)
    def test_trocar_email_rejeita_email_usado_como_login_de_outra_conta(self):
        get_user_model().objects.create_user(username="outro@example.com", email="")
        user = get_user_model().objects.create_user(username="eu@example.com", password="x", email="eu@example.com")
        c = APIClient()
        c.force_authenticate(user)
        self.assertEqual(c.post("/api/me/email/", {"email": "outro@example.com"}, format="json").status_code, 400)
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

class DashboardResumoTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Empresa Dash")
        self.other = Company.objects.create(name="Outra")
        self.user = get_user_model().objects.create_user(username="dash-op")
        self.company.members.add(self.user)
        self.ana = get_user_model().objects.create_user(username="ana")
        self.company.members.add(self.ana)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def lead(self, contact, company=None, **kw):
        return Lead.objects.create(company=company or self.company, contact=contact, state="x", **kw)

    def test_resumo_conta_todos_os_leads_mesmo_acima_de_uma_pagina(self):
        for i in range(105):
            self.lead(f"+55859990{i:05d}", bot_closed=True, mode="HUMANO", owner=self.ana, desfecho="encerrado", temperature="Quente")
        self.lead("+5585888000001")
        data = self.client.get(f"/api/leads/resumo/?company={self.company.pk}&dias=all").json()
        self.assertEqual(data["total"], 106)
        self.assertEqual(data["desfechos"]["encerrado"], 105)
        self.assertEqual(data["status"]["despachado"], 105)
        self.assertEqual(data["status"]["automatico"], 1)
        self.assertEqual(len(data["atendimentos"]), 106)

    def test_resumo_status_e_exclusivo_e_soma_o_total(self):
        self.lead("+5585000000001")  # automático
        self.lead("+5585000000002", mode="HUMANO")  # escalado pelo CRM
        self.lead("+5585000000003", bot_closed=True, temperature="Quente")  # qualificado, ainda sem owner
        self.lead("+5585000000004", bot_closed=True, mode="HUMANO", owner=self.ana, etapa_atendimento="negociacao", temperature="Quente")
        self.lead("+5585000000005", bot_closed=True, temperature="Desqualificado")
        self.lead("+5585000000006", bot_closed=True, mode="HUMANO", owner=self.ana, desfecho="falha", temperature="Quente")
        data = self.client.get(f"/api/leads/resumo/?company={self.company.pk}&dias=all").json()
        self.assertEqual(data["status"], {"despachado": 1, "automatico": 1, "aguardando": 2, "equipe": 1, "desqualificado": 1, "especial": 0, "nao_prosseguiram": 0})
        self.assertEqual(sum(data["status"].values()), data["total"])

    def test_resumo_taxa_por_atendente_usa_desfecho_nao_bot_closed(self):
        self.lead("+5585000000011", bot_closed=True, mode="HUMANO", owner=self.ana, etapa_atendimento="negociacao")
        self.lead("+5585000000012", bot_closed=True, mode="HUMANO", owner=self.ana, desfecho="encerrado")
        self.lead("+5585000000013")  # sem owner: não entra na tabela de atendentes
        data = self.client.get(f"/api/leads/resumo/?company={self.company.pk}&dias=all").json()
        self.assertEqual(data["por_owner"], [{"owner_id": self.ana.pk, "owner": "ana", "atendimentos": 2, "concluidos": 1, "sucesso": 1}])

    def test_resumo_mesmo_contato_reaberto_conta_os_dois_leads(self):
        self.lead("+5585000000021", bot_closed=True, mode="HUMANO", owner=self.ana, desfecho="encerrado")
        self.lead("+5585000000021")
        data = self.client.get(f"/api/leads/resumo/?company={self.company.pk}&dias=all").json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["status"]["despachado"], 1)

    def test_resumo_filtra_periodo_area_e_isola_empresa(self):
        antigo = self.lead("+5585000000031", especialidade="Consumidor")
        Lead.objects.filter(pk=antigo.pk).update(created_at=timezone.now() - timedelta(days=60))
        self.lead("+5585000000032", especialidade="Trabalhista")
        self.lead("+5585000000033", company=self.other)
        base = f"/api/leads/resumo/?company={self.company.pk}"
        self.assertEqual(self.client.get(base + "&dias=all").json()["total"], 2)
        self.assertEqual(self.client.get(base + "&dias=30").json()["total"], 1)
        self.assertEqual(self.client.get(base + "&dias=all&area=Consumidor").json()["total"], 1)
        self.assertEqual(self.client.get(f"/api/leads/resumo/?company={self.other.pk}").status_code, 404)
        self.assertEqual(self.client.get(base + "&dias=abc").status_code, 400)

    def test_resumo_agrupa_mes_por_ano_mes_em_ordem(self):
        a = self.lead("+5585000000041")
        b = self.lead("+5585000000042")
        Lead.objects.filter(pk=a.pk).update(created_at=timezone.now().replace(year=2025, month=3, day=10))
        Lead.objects.filter(pk=b.pk).update(created_at=timezone.now().replace(year=2026, month=3, day=10))
        meses = [m for m, _ in self.client.get(f"/api/leads/resumo/?company={self.company.pk}&dias=all").json()["por_mes"]]
        self.assertEqual(meses, ["2025-03", "2026-03"])

    def test_periodo_especifico_inclui_dias_inteiros_no_fuso_da_empresa(self):
        from datetime import datetime
        timestamps = ["2026-10-07T02:59:59.999999+00:00", "2026-10-07T03:00:00+00:00", "2026-10-08T02:59:59.999999+00:00", "2026-10-08T03:00:00+00:00"]
        leads = []
        for index, timestamp in enumerate(timestamps):
            lead = self.lead(f"+55850000900{index}", name=f"Lead {index}", especialidade="Consumidor" if index == 1 else "Trabalhista")
            Lead.objects.filter(pk=lead.pk).update(created_at=datetime.fromisoformat(timestamp))
            leads.append(lead)
        self.lead("+558500009009", company=self.other)
        base = f"/api/leads/resumo/?company={self.company.pk}&data_inicio=2026-10-07&data_fim=2026-10-07"
        data = self.client.get(base).json()
        self.assertEqual(data["total"], 2)
        self.assertEqual({row["id"] for row in data["atendimentos"]}, {str(leads[1].pk), str(leads[2].pk)})
        filtrado = self.client.get(base + "&area=Consumidor&q=Lead 1").json()
        self.assertEqual(filtrado["total"], 1)
        self.assertEqual(filtrado["atendimentos"][0]["id"], str(leads[1].pk))

    def test_periodo_especifico_substitui_filtro_de_dias_e_valida_intervalo(self):
        from datetime import datetime
        lead = self.lead("+558500009010")
        Lead.objects.filter(pk=lead.pk).update(created_at=datetime.fromisoformat("2020-01-02T12:00:00+00:00"))
        base = f"/api/leads/resumo/?company={self.company.pk}"
        data = self.client.get(base + "&dias=1&data_inicio=2020-01-02&data_fim=2020-01-02").json()
        self.assertEqual(data["total"], 1)
        for query in ["data_inicio=2026-10-07", "data_fim=2026-10-07", "data_inicio=2026-10-08&data_fim=2026-10-07", "data_inicio=abc&data_fim=2026-10-07", "data_inicio=2026-02-30&data_fim=2026-03-01"]:
            self.assertEqual(self.client.get(base + "&" + query).status_code, 400, query)

    def test_listas_dos_cards_correspondem_a_contagem_e_sucesso_da_triagem(self):
        self.lead("+558500009021")
        qualified = self.lead("+558500009022", bot_closed=True, temperature="Qualificado", demand="Desconto indevido")
        self.lead("+558500009023", bot_closed=True, temperature="Desqualificado", desfecho="desqualificado")
        self.lead("+558500009024", bot_closed=True, temperature="Desconfiado")
        self.lead("+558500009025", bot_closed=True, origem_manual=True, mode="HUMANO")
        self.lead("+558500009026", mode="HUMANO")
        self.lead("+558500009027", bot_closed=True, temperature="Quente", desfecho="encerrado")
        self.lead("+558500009028", bot_closed=True, temperature="", desfecho="bloqueado")
        data = self.client.get(f"/api/leads/resumo/?company={self.company.pk}&dias=all").json()
        rows = data["atendimentos"]
        self.assertEqual(len(rows), data["total"])
        self.assertEqual(data["triagem_concluida"], 2)  # qualificada + escalada para humano, ambas na fila de Pendências
        self.assertEqual(sum(row["triagem_concluida"] for row in rows), data["triagem_concluida"])
        for category, count in data["status"].items():
            self.assertEqual(sum(row["categoria_status"] == category for row in rows), count)
        self.assertEqual(sum(row["categoria_status"] == "desqualificado" for row in rows), data["desqualificados"])
        self.assertEqual(next(row for row in rows if row["id"] == str(qualified.pk))["demand"], "Desconto indevido")

    def test_lista_ativos_exclui_despachados_manuais_e_desqualificados(self):
        ativo = self.lead("+5585000000051", bot_closed=True, temperature="Quente")
        self.lead("+5585000000052", bot_closed=True, desfecho="encerrado", temperature="Quente")
        self.lead("+5585000000053", bot_closed=True, mode="HUMANO", origem_manual=True)
        self.lead("+5585000000054", bot_closed=True, temperature="Desconfiado")
        ids = [l["id"] for l in self.client.get(f"/api/leads/?company={self.company.pk}&ativos=1").json()["results"]]
        self.assertEqual(ids, [str(ativo.pk)])

class VarreduraFixesTests(TestCase):
    """Regressões da varredura de bugs: dono do lead por usuário (FK), lead escalado
    assumível, desqualificado não mudo pra sempre, liberar sem religar bot, cadastro
    manual validado e conta do agente fora das ações de equipe."""
    def setUp(self):
        self.company = Company.objects.create(name="Empresa Fix")
        for qid, text in [("apresentacao", "Olá!"), ("nome", "Seu nome?"), ("validar", "Confirma?"), ("encerramento", "Obrigado.")]:
            Question.objects.create(company=self.company, question_id=qid, text=text)
        User = get_user_model()
        self.maria = User.objects.create_user(username="maria@x.com", first_name="Maria")
        self.joao = User.objects.create_user(username="joao@x.com", first_name="João")
        self.company.members.add(self.maria, self.joao)

    def send(self, mid="1", contact="+5585911112222", **kwargs):
        data = {"contact": contact, "message_id": mid, "kind": "text", "marker": "Q", "question_id": "apresentacao",
                "fields": {}, "human_required": False, "reason": "pedido humano", **kwargs}
        return receive(self.company, data)

    def classificar(self, temperatura="Quente", contact="+5585911112222"):
        for mid, kw in [("c1", {}), ("c2", {"marker": "ATUALIZAR", "fields": {"nome": "Ana", "proxima": "nome"}}), ("c3", {"marker": "VALIDAR"})]:
            Event.objects.filter(pk=self.send(f"{contact}{mid}", contact=contact, **kw)["event_id"]).update(delivery="SENT")
        self.send(f"{contact}c4", contact=contact, marker="CLASSIFICADO", fields={"temperatura": temperatura, "prioridade": "Alta"})
        return Lead.objects.filter(contact=contact).latest("created_at")

    def cliente(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def url(self, lead, acao):
        return f"/api/leads/{lead.pk}/{acao}/?company={self.company.pk}"

    def test_dono_do_lead_e_o_usuario_mesmo_trocando_ou_imitando_nome(self):
        from .models import Profile
        lead = self.classificar()
        maria = self.cliente(self.maria)
        self.assertEqual(maria.post(self.url(lead, "negociar")).status_code, 200)
        me = maria.get("/api/me/").json()
        detalhe = maria.get(f"/api/leads/{lead.pk}/?company={self.company.pk}").json()
        self.assertEqual(detalhe["owner"], me["id"])
        self.assertEqual(detalhe["owner_nome"], "Maria")
        # Maria troca o nome de exibição: continua dona.
        Profile.objects.update_or_create(user=self.maria, defaults={"display_name": "Maria Silva"})
        # João copia o nome dela: não vira dono.
        Profile.objects.update_or_create(user=self.joao, defaults={"display_name": "Maria Silva"})
        self.assertEqual(self.cliente(self.joao).post(self.url(lead, "negociar")).status_code, 400)
        self.assertEqual(maria.post(self.url(lead, "negociar")).status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.owner, self.maria)

    def test_desligar_atendente_solta_os_leads_dele(self):
        lead = self.classificar()
        self.cliente(self.maria).post(self.url(lead, "negociar"))
        self.maria.delete()
        lead.refresh_from_db()
        self.assertIsNone(lead.owner)
        self.assertEqual(self.cliente(self.joao).post(self.url(lead, "negociar")).status_code, 200)

    def test_lead_escalado_antes_da_triagem_pode_ser_assumido_e_aparece_nos_ativos(self):
        self.send("1")
        self.send("2", human_required=True)
        lead = Lead.objects.get()
        self.assertEqual(lead.mode, "HUMANO")
        self.assertFalse(lead.bot_closed)
        maria = self.cliente(self.maria)
        ativos = maria.get(f"/api/leads/?company={self.company.pk}&ativos=1").json()["results"]
        self.assertIn(str(lead.pk), [l["id"] for l in ativos])
        self.assertEqual(maria.post(self.url(lead, "reivindicar")).status_code, 200)
        self.assertEqual(self.send("3")["action"], "NO_REPLY")

    def test_liberar_nao_religa_bot_de_lead_escalado_nem_lead_sem_dono(self):
        self.send("1")
        self.send("2", human_required=True)
        lead = Lead.objects.get()
        maria = self.cliente(self.maria)
        self.assertEqual(maria.post(self.url(lead, "liberar")).status_code, 400)  # ninguém assumiu
        lead.refresh_from_db()
        self.assertEqual(lead.mode, "HUMANO")
        maria.post(self.url(lead, "reivindicar"))
        self.assertEqual(maria.post(self.url(lead, "liberar")).status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.mode, "HUMANO")
        self.assertIsNone(lead.owner)
        self.assertEqual(self.send("3")["action"], "NO_REPLY")

    def test_desqualificado_sai_dos_ativos_e_libera_o_numero_na_hora(self):
        lead = self.classificar("Desqualificado")
        self.assertEqual(lead.desfecho, "desqualificado")
        self.assertIsNotNone(lead.concluido_em)
        # Sem quarentena: a próxima mensagem já abre um lead novo do zero.
        self.assertEqual(self.send("depois-1")["action"], "TEXTO")
        self.assertEqual(Lead.objects.count(), 2)
        # Atendente nunca escolhe o desfecho automático no despacho.
        novo = Lead.objects.get(desfecho="")
        Lead.objects.filter(pk=novo.pk).update(bot_closed=True, temperature="Quente")
        resp = self.cliente(self.maria).post(self.url(novo, "preparar-despacho"), {"desfecho": "desqualificado"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_lead_manual_valida_tamanho_normaliza_contato_e_nunca_da_500(self):
        maria = self.cliente(self.maria)
        url = f"/api/leads/manual/?company={self.company.pk}"
        ok = maria.post(url, {"name": "Cliente", "contact": "(85) 99999-8888"}, format="json")
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(ok.json()["contact"], "+5585999998888")
        self.assertEqual(ok.json()["owner"], self.maria.pk)
        duplicado = maria.post(url, {"contact": "+55 85 99999-8888"}, format="json")
        self.assertEqual(duplicado.status_code, 400)
        for payload in [{"contact": "1" * 30}, {"contact": "+5585977776666", "name": "x" * 200}, {"contact": "+5585977776666", "demand": "x" * 400}, {"contact": "abc"}, {}]:
            resp = maria.post(url, payload, format="json")
            self.assertEqual(resp.status_code, 400, payload)
            self.assertIn("detail", resp.json())

    def test_equipe_nao_desliga_nem_redefine_senha_da_conta_do_agente(self):
        from django.contrib.auth.models import Group
        agente = get_user_model().objects.create_user(username="agente.empresa-fix")
        agente.groups.add(Group.objects.get_or_create(name="agente")[0])
        self.company.members.add(agente)
        empresa = get_user_model().objects.create_user(username="empresa-fix", is_staff=True)
        self.company.members.add(empresa)
        c = self.cliente(empresa)
        self.assertEqual(c.post(f"/api/companies/{self.company.pk}/equipe/{agente.pk}/redefinir-senha/").status_code, 404)
        self.assertEqual(c.delete(f"/api/companies/{self.company.pk}/equipe/{agente.pk}/").status_code, 404)
        self.assertTrue(get_user_model().objects.filter(pk=agente.pk).exists())

    def test_meus_lista_so_negociacao_e_manuais_do_proprio_atendente(self):
        lead = self.classificar()
        maria = self.cliente(self.maria)
        maria.post(self.url(lead, "negociar"))
        maria.post(f"/api/leads/manual/?company={self.company.pk}", {"contact": "+5585933334444"}, format="json")
        self.cliente(self.joao).post(f"/api/leads/manual/?company={self.company.pk}", {"contact": "+5585955556666"}, format="json")
        meus = maria.get(f"/api/leads/?company={self.company.pk}&meus=1").json()
        self.assertEqual(meus["count"], 2)
        self.assertTrue(all(l["owner"] == self.maria.pk for l in meus["results"]))

class ExcluirEmpresaTests(TestCase):
    def setUp(self):
        from .services import seed_roteiro_padrao, gerar_token_agente
        User = get_user_model()
        self.su = User.objects.create_superuser(username="root-exclusao", password="x")
        self.empresa = Company.objects.create(name="Empresa Apagavel")
        seed_roteiro_padrao(self.empresa)
        Area.objects.create(company=self.empresa, name="Trabalhista")
        CompanyInfo.objects.create(company=self.empresa, title="Horário", content="8-18")
        self.outra = Company.objects.create(name="Empresa Que Fica")
        seed_roteiro_padrao(self.outra)
        self.exclusivo = User.objects.create_user(username="so-daqui@x.com")
        self.compartilhado = User.objects.create_user(username="duas-empresas@x.com")
        self.empresa.members.add(self.exclusivo, self.compartilhado, self.su)
        self.outra.members.add(self.compartilhado)
        self.token = gerar_token_agente(self.empresa, 30)["token"]
        receive(self.empresa, {"contact": "+5585911112222", "message_id": "m1", "kind": "text", "marker": "Q",
                               "question_id": "apresentacao", "fields": {}, "human_required": False, "reason": "pedido humano"})
        Lead.objects.filter(company=self.empresa).update(owner=self.exclusivo)
        receive(self.outra, {"contact": "+5585933334444", "message_id": "m2", "kind": "text", "marker": "Q",
                             "question_id": "apresentacao", "fields": {}, "human_required": False, "reason": "pedido humano"})
        self.client_su = APIClient()
        self.client_su.force_authenticate(self.su)

    def url(self):
        return f"/api/admin-companies/{self.empresa.pk}/"

    def test_exclui_empresa_e_tudo_dela_preservando_contas_compartilhadas(self):
        resp = self.client_su.delete(self.url(), {"confirmar_nome": "Empresa Apagavel"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        User = get_user_model()
        self.assertFalse(Company.objects.filter(pk=self.empresa.pk).exists())
        for model in (Lead, Question, Area, CompanyInfo, Variavel, VariavelRoteiro):
            self.assertFalse(model.objects.filter(company_id=self.empresa.pk).exists(), model.__name__)
        self.assertFalse(Event.objects.filter(lead__company_id=self.empresa.pk).exists())
        self.assertFalse(User.objects.filter(username="so-daqui@x.com").exists())
        self.assertFalse(User.objects.filter(username__startswith="agente.empresa-apagavel").exists())
        from rest_framework.authtoken.models import Token
        self.assertFalse(Token.objects.filter(key=self.token).exists())
        self.assertTrue(User.objects.filter(pk=self.compartilhado.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.su.pk).exists())
        self.assertEqual(Lead.objects.filter(company=self.outra).count(), 1)
        self.assertTrue(Question.objects.filter(company=self.outra).exists())

    def test_token_do_agente_da_empresa_excluida_para_de_autenticar(self):
        self.client_su.delete(self.url(), {"confirmar_nome": "Empresa Apagavel"}, format="json")
        agente = APIClient()
        agente.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")
        self.assertEqual(agente.get(self.url().replace("admin-companies", "companies")).status_code, 401)

    def test_exige_nome_exato_como_confirmacao(self):
        for body in ({}, {"confirmar_nome": "empresa apagavel"}, {"confirmar_nome": "Outra"}):
            self.assertEqual(self.client_su.delete(self.url(), body, format="json").status_code, 400)
        self.assertTrue(Company.objects.filter(pk=self.empresa.pk).exists())

    def test_so_superuser_pode_excluir(self):
        User = get_user_model()
        staff = User.objects.create_user(username="empresa-staff@x.com", is_staff=True)
        self.empresa.members.add(staff)
        c = APIClient()
        c.force_authenticate(staff)
        self.assertEqual(c.delete(self.url(), {"confirmar_nome": "Empresa Apagavel"}, format="json").status_code, 403)
        self.assertTrue(Company.objects.filter(pk=self.empresa.pk).exists())


class DespachoEConcluidosTests(TestCase):
    """Atendente fecha o lead pelo Despacho (escolhendo desfecho e área da empresa) e o
    Dashboard lista os concluídos com suas classificações, com os mesmos filtros do resumo."""
    def setUp(self):
        from .models import Area
        User = get_user_model()
        self.company = Company.objects.create(name="Empresa Despacho")
        self.other = Company.objects.create(name="Outra Despacho")
        for nome in ["Trabalhista", "Consumidor"]:
            Area.objects.create(company=self.company, name=nome)
        Area.objects.create(company=self.other, name="Tributário")
        self.ana = User.objects.create_user(username="ana@d.com", first_name="Ana")
        self.bia = User.objects.create_user(username="bia@d.com", first_name="Bia")
        self.empresa = User.objects.create_user(username="empresa@d.com", is_staff=True)
        self.company.members.add(self.ana, self.bia, self.empresa)

    def cliente(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def lead(self, contact, **kw):
        base = {"bot_closed": True, "temperature": "Quente", "state": "ENCERRADO_CLASSIFICADO"}
        base.update(kw)
        return Lead.objects.create(company=self.company, contact=contact, **base)

    def url(self, lead, acao):
        return f"/api/leads/{lead.pk}/{acao}/?company={self.company.pk}"

    def test_atendente_fecha_lead_pelo_despacho_escolhendo_area_da_empresa(self):
        lead = self.lead("+5585977770001", especialidade="Consumidor")
        ana = self.cliente(self.ana)
        self.assertEqual(ana.post(self.url(lead, "negociar")).status_code, 200)
        r = ana.post(self.url(lead, "preparar-despacho"), {"desfecho": "encerrado", "especialidade": "Trabalhista"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["especialidade"], "Trabalhista")
        self.assertEqual(r.json()["desfecho_pendente"], "encerrado")
        # Aparece em "Meus Atendimentos" enquanto está no Despacho.
        meus = [l["id"] for l in ana.get(f"/api/leads/?company={self.company.pk}&meus=1").json()["results"]]
        self.assertIn(str(lead.pk), meus)
        self.assertEqual(ana.post(f"/api/leads/enviar-despachos/?company={self.company.pk}").json(), {"enviados": 1})
        lead.refresh_from_db()
        self.assertEqual((lead.desfecho, lead.especialidade), ("encerrado", "Trabalhista"))
        self.assertIsNotNone(lead.concluido_em)
        meus = [l["id"] for l in ana.get(f"/api/leads/?company={self.company.pk}&meus=1").json()["results"]]
        self.assertNotIn(str(lead.pk), meus)

    def test_area_de_outra_empresa_ou_inexistente_da_400_e_nao_altera_nada(self):
        lead = self.lead("+5585977770002", especialidade="Consumidor")
        ana = self.cliente(self.ana)
        ana.post(self.url(lead, "negociar"))
        for area in ["Tributário", "Inventada"]:
            r = ana.post(self.url(lead, "preparar-despacho"), {"desfecho": "encerrado", "especialidade": area}, format="json")
            self.assertEqual(r.status_code, 400)
        lead.refresh_from_db()
        self.assertEqual((lead.especialidade, lead.etapa_atendimento, lead.desfecho_pendente), ("Consumidor", "negociacao", ""))

    def test_so_o_dono_despacha_e_empresa_nao_despacha(self):
        lead = self.lead("+5585977770003")
        self.cliente(self.ana).post(self.url(lead, "negociar"))
        r = self.cliente(self.bia).post(self.url(lead, "preparar-despacho"), {"desfecho": "encerrado", "especialidade": "Trabalhista"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.cliente(self.empresa).post(self.url(lead, "preparar-despacho"), {"desfecho": "encerrado"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_lead_manual_tambem_fecha_pelo_despacho(self):
        ana = self.cliente(self.ana)
        criado = ana.post(f"/api/leads/manual/?company={self.company.pk}", {"name": "Zé", "contact": "85977770004"}, format="json").json()
        r = ana.post(f"/api/leads/{criado['id']}/preparar-despacho/?company={self.company.pk}", {"desfecho": "comprometido", "especialidade": "Consumidor"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        meus = [l["id"] for l in ana.get(f"/api/leads/?company={self.company.pk}&meus=1").json()["results"]]
        self.assertIn(criado["id"], meus)
        self.assertEqual(ana.post(f"/api/leads/enviar-despachos/?company={self.company.pk}").json(), {"enviados": 1})
        self.assertEqual(Lead.objects.get(pk=criado["id"]).desfecho, "comprometido")

    def test_resumo_lista_concluidos_com_classificacao_e_filtros(self):
        agora = timezone.now()
        ok = self.lead("+5585977770010", owner=self.ana, mode="HUMANO", desfecho="encerrado", especialidade="Trabalhista", priority="Alta", concluido_em=agora)
        self.lead("+5585977770011", owner=self.bia, mode="HUMANO", desfecho="falha", especialidade="Consumidor", concluido_em=agora - timedelta(hours=1))
        self.lead("+5585977770012", temperature="Desqualificado", desfecho="desqualificado", concluido_em=agora)
        self.lead("+5585977770013", owner=self.ana, mode="HUMANO", etapa_atendimento="negociacao")
        empresa = self.cliente(self.empresa)
        data = empresa.get(f"/api/leads/resumo/?company={self.company.pk}&dias=all").json()
        self.assertEqual(data["sucesso"], 1)
        self.assertEqual([c["desfecho"] for c in data["concluidos"]], ["encerrado", "falha"])
        primeiro = data["concluidos"][0]
        self.assertEqual(primeiro["id"], str(ok.pk))
        self.assertEqual((primeiro["temperature"], primeiro["priority"], primeiro["especialidade"], primeiro["owner"]), ("Quente", "Alta", "Trabalhista", "Ana"))
        self.assertIsNotNone(primeiro["concluido_em"])
        # Totais batem com a lista e com os tiles.
        self.assertEqual(len(data["concluidos"]), sum(data["desfechos"].values()))
        self.assertEqual(len(data["concluidos"]), data["status"]["despachado"])
        self.assertEqual(data["desqualificados"], data["status"]["desqualificado"])
        # Mesmo filtro de área do resto do resumo.
        filtrado = empresa.get(f"/api/leads/resumo/?company={self.company.pk}&dias=all&area=Trabalhista").json()
        self.assertEqual([c["id"] for c in filtrado["concluidos"]], [str(ok.pk)])
        self.assertEqual(filtrado["sucesso"], 1)

    def test_resumo_triagem_concluida_nao_conta_cadastro_manual(self):
        self.lead("+5585977770020")
        self.lead("+5585977770021", origem_manual=True, mode="HUMANO", owner=self.ana)
        data = self.cliente(self.empresa).get(f"/api/leads/resumo/?company={self.company.pk}&dias=all").json()
        self.assertEqual(data["triagem_concluida"], 1)
        self.assertEqual(data["total"], 2)


class AgenteContextoEUrgenciaTests(TestCase):
    """Número do agente, GET /agente/contexto/ e CLASSIFICADO por notas × pesos."""
    def setUp(self):
        from django.contrib.auth.models import Group
        from rest_framework.authtoken.models import Token
        self.company = Company.objects.create(name="Rufus Teste", numero_agente="+5586994238125", agente_conversacional=False)
        self.other = Company.objects.create(name="Outra")
        Area.objects.create(company=self.company, name="Trabalhista")
        Area.objects.create(company=self.company, name="Consumidor")
        self.v_alta = Variavel.objects.create(company=self.company, name="Situação", peso=9)
        self.v_media = Variavel.objects.create(company=self.company, name="Renda", peso=7)
        self.v_baixa = Variavel.objects.create(company=self.company, name="Avaliar", peso=4)
        Question.objects.create(company=self.company, question_id="apresentacao", text="Olá, {empresa}!")
        Question.objects.create(company=self.company, question_id="validar", text="Confirma?")
        Question.objects.create(company=self.company, question_id="encerramento", text="Obrigado.")
        Question.objects.create(company=self.company, question_id="nome", text="Seu nome?", ordem=0, obrigatoria=True)
        Question.objects.create(company=self.company, question_id="situacao", text="Qual a situação?", ordem=1, obrigatoria=True, variavel=self.v_alta)
        Question.objects.create(company=self.company, question_id="afetou_renda", text="Afetou a renda?", ordem=2, variavel=self.v_media)
        Question.objects.create(company=self.company, question_id="vazia", text="", ordem=3, variavel=self.v_media)
        Question.objects.create(company=self.company, question_id="avaliar", text="Quer avaliação?", ordem=4, variavel=self.v_baixa)
        agente = get_user_model().objects.create_user(username="agente.rufus-teste")
        agente.groups.add(Group.objects.get_or_create(name="agente")[0])
        self.company.members.add(agente)
        self.agent_client = APIClient()
        self.agent_client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=agente).key}")

    def send(self, mid, contact="+5585911113333", **kwargs):
        data = {"contact": contact, "message_id": mid, "kind": "text", "marker": "Q", "question_id": "apresentacao",
                "fields": {}, "human_required": False, "reason": "pedido humano", **kwargs}
        return receive(self.company, data)

    def ate_validar(self, contact="+5585911113333"):
        for i, kw in enumerate([{}, {"marker": "ATUALIZAR", "fields": {"nome": "Ana", "proxima": "situacao"}},
                                {"marker": "VALIDAR", "fields": {"tema": "verbas"}}], start=1):
            r = self.send(f"v{i}", contact=contact, **kw)
            Event.objects.filter(pk=r["event_id"]).update(delivery="SENT")

    def test_mensagem_do_proprio_numero_do_agente_nao_cria_lead_nem_evento(self):
        r = self.send("1", contact="+5586994238125")
        self.assertEqual(r, {"action": "NO_REPLY", "proprio_numero": True})
        self.assertEqual(Lead.objects.count(), 0)
        self.assertEqual(Event.objects.count(), 0)

    def test_lead_novo_nasce_sem_dono(self):
        self.send("1")
        self.assertIsNone(Lead.objects.get().owner)

    def test_contexto_do_agente_lista_roteiro_areas_e_faixas(self):
        resp = self.agent_client.get(f"/api/companies/{self.company.pk}/agente/contexto/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["empresa"], "Rufus Teste")
        self.assertFalse(body["agente_conversacional"])
        self.assertEqual(body["numero_agente"], "+5586994238125")
        self.assertEqual(body["areas"], ["Consumidor", "Trabalhista"])
        self.assertEqual([p["question_id"] for p in body["perguntas"]], ["nome", "situacao", "afetou_renda", "avaliar"])
        situacao = body["perguntas"][1]
        self.assertEqual(situacao["variavel"], {"nome": "Situação", "peso": 9})
        self.assertTrue(situacao["obrigatoria"])
        self.assertEqual({q["question_id"] for q in body["fora_do_fluxo"]}, {"apresentacao", "validar", "encerramento"})
        textos = {q["question_id"]: q["texto"] for q in body["fora_do_fluxo"]}
        self.assertEqual(textos["apresentacao"], "Olá, {empresa}!")
        self.assertEqual(body["faixas_urgencia"][0], {"min": 0, "max_exclusivo": 3, "temperatura": "Desqualificado"})
        self.assertEqual(body["faixas_urgencia"][-1], {"min": 9, "max_exclusivo": None, "temperatura": "Quente"})
        self.assertEqual(Lead.objects.count(), 0)
        self.assertEqual(Event.objects.count(), 0)

    def test_contexto_de_outra_empresa_da_404(self):
        self.assertEqual(self.agent_client.get(f"/api/companies/{self.other.pk}/agente/contexto/").status_code, 404)
        self.assertEqual(APIClient().get(f"/api/companies/{self.company.pk}/agente/contexto/").status_code, 401)

    def test_contexto_liberado_para_membro_humano(self):
        humano = get_user_model().objects.create_user(username="atendente-ctx")
        self.company.members.add(humano)
        c = APIClient()
        c.force_authenticate(humano)
        self.assertEqual(c.get(f"/api/companies/{self.company.pk}/agente/contexto/").status_code, 200)

    def test_classificado_por_notas_calcula_no_crm_e_prevalece_sobre_temperatura_do_agente(self):
        self.ate_validar()
        r = self.send("c", marker="CLASSIFICADO", fields={
            "notas": {"situacao": 8, "afetou_renda": 10, "avaliar": 6, "desconhecida": 10, "nome": 10},
            "temperatura": "Desqualificado",
        })
        self.assertEqual(r["action"], "TEXTO")
        lead = Lead.objects.get()
        self.assertEqual(lead.temperature, "Qualificado")
        self.assertEqual(lead.priority, "Média")
        self.assertTrue(lead.bot_closed)
        # Detalhamento (variável do sistema, peso 3): nota calculada pelo CRM entra na mesma média.
        self.assertEqual(lead.urgencia_detalhe, {
            "notas": {"situacao": 8.0, "afetou_renda": 10.0, "avaliar": 6.0, "_detalhamento": 1.2},
            "pesos": {"situacao": 9, "afetou_renda": 7, "avaliar": 4, "_detalhamento": 3},
            "nomes": {"situacao": "Situação", "afetou_renda": "Renda", "avaliar": "Avaliar", "_detalhamento": "Detalhamento"},
            "score": 7.37,
            "temperatura_calculada": "Qualificado",
        })

    def test_classificado_por_notas_quente_vira_prioridade_alta_e_respeita_prioridade_enviada(self):
        from .services import variavel_detalhamento
        Variavel.objects.filter(pk=variavel_detalhamento(self.company).pk).update(peso=0)  # isola a média das notas
        self.ate_validar()
        self.send("c", marker="CLASSIFICADO", fields={"notas": {"situacao": 10, "avaliar": 9}})
        self.assertEqual((Lead.objects.get().temperature, Lead.objects.get().priority), ("Quente", "Alta"))
        self.ate_validar(contact="+5585911114444")
        self.send("c", contact="+5585911114444", marker="CLASSIFICADO", fields={"notas": {"situacao": 10}, "prioridade": "Baixa"})
        self.assertEqual(Lead.objects.get(contact="+5585911114444").priority, "Baixa")

    def test_detalhamento_nota_calculada_pelo_crm_e_peso_da_empresa_mudam_a_urgencia(self):
        from .services import calcular_detalhamento
        lead = Lead(company=self.company, contact="+5585900000001")
        self.assertEqual(calcular_detalhamento(lead), 0)
        rico = {"tema": "x" * 130, "observacoes": "um; dois; três", "impacto": "perdeu a renda", "nome": "Joana"}
        self.assertEqual(calcular_detalhamento(lead, rico), 9)
        self.ate_validar()
        self.send("c", marker="CLASSIFICADO", fields={"notas": {"situacao": 10, "avaliar": 10}, **rico})
        quente = Lead.objects.get()
        self.assertEqual(quente.urgencia_detalhe["notas"]["_detalhamento"], 9)
        self.assertEqual(quente.temperature, "Quente")
        # Mesmas notas, cliente que contou pouco: o detalhamento baixo puxa a média para baixo.
        self.ate_validar(contact="+5585911115555")
        self.send("c", contact="+5585911115555", marker="CLASSIFICADO", fields={"notas": {"situacao": 10, "avaliar": 10}})
        raso = Lead.objects.get(contact="+5585911115555")
        self.assertLess(raso.urgencia_detalhe["notas"]["_detalhamento"], 3)
        self.assertEqual(raso.temperature, "Qualificado")

    def test_variavel_detalhamento_e_obrigatoria_so_o_peso_muda(self):
        from .services import seed_roteiro_padrao
        empresa = Company.objects.create(name="Nova")
        seed_roteiro_padrao(empresa)
        det = Variavel.objects.get(company=empresa, name="Detalhamento")
        self.assertTrue(det.builtin)
        self.assertEqual(det.peso, 3)
        staff = get_user_model().objects.create_user("emp-det", password="x", is_staff=True)
        empresa.members.add(staff)
        c = APIClient(); c.force_authenticate(staff)
        url = f"/api/variaveis/{det.pk}/?company={empresa.pk}"
        self.assertEqual(c.patch(url, {"name": "Outro"}, format="json").status_code, 400)
        self.assertEqual(c.delete(url).status_code, 400)
        r = c.patch(url, {"peso": 8}, format="json")
        self.assertEqual((r.status_code, r.json()["peso"], r.json()["builtin"]), (200, 8, True))
        self.assertTrue(Variavel.objects.filter(pk=det.pk).exists())

    def test_urgencia_detalhe_de_lead_antigo_ganha_nomes_das_variaveis(self):
        lead = Lead.objects.create(company=self.company, contact="+5585900000002", temperature="Frio",
                                   urgencia_detalhe={"notas": {"situacao": 6}, "pesos": {"situacao": 9}, "score": 6, "temperatura_calculada": "Frio"})
        staff = get_user_model().objects.create_user("emp-nomes", password="x", is_staff=True)
        self.company.members.add(staff)
        c = APIClient(); c.force_authenticate(staff)
        r = c.get(f"/api/leads/{lead.pk}/?company={self.company.pk}")
        self.assertEqual(r.json()["urgencia_detalhe"]["nomes"], {"situacao": "Situação"})

    def test_classificado_com_notas_sem_peso_reinicia_triagem(self):
        self.ate_validar()
        r = self.send("c", marker="CLASSIFICADO", fields={"notas": {"nome": 10, "inexistente": 9}})
        self.assertEqual(r["action"], "NO_REPLY")
        self.assertTrue(r["lead_apagado"])
        self.assertEqual(Lead.objects.count(), 0)

    def test_classificado_exige_notas_ou_temperatura_e_prioridade(self):
        from .serializers import IncomingSerializer
        base = {"contact": "+5585911113333", "message_id": "x", "marker": "CLASSIFICADO"}
        self.assertFalse(IncomingSerializer(data={**base, "fields": {}}).is_valid())
        self.assertFalse(IncomingSerializer(data={**base, "fields": {"temperatura": "Quente"}}).is_valid())
        self.assertFalse(IncomingSerializer(data={**base, "fields": {"notas": {"situacao": 11}}}).is_valid())
        self.assertTrue(IncomingSerializer(data={**base, "fields": {"notas": {"situacao": 7}}}).is_valid())
        self.assertTrue(IncomingSerializer(data={**base, "fields": {"temperatura": "Quente", "prioridade": "Alta"}}).is_valid())

    def test_numero_fica_mudo_apos_classificado_ate_o_despacho(self):
        from .services import preparar_despacho, enviar_despachos
        self.ate_validar()
        self.send("c", marker="CLASSIFICADO", fields={"notas": {"situacao": 8}})
        self.assertEqual(self.send("depois-1", marker="REPETIR")["action"], "NO_REPLY")
        lead = Lead.objects.get()
        atendente = get_user_model().objects.create_user(username="atendente-mudo")
        self.company.members.add(atendente)
        lead.owner = atendente
        lead.mode = "HUMANO"
        lead.save()
        self.assertIsNone(preparar_despacho(lead.pk, "encerrado", atendente))
        self.assertEqual(enviar_despachos(atendente, self.company), 1)
        r = self.send("depois-2")
        self.assertEqual(r["action"], "TEXTO")
        self.assertNotEqual(r["lead_id"], str(lead.pk))

class ContatoFecharDonoPendenciasTests(TestCase):
    """GET /agente/contato/, lead_novo + apresentação forçada, fechar lead (apaga),
    espera compartilhada, dono ao negociar/devolver e Pendências."""
    def setUp(self):
        from django.contrib.auth.models import Group
        from rest_framework.authtoken.models import Token
        self.company = Company.objects.create(name="Contato Teste", numero_agente="+5586994238125")
        self.other = Company.objects.create(name="Outra")
        for qid, text in [("apresentacao", "Olá!"), ("nome", "Seu nome?"), ("validar", "Confirma?"), ("encerramento", "Obrigado.")]:
            Question.objects.create(company=self.company, question_id=qid, text=text)
        agente = get_user_model().objects.create_user(username="agente.contato-teste")
        agente.groups.add(Group.objects.get_or_create(name="agente")[0])
        self.company.members.add(agente)
        self.agent_client = APIClient()
        self.agent_client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=agente).key}")
        self.empresa = get_user_model().objects.create_user(username="empresa@contato.test", is_staff=True)
        self.ana = get_user_model().objects.create_user(username="ana@contato.test")
        self.bia = get_user_model().objects.create_user(username="bia@contato.test")
        self.company.members.add(self.empresa, self.ana, self.bia)

    def send(self, mid, contact="+5585911114444", **kwargs):
        data = {"contact": contact, "message_id": mid, "kind": "text", "marker": "Q", "question_id": "apresentacao",
                "fields": {}, "human_required": False, "reason": "pedido humano", **kwargs}
        r = receive(self.company, data)
        if r.get("event_id"):
            Event.objects.filter(pk=r["event_id"]).update(delivery="SENT")
        return r

    def classificar(self, contact="+5585911114444", temperatura="Quente"):
        self.send(f"{contact}1", contact=contact)
        self.send(f"{contact}2", contact=contact, marker="ATUALIZAR", fields={"nome": "Ana", "proxima": "nome"})
        self.send(f"{contact}3", contact=contact, marker="VALIDAR")
        self.send(f"{contact}4", contact=contact, marker="CLASSIFICADO", fields={"temperatura": temperatura, "prioridade": "Alta"})
        return Lead.objects.filter(contact=contact).latest("created_at")

    def contato(self, contact, client=None, company=None):
        company = company or self.company
        return (client or self.agent_client).get(f"/api/companies/{company.pk}/agente/contato/", {"contact": contact})

    def cliente(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_contato_cobre_todos_os_motivos_com_a_mesma_regra_do_incoming(self):
        r = self.contato("+5585911114444").json()
        self.assertEqual(r, {"contact": "+5585911114444", "lead_id": None, "aceita_agente": True, "motivo": "sem_lead", "ultima_pergunta": None, "repeticoes": 0, "especialidade": "", "pergunta_inicial": "apresentacao", "conversa_livre_restante": 0, "campos": {}, "variaveis_roteiro": {}, "observacoes": "", "pode_classificar": False, "perguntas_obrigatorias_pendentes": [], "notas_urgencia": {}, "atendimento_humano_habilitado": True, "pedido_humano_pendente": False, "variaveis_humano_pendentes": []})
        self.send("a1")
        self.send("a2", marker="ATUALIZAR", fields={"proxima": "nome"})
        r = self.contato("+5585911114444").json()
        self.assertEqual((r["aceita_agente"], r["motivo"], r["ultima_pergunta"]), (True, "em_triagem", "nome"))
        self.assertEqual(r["lead_id"], str(Lead.objects.get().pk))
        self.send("a3", marker="VALIDAR")
        self.send("a4", marker="CLASSIFICADO", fields={"temperatura": "Quente", "prioridade": "Alta"})
        r = self.contato("+5585911114444").json()
        self.assertEqual((r["aceita_agente"], r["motivo"], r["ultima_pergunta"]), (False, "classificado", None))
        # /incoming/ concorda: classificado -> NO_REPLY.
        self.assertEqual(self.send("a5")["action"], "NO_REPLY")
        self.assertEqual(self.contato("+5586994238125").json()["motivo"], "proprio_numero")
        self.assertFalse(self.contato("+5586994238125").json()["aceita_agente"])

    def test_contato_humano_e_desqualificado_liberado(self):
        self.send("h1", contact="+5585900000001", human_required=True)
        self.assertEqual(self.contato("+5585900000001").json()["motivo"], "humano")
        self.classificar(contact="+5585900000002", temperatura="Desqualificado")
        r = self.contato("+5585900000002").json()
        self.assertEqual((r["aceita_agente"], r["motivo"]), (True, "sem_lead"))

    def test_contato_permissoes_e_validacao(self):
        self.assertEqual(self.contato("5585911114444").status_code, 400)
        self.assertEqual(self.contato("+5585911114444", company=self.other).status_code, 404)
        self.assertEqual(self.contato("+5585911114444", client=self.cliente(self.ana)).status_code, 200)
        self.assertEqual(Lead.objects.count(), 0)

    def test_lead_novo_sempre_comeca_pela_apresentacao(self):
        r = self.send("n1", marker="ATUALIZAR", fields={"nome": "Zé", "proxima": "nome"})
        self.assertEqual((r["action"], r["question_id"], r["content"], r["lead_novo"]), ("TEXTO", "apresentacao", "Olá!", True))
        lead = Lead.objects.get()
        self.assertEqual((lead.state, lead.name), ("apresentacao", ""))
        r2 = self.send("n2", marker="ATUALIZAR", fields={"nome": "Zé", "proxima": "nome"})
        self.assertEqual((r2["question_id"], r2["lead_novo"]), ("nome", False))

    def test_fechar_lead_apaga_e_reinicia_triagem(self):
        lead = self.classificar()
        self.assertGreater(Event.objects.filter(lead=lead).count(), 0)
        # Atendente não fecha; Empresa fecha (apaga lead + eventos).
        self.assertEqual(self.cliente(self.ana).delete(f"/api/leads/{lead.pk}/?company={self.company.pk}").status_code, 403)
        self.assertEqual(self.cliente(self.empresa).delete(f"/api/leads/{lead.pk}/?company={self.company.pk}").status_code, 204)
        self.assertFalse(Lead.objects.filter(pk=lead.pk).exists())
        self.assertEqual(Event.objects.filter(lead_id=lead.pk).count(), 0)
        self.assertEqual(self.contato("+5585911114444").json()["motivo"], "sem_lead")
        r = self.send("depois", marker="REPETIR")
        self.assertEqual((r["action"], r["question_id"], r["lead_novo"]), ("TEXTO", "apresentacao", True))

    def test_espera_sem_dono_pode_ser_devolvida_e_assumida_por_outro_atendente(self):
        lead = self.classificar()
        ana, bia = self.cliente(self.ana), self.cliente(self.bia)
        r = ana.post(f"/api/leads/{lead.pk}/reivindicar/?company={self.company.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["owner"], r.json()["etapa_atendimento"]), (None, "espera"))
        # Em espera é compartilhado: Bia pode devolver um card movido pela Ana.
        r = bia.post(f"/api/leads/{lead.pk}/liberar/?company={self.company.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["owner"], r.json()["etapa_atendimento"]), (None, ""))
        self.assertEqual(bia.post(f"/api/leads/{lead.pk}/reivindicar/?company={self.company.pk}").json()["owner"], None)
        # Ana assume a fila da Bia, e só então fica restrito à responsável.
        r = ana.post(f"/api/leads/{lead.pk}/negociar/?company={self.company.pk}")
        self.assertEqual((r.status_code, r.json()["owner"]), (200, self.ana.pk))
        self.assertEqual(bia.post(f"/api/leads/{lead.pk}/negociar/?company={self.company.pk}").status_code, 400)
        self.assertEqual(bia.post(f"/api/leads/{lead.pk}/liberar/?company={self.company.pk}").status_code, 400)

    def test_pendencias_lista_classificados_e_em_espera_com_em_espera_primeiro(self):
        espera = self.classificar(contact="+5585900000011", temperatura="Qualificado")
        classif = self.classificar(contact="+5585900000012", temperatura="Quente")
        negoc = self.classificar(contact="+5585900000013")
        self.classificar(contact="+5585900000014", temperatura="Desqualificado")
        self.send("t1", contact="+5585900000015")  # ainda em triagem
        ana = self.cliente(self.ana)
        ana.post(f"/api/leads/{espera.pk}/reivindicar/?company={self.company.pk}")
        ana.post(f"/api/leads/{negoc.pk}/negociar/?company={self.company.pk}")
        ids = [l["id"] for l in ana.get(f"/api/leads/?company={self.company.pk}&pending=1").json()["results"]]
        self.assertEqual(ids, [str(espera.pk), str(classif.pk)])
        # "Pegar Lead" (negociar) tira de Pendências e leva pra Meus Atendimentos.
        ana.post(f"/api/leads/{classif.pk}/negociar/?company={self.company.pk}")
        meus = [l["id"] for l in ana.get(f"/api/leads/?company={self.company.pk}&meus=1").json()["results"]]
        self.assertIn(str(classif.pk), meus)
        pend = [l["id"] for l in ana.get(f"/api/leads/?company={self.company.pk}&pending=1").json()["results"]]
        self.assertEqual(pend, [str(espera.pk)])

    def test_espera_nao_aparece_em_meus_atendimentos_nem_no_desempenho_do_atendente(self):
        lead = self.classificar()
        ana, bia = self.cliente(self.ana), self.cliente(self.bia)
        r = ana.post(f"/api/leads/{lead.pk}/reivindicar/?company={self.company.pk}")
        self.assertEqual(r.status_code, 200)
        for client in [ana, bia]:
            self.assertEqual(client.get(f"/api/leads/?company={self.company.pk}&meus=1").json()["count"], 0)
            pendentes = client.get(f"/api/leads/?company={self.company.pk}&pending=1").json()["results"]
            self.assertEqual([(p["id"], p["owner"]) for p in pendentes], [(str(lead.pk), None)])
        self.assertEqual(ana.get(f"/api/leads/resumo/?company={self.company.pk}").json()["por_owner"], [])

    def test_triagem_ainda_ativa_nao_pode_ir_para_espera(self):
        self.send("triagem")
        lead = Lead.objects.get()
        r = self.cliente(self.ana).post(f"/api/leads/{lead.pk}/reivindicar/?company={self.company.pk}")
        self.assertEqual(r.status_code, 400)
        lead.refresh_from_db()
        self.assertEqual((lead.owner, lead.etapa_atendimento, lead.bot_closed), (None, "", False))

    def test_migracao_retira_dono_apenas_dos_leads_ativos_em_espera(self):
        from importlib import import_module
        from types import SimpleNamespace
        from django.apps import apps
        from django.db import connection
        espera = Lead.objects.create(company=self.company, contact="+5585900000101", owner=self.ana, bot_closed=True, etapa_atendimento="espera")
        negociacao = Lead.objects.create(company=self.company, contact="+5585900000102", owner=self.ana, bot_closed=True, etapa_atendimento="negociacao")
        concluido = Lead.objects.create(company=self.company, contact="+5585900000103", owner=self.bia, bot_closed=True, etapa_atendimento="espera", desfecho="encerrado")
        migration = import_module("crm.migrations.0031_espera_sem_responsavel")
        migration.liberar_espera(apps, SimpleNamespace(connection=connection))
        espera.refresh_from_db()
        negociacao.refresh_from_db()
        concluido.refresh_from_db()
        self.assertIsNone(espera.owner)
        self.assertEqual(espera.etapa_atendimento, "espera")
        self.assertEqual(negociacao.owner, self.ana)
        self.assertEqual(concluido.owner, self.bia)

class AcompanharTriagemEPedidoHumanoTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        self.company = Company.objects.create(name="Acompanhar triagem")
        self.other = Company.objects.create(name="Outra triagem")
        self.ana = get_user_model().objects.create_user(username="ana-acompanhar")
        self.bia = get_user_model().objects.create_user(username="bia-acompanhar")
        self.empresa = get_user_model().objects.create_user(username="empresa-acompanhar", is_staff=True)
        self.agente = get_user_model().objects.create_user(username="agente-acompanhar")
        self.agente.groups.add(Group.objects.get_or_create(name="agente")[0])
        self.company.members.add(self.ana, self.bia, self.empresa, self.agente)
        self.lead = Lead.objects.create(company=self.company, contact="+5585900000201", state="nome")

    def client_for(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def url(self):
        return f"/api/leads/{self.lead.pk}/acompanhar/?company={self.company.pk}"

    def test_acompanhar_assume_novo_lead_sem_dados_e_para_o_agente(self):
        ana = self.client_for(self.ana)
        r = ana.post(self.url())
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["owner"], r.json()["mode"], r.json()["etapa_atendimento"]), (self.ana.pk, "HUMANO", "negociacao"))
        self.lead.refresh_from_db()
        self.assertFalse(self.lead.bot_closed)  # assumir não inventa uma classificação
        self.assertEqual((self.lead.state, self.lead.name, self.lead.demand, self.lead.temperature), ("nome", "", "", ""))
        self.assertTrue(self.lead.events.filter(summary="Atendente assumiu atendimento durante a triagem").exists())
        meus = ana.get(f"/api/leads/?company={self.company.pk}&meus=1").json()["results"]
        self.assertEqual([l["id"] for l in meus], [str(self.lead.pk)])
        result = receive(self.company, {"contact": self.lead.contact, "message_id": "apos-acompanhar", "marker": "Q", "question_id": "nome", "kind": "text", "fields": {}, "human_required": False, "reason": "pedido humano"})
        self.assertEqual(result["action"], "NO_REPLY")
        self.assertEqual(self.client_for(self.bia).post(self.url()).status_code, 400)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.owner, self.ana)

    def test_acompanhar_respeita_perfis_e_empresa(self):
        for user in [self.empresa, self.agente]:
            with self.subTest(user=user.username):
                self.assertEqual(self.client_for(user).post(self.url()).status_code, 403)
        self.assertEqual(self.client_for(self.ana).post(f"/api/leads/{self.lead.pk}/acompanhar/?company={self.other.pk}").status_code, 404)
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.owner)
        self.assertEqual(self.lead.mode, "AUTOMÁTICO")

    def test_acompanhar_nao_reabre_classificados_desqualificados_ou_concluidos(self):
        for changes in [{"bot_closed": True}, {"temperature": "Desqualificado"}, {"desfecho": "encerrado"}, {"mode": "HUMANO"}, {"etapa_atendimento": "espera"}, {"origem_manual": True}]:
            with self.subTest(changes=changes):
                Lead.objects.filter(pk=self.lead.pk).update(bot_closed=False, temperature="", desfecho="", mode="AUTOMÁTICO", etapa_atendimento="", origem_manual=False)
                Lead.objects.filter(pk=self.lead.pk).update(**changes)
                self.assertEqual(self.client_for(self.ana).post(self.url()).status_code, 400)
                self.lead.refresh_from_db()
                self.assertIsNone(self.lead.owner)

    def test_pedido_humano_preenche_demanda_e_registra_motivo_sem_qualificar(self):
        result = receive(self.company, {"contact": self.lead.contact, "message_id": "pedido-direto", "marker": "ATUALIZAR", "question_id": "", "kind": "text", "fields": {}, "human_required": True, "reason": "pedido humano"})
        self.assertEqual(result["action"], "NO_REPLY")
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.demand, "Cliente pediu contato direto com atendente humano")
        self.assertEqual((self.lead.name, self.lead.mode, self.lead.temperature, self.lead.owner), ("", "HUMANO", "", None))
        self.assertEqual(self.lead.events.get().summary, "Encaminhado para atendimento humano: pedido humano")

    def test_pedido_humano_preserva_demanda_e_nao_duplica_motivo(self):
        from .services import escalate
        self.lead.demand = "Revisar rescisão"
        escalate(self.lead, "pedido humano")
        self.assertEqual(self.lead.demand, "Revisar rescisão | Cliente pediu contato direto com atendente humano")
        escalate(self.lead, "pedido humano")
        self.assertEqual(self.lead.demand.count("Cliente pediu contato direto com atendente humano"), 1)
        self.lead.demand = "X" * 300
        escalate(self.lead, "pedido humano")
        self.assertEqual(len(self.lead.demand), 300)
        self.assertTrue(self.lead.demand.endswith("Cliente pediu contato direto com atendente humano"))

    def test_decisao_profissional_nao_e_registrada_como_pedido_do_cliente(self):
        from .services import escalate
        escalate(self.lead, "decisão profissional")
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.demand, self.lead.next_action), ("", "decisão profissional"))

    def test_migracao_registra_motivo_em_pedidos_existentes_e_e_idempotente(self):
        from importlib import import_module
        from types import SimpleNamespace
        from django.apps import apps
        from django.db import connection
        self.lead.mode = "HUMANO"
        self.lead.next_action = "pedido humano"
        self.lead.save()
        profissional = Lead.objects.create(company=self.company, contact="+5585900000202", mode="HUMANO", next_action="decisão profissional")
        migration = import_module("crm.migrations.0032_demanda_pedido_humano")
        for _ in range(2):
            migration.registrar_pedido_humano(apps, SimpleNamespace(connection=connection))
        self.lead.refresh_from_db()
        profissional.refresh_from_db()
        self.assertEqual(self.lead.demand, "Cliente pediu contato direto com atendente humano")
        self.assertEqual(profissional.demand, "")


class PermissoesValidacaoTests(TestCase):
    """Matriz de permissões validada no dev local: regressões encontradas na varredura por papel."""
    def setUp(self):
        from django.contrib.auth.models import Group
        U = get_user_model()
        self.company = Company.objects.create(name="Empresa Perm")
        self.empresa = U.objects.create_user(username="empresa-perm", is_staff=True)
        self.ana = U.objects.create_user(username="ana-perm")
        self.bia = U.objects.create_user(username="bia-perm")
        self.agente = U.objects.create_user(username="agente-perm")
        self.agente.groups.add(Group.objects.get_or_create(name="agente")[0])
        self.company.members.add(self.empresa, self.ana, self.bia, self.agente)
        self.lead = Lead.objects.create(company=self.company, contact="+5586900001111", owner=self.ana, bot_closed=True, etapa_atendimento="negociacao")
    def client_for(self, user):
        c = APIClient(); c.force_authenticate(user); return c
    def test_agente_nao_lista_equipe(self):
        url = f"/api/companies/{self.company.pk}/equipe/"
        self.assertEqual(self.client_for(self.agente).get(url).status_code, 403)
        self.assertEqual(self.client_for(self.empresa).get(url).status_code, 200)
        self.assertEqual(self.client_for(self.ana).get(url).status_code, 200)
    def test_atendente_so_edita_lead_proprio(self):
        url = f"/api/leads/{self.lead.pk}/?company={self.company.pk}"
        self.assertEqual(self.client_for(self.bia).patch(url, {"priority": "Baixa"}, format="json").status_code, 403)
        self.assertEqual(self.client_for(self.ana).patch(url, {"priority": "Baixa"}, format="json").status_code, 200)
        self.assertEqual(self.client_for(self.empresa).patch(url, {"priority": "Alta"}, format="json").status_code, 200)
        self.assertEqual(self.client_for(self.agente).patch(url, {"priority": "Alta"}, format="json").status_code, 403)
    def test_atendente_edita_apenas_nome_de_lead_sem_dono_sem_assumi_lo(self):
        self.lead.owner = None
        self.lead.etapa_atendimento = "espera"
        self.lead.save()
        url = f"/api/leads/{self.lead.pk}/?company={self.company.pk}"
        bia = self.client_for(self.bia)
        r = bia.patch(url, {"name": "  Maria Silva  "}, format="json")
        self.assertEqual(r.status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.name, "Maria Silva")
        self.assertIsNone(self.lead.owner)
        self.assertEqual(self.lead.etapa_atendimento, "espera")
        self.assertEqual(bia.patch(url, {"name": "Outro", "priority": "Baixa"}, format="json").status_code, 403)
        self.assertEqual(bia.patch(url, {"name": "X" * 161}, format="json").status_code, 400)
        self.assertEqual(self.client_for(self.agente).patch(url, {"name": "Outro"}, format="json").status_code, 403)
        outra = Company.objects.create(name="Outra Perm")
        self.assertEqual(bia.patch(f"/api/leads/{self.lead.pk}/?company={outra.pk}", {"name": "Outro"}, format="json").status_code, 404)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.name, "Maria Silva")
    def test_nome_editavel_durante_triagem_e_classificado_mas_nao_de_outro_responsavel(self):
        url = f"/api/leads/{self.lead.pk}/?company={self.company.pk}"
        bia = self.client_for(self.bia)
        self.assertEqual(bia.patch(url, {"name": "Outro"}, format="json").status_code, 403)
        for bot_closed in [False, True]:
            self.lead.owner = None
            self.lead.bot_closed = bot_closed
            self.lead.etapa_atendimento = ""
            self.lead.save()
            with self.subTest(bot_closed=bot_closed):
                self.assertEqual(bia.patch(url, {"name": "Nome corrigido"}, format="json").status_code, 200)
                self.lead.refresh_from_db()
                self.assertEqual(self.lead.name, "Nome corrigido")
                self.assertIsNone(self.lead.owner)
    def test_convites_so_para_empresa(self):
        url = f"/api/convites/?company={self.company.pk}"
        self.assertEqual(self.client_for(self.ana).get(url).status_code, 403)
        self.assertEqual(self.client_for(self.agente).get(url).status_code, 403)
        self.assertEqual(self.client_for(self.empresa).get(url).status_code, 200)


import os
import shutil
import subprocess
import tempfile
from unittest import mock, skipUnless
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings


def _wav(segundos=1.0):
    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}", "-f", "wav", "pipe:1"],
        check=True, capture_output=True,
    )
    return out.stdout


def _codec(caminho):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name,channels,sample_rate",
                          "-of", "default=nw=1", caminho], check=True, capture_output=True, text=True)
    return out.stdout


class MensagensAudioTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.company = Company.objects.create(name="Empresa Áudio", allow_transcription=True, mensagens_audio=True)
        self.q = Question.objects.create(company=self.company, question_id="apresentacao", text="Olá, aqui é a {empresa}.<br>Vamos começar?")
        Question.objects.create(company=self.company, question_id="nome", text="Qual é o seu nome?")
        self.agente = get_user_model().objects.create_user(username="agente-audio")
        self.company.members.add(self.agente)
        self.empresa = get_user_model().objects.create_user(username="empresa-audio", is_staff=True)
        self.company.members.add(self.empresa)
        self.atendente = get_user_model().objects.create_user(username="atendente-audio")
        self.company.members.add(self.atendente)
    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
    def payload(self, mid="1"):
        return {"contact": "+5585988887777", "message_id": mid, "kind": "text", "marker": "Q", "question_id": "apresentacao", "fields": {}}
    def incoming(self, mid="1"):
        c = APIClient()
        c.force_authenticate(self.agente)
        return c.post(f"/api/companies/{self.company.id}/incoming/", self.payload(mid), format="json")

    def test_tts_quando_nao_ha_gravacao(self):
        with mock.patch("crm.audio.gerar_tts", return_value="tts/abc.ogg") as gerar:
            r = self.incoming()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["action"], "AUDIO")
        self.assertEqual(body["audio_origem"], "tts")
        self.assertEqual(body["audio_url"], "http://testserver/media/tts/abc.ogg")
        self.assertEqual(body["content"], "Olá, aqui é a Empresa Áudio.<br>Vamos começar?")
        self.assertEqual(gerar.call_args[0], ("Olá, aqui é a Empresa Áudio.<br>Vamos começar?", "pt-BR-FranciscaNeural"))
        evento = Event.objects.get(pk=body["event_id"])
        self.assertEqual(evento.result["action"], "AUDIO")
        self.assertEqual(evento.delivery, "PENDING")

    def test_gravacao_da_pergunta_substitui_tts(self):
        self.q.audio_gravado.save("x.ogg", ContentFile(b"OggS"), save=True)
        with mock.patch("crm.audio.gerar_tts") as gerar:
            body = self.incoming().json()
        gerar.assert_not_called()
        self.assertEqual(body["action"], "AUDIO")
        self.assertEqual(body["audio_origem"], "gravado")
        self.assertTrue(body["audio_url"].startswith("http://testserver/media/roteiro_audio/"))

    def test_repeticao_de_pergunta_gravada_fala_prefixo_via_tts(self):
        self.q.audio_gravado.save("x.ogg", ContentFile(b"OggS"), save=True)
        first = self.incoming().json()
        Event.objects.filter(pk=first["event_id"]).update(delivery="SENT")
        client = APIClient()
        client.force_authenticate(self.agente)
        with mock.patch("crm.audio.gerar_tts", return_value="tts/repetida.ogg") as gerar:
            body = client.post(f"/api/companies/{self.company.id}/incoming/", {**self.payload("2"), "marker": "REPETIR"}, format="json").json()
        expected = "Por favor, responda novamente. Olá, aqui é a Empresa Áudio.<br>Vamos começar?"
        gerar.assert_called_once_with(expected, self.company.voz_tts)
        self.assertEqual((body["action"], body["audio_origem"], body["content"]), ("AUDIO", "tts", expected))

    def test_mensagem_humana_personalizada_fala_dados_via_tts(self):
        question = Question.objects.create(company=self.company, question_id="necessidade_humana", text="{nome}, vou chamar um atendente.")
        question.audio_gravado.save("humano.ogg", ContentFile(b"OggS"), save=True)
        client = APIClient()
        client.force_authenticate(self.agente)
        with mock.patch("crm.audio.gerar_tts", return_value="tts/humano.ogg") as gerar:
            body = client.post(f"/api/companies/{self.company.id}/incoming/", {
                **self.payload(), "marker": "ATUALIZAR", "human_required": True, "reason": "pedido humano", "fields": {"nome": "Ana"},
            }, format="json").json()
        gerar.assert_called_once_with("Ana, vou chamar um atendente.", self.company.voz_tts)
        self.assertEqual((body["action"], body["audio_origem"]), ("AUDIO", "tts"))

    def test_falha_de_tts_mantem_texto(self):
        with mock.patch("crm.audio.gerar_tts", side_effect=TimeoutError("lento")):
            body = self.incoming().json()
        self.assertEqual(body["action"], "TEXTO")
        self.assertNotIn("audio_url", body)
        self.assertIn("audio_erro", body)
        self.assertEqual(Event.objects.get(pk=body["event_id"]).delivery, "PENDING")

    def test_sem_portao_do_admin_fica_em_texto(self):
        Company.objects.filter(pk=self.company.pk).update(allow_transcription=False)
        with mock.patch("crm.audio.gerar_tts") as gerar:
            body = self.incoming().json()
        gerar.assert_not_called()
        self.assertEqual(body["action"], "TEXTO")

    def test_opcao_desligada_fica_em_texto(self):
        Company.objects.filter(pk=self.company.pk).update(mensagens_audio=False)
        body = self.incoming().json()
        self.assertEqual(body["action"], "TEXTO")
        self.assertNotIn("audio_url", body)

    def test_no_reply_nao_gera_audio(self):
        with mock.patch("crm.audio.gerar_tts", return_value="tts/abc.ogg"):
            self.incoming("1")
            with mock.patch("crm.audio.gerar_tts") as gerar:
                body = self.incoming("1").json()
        gerar.assert_not_called()
        self.assertEqual(body["action"], "NO_REPLY")

    def test_contexto_informa_mensagens_audio(self):
        from .services import contexto_agente
        self.assertTrue(contexto_agente(self.company)["mensagens_audio"])
        Company.objects.filter(pk=self.company.pk).update(allow_transcription=False)
        self.company.refresh_from_db()
        self.assertFalse(contexto_agente(self.company)["mensagens_audio"])

    def test_opcoes_do_agente_exigem_portao_do_admin(self):
        Company.objects.filter(pk=self.company.pk).update(allow_transcription=False, mensagens_audio=False)
        c = APIClient()
        c.force_authenticate(self.empresa)
        r = c.patch(f"/api/companies/{self.company.id}/", {"mensagens_audio": True}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Admin", str(r.json()))
        Company.objects.filter(pk=self.company.pk).update(allow_transcription=True)
        r = c.patch(f"/api/companies/{self.company.id}/", {"mensagens_audio": True, "voz_tts": "pt-BR-AntonioNeural"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["mensagens_audio"])
        self.assertEqual(r.json()["voz_tts"], "pt-BR-AntonioNeural")
        r = c.patch(f"/api/companies/{self.company.id}/", {"voz_tts": "en-US-Inventada"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_upload_converte_para_ogg_opus_e_remove(self):
        c = APIClient()
        c.force_authenticate(self.empresa)
        arquivo = SimpleUploadedFile("teste.wav", _wav(1.5), content_type="audio/wav")
        r = c.post(f"/api/questions/{self.q.id}/audio/?company={self.company.id}", {"arquivo": arquivo}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.q.refresh_from_db()
        self.assertTrue(self.q.audio_gravado.name.endswith(".ogg"))
        info = _codec(self.q.audio_gravado.path)
        self.assertIn("codec_name=opus", info)
        self.assertIn("channels=1", info)
        self.assertIn("sample_rate=48000", info)
        self.assertTrue(r.json()["audio_gravado"])
        servido = Client().get("/media/" + self.q.audio_gravado.name)
        self.assertEqual(servido.status_code, 200)
        caminho = self.q.audio_gravado.path
        r = c.delete(f"/api/questions/{self.q.id}/audio/?company={self.company.id}")
        self.assertEqual(r.status_code, 200)
        self.q.refresh_from_db()
        self.assertFalse(self.q.audio_gravado)
        self.assertFalse(os.path.exists(caminho))

    def test_upload_recusa_longo_vazio_e_nao_audio(self):
        c = APIClient()
        c.force_authenticate(self.empresa)
        url = f"/api/questions/{self.q.id}/audio/?company={self.company.id}"
        longo = SimpleUploadedFile("longo.wav", _wav(125), content_type="audio/wav")
        self.assertEqual(c.post(url, {"arquivo": longo}, format="multipart").status_code, 400)
        texto = SimpleUploadedFile("x.txt", b"nao sou audio", content_type="text/plain")
        self.assertEqual(c.post(url, {"arquivo": texto}, format="multipart").status_code, 400)
        quebrado = SimpleUploadedFile("x.mp3", b"nao sou audio", content_type="audio/mpeg")
        self.assertEqual(c.post(url, {"arquivo": quebrado}, format="multipart").status_code, 400)
        self.assertEqual(c.post(url, {}, format="multipart").status_code, 400)

    def test_atendente_e_agente_nao_gravam(self):
        url = f"/api/questions/{self.q.id}/audio/?company={self.company.id}"
        for user in (self.atendente, self.agente):
            c = APIClient()
            c.force_authenticate(user)
            arquivo = SimpleUploadedFile("t.wav", _wav(1), content_type="audio/wav")
            self.assertEqual(c.post(url, {"arquivo": arquivo}, format="multipart").status_code, 403)

    def test_media_de_audio_servida_e_restrita(self):
        from django.core.files.storage import default_storage
        default_storage.save("tts/abc.ogg", ContentFile(b"OggS"))
        servido = Client().get("/media/tts/abc.ogg")
        self.assertEqual(servido.status_code, 200)
        self.assertEqual(servido["Content-Type"], "audio/ogg")
        self.assertEqual(Client().get("/media/tts/../settings.py").status_code, 404)

    def test_texto_para_fala_remove_marcacao(self):
        from .audio import texto_para_fala
        self.assertEqual(texto_para_fala("Nome: Ana<br>Área: X<br/><b>ok</b>"), "Nome: Ana. Área: X. ok")

    def test_gerar_tts_usa_cache(self):
        from . import audio
        def falso_sintetizar(texto, voz, destino, timeout):
            subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", destino], check=True)
        with mock.patch("crm.audio.sintetizar", side_effect=falso_sintetizar) as sint:
            a = audio.gerar_tts("Olá<br>mundo", "pt-BR-FranciscaNeural")
            b = audio.gerar_tts("Olá<br>mundo", "pt-BR-FranciscaNeural")
        self.assertEqual(a, b)
        self.assertEqual(sint.call_count, 1)
        self.assertIn("codec_name=opus", _codec(os.path.join(self.media, a)))

    @skipUnless(os.environ.get("RUN_NETWORK_TESTS") == "1", "TTS real (edge-tts) precisa de rede: RUN_NETWORK_TESTS=1")
    def test_tts_real_edge(self):
        from . import audio
        relativo = audio.gerar_tts("Olá! Este é um teste de voz.", "pt-BR-FranciscaNeural")
        self.assertIn("codec_name=opus", _codec(os.path.join(self.media, relativo)))


class SpinPorAreaTests(TestCase):
    """Perguntas fixas + listas {Área}-SPIN: modelo, validações, contrato do agente e reorder."""
    def setUp(self):
        from django.contrib.auth.models import Group
        from rest_framework.authtoken.models import Token
        from .services import seed_roteiro_padrao
        self.company = Company.objects.create(name="Rufus SPIN")
        self.other = Company.objects.create(name="Outra SPIN")
        seed_roteiro_padrao(self.company)
        Question.objects.filter(company=self.company).exclude(text__gt="").update(text="texto")
        self.trab = Area.objects.create(company=self.company, name="Trabalhista")
        self.cons = Area.objects.create(company=self.company, name="Consumidor")
        self.prev = Area.objects.create(company=self.company, name="Previdenciário")
        self.area_outra = Area.objects.create(company=self.other, name="Trabalhista")
        self.v = Variavel.objects.get(company=self.company, name="Geral")
        self.tema = VariavelRoteiro.objects.get(company=self.company, slug="tema")
        empresa = get_user_model().objects.create_user(username="empresa.spin", is_staff=True)
        self.company.members.add(empresa)
        self.client = APIClient()
        self.client.force_authenticate(empresa)
        agente = get_user_model().objects.create_user(username="agente.spin")
        agente.groups.add(Group.objects.get_or_create(name="agente")[0])
        self.company.members.add(agente)
        self.agent = APIClient()
        self.agent.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=agente).key}")

    def criar(self, question_id, area=None, etapa="", ordem=0, **extra):
        return Question.objects.create(company=self.company, question_id=question_id, text=f"{question_id}?", variavel=self.v,
                                       area=area, etapa_spin=etapa, ordem=ordem, **extra)

    def post(self, **data):
        return self.client.post(f"/api/questions/?company={self.company.id}", {"variavel": self.v.id, "text": "x", **data}, format="json")

    def patch(self, q, **data):
        return self.client.patch(f"/api/questions/{q.id}/?company={self.company.id}", data, format="json")

    def test_criar_pergunta_spin_e_validacoes(self):
        r = self.post(question_id="trab_situacao", area=self.trab.id, etapa_spin="situacao")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["area"], r.json()["etapa_spin"]), (self.trab.id, "situacao"))
        self.assertEqual(self.post(question_id="x1", area=self.area_outra.id).status_code, 400)
        duplicada = self.post(question_id="trab_situacao", area=self.trab.id)
        self.assertEqual(duplicada.status_code, 400)
        self.assertIn("question_id", duplicada.json())
        self.assertEqual(self.post(question_id="x2", etapa_spin="problema").status_code, 400)
        nome = Question.objects.get(company=self.company, question_id="nome")
        situacao = Question.objects.get(company=self.company, question_id="situacao")
        apresentacao = Question.objects.get(company=self.company, question_id="apresentacao")
        for q in (nome, situacao, apresentacao):
            self.assertEqual(self.patch(q, area=self.trab.id).status_code, 400, q.question_id)
        demanda = Question.objects.get(company=self.company, question_id="demanda")
        self.assertEqual(self.patch(demanda, area=self.trab.id, etapa_spin="problema").status_code, 200)

    def test_tema_builtin_em_no_maximo_uma_pergunta_por_area(self):
        p1 = self.criar("trab_problema", self.trab, "problema")
        self.assertEqual(self.patch(p1, variavel_roteiro=self.tema.id).status_code, 200)
        p2 = self.criar("trab_problema2", self.trab, "problema", ordem=1)
        self.assertEqual(self.patch(p2, variavel_roteiro=self.tema.id).status_code, 400)
        p3 = self.criar("cons_problema", self.cons, "problema")
        self.assertEqual(self.patch(p3, variavel_roteiro=self.tema.id).status_code, 200)
        fixa = self.criar("fixa_extra")
        self.assertEqual(self.patch(fixa, variavel_roteiro=self.tema.id).status_code, 400)
        nome_vr = VariavelRoteiro.objects.get(company=self.company, slug="nome")
        self.assertEqual(self.patch(p3, variavel_roteiro=nome_vr.id).status_code, 400)

    def test_area_com_spin_nao_pode_ser_excluida(self):
        self.criar("trab_situacao", self.trab, "situacao")
        r = self.client.delete(f"/api/areas/{self.trab.id}/?company={self.company.id}")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Trabalhista-SPIN", r.json()["detail"])
        self.assertEqual(self.client.delete(f"/api/areas/{self.prev.id}/?company={self.company.id}").status_code, 204)

    def test_contexto_separa_fixas_e_spin_por_area(self):
        self.criar("trab_problema", self.trab, "problema", ordem=1)
        self.criar("trab_situacao", self.trab, "situacao", ordem=0)
        Question.objects.create(company=self.company, question_id="trab_vazia", text="", variavel=self.v, area=self.trab, ordem=2)
        r = self.agent.get(f"/api/companies/{self.company.id}/agente/contexto/")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(set(data["spin"]), {"Trabalhista", "Consumidor", "Previdenciário"})
        self.assertEqual([q["question_id"] for q in data["spin"]["Trabalhista"]], ["trab_situacao", "trab_problema"])
        self.assertEqual(data["spin"]["Trabalhista"][0]["etapa_spin"], "situacao")
        self.assertEqual(data["spin"]["Consumidor"], [])
        fixas = [q["question_id"] for q in data["perguntas"]]
        self.assertIn("nome", fixas)
        self.assertNotIn("trab_situacao", fixas)

    def send(self, mid, **kw):
        data = {"contact": "+5585977776666", "message_id": mid, "kind": "text", "marker": "Q", "question_id": "apresentacao",
                "fields": {}, "human_required": False, "reason": "pedido humano", **kw}
        r = receive(self.company, data)
        if r.get("event_id"):
            Event.objects.filter(pk=r["event_id"]).update(delivery="SENT")
        return r

    def test_contato_expoe_especialidade_e_incoming_valida_area_do_spin(self):
        self.criar("trab_situacao", self.trab, "situacao")
        self.criar("cons_situacao", self.cons, "situacao")
        self.send("1")
        st = self.agent.get(f"/api/companies/{self.company.id}/agente/contato/?contact=%2B5585977776666").json()
        self.assertEqual(st["especialidade"], "")
        # SPIN antes de classificar a área → erro do agente: triagem reiniciada
        r = self.send("2", marker="ATUALIZAR", fields={"proxima": "trab_situacao"})
        self.assertEqual((r["action"], r.get("lead_apagado")), ("NO_REPLY", True))
        self.assertFalse(Lead.objects.filter(contact="+5585977776666").exists())

    def test_spin_da_area_certa_avanca_e_de_outra_area_reinicia(self):
        self.criar("trab_situacao", self.trab, "situacao")
        self.criar("cons_situacao", self.cons, "situacao")
        self.send("1")
        r = self.send("2", marker="ATUALIZAR", fields={"especialidade": "Trabalhista", "proxima": "trab_situacao"})
        self.assertEqual((r["action"], r["question_id"]), ("TEXTO", "trab_situacao"))
        st = self.agent.get(f"/api/companies/{self.company.id}/agente/contato/?contact=%2B5585977776666").json()
        self.assertEqual(st["especialidade"], "Trabalhista")
        r = self.send("3", marker="ATUALIZAR", fields={"proxima": "cons_situacao"})
        self.assertEqual((r["action"], r.get("lead_apagado")), ("NO_REPLY", True))
        self.assertFalse(Lead.objects.filter(contact="+5585977776666").exists())

    def test_reorder_persiste_ordem_dentro_da_lista(self):
        a = self.criar("trab_a", self.trab, "situacao", ordem=0)
        b = self.criar("trab_b", self.trab, "problema", ordem=1)
        self.assertEqual(self.patch(a, ordem=1).status_code, 200)
        self.assertEqual(self.patch(b, ordem=0).status_code, 200)
        r = self.agent.get(f"/api/companies/{self.company.id}/agente/contexto/").json()
        self.assertEqual([q["question_id"] for q in r["spin"]["Trabalhista"]], ["trab_b", "trab_a"])
        fixa_nome = Question.objects.get(company=self.company, question_id="nome")
        self.assertIsNone(fixa_nome.area)


class BlacklistEFiltragemTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        self.company = Company.objects.create(name="Bloqueios")
        self.other = Company.objects.create(name="Outra empresa")
        self.ana = get_user_model().objects.create_user(username="ana-bloqueios")
        self.bia = get_user_model().objects.create_user(username="bia-bloqueios")
        self.empresa = get_user_model().objects.create_user(username="empresa-bloqueios", is_staff=True)
        self.agente = get_user_model().objects.create_user(username="agente.bloqueios")
        self.agente.groups.add(Group.objects.get_or_create(name="agente")[0])
        self.company.members.add(self.ana, self.bia, self.empresa, self.agente)
        self.contact = "+5585999998888"
        self.client = APIClient()
        self.client.force_authenticate(self.ana)
        for qid in ["apresentacao", "nome", "validar", "encerramento"]:
            Question.objects.create(company=self.company, question_id=qid, text=f"Pergunta {qid}")

    def send(self, mid, **kwargs):
        data = {"contact": self.contact, "message_id": mid, "kind": "text", "marker": "Q", "question_id": "apresentacao",
                "fields": {}, "human_required": False, "reason": "pedido humano", **kwargs}
        result = receive(self.company, data)
        if result.get("event_id"):
            Event.objects.filter(pk=result["event_id"]).update(delivery="SENT")
        return result

    def test_empresa_e_atendentes_adicionam_normalizam_e_removem(self):
        base = f"/api/blacklist/?company={self.company.pk}"
        for user in [self.ana, self.empresa]:
            with self.subTest(user=user.username):
                self.client.force_authenticate(user)
                response = self.client.post(base, {"contact": "(85) 99999-8888", "motivo": "Teste"}, format="json")
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()["contact"], self.contact)
                self.assertEqual(response.json()["adicionado_por"], user.pk)
                self.client.force_authenticate(self.bia)
                self.assertEqual(self.client.get(base).json()["count"], 1)
                self.assertEqual(self.client.post(base, {"contact": self.contact}, format="json").status_code, 400)
                self.assertEqual(self.client.delete(f"/api/blacklist/{response.json()['id']}/?company={self.company.pk}").status_code, 204)
        self.assertEqual(self.client.post(base, {"contact": "abc"}, format="json").status_code, 400)

    def test_blacklist_isolada_e_agente_sem_acesso(self):
        entry = Blacklist.objects.create(company=self.company, contact=self.contact)
        base = f"/api/blacklist/?company={self.company.pk}"
        self.assertEqual(self.client.get(f"/api/blacklist/?company={self.other.pk}").status_code, 404)
        foreign = Blacklist.objects.create(company=self.other, contact=self.contact)
        self.assertEqual(self.client.delete(f"/api/blacklist/{foreign.pk}/?company={self.company.pk}").status_code, 404)
        self.client.force_authenticate(self.agente)
        self.assertEqual(self.client.get(base).status_code, 403)
        self.assertEqual(self.client.post(base, {"contact": self.contact}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(f"/api/blacklist/{entry.pk}/?company={self.company.pk}").status_code, 403)

    def test_bot_ignora_texto_audio_e_marcadores_sem_lead_ou_evento(self):
        Blacklist.objects.create(company=self.company, contact=self.contact)
        self.client.force_authenticate(self.agente)
        status = self.client.get(f"/api/companies/{self.company.pk}/agente/contato/", {"contact": self.contact}).json()
        self.assertEqual((status["aceita_agente"], status["motivo"], status["lead_id"]), (False, "blacklist", None))
        for kind in ["text", "audio"]:
            for marker in ["Q", "REPETIR", "ATUALIZAR", "VALIDAR", "CLASSIFICADO"]:
                result = self.client.post(f"/api/companies/{self.company.pk}/incoming/", {
                    "contact": self.contact, "message_id": f"{kind}-{marker}", "kind": kind,
                    "marker": marker, "question_id": "apresentacao", "fields": {"temperatura": "Quente", "prioridade": "Alta"},
                }, format="json")
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json(), {"action": "NO_REPLY", "blacklist": True})
        self.assertFalse(Lead.objects.exists())
        self.assertFalse(Event.objects.exists())
        # Mesmo número continua livre na outra empresa.
        self.assertEqual(receive(self.other, {"contact": self.contact, "message_id": "outra", "kind": "text", "marker": "Q",
                                            "question_id": "apresentacao", "fields": {}, "human_required": False})["lead_novo"], True)

    def test_bloqueio_com_lead_ativo_nao_altera_nem_processa_entrada(self):
        self.send("inicial")
        lead = Lead.objects.get()
        Blacklist.objects.create(company=self.company, contact=self.contact)
        before = Event.objects.count()
        self.assertEqual(self.send("bloqueado", marker="VALIDAR")["action"], "NO_REPLY")
        self.assertEqual(Event.objects.count(), before)
        lead.refresh_from_db()
        self.assertEqual(lead.state, "apresentacao")

    def test_despachar_bloquear_e_desbloquear_libera_nova_triagem(self):
        lead = Lead.objects.create(company=self.company, contact=self.contact, bot_closed=True,
                                   owner=self.ana, mode="HUMANO", etapa_atendimento="negociacao", temperature="Quente")
        result = self.client.post(f"/api/leads/{lead.pk}/despachar-bloquear/?company={self.company.pk}", {}, format="json")
        self.assertEqual(result.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual((lead.desfecho, lead.desfecho_pendente, lead.etapa_atendimento), ("bloqueado", "", ""))
        self.assertIsNotNone(lead.concluido_em)
        for filtro in ["ativos", "meus", "pending"]:
            self.assertEqual(self.client.get(f"/api/leads/?company={self.company.pk}&{filtro}=1").json()["count"], 0)
        resumo = self.client.get(f"/api/leads/resumo/?company={self.company.pk}&dias=all").json()
        self.assertEqual(resumo["desfechos"]["bloqueado"], 1)
        self.assertEqual((resumo["por_owner"][0]["concluidos"], resumo["sucesso"]), (1, 0))
        self.assertEqual(self.send("ignorado")["action"], "NO_REPLY")
        entry = Blacklist.objects.get()
        self.client.force_authenticate(self.empresa)
        self.assertEqual(self.client.delete(f"/api/blacklist/{entry.pk}/?company={self.company.pk}").status_code, 204)
        result = self.send("novo", marker="REPETIR")
        self.assertEqual((result["lead_novo"], result["question_id"]), (True, "apresentacao"))
        self.assertNotEqual(result["lead_id"], str(lead.pk))
        lead.refresh_from_db()
        self.assertEqual(lead.desfecho, "bloqueado")

    def test_so_dono_em_meus_atendimentos_bloqueia(self):
        lead = Lead.objects.create(company=self.company, contact=self.contact, bot_closed=True, owner=self.ana, etapa_atendimento="negociacao")
        url = f"/api/leads/{lead.pk}/despachar-bloquear/?company={self.company.pk}"
        for user, code in [(self.bia, 400), (self.empresa, 403), (self.agente, 403)]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.post(url, {}, format="json").status_code, code)
        self.assertFalse(Blacklist.objects.exists())
        self.client.force_authenticate(self.ana)
        lead.etapa_atendimento = "espera"
        lead.save()
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 400)
        lead.etapa_atendimento = "despacho"
        lead.desfecho_pendente = "encerrado"
        lead.save()
        Blacklist.objects.create(company=self.company, contact=self.contact)
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 200)
        self.assertEqual(Blacklist.objects.count(), 1)
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 400)

    def test_atendimento_manual_tambem_pode_bloquear(self):
        lead = Lead.objects.create(company=self.company, contact=self.contact, owner=self.ana, origem_manual=True)
        response = self.client.post(f"/api/leads/{lead.pk}/despachar-bloquear/?company={self.company.pk}", {}, format="json")
        self.assertEqual(response.status_code, 200)
        lead.refresh_from_db()
        self.assertTrue(lead.bot_closed)

    def test_fora_de_escopo_nao_qualifica_nem_fica_alta_em_nenhum_marcador(self):
        # Mesmo sem uma Area "Fora de escopo" cadastrada, sai do funil.
        for marker in ["ATUALIZAR", "VALIDAR", "CLASSIFICADO"]:
            with self.subTest(marker=marker):
                self.send(f"inicio-{marker}")
                result = self.send(marker, marker=marker, fields={"especialidade": "Fora de escopo", "nome": "Ana",
                                    "proxima": "nome", "temperatura": "Quente", "prioridade": "Alta"})
                self.assertEqual(result["action"], "NO_REPLY")
                lead = Lead.objects.get(pk=result["lead_id"])
                self.assertEqual((lead.temperature, lead.priority, lead.desfecho, lead.name), ("Desqualificado", "Baixa", "desqualificado", "Ana"))
                self.assertEqual(self.client.get(f"/api/leads/?company={self.company.pk}&ativos=1").json()["count"], 0)
        self.assertEqual(Lead.objects.count(), 3)
        self.assertTrue(self.send("reinicio")["lead_novo"])

    def test_fora_de_escopo_human_required_e_pedido_humano_distintos(self):
        result = self.send("fora", human_required=True, reason="fora de escopo")
        lead = Lead.objects.get(pk=result["lead_id"])
        self.assertEqual((lead.temperature, lead.priority, lead.desfecho), ("Desqualificado", "Baixa", "desqualificado"))
        self.assertEqual(self.client.get(f"/api/leads/?company={self.company.pk}&pending=1").json()["count"], 0)
        self.send("humano", human_required=True, reason="pedido humano")
        self.assertEqual(self.client.get(f"/api/leads/?company={self.company.pk}&pending=1").json()["count"], 1)

    def test_triagem_sem_last_contact_antiga_e_removida(self):
        from .services import apagar_triagens_abandonadas
        lead = Lead.objects.create(company=self.company, contact=self.contact)
        Lead.objects.filter(pk=lead.pk).update(created_at=timezone.now() - timedelta(days=2))
        self.assertEqual(apagar_triagens_abandonadas(), 1)
        self.assertTrue(self.send("reinicio")["lead_novo"])

    def test_migracao_corrige_legados_sem_apagar_atendimentos_assumidos(self):
        import importlib
        from django.apps import apps
        from django.db import connection
        from types import SimpleNamespace
        fora = Lead.objects.create(company=self.company, contact=self.contact, priority="Alta", mode="HUMANO", next_action="fora de escopo")
        abandonado = Lead.objects.create(company=self.company, contact="+5585999998887", bot_closed=True, temperature="Frio", urgencia_detalhe={"motivo": "abandono"})
        assumido = Lead.objects.create(company=self.company, contact="+5585999998886", bot_closed=True, owner=self.ana, urgencia_detalhe={"motivo": "abandono"})
        corrigir = importlib.import_module("crm.migrations.0030_fora_de_escopo_desqualificado").corrigir
        corrigir(apps, SimpleNamespace(connection=connection))
        fora.refresh_from_db()
        self.assertEqual((fora.priority, fora.temperature, fora.desfecho), ("Baixa", "Desqualificado", "desqualificado"))
        self.assertFalse(Lead.objects.filter(pk=abandonado.pk).exists())
        self.assertTrue(Lead.objects.filter(pk=assumido.pk).exists())
        corrigir(apps, SimpleNamespace(connection=connection))
        self.assertEqual(Lead.objects.count(), 2)


class NecessidadeHumanaTests(TestCase):
    def setUp(self):
        from .services import seed_roteiro_padrao
        self.company = Company.objects.create(name="Empresa Humano")
        self.other = Company.objects.create(name="Outra Humano")
        seed_roteiro_padrao(self.company)
        self.question = Question.objects.get(company=self.company, question_id="necessidade_humana")
        self.nome = self.company.variaveis_roteiro.get(slug="nome")
        self.extra = VariavelRoteiro.objects.create(company=self.company, name="Idade", slug="idade")
        self.user = get_user_model().objects.create_user(username="editor-humano", is_staff=True)
        self.company.members.add(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = f"/api/questions/{self.question.pk}/?company={self.company.pk}"

    def send(self, mid="humano-1", **kwargs):
        return receive(self.company, {
            "contact": "+5585912345678", "message_id": mid, "kind": "text", "marker": "ATUALIZAR",
            "question_id": "", "fields": {}, "human_required": True, "reason": "pedido humano", **kwargs,
        })

    def test_envia_mensagem_uma_vez_e_bloqueia_proximas_respostas(self):
        result = self.send()
        self.assertEqual((result["action"], result["question_id"]), ("TEXTO", "necessidade_humana"))
        self.assertEqual(result["content"], self.question.text)
        lead = Lead.objects.get()
        self.assertEqual((lead.mode, lead.priority), ("HUMANO", "Alta"))
        self.assertFalse(lead.bot_closed)
        self.assertEqual(Event.objects.get(pk=result["event_id"]).delivery, "PENDING")
        self.assertEqual(self.send()["action"], "NO_REPLY")
        self.assertTrue(self.send()["duplicate"])
        self.assertEqual(self.send("humano-2")["action"], "NO_REPLY")
        self.assertEqual(Lead.objects.count(), 1)

    def test_renderiza_dados_recebidos_no_mesmo_pedido(self):
        self.question.text = "{nome}, idade {idade}: vou chamar um atendente."
        self.question.save()
        self.question.variaveis_obrigatorias.set([self.nome, self.extra])
        result = self.send(fields={"nome": "Ana", "variaveis_roteiro": {"idade": "40 anos"}})
        self.assertEqual(result["content"], "Ana, idade 40 anos: vou chamar um atendente.")
        self.assertEqual(Lead.objects.get().variaveis_roteiro, {"idade": "40 anos"})

    def test_variavel_sem_valor_pergunta_e_mantem_automatico(self):
        from .services import status_contato
        self.question.text = "Antes de chamar um atendente, qual é o seu nome?"
        self.question.save()
        self.question.variaveis_obrigatorias.set([self.nome])
        result = self.send()
        self.assertEqual((result["action"], result["question_id"], result["content"]), ("TEXTO", "necessidade_humana", self.question.text))
        lead = Lead.objects.get()
        self.assertEqual((lead.mode, lead.pedido_humano_pendente, lead.bot_closed), ("AUTOMÁTICO", True, False))
        self.assertEqual(lead.demand, "")
        status = status_contato(self.company, lead.contact)
        self.assertTrue(status["aceita_agente"])
        self.assertTrue(status["pedido_humano_pendente"])
        self.assertEqual(status["variaveis_humano_pendentes"], ["nome"])
        # A próxima mensagem não precisa repetir o sinalizador human_required.
        result = self.send("resposta", human_required=False, fields={"nome": "Ana", "proxima": "situacao"})
        self.assertEqual(result["action"], "NO_REPLY")
        lead.refresh_from_db()
        self.assertEqual((lead.name, lead.mode, lead.pedido_humano_pendente), ("Ana", "HUMANO", False))

    def test_coleta_parcial_pede_apenas_proxima_variavel_faltante(self):
        demanda = self.company.variaveis_roteiro.get(slug="tema")
        self.question.text = "Para falar com um atendente, informe seu nome e sua demanda."
        self.question.save()
        self.question.variaveis_obrigatorias.set([self.nome, demanda])
        Question.objects.filter(company=self.company, question_id="demanda").update(text="Qual é a sua demanda?")
        self.send()
        partial = self.send("nome", fields={"nome": "Ana"})
        self.assertEqual((partial["question_id"], partial["content"]), ("demanda", "Qual é a sua demanda?"))
        lead = Lead.objects.get()
        self.assertEqual((lead.mode, lead.demand), ("AUTOMÁTICO", ""))
        final = self.send("demanda", fields={"tema": "Revisão de rescisão"})
        self.assertEqual(final["action"], "NO_REPLY")
        lead.refresh_from_db()
        self.assertEqual(lead.mode, "HUMANO")
        self.assertTrue(lead.demand.startswith("Revisão de rescisão"))

    def test_nao_pula_variaveis_com_classificado_ou_repeticoes(self):
        self.question.variaveis_obrigatorias.set([self.extra])
        self.send()
        for index in range(5):
            result = self.send(str(index), marker="CLASSIFICADO", human_required=False, fields={"temperatura": "Quente", "encerramento_antecipado": True})
            self.assertEqual(result["content"].count("Por favor, responda novamente."), 1)
            lead = Lead.objects.get()
            self.assertEqual((lead.mode, lead.temperature, lead.pedido_humano_pendente, lead.bot_closed), ("AUTOMÁTICO", "", True, False))
        self.send("completo", fields={"variaveis_roteiro": {"idade": "40 anos"}})
        self.assertEqual(Lead.objects.get().mode, "HUMANO")

    def test_nao_transfere_com_valor_em_branco_ou_slug_inventado(self):
        self.question.variaveis_obrigatorias.set([self.extra])
        self.send()
        self.send("incompleto", fields={"variaveis_roteiro": {"idade": "   ", "inexistente": "40 anos"}})
        self.assertEqual(Lead.objects.get().mode, "AUTOMÁTICO")

    def test_api_mantem_pedido_pendente_e_transfere_depois_da_resposta(self):
        self.question.text = "Informe seu nome e sua idade antes do atendimento humano."
        self.question.save()
        self.question.variaveis_obrigatorias.set([self.nome, self.extra])
        url = f"/api/companies/{self.company.pk}/incoming/"
        payload = {"contact": "+5585912345678", "message_id": "pedido", "marker": "ATUALIZAR", "human_required": True, "reason": "pedido humano"}
        first = self.client.post(url, payload, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["question_id"], "necessidade_humana")
        status_url = f"/api/companies/{self.company.pk}/agente/contato/?contact=%2B5585912345678"
        status = self.client.get(status_url).json()
        self.assertTrue(status["aceita_agente"])
        self.assertTrue(status["pedido_humano_pendente"])
        self.assertEqual(set(status["variaveis_humano_pendentes"]), {"nome", "idade"})
        response = self.client.post(url, {
            "contact": payload["contact"], "message_id": "resposta", "marker": "ATUALIZAR",
            "fields": {"nome": "Ana", "variaveis_roteiro": {"idade": "40 anos"}},
        }, format="json")
        self.assertEqual((response.status_code, response.json()["action"]), (200, "NO_REPLY"))
        status = self.client.get(status_url).json()
        self.assertFalse(status["aceita_agente"])
        self.assertFalse(status["pedido_humano_pendente"])
        self.assertEqual(status["motivo"], "humano")

    def test_outros_motivos_nao_disparam_mensagem(self):
        for index, reason in enumerate(["urgência ou risco", "fora de escopo", "falha de integração", "decisão profissional"]):
            with self.subTest(reason=reason):
                result = self.send(str(index), reason=reason, contact=f"+558591234568{index}")
                self.assertEqual(result["action"], "NO_REPLY")

    def test_api_seleciona_dados_sem_exigir_placeholder_na_mensagem(self):
        valid = self.client.patch(self.url, {"text": "Antes de chamar um atendente, qual é o seu nome?", "variaveis_obrigatorias": [self.nome.pk]}, format="json")
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.json()["variaveis_obrigatorias"], [self.nome.pk])
        self.assertEqual(self.client.patch(self.url, {"text": "Informe seu nome, por favor."}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(self.url, {"text": ""}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(self.url, {"variaveis_obrigatorias": [], "text": "Vou chamar um atendente."}, format="json").status_code, 200)

    def test_variavel_de_outra_empresa_e_recusada(self):
        other_variable = VariavelRoteiro.objects.create(company=self.other, name="Segredo", slug="segredo")
        result = self.client.patch(self.url, {"text": "{segredo}", "variaveis_obrigatorias": [other_variable.pk]}, format="json")
        self.assertEqual(result.status_code, 400)
        self.assertIn("variaveis_obrigatorias", result.json())

    def test_nao_exclui_nem_renomeia_mensagem_obrigatoria(self):
        self.assertTrue(self.question.obrigatoria)
        self.assertEqual(self.client.delete(self.url).status_code, 400)
        self.assertEqual(self.client.patch(self.url, {"question_id": "outro_texto"}, format="json").status_code, 400)

    def test_nao_exclui_variavel_selecionada(self):
        self.question.variaveis_obrigatorias.set([self.extra])
        url = f"/api/variaveis-roteiro/{self.extra.pk}/?company={self.company.pk}"
        self.assertEqual(self.client.delete(url).status_code, 400)
        self.question.variaveis_obrigatorias.clear()
        self.assertEqual(self.client.delete(url).status_code, 204)

    def test_seletor_nao_e_aceito_em_outros_textos(self):
        question = Question.objects.get(company=self.company, question_id="apresentacao")
        result = self.client.patch(f"/api/questions/{question.pk}/?company={self.company.pk}", {"variaveis_obrigatorias": [self.nome.pk]}, format="json")
        self.assertEqual(result.status_code, 400)

    def test_contexto_inclui_mensagem_e_slugs_obrigatorios_fora_do_fluxo(self):
        from .services import contexto_agente
        self.question.variaveis_obrigatorias.set([self.nome])
        context = contexto_agente(self.company)
        human = next(q for q in context["fora_do_fluxo"] if q["question_id"] == "necessidade_humana")
        self.assertEqual(human["variaveis_obrigatorias"], ["nome"])
        self.assertNotIn("necessidade_humana", [q["question_id"] for q in context["perguntas"]])

    def test_migracao_e_seed_preservam_texto_existente(self):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection
        from types import SimpleNamespace
        from .services import seed_roteiro_padrao
        self.question.text = "Texto aprovado pela empresa"
        self.question.save()
        migration = import_module("crm.migrations.0033_necessidade_humana")
        for _ in range(2):
            migration.seed_necessidade_humana(apps, SimpleNamespace(connection=connection))
            seed_roteiro_padrao(self.company)
        self.question.refresh_from_db()
        self.assertEqual(self.question.text, "Texto aprovado pela empresa")
        self.assertEqual(Question.objects.filter(question_id="necessidade_humana").count(), 2)
        self.assertTrue(Question.objects.get(company=self.other, question_id="necessidade_humana").obrigatoria)


class AdminContasEmpresaAgenteTests(TestCase):
    """Painel Admin → seletor da empresa: controle da conta do agente e das contas Empresa."""

    def setUp(self):
        from .services import seed_roteiro_padrao
        User = get_user_model()
        self.su = User.objects.create_superuser(username="root-contas", password="x")
        self.empresa = Company.objects.create(name="Contas Ltda")
        seed_roteiro_padrao(self.empresa)
        self.outra = Company.objects.create(name="Outra Contas")
        seed_roteiro_padrao(self.outra)
        self.c = APIClient()
        self.c.force_authenticate(self.su)
        self.base = f"/api/admin-companies/{self.empresa.pk}"

    def gerar_chave(self, company=None):
        company = company or self.empresa
        resp = self.c.post(f"/api/admin-companies/{company.pk}/agente/", {"validade_dias": 30}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()["token"]

    def criar_empresa(self, email="dono@contas.com", nome="Dono da Empresa"):
        resp = self.c.post(f"{self.base}/contas/empresa/", {"email": email, "nome": nome}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        return resp.json()

    def login(self, username, password):
        return APIClient().post("/api/login/", {"username": username, "password": password}, format="json")

    def agente_client(self, token):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        return c

    def test_contas_lista_agente_e_contas_empresa(self):
        self.gerar_chave()
        self.criar_empresa()
        dados = self.c.get(f"{self.base}/contas/").json()
        self.assertTrue(dados["agente"]["existe"])
        self.assertTrue(dados["agente"]["vinculada"])
        self.assertTrue(dados["agente"]["ativa"])
        self.assertTrue(dados["agente"]["masked_key"])
        self.assertEqual(dados["agentes_extras"], [])
        self.assertEqual([c["username"] for c in dados["empresa"]], ["dono@contas.com"])
        self.assertTrue(dados["empresa"][0]["must_change_password"])
        self.assertTrue(dados["empresa"][0]["is_active"])

    def test_conta_desvinculada_nao_e_agente_ativo_e_religa_sem_trocar_a_chave(self):
        token = self.gerar_chave()
        agente = get_user_model().objects.get(username="agente.contas-ltda")
        self.empresa.members.remove(agente)
        # O sintoma real: chave válida, mas o agente recebe 404 e o painel dizia "Agente ativo".
        self.assertEqual(self.agente_client(token).get(f"/api/companies/{self.empresa.pk}/agente/contexto/").status_code, 404)
        status = self.c.get(f"{self.base}/contas/").json()["agente"]
        self.assertFalse(status["vinculada"])
        self.assertTrue(status["masked_key"])
        self.assertFalse(self.c.get(f"{self.base}/").json()["tem_agente_ativo"])

        resp = self.c.post(f"{self.base}/contas/agente/vincular/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()["vinculada"])
        self.assertEqual(resp.json()["masked_key"], status["masked_key"])  # mesma chave
        self.assertEqual(self.agente_client(token).get(f"/api/companies/{self.empresa.pk}/agente/contexto/").status_code, 200)
        self.assertTrue(self.c.get(f"{self.base}/").json()["tem_agente_ativo"])
        self.assertEqual(self.c.post(f"{self.base}/contas/agente/vincular/").status_code, 200)  # idempotente

    def test_vincular_cria_a_conta_quando_ela_nao_existe_e_reativa_conta_desativada(self):
        User = get_user_model()
        status = self.c.post(f"{self.base}/contas/agente/vincular/").json()
        self.assertTrue(status["existe"] and status["vinculada"])
        self.assertIsNone(status["masked_key"])  # conta criada sem chave
        agente = User.objects.get(username="agente.contas-ltda")
        self.assertFalse(agente.has_usable_password())
        self.assertTrue(agente.groups.filter(name="agente").exists())
        agente.is_active = False
        agente.save()
        self.assertFalse(self.c.get(f"{self.base}/contas/").json()["agente"]["ativa"])
        self.assertTrue(self.c.post(f"{self.base}/contas/agente/vincular/").json()["ativa"])

    def test_gerar_chave_com_empresa_renomeada_reaproveita_a_conta(self):
        User = get_user_model()
        self.gerar_chave()
        self.assertEqual(self.c.patch(f"{self.base}/", {"name": "Nome Totalmente Novo"}, format="json").status_code, 200)
        self.assertTrue(self.c.get(f"{self.base}/contas/").json()["agente"]["existe"])
        self.gerar_chave()
        self.assertEqual(User.objects.filter(groups__name="agente").count(), 1)

    def test_conta_de_agente_de_outra_empresa_nunca_e_religada(self):
        User = get_user_model()
        grupo, _ = __import__("django.contrib.auth.models", fromlist=["Group"]).Group.objects.get_or_create(name="agente")
        alheia = User.objects.create_user(username="agente.contas-ltda")
        alheia.groups.add(grupo)
        self.outra.members.add(alheia)
        resp = self.c.post(f"{self.base}/contas/agente/vincular/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("outra empresa", resp.json()["detail"])
        self.assertFalse(self.empresa.members.filter(pk=alheia.pk).exists())
        self.assertEqual(self.c.post(f"{self.base}/agente/", {"validade_dias": 30}, format="json").status_code, 400)

    def test_criar_conta_empresa(self):
        dados = self.criar_empresa(email="  Dono@Contas.com ", nome="Dono da Empresa")
        User = get_user_model()
        user = User.objects.get(username="dono@contas.com")
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(self.empresa.members.filter(pk=user.pk).exists())
        self.assertFalse(self.outra.members.filter(pk=user.pk).exists())
        self.assertTrue(PasswordChangeRequired.objects.filter(user=user).exists())
        self.assertTrue(dados["email_enviado"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(dados["senha_provisoria"], mail.outbox[0].body)
        # A senha provisória realmente entra, e o sistema exige a troca.
        resp = self.login("dono@contas.com", dados["senha_provisoria"])
        self.assertEqual(resp.status_code, 200, resp.content)
        me = APIClient()
        me.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.json()['access']}")
        self.assertTrue(me.get("/api/me/").json()["must_change_password"])

    def test_criar_conta_empresa_rejeita_email_invalido_e_duplicado(self):
        User = get_user_model()
        for ruim in ["", "abc", "a@b", "a b@c.com"]:
            self.assertEqual(self.c.post(f"{self.base}/contas/empresa/", {"email": ruim}, format="json").status_code, 400, ruim)
        self.criar_empresa(email="dono@contas.com")
        self.assertEqual(self.c.post(f"{self.base}/contas/empresa/", {"email": "DONO@contas.com"}, format="json").status_code, 400)
        User.objects.create_user(username="x", email="alheio@outra.com").companies.add(self.outra)
        resp = self.c.post(f"{self.base}/contas/empresa/", {"email": "alheio@outra.com"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Já existe", resp.json()["detail"])

    def test_falha_no_envio_do_email_nao_desfaz_a_conta(self):
        from unittest import mock
        with mock.patch("crm.services.send_credentials_email", side_effect=RuntimeError("smtp fora")):
            resp = self.c.post(f"{self.base}/contas/empresa/", {"email": "dono@contas.com"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertFalse(resp.json()["email_enviado"])
        self.assertTrue(resp.json()["senha_provisoria"])
        self.assertTrue(get_user_model().objects.filter(username="dono@contas.com").exists())

    def test_redefinir_senha_da_conta_empresa(self):
        dados = self.criar_empresa()
        conta_id = dados["conta"]["id"]
        resp = self.c.post(f"{self.base}/contas/empresa/{conta_id}/redefinir-senha/")
        self.assertEqual(resp.status_code, 200, resp.content)
        nova = resp.json()["senha_provisoria"]
        self.assertNotEqual(nova, dados["senha_provisoria"])
        self.assertTrue(resp.json()["email_enviado"])
        self.assertEqual(len(mail.outbox), 2)
        self.assertGreaterEqual(self.login("dono@contas.com", dados["senha_provisoria"]).status_code, 400)
        self.assertEqual(self.login("dono@contas.com", nova).status_code, 200)
        self.assertTrue(PasswordChangeRequired.objects.filter(user_id=conta_id).exists())

    def test_so_alcanca_contas_empresa_desta_empresa(self):
        User = get_user_model()
        atendente = User.objects.create_user(username="atendente@contas.com")
        self.empresa.members.add(atendente)
        outra_conta = User.objects.create_user(username="dono@outra.com", is_staff=True)
        self.outra.members.add(outra_conta)
        self.gerar_chave()
        agente = User.objects.get(username="agente.contas-ltda")
        for alvo in (atendente, outra_conta, agente, self.su):
            self.assertEqual(self.c.post(f"{self.base}/contas/empresa/{alvo.pk}/redefinir-senha/").status_code, 404, alvo.username)
            self.assertEqual(self.c.patch(f"{self.base}/contas/empresa/{alvo.pk}/", {"is_active": False}, format="json").status_code, 404, alvo.username)
            alvo.refresh_from_db()
            self.assertTrue(alvo.is_active)
        self.assertEqual(self.c.get(f"{self.base}/contas/").json()["empresa"], [])

    def test_desativar_e_reativar_conta_empresa(self):
        dados = self.criar_empresa()
        conta_id = dados["conta"]["id"]
        url = f"{self.base}/contas/empresa/{conta_id}/"
        self.assertEqual(self.c.patch(url, {"is_active": "nao"}, format="json").status_code, 400)
        self.assertFalse(self.c.patch(url, {"is_active": False}, format="json").json()["conta"]["is_active"])
        self.assertGreaterEqual(self.login("dono@contas.com", dados["senha_provisoria"]).status_code, 400)
        self.assertTrue(self.c.patch(url, {"is_active": True}, format="json").json()["conta"]["is_active"])
        self.assertEqual(self.login("dono@contas.com", dados["senha_provisoria"]).status_code, 200)

    def test_revogar_chave_de_conta_de_agente_extra(self):
        from django.contrib.auth.models import Group
        from rest_framework.authtoken.models import Token
        User = get_user_model()
        principal_token = self.gerar_chave()
        grupo, _ = Group.objects.get_or_create(name="agente")
        legado = User.objects.create_user(username="agente.nome-antigo")
        legado.groups.add(grupo)
        self.empresa.members.add(legado)
        Token.objects.create(user=legado)
        alheio = User.objects.create_user(username="agente.de-outra")
        alheio.groups.add(grupo)
        self.outra.members.add(alheio)
        Token.objects.create(user=alheio)

        extras = self.c.get(f"{self.base}/contas/").json()["agentes_extras"]
        self.assertEqual([e["username"] for e in extras], ["agente.nome-antigo"])
        self.assertTrue(extras[0]["masked_key"])

        url = f"{self.base}/agente/"
        self.assertEqual(self.c.delete(f"{url}?user_id={alheio.pk}").status_code, 404)
        self.assertTrue(Token.objects.filter(user=alheio).exists())
        self.assertEqual(self.c.delete(f"{url}?user_id=abc").status_code, 400)
        self.assertEqual(self.c.delete(f"{url}?user_id={legado.pk}").status_code, 200)
        self.assertFalse(Token.objects.filter(user=legado).exists())
        self.assertEqual(self.agente_client(principal_token).get(f"/api/companies/{self.empresa.pk}/agente/contexto/").status_code, 200)
        self.assertEqual(self.c.delete(url).status_code, 200)  # sem user_id: a principal
        self.assertEqual(self.agente_client(principal_token).get(f"/api/companies/{self.empresa.pk}/agente/contexto/").status_code, 401)

    def test_so_superuser_acessa_os_controles(self):
        from django.contrib.auth.models import Group
        User = get_user_model()
        empresa = User.objects.create_user(username="dono-estaff@x.com", is_staff=True)
        atendente = User.objects.create_user(username="atendente@x.com")
        agente = User.objects.create_user(username="agente.qualquer")
        agente.groups.add(Group.objects.get_or_create(name="agente")[0])
        self.empresa.members.add(empresa, atendente, agente)
        alvo = self.criar_empresa()["conta"]["id"]
        chamadas = [
            ("get", f"{self.base}/contas/", None),
            ("post", f"{self.base}/contas/agente/vincular/", None),
            ("post", f"{self.base}/contas/empresa/", {"email": "novo@x.com"}),
            ("post", f"{self.base}/contas/empresa/{alvo}/redefinir-senha/", None),
            ("patch", f"{self.base}/contas/empresa/{alvo}/", {"is_active": False}),
            ("delete", f"{self.base}/agente/", None),
        ]
        for quem in (empresa, atendente, agente):
            cliente = APIClient()
            cliente.force_authenticate(quem)
            for metodo, url, corpo in chamadas:
                resp = getattr(cliente, metodo)(url, corpo, format="json") if corpo is not None else getattr(cliente, metodo)(url)
                self.assertEqual(resp.status_code, 403, f"{quem.username} {metodo} {url}")
        for metodo, url, corpo in chamadas:
            anonimo = APIClient()
            resp = getattr(anonimo, metodo)(url, corpo, format="json") if corpo is not None else getattr(anonimo, metodo)(url)
            self.assertIn(resp.status_code, (401, 403), f"anônimo {metodo} {url}")
        self.assertTrue(User.objects.get(pk=alvo).is_active)


class ConversaLivreTests(TestCase):
    """Marcador RESPONDER: conversa livre do agente, só antes do fluxo e validada pelo CRM."""
    def setUp(self):
        self.company = Company.objects.create(name="Ismael Teste", agente_conversacional=True)
        Question.objects.create(company=self.company, question_id="apresentacao", text="Olá! Quer ser atendido?")
        Question.objects.create(company=self.company, question_id="nome", text="Seu nome?", ordem=0, obrigatoria=True)
        CompanyInfo.objects.create(company=self.company, title="Horário", content="Seg a sex, 9h às 18h")
        CompanyInfo.objects.create(company=self.company, title="Vazio", content="  ")

    def send(self, mid, contact="+5585911119999", **kwargs):
        data = {"contact": contact, "message_id": mid, "kind": "text", "marker": "Q", "question_id": "apresentacao",
                "fields": {}, "human_required": False, "reason": "pedido humano", **kwargs}
        r = receive(self.company, data)
        if r.get("event_id"):
            Event.objects.filter(pk=r["event_id"]).update(delivery="SENT")
        return r

    def responder(self, mid, texto="Atendemos de segunda a sexta, das 9h às 18h.", **kw):
        return self.send(mid, marker="RESPONDER", question_id="", fields={"texto": texto}, **kw)

    def test_responde_livre_depois_da_apresentacao_sem_sair_da_etapa(self):
        self.send("1")
        r = self.responder("2")
        self.assertEqual(r["action"], "TEXTO")
        self.assertEqual(r["content"], "Atendemos de segunda a sexta, das 9h às 18h.")
        lead = Lead.objects.get()
        self.assertEqual(lead.state, "apresentacao")
        self.assertEqual(Event.objects.get(pk=r["event_id"]).marker, "RESPONDER")

    def test_primeira_mensagem_nunca_vira_resposta_livre(self):
        r = self.responder("1")
        self.assertEqual(r["question_id"], "apresentacao")
        self.assertIn("Olá!", r["content"])
        self.assertEqual(Lead.objects.get().state, "apresentacao")

    def test_bloqueia_depois_que_o_fluxo_comecou(self):
        self.send("1")
        self.send("2", marker="ATUALIZAR", question_id="", fields={"proxima": "nome"})
        r = self.responder("3")
        self.assertEqual(r["action"], "NO_REPLY")
        self.assertEqual(Lead.objects.get().state, "nome")

    def test_bloqueia_sem_agente_conversacional_ou_com_etapa_inicial(self):
        self.send("1")
        Company.objects.filter(pk=self.company.pk).update(agente_conversacional=False)
        self.company.refresh_from_db()
        self.assertEqual(self.responder("2")["action"], "NO_REPLY")
        Company.objects.filter(pk=self.company.pk).update(agente_conversacional=True)
        self.company.refresh_from_db()
        self.assertEqual(self.responder("3")["action"], "TEXTO")

    def test_texto_invalido_nao_e_enviado(self):
        self.send("1")
        self.assertEqual(self.responder("2", texto="   ")["action"], "NO_REPLY")
        self.assertEqual(self.responder("3", texto="a" * 1001)["action"], "NO_REPLY")
        self.assertEqual(self.responder("4", texto="veja [[AXIOMA:Q:nome]]")["action"], "NO_REPLY")
        self.assertEqual(Lead.objects.get().state, "apresentacao")

    def test_limite_de_respostas_reenvia_o_texto_aprovado(self):
        from .services import MAX_RESPOSTAS_LIVRES
        self.send("1")
        for i in range(MAX_RESPOSTAS_LIVRES):
            self.assertEqual(self.responder(f"r{i}", texto=f"resp {i}")["content"], f"resp {i}")
        r = self.responder("extra")
        self.assertEqual(r["question_id"], "apresentacao")
        self.assertIn("Olá!", r["content"])
        status = status_contato(self.company, "+5585911119999")
        self.assertEqual(status["conversa_livre_restante"], 0)

    def test_status_e_contexto_expoem_a_janela_e_os_dados_da_empresa(self):
        self.send("1")
        self.assertEqual(status_contato(self.company, "+5585911119999")["conversa_livre_restante"], 6)
        ctx = contexto_agente(self.company)["conversa_livre"]
        self.assertTrue(ctx["ativa"])
        self.assertEqual(ctx["dados_empresa"], [{"titulo": "Horário", "conteudo": "Seg a sex, 9h às 18h"}])
        self.send("2", marker="ATUALIZAR", question_id="", fields={"proxima": "nome"})
        self.assertEqual(status_contato(self.company, "+5585911119999")["conversa_livre_restante"], 0)

    def test_contexto_sem_modo_conversacional_nao_entrega_dados_da_empresa(self):
        Company.objects.filter(pk=self.company.pk).update(agente_conversacional=False)
        self.company.refresh_from_db()
        self.assertEqual(contexto_agente(self.company)["conversa_livre"], {"ativa": False, "maximo_respostas": 6, "dados_empresa": []})

    def test_serializer_aceita_marcador_e_texto(self):
        from .serializers import IncomingSerializer
        s = IncomingSerializer(data={"contact": "+5585911119999", "message_id": "x", "marker": "RESPONDER", "fields": {"texto": "oi"}})
        self.assertTrue(s.is_valid(), s.errors)


class ObservacoesDoLeadTests(TestCase):
    """Campo de observações (Lead.notes): dados não sensíveis gravados pelo agente, separados por ';'."""
    def setUp(self):
        from django.contrib.auth.models import Group
        from rest_framework.authtoken.models import Token
        self.company = Company.objects.create(name="Obs Teste")
        Area.objects.create(company=self.company, name="Consumidor")
        Question.objects.create(company=self.company, question_id="apresentacao", text="Olá!")
        Question.objects.create(company=self.company, question_id="nome", text="Seu nome?", ordem=0)
        Question.objects.create(company=self.company, question_id="situacao", text="Qual a situação?", ordem=1)
        self.contact = "+5585911110001"

    def atualizar(self, mid, **fields):
        data = {"contact": self.contact, "message_id": mid, "kind": "text", "marker": "ATUALIZAR", "question_id": "",
                "fields": fields, "human_required": False, "reason": "pedido humano"}
        r = receive(self.company, data)
        if r.get("event_id"):
            Event.objects.filter(pk=r["event_id"]).update(delivery="SENT")
        return r

    def abrir(self):
        data = {"contact": self.contact, "message_id": "a0", "kind": "text", "marker": "Q", "question_id": "apresentacao",
                "fields": {}, "human_required": False, "reason": "pedido humano"}
        r = receive(self.company, data)
        Event.objects.filter(pk=r["event_id"]).update(delivery="SENT")

    def test_merge_acrescenta_sem_duplicar_e_preserva_edicao_da_atendente(self):
        from .services import mesclar_observacoes
        self.assertEqual(mesclar_observacoes("Já tem advogado", "Filha envia documentos;  já tem advogado ;Não pode enviar senha agora"),
                         "Já tem advogado; Filha envia documentos; Não pode enviar senha agora")

    def test_filtra_dados_sensiveis(self):
        from .services import mesclar_observacoes
        r = mesclar_observacoes("", "CPF 123.456.789-09; senha é 1234; código: 889977; telefone 86 99999 8888; Filha ajuda com o app")
        self.assertEqual(r, "Filha ajuda com o app")

    def test_limite_de_tamanho_e_de_item(self):
        from .services import mesclar_observacoes, LIMITE_OBSERVACOES, LIMITE_ITEM_OBSERVACAO
        r = mesclar_observacoes("", "; ".join(f"item numero {chr(65 + i % 26)}{'x' * 100} {i}" for i in range(60)))
        self.assertLessEqual(len(r), LIMITE_OBSERVACOES)
        self.assertLessEqual(max(len(i) for i in r.split("; ")), LIMITE_ITEM_OBSERVACAO)

    def test_agente_grava_e_repeticao_e_idempotente(self):
        self.abrir()
        self.atualizar("a1", nome="Ana", proxima="nome", observacoes="Filha envia os documentos quando chegar; Não pode enviar senha agora")
        self.atualizar("a2", proxima="situacao", observacoes="Não pode enviar senha agora; Recebe só R$ 700")
        lead = Lead.objects.get()
        self.assertEqual(lead.notes, "Filha envia os documentos quando chegar; Não pode enviar senha agora; Recebe só R$ 700")
        self.assertEqual(lead.demand, "")

    def test_status_do_contato_traz_observacoes(self):
        from .services import status_contato
        self.abrir()
        self.atualizar("a1", proxima="nome", observacoes="Prefere contato à noite")
        self.assertEqual(status_contato(self.company, self.contact)["observacoes"], "Prefere contato à noite")

    def test_serializer_aceita_observacoes_e_api_expoe_ao_atendente(self):
        from .serializers import IncomingSerializer
        s = IncomingSerializer(data={"contact": self.contact, "message_id": "x", "marker": "ATUALIZAR", "fields": {"proxima": "nome", "observacoes": "a; b"}})
        self.assertTrue(s.is_valid(), s.errors)
        self.abrir()
        self.atualizar("a1", proxima="nome", observacoes="Prefere contato à noite")
        user = get_user_model().objects.create_user(username="atend@x.com", email="atend@x.com")
        self.company.members.add(user)
        c = APIClient(); c.force_authenticate(user)
        lead = Lead.objects.get()
        body = c.get(f"/api/leads/{lead.pk}/?company={self.company.pk}").json()
        self.assertEqual(body["notes"], "Prefere contato à noite")


class SituacaoEspecialTests(TestCase):
    """situacao_especial: lead em triagem que vira "Outras situações" (ex.: acompanhamento de processo)."""
    def setUp(self):
        self.company = Company.objects.create(name="Esp Teste")
        seed_roteiro_padrao(self.company)
        Question.objects.filter(company=self.company, question_id="apresentacao").update(text="Olá!")
        Area.objects.create(company=self.company, name="Consumidor")
        self.contact = "+5585911110002"
        User = get_user_model()
        self.atendente = User.objects.create_user(username="a1@x.com", email="a1@x.com")
        self.outro = User.objects.create_user(username="a2@x.com", email="a2@x.com")
        self.empresa = User.objects.create_user(username="e@x.com", email="e@x.com", is_staff=True)
        for u in (self.atendente, self.outro, self.empresa):
            self.company.members.add(u)

    def client_de(self, user):
        c = APIClient(); c.force_authenticate(user); return c

    def send(self, mid, marker="ATUALIZAR", **fields):
        data = {"contact": self.contact, "message_id": mid, "kind": "text", "marker": marker,
                "question_id": "apresentacao" if marker == "Q" else "", "fields": fields,
                "human_required": False, "reason": "pedido humano"}
        r = receive(self.company, data)
        if r.get("event_id"):
            Event.objects.filter(pk=r["event_id"]).update(delivery="SENT")
        return r

    def especial(self, mid="e1", **extra):
        return self.send(mid, situacao_especial="acompanhamento", observacoes="Quer saber o andamento do processo", **extra)

    def test_lead_em_triagem_vira_acompanhamento_e_recebe_o_texto_obrigatorio(self):
        self.send("a0", marker="Q")
        r = self.especial()
        self.assertEqual((r["action"], r["question_id"]), ("TEXTO", "especial_acompanhamento"))
        lead = Lead.objects.get()
        self.assertEqual((lead.situacao_especial, lead.temperature, lead.bot_closed, lead.desfecho), ("acompanhamento", "", True, ""))
        self.assertEqual(lead.notes, "Quer saber o andamento do processo")
        self.assertEqual(lead.next_action, "Acompanhar processo")
        # O número segue preso: o agente não atende mais esse contato até concluir.
        self.assertEqual(self.send("a9", marker="Q")["action"], "NO_REPLY")
        self.assertEqual(Lead.objects.filter(contact=self.contact).count(), 1)

    def test_primeira_mensagem_ja_pode_ser_acompanhamento(self):
        r = self.especial("p1")
        self.assertEqual(r["action"], "TEXTO")
        self.assertEqual(Lead.objects.get().situacao_especial, "acompanhamento")

    def test_etapa_inicial_ligada_classifica_em_silencio(self):
        area = Area.objects.get(company=self.company)
        Question.objects.create(company=self.company, question_id="cons_a", text="Pergunta?", area=area, etapa_spin="situacao")
        Company.objects.filter(pk=self.company.pk).update(etapa_inicial=True, spin_inicial=area)
        self.company.refresh_from_db()
        r = self.especial("s1")
        self.assertEqual(r["action"], "NO_REPLY")
        lead = Lead.objects.get()
        self.assertEqual((lead.situacao_especial, lead.bot_closed), ("acompanhamento", True))

    def test_texto_desabilitado_ou_vazio_tambem_fica_em_silencio(self):
        Question.objects.filter(company=self.company, question_id="especial_acompanhamento").update(habilitada=False)
        self.assertEqual(self.especial("d1")["action"], "NO_REPLY")
        self.assertEqual(Lead.objects.get().situacao_especial, "acompanhamento")

    def test_lead_ja_classificado_nao_muda_de_categoria(self):
        self.send("a0", marker="Q")
        Lead.objects.update(bot_closed=True, state="ENCERRADO_CLASSIFICADO", temperature="Quente")
        r = self.especial("x1")
        self.assertEqual(r["action"], "NO_REPLY")
        self.assertEqual(Lead.objects.get().situacao_especial, "")

    def test_filas_do_kanban_nao_incluem_e_a_lista_outras_situacoes_inclui(self):
        self.send("a0", marker="Q"); self.especial()
        c = self.client_de(self.atendente)
        base = f"/api/leads/?company={self.company.pk}"
        self.assertEqual(c.get(base + "&pending=1").json()["count"], 0)
        self.assertEqual(c.get(base + "&ativos=1").json()["count"], 0)
        lista = c.get(base + "&especial=1").json()
        self.assertEqual(lista["count"], 1)
        self.assertEqual(lista["results"][0]["situacao_especial"], "acompanhamento")
        self.assertEqual(self.client_de(self.empresa).get(base + "&especial=1").json()["count"], 1)

    def test_assumir_e_concluir_liberam_o_numero(self):
        self.send("a0", marker="Q"); self.especial()
        lead = Lead.objects.get()
        url = lambda acao: f"/api/leads/{lead.pk}/especial/{acao}/?company={self.company.pk}"
        self.assertEqual(self.client_de(self.empresa).post(url("assumir")).status_code, 403)
        self.assertEqual(self.client_de(self.atendente).post(url("assumir")).status_code, 200)
        self.assertEqual(self.client_de(self.outro).post(url("assumir")).status_code, 400)
        self.assertEqual(self.client_de(self.outro).post(url("concluir")).status_code, 400)
        self.assertEqual(self.client_de(self.atendente).post(url("concluir")).status_code, 200)
        lead.refresh_from_db()
        self.assertEqual((lead.desfecho, lead.owner_id), ("encerrado", self.atendente.pk))
        self.assertEqual(self.client_de(self.atendente).post(url("concluir")).status_code, 400)
        # Número livre: a próxima mensagem abre um lead novo, pela apresentação.
        r = self.send("n1", marker="Q")
        self.assertEqual((r["action"], r["lead_novo"]), ("TEXTO", True))

    def test_conta_empresa_pode_concluir(self):
        self.send("a0", marker="Q"); self.especial()
        lead = Lead.objects.get()
        r = self.client_de(self.empresa).post(f"/api/leads/{lead.pk}/especial/concluir/?company={self.company.pk}")
        self.assertEqual(r.status_code, 200)

    def test_dashboard_aberto_e_especial_e_depois_do_despacho_conta_como_despachado(self):
        from .services import resumo_dashboard
        self.send("a0", marker="Q"); self.especial()
        lead = Lead.objects.get()
        aberto = resumo_dashboard(self.company)
        self.assertEqual((aberto["status"]["especial"], aberto["status"]["despachado"]), (1, 0))
        self.assertEqual([a["categoria_status"] for a in aberto["atendimentos"]], ["especial"])
        r = self.client_de(self.atendente).post(f"/api/leads/{lead.pk}/especial/despachar/?company={self.company.pk}", {"desfecho": "comprometido"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        fechado = resumo_dashboard(self.company)
        self.assertEqual((fechado["status"]["especial"], fechado["status"]["despachado"]), (0, 1))
        self.assertEqual((fechado["desfechos"]["comprometido"], len(fechado["concluidos"])), (1, 1))
        self.assertEqual(fechado["por_owner"][0]["concluidos"], 1)
        self.assertEqual(sum(fechado["status"].values()), fechado["total"])

    def test_despachar_classifica_desfecho_e_area_e_valida_entradas(self):
        Area.objects.create(company=self.company, name="Previdenciário")
        self.send("a0", marker="Q"); self.especial()
        lead = Lead.objects.get()
        url = f"/api/leads/{lead.pk}/especial/despachar/?company={self.company.pk}"
        c = self.client_de(self.atendente)
        self.assertEqual(c.post(url, {"desfecho": "inexistente"}, format="json").status_code, 400)
        self.assertEqual(c.post(url, {"desfecho": "encerrado", "especialidade": "Area Falsa"}, format="json").status_code, 400)
        self.assertEqual(self.client_de(self.outro).post(url, {"desfecho": "encerrado"}, format="json").status_code, 200)  # sem responsável: quem despacha assume
        lead.refresh_from_db()
        self.assertEqual((lead.desfecho, lead.owner_id, lead.etapa_atendimento), ("encerrado", self.outro.pk, ""))

    def test_despachar_com_area_e_so_o_responsavel_ou_empresa(self):
        Area.objects.create(company=self.company, name="Previdenciário")
        self.send("a0", marker="Q"); self.especial()
        lead = Lead.objects.get()
        url = f"/api/leads/{lead.pk}/especial/despachar/?company={self.company.pk}"
        self.client_de(self.atendente).post(f"/api/leads/{lead.pk}/especial/assumir/?company={self.company.pk}")
        self.assertEqual(self.client_de(self.outro).post(url, {"desfecho": "falha"}, format="json").status_code, 400)
        r = self.client_de(self.empresa).post(url, {"desfecho": "falha", "especialidade": "Previdenciário"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        lead.refresh_from_db()
        self.assertEqual((lead.desfecho, lead.especialidade, lead.owner_id), ("falha", "Previdenciário", self.atendente.pk))

    def test_despachar_e_bloquear_poe_o_numero_na_blacklist(self):
        from .models import Blacklist
        self.send("a0", marker="Q"); self.especial()
        lead = Lead.objects.get()
        r = self.client_de(self.atendente).post(f"/api/leads/{lead.pk}/especial/despachar/?company={self.company.pk}", {"desfecho": "bloqueado"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Blacklist.objects.filter(company=self.company, contact=self.contact).exists())
        self.assertEqual(self.send("b1", marker="Q")["action"], "NO_REPLY")

    def test_contexto_lista_situacoes_e_texto_obrigatorio_nao_pode_ser_excluido(self):
        ctx = contexto_agente(self.company)
        self.assertEqual([s["valor"] for s in ctx["situacoes_especiais"]], ["acompanhamento"])
        self.assertIn("especial_acompanhamento", [q["question_id"] for q in ctx["fora_do_fluxo"]])
        q = Question.objects.get(company=self.company, question_id="especial_acompanhamento")
        self.assertTrue(q.obrigatoria)
        c = self.client_de(self.empresa)
        self.assertEqual(c.delete(f"/api/questions/{q.pk}/?company={self.company.pk}").status_code, 400)

    def test_valor_desconhecido_e_rejeitado_pelo_serializer(self):
        from .serializers import IncomingSerializer
        ok = IncomingSerializer(data={"contact": self.contact, "message_id": "x", "marker": "ATUALIZAR", "fields": {"situacao_especial": "acompanhamento"}})
        ruim = IncomingSerializer(data={"contact": self.contact, "message_id": "x", "marker": "ATUALIZAR", "fields": {"situacao_especial": "outra"}})
        self.assertTrue(ok.is_valid(), ok.errors)
        self.assertFalse(ruim.is_valid())


class ContagemDiariaTests(TestCase):
    """Novas leads do dia e "não prosseguiram" (apagadas pelo Celery) sobrevivem à exclusão dos leads."""
    def setUp(self):
        self.company = Company.objects.create(name="Contagem Teste")
        seed_roteiro_padrao(self.company)
        Question.objects.filter(company=self.company, question_id="apresentacao").update(text="Olá!")

    def abrir(self, contact, mid="m1"):
        data = {"contact": contact, "message_id": mid, "kind": "text", "marker": "Q", "question_id": "apresentacao",
                "fields": {}, "human_required": False, "reason": "pedido humano"}
        r = receive(self.company, data)
        Event.objects.filter(pk=r["event_id"]).update(delivery="SENT")
        return r

    def contagem(self):
        from .models import ContagemDiaria
        return {c.data: (c.novas, c.nao_prosseguiram) for c in ContagemDiaria.objects.filter(company=self.company)}

    def test_conta_so_leads_novos_e_nao_mensagens_seguintes(self):
        self.abrir("+5585911110010"); self.abrir("+5585911110010", "m2"); self.abrir("+5585911110011")
        self.assertEqual(self.contagem(), {timezone.localdate(): (2, 0)})

    def test_celery_apaga_e_soma_em_nao_prosseguiram_no_dia_do_nascimento(self):
        from .services import apagar_triagens_abandonadas
        self.abrir("+5585911110010"); self.abrir("+5585911110011")
        antigo = timezone.now() - timedelta(days=4)  # passa de todos os prazos (lembrete ligado: 72h sem tentativa)
        Lead.objects.filter(contact="+5585911110010").update(created_at=antigo, last_contact=antigo)
        self.assertEqual(apagar_triagens_abandonadas(), 1)
        c = self.contagem()
        self.assertEqual(c[timezone.localdate()], (2, 0))
        self.assertEqual(c[timezone.localtime(antigo).date()], (0, 1))
        # Idempotente: nada novo para apagar, nada some do contador.
        self.assertEqual(apagar_triagens_abandonadas(), 0)

    def test_apagar_lead_por_erro_do_agente_nao_conta_como_nao_prosseguiu(self):
        self.abrir("+5585911110010")
        data = {"contact": "+5585911110010", "message_id": "x", "kind": "text", "marker": "CLASSIFICADO", "question_id": "",
                "fields": {"temperatura": "Quente", "prioridade": "Alta"}, "human_required": False, "reason": "pedido humano"}
        self.assertTrue(receive(self.company, data).get("lead_apagado"))
        self.assertEqual(self.contagem()[timezone.localdate()], (1, 0))

    def test_resumo_traz_contadores_e_respeita_periodo_e_filtros(self):
        from .models import ContagemDiaria
        from .services import resumo_dashboard
        hoje = timezone.localdate()
        ContagemDiaria.objects.create(company=self.company, data=hoje, novas=3, nao_prosseguiram=1)
        ContagemDiaria.objects.create(company=self.company, data=hoje - timedelta(days=10), novas=5, nao_prosseguiram=2)
        r = resumo_dashboard(self.company)
        self.assertEqual((r["novas_leads"], r["nao_prosseguiram"], r["novas_hoje"]), (8, 3, 3))
        r7 = resumo_dashboard(self.company, dias=7)
        self.assertEqual((r7["novas_leads"], r7["nao_prosseguiram"]), (3, 1))
        rp = resumo_dashboard(self.company, data_inicio=hoje - timedelta(days=12), data_fim=hoje - timedelta(days=8))
        self.assertEqual((rp["novas_leads"], rp["nao_prosseguiram"]), (5, 2))
        # Com filtro de área/busca não dá para atribuir (o lead apagado não existe mais): nulos.
        self.assertIsNone(resumo_dashboard(self.company, area="Consumidor")["nao_prosseguiram"])
        self.assertIsNone(resumo_dashboard(self.company, busca="x")["novas_leads"])


class TemperaturaFrioTests(TestCase):
    """"Remarketing" foi renomeada para "Frio"."""
    def test_faixa_e_choices_usam_frio(self):
        from .services import FAIXAS_URGENCIA
        self.assertIn("Frio", [t for _, _, t in FAIXAS_URGENCIA])
        self.assertNotIn("Remarketing", [c[0] for c in Lead.TEMPERATURA_CHOICES])

    def test_serializer_aceita_o_nome_antigo_como_alias(self):
        from .serializers import IncomingSerializer
        for nome in ("Frio", "Remarketing"):
            s = IncomingSerializer(data={"contact": "+5585911110099", "message_id": "x", "marker": "CLASSIFICADO",
                                         "fields": {"temperatura": nome, "prioridade": "Baixa"}})
            self.assertTrue(s.is_valid(), s.errors)
            self.assertEqual(s.validated_data["fields"]["temperatura"], "Frio")

    def test_migracao_renomeia_temperatura_e_detalhe(self):
        import importlib
        from django.apps import apps as django_apps
        mod = importlib.import_module("crm.migrations.0039_temperatura_frio")
        company = Company.objects.create(name="Mig")
        lead = Lead.objects.create(company=company, contact="+5585911110098", temperature="Frio", urgencia_detalhe={"temperatura_calculada": "Frio"})
        Lead.objects.filter(pk=lead.pk).update(temperature="Remarketing", urgencia_detalhe={"temperatura_calculada": "Remarketing", "score": 6.0})

        class Schema:
            class connection:
                alias = "default"
        mod.renomear(django_apps, Schema)
        lead.refresh_from_db()
        self.assertEqual((lead.temperature, lead.urgencia_detalhe), ("Frio", {"temperatura_calculada": "Frio", "score": 6.0}))


class SituacaoEspecialManualTests(TestCase):
    """Cadastro manual de acompanhamento (tela Outras situações)."""
    def setUp(self):
        self.company = Company.objects.create(name="Esp Manual")
        seed_roteiro_padrao(self.company)
        User = get_user_model()
        self.atendente = User.objects.create_user(username="m1@x.com", email="m1@x.com")
        self.empresa = User.objects.create_user(username="m2@x.com", email="m2@x.com", is_staff=True)
        for u in (self.atendente, self.empresa):
            self.company.members.add(u)

    def post(self, user, **dados):
        c = APIClient(); c.force_authenticate(user)
        return c.post(f"/api/leads/especial/?company={self.company.pk}", dados, format="json")

    def test_atendente_cadastra_e_vira_responsavel_sem_contar_como_nova_lead(self):
        from .models import ContagemDiaria
        r = self.post(self.atendente, name="Maria", contact="85 99999-1111", demand="Processo trabalhista", observacoes="Filha liga; CPF 123.456.789-09")
        self.assertEqual(r.status_code, 201, r.content)
        lead = Lead.objects.get()
        self.assertEqual((lead.situacao_especial, lead.owner_id, lead.contact, lead.demand, lead.bot_closed, lead.origem_manual),
                         ("acompanhamento", self.atendente.pk, "+5585999991111", "Processo trabalhista", True, True))
        self.assertEqual(lead.notes, "Filha liga")
        self.assertEqual(ContagemDiaria.objects.count(), 0)

    def test_empresa_cadastra_sem_responsavel(self):
        r = self.post(self.empresa, name="Ana", contact="+5585999992222")
        self.assertEqual(r.status_code, 201)
        self.assertIsNone(Lead.objects.get().owner)

    def test_aparece_em_outras_situacoes_e_nao_em_meus_atendimentos(self):
        self.post(self.atendente, name="Maria", contact="+5585999991111")
        c = APIClient(); c.force_authenticate(self.atendente)
        base = f"/api/leads/?company={self.company.pk}"
        self.assertEqual(c.get(base + "&especial=1").json()["count"], 1)
        self.assertEqual(c.get(base + "&meus=1").json()["count"], 0)
        self.assertEqual(c.get(base + "&ativos=1").json()["count"], 0)

    def test_contato_ativo_duplicado_e_telefone_invalido(self):
        self.assertEqual(self.post(self.atendente, contact="+5585999991111").status_code, 201)
        r = self.post(self.atendente, contact="+5585999991111")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "Já existe um lead ativo com esse contato nesta empresa."))
        self.assertEqual(self.post(self.atendente, contact="123").status_code, 400)
        self.assertEqual(self.post(self.atendente).status_code, 400)

    def test_agente_nao_atende_o_numero_enquanto_o_acompanhamento_estiver_aberto(self):
        from .services import avaliar_contato
        self.post(self.atendente, contact="+5585999991111")
        self.assertEqual(avaliar_contato(self.company, "+5585999991111")[1:], (False, "classificado"))


class CadastroManualIgnoradoPeloAgenteTests(TestCase):
    """Número cadastrado manualmente (atendimento ou acompanhamento) nunca é atendido pelo agente."""
    def setUp(self):
        self.company = Company.objects.create(name="Manual Ignorado")
        seed_roteiro_padrao(self.company)
        Question.objects.filter(company=self.company, question_id="apresentacao").update(text="Olá!")
        self.atendente = get_user_model().objects.create_user(username="ig@x.com", email="ig@x.com")
        self.company.members.add(self.atendente)
        self.client_a = APIClient(); self.client_a.force_authenticate(self.atendente)

    def cadastra(self, caminho, contact):
        r = self.client_a.post(f"/api/leads/{caminho}/?company={self.company.pk}", {"name": "Fulana", "contact": contact, "demand": "x"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)

    def mensagem_do_contato(self, contact, marker):
        data = {"contact": contact, "message_id": f"{marker}-1", "kind": "text", "marker": marker, "question_id": "apresentacao" if marker == "Q" else "",
                "fields": {"proxima": "nome"} if marker == "ATUALIZAR" else {}, "human_required": False, "reason": "pedido humano"}
        return receive(self.company, data)

    def confere_ignorado(self, contact, motivo):
        from .services import avaliar_contato, status_contato
        lead, aceita, mot = avaliar_contato(self.company, contact)
        self.assertEqual((aceita, mot), (False, motivo))
        self.assertFalse(status_contato(self.company, contact)["aceita_agente"])
        for marker in ("Q", "ATUALIZAR", "REPETIR"):
            r = self.mensagem_do_contato(contact, marker)
            self.assertEqual(r["action"], "NO_REPLY", marker)
        # Nenhum lead novo, nenhuma resposta pendente de entrega, o lead segue como foi cadastrado.
        self.assertEqual(Lead.objects.filter(contact=contact).count(), 1)
        lead.refresh_from_db()
        self.assertEqual(lead.desfecho, "")
        self.assertFalse(Event.objects.filter(lead=lead, delivery="PENDING").exists())

    def test_atendimento_manual_e_ignorado(self):
        self.cadastra("manual", "+5585999991001")
        self.confere_ignorado("+5585999991001", "humano")

    def test_acompanhamento_manual_e_ignorado(self):
        self.cadastra("especial", "+5585999991002")
        self.confere_ignorado("+5585999991002", "classificado")

    def test_numero_so_volta_ao_agente_depois_de_concluir(self):
        self.cadastra("especial", "+5585999991003")
        lead = Lead.objects.get()
        r = self.client_a.post(f"/api/leads/{lead.pk}/especial/concluir/?company={self.company.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.mensagem_do_contato("+5585999991003", "Q")["action"], "TEXTO")


class DashboardTotalComNaoProsseguiramTests(TestCase):
    """Total de atendimentos = leads existentes + os que não prosseguiram (apagados pelo Celery)."""
    def setUp(self):
        self.company = Company.objects.create(name="Total Teste")
        Lead.objects.create(company=self.company, contact="+5585999990001", especialidade="Consumidor")
        Lead.objects.create(company=self.company, contact="+5585999990002", bot_closed=True, temperature="Quente")
        from .models import ContagemDiaria
        ContagemDiaria.objects.create(company=self.company, data=timezone.localdate(), novas=5, nao_prosseguiram=3)

    def test_total_soma_os_que_nao_prosseguiram_e_o_status_fecha_com_o_total(self):
        from .services import resumo_dashboard
        r = resumo_dashboard(self.company)
        self.assertEqual((r["total"], r["status"]["nao_prosseguiram"], r["nao_prosseguiram"]), (5, 3, 3))
        self.assertEqual(sum(r["status"].values()), r["total"])

    def test_com_filtro_de_area_o_total_so_tem_os_leads_existentes(self):
        from .services import resumo_dashboard
        r = resumo_dashboard(self.company, area="Consumidor")
        self.assertEqual((r["total"], r["status"]["nao_prosseguiram"], r["nao_prosseguiram"]), (1, 0, None))
        self.assertEqual(sum(r["status"].values()), r["total"])

    def test_atendimentos_e_acompanhamentos_manuais_entram_no_total(self):
        from .services import resumo_dashboard
        user = get_user_model().objects.create_user(username="tot@x.com", email="tot@x.com")
        self.company.members.add(user)
        c = APIClient(); c.force_authenticate(user)
        base = f"?company={self.company.pk}"
        self.assertEqual(c.post("/api/leads/manual/" + base, {"name": "A", "contact": "+5585999990003"}, format="json").status_code, 201)
        self.assertEqual(c.post("/api/leads/especial/" + base, {"name": "B", "contact": "+5585999990004"}, format="json").status_code, 201)
        r = resumo_dashboard(self.company)
        self.assertEqual(r["total"], 7)  # 2 do agente + 2 manuais + 3 que não prosseguiram
        self.assertEqual((r["status"]["equipe"], r["status"]["especial"], r["status"]["aguardando"]), (1, 1, 1))
        self.assertEqual(sum(r["status"].values()), r["total"])
        self.assertEqual({a["contact"] for a in r["atendimentos"] if a["origem_manual"]}, {"+5585999990003", "+5585999990004"})

    def test_triagem_concluida_so_tem_qualificadas_e_em_espera(self):
        from .services import resumo_dashboard
        mk = lambda n, **kw: Lead.objects.create(company=self.company, contact=f"+55859999100{n}", bot_closed=True, temperature="Qualificado", **kw)
        mk(1)                                           # Qualificados
        mk(2, etapa_atendimento="espera")               # Em espera
        mk(3, etapa_atendimento="negociacao", mode="HUMANO")  # já com um atendente
        mk(4, etapa_atendimento="despacho", mode="HUMANO")
        mk(5, desfecho="encerrado")                     # despachada
        mk(6, situacao_especial="acompanhamento")       # outras situações
        r = resumo_dashboard(self.company)
        marcados = {a["contact"] for a in r["atendimentos"] if a["triagem_concluida"]}
        # O lead Quente do setUp também está em Qualificados.
        self.assertEqual(marcados, {"+558599991001", "+558599991002", "+5585999990002"})
        self.assertEqual(r["triagem_concluida"], 3)

    def test_com_a_equipe_so_tem_negociacao_despacho_e_cadastros_manuais(self):
        from .services import resumo_dashboard
        mk = lambda n, **kw: Lead.objects.create(company=self.company, contact=f"+55859999200{n}", bot_closed=True, temperature="Qualificado", **kw)
        mk(1)                                                   # Qualificados -> aguardando
        mk(2, etapa_atendimento="espera")                       # Em espera -> aguardando
        mk(3, etapa_atendimento="negociacao", mode="HUMANO")    # Em negociação -> equipe
        mk(4, etapa_atendimento="despacho", mode="HUMANO")      # Despacho do atendente -> equipe
        mk(5, origem_manual=True, mode="HUMANO")                # cadastro manual -> equipe
        r = resumo_dashboard(self.company)
        por_contato = {a["contact"]: a["categoria_status"] for a in r["atendimentos"]}
        self.assertEqual([por_contato[f"+55859999200{n}"] for n in range(1, 6)], ["aguardando", "aguardando", "equipe", "equipe", "equipe"])
        self.assertEqual(sum(r["status"].values()), r["total"])


class HistoricoDeConversaTests(TestCase):
    """Coleta do histórico de conversa (portão do Admin) e endpoint /leads/{id}/conversa/."""
    def setUp(self):
        self.company = Company.objects.create(name="Historico Teste", coletar_historico_conversa=True)
        seed_roteiro_padrao(self.company)
        Question.objects.filter(company=self.company, question_id="apresentacao").update(text="Olá! Quer ser atendido?")
        Question.objects.filter(company=self.company, question_id="nome").update(text="Qual é o seu nome?")
        User = get_user_model()
        self.atendente = User.objects.create_user(username="h1@x.com", email="h1@x.com")
        self.estranho = User.objects.create_user(username="h2@x.com", email="h2@x.com")
        self.company.members.add(self.atendente)
        self.contact = "+5585911112001"

    def send(self, mid, mensagem="", marker="ATUALIZAR", company=None, **fields):
        data = {"contact": self.contact, "message_id": mid, "kind": "text", "marker": marker,
                "question_id": "apresentacao" if marker == "Q" else "", "fields": fields, "mensagem": mensagem,
                "human_required": False, "reason": "pedido humano"}
        r = receive(company or self.company, data)
        if r.get("event_id"):
            Event.objects.filter(pk=r["event_id"]).update(delivery="SENT")
        return r

    def conversa(self, user, lead):
        c = APIClient(); c.force_authenticate(user)
        return c.get(f"/api/leads/{lead.pk}/conversa/?company={lead.company_id}")

    def test_guarda_mensagens_do_cliente_e_respostas_em_ordem(self):
        self.send("m1", "Olá, boa tarde", marker="Q")
        self.send("m2", "Meu nome é Ana, desconto indevido no benefício", proxima="nome", nome="Ana")
        lead = Lead.objects.get()
        r = self.conversa(self.atendente, lead).json()
        self.assertTrue(r["coleta_ativa"])
        self.assertEqual([(m["quem"], m["texto"]) for m in r["mensagens"]], [
            ("cliente", "Olá, boa tarde"), ("agente", "Olá! Quer ser atendido?"),
            ("cliente", "Meu nome é Ana, desconto indevido no benefício"), ("agente", "Qual é o seu nome?"),
        ])

    def test_redige_numeros_longos_e_senhas_no_historico(self):
        from .services import redigir_dados_sensiveis
        self.assertEqual(redigir_dados_sensiveis("CPF 123.456.789-09, minha senha é abc123 e recebo R$ 1.600"), "CPF [número omitido], minha senha é [omitido] e recebo R$ 1.600")
        self.send("m1", "meu telefone é 86 99999 8888 e o código: 889977", marker="Q")
        lead = Lead.objects.get()
        textos = [m["texto"] for m in self.conversa(self.atendente, lead).json()["mensagens"] if m["quem"] == "cliente"]
        self.assertEqual(textos, ["meu telefone é [número omitido] e o código: [omitido]"])

    def test_com_a_coleta_desligada_nada_e_guardado_e_o_endpoint_diz_isso(self):
        Company.objects.filter(pk=self.company.pk).update(coletar_historico_conversa=False)
        self.company.refresh_from_db()
        self.send("m1", "Olá", marker="Q")
        lead = Lead.objects.get()
        self.assertFalse(Event.objects.filter(lead=lead).exclude(mensagem_cliente="").exists())
        self.assertEqual(self.conversa(self.atendente, lead).json(), {"coleta_ativa": False, "mensagens": []})

    def test_historico_termina_na_mensagem_que_classificou(self):
        self.send("m1", "Olá", marker="Q")
        lead = Lead.objects.get()
        Event.objects.create(lead=lead, message_id="c1", marker="CLASSIFICADO", mensagem_cliente="Última resposta", result={"action": "TEXTO", "content": "Obrigado."})
        Event.objects.create(lead=lead, message_id="c2", marker="", mensagem_cliente="Depois de classificado")
        textos = [m["texto"] for m in self.conversa(self.atendente, lead).json()["mensagens"]]
        self.assertIn("Última resposta", textos)
        self.assertIn("Obrigado.", textos)
        self.assertNotIn("Depois de classificado", textos)

    def test_so_membros_da_empresa_veem_o_historico(self):
        self.send("m1", "Olá", marker="Q")
        lead = Lead.objects.get()
        self.assertEqual(self.conversa(self.estranho, lead).status_code, 404)
        self.assertEqual(self.conversa(self.atendente, lead).status_code, 200)

    def test_mensagem_duplicada_nao_duplica_o_historico(self):
        self.send("m1", "Olá", marker="Q")
        self.send("m1", "Olá", marker="Q")
        lead = Lead.objects.get()
        self.assertEqual(len([m for m in self.conversa(self.atendente, lead).json()["mensagens"] if m["quem"] == "cliente"]), 1)

    def test_admin_liga_e_empresa_nao_altera_e_serializer_aceita_mensagem(self):
        from .serializers import IncomingSerializer
        admin = get_user_model().objects.create_superuser(username="adm@x.com", email="adm@x.com", password="x")
        ca = APIClient(); ca.force_authenticate(admin)
        r = ca.patch(f"/api/admin-companies/{self.company.pk}/", {"coletar_historico_conversa": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.company.refresh_from_db()
        self.assertFalse(self.company.coletar_historico_conversa)
        empresa = get_user_model().objects.create_user(username="emp@x.com", email="emp@x.com", is_staff=True)
        self.company.members.add(empresa)
        ce = APIClient(); ce.force_authenticate(empresa)
        ce.patch(f"/api/companies/{self.company.pk}/", {"coletar_historico_conversa": True}, format="json")
        self.company.refresh_from_db()
        self.assertFalse(self.company.coletar_historico_conversa)
        self.assertEqual(ce.get(f"/api/companies/{self.company.pk}/").json()["coletar_historico_conversa"], False)
        s = IncomingSerializer(data={"contact": self.contact, "message_id": "x", "marker": "Q", "question_id": "apresentacao", "mensagem": "oi"})
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(s.validated_data["mensagem"], "oi")

    def test_contexto_avisa_a_ponte_para_enviar_o_texto(self):
        self.assertTrue(contexto_agente(self.company)["coletar_historico"])
        Company.objects.filter(pk=self.company.pk).update(coletar_historico_conversa=False)
        self.company.refresh_from_db()
        self.assertFalse(contexto_agente(self.company)["coletar_historico"])


import tempfile
from django.test import override_settings


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="crm-test-media-"))
class IdentidadeVisualTests(TestCase):
    """Identidade visual da empresa: nome, logo e gradiente da barra lateral (só a conta Empresa edita)."""
    def setUp(self):
        User = get_user_model()
        self.company = Company.objects.create(name="Marca Teste")
        self.outra = Company.objects.create(name="Outra Marca")
        self.empresa = User.objects.create_user(username="m-emp@x.com", email="m-emp@x.com", is_staff=True)
        self.atendente = User.objects.create_user(username="m-at@x.com", email="m-at@x.com")
        self.estranho = User.objects.create_user(username="m-ext@x.com", email="m-ext@x.com", is_staff=True)
        for u in (self.empresa, self.atendente):
            self.company.members.add(u)
        self.outra.members.add(self.estranho)
        self.url = f"/api/companies/{self.company.pk}/identidade/"

    def client_de(self, user):
        c = APIClient(); c.force_authenticate(user); return c

    def png(self, tamanho=(600, 300), formato="PNG", nome="logo.png"):
        from io import BytesIO
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        buf = BytesIO(); Image.new("RGBA", tamanho, (200, 30, 30, 255)).save(buf, formato)
        return SimpleUploadedFile(nome, buf.getvalue(), content_type=f"image/{formato.lower()}")

    def test_padrao_e_vazio_e_atendente_da_empresa_enxerga_a_identidade(self):
        r = self.client_de(self.atendente).get(f"/api/companies/{self.company.pk}/").json()["identidade_visual"]
        self.assertEqual(r, {"nome": "", "logo_url": None, "cor_principal": None, "cor_contraste": None})
        self.client_de(self.empresa).post(self.url, {"nome": "Silva Advogados", "cor_principal": "#112233", "cor_contraste": "#ABCDEF"}, format="json")
        r = self.client_de(self.atendente).get(f"/api/companies/{self.company.pk}/").json()["identidade_visual"]
        self.assertEqual((r["nome"], r["cor_principal"], r["cor_contraste"]), ("Silva Advogados", "#112233", "#abcdef"))

    def test_so_a_conta_empresa_da_propria_empresa_altera(self):
        dados = {"nome": "X", "cor_principal": "#112233", "cor_contraste": "#445566"}
        self.assertEqual(self.client_de(self.atendente).post(self.url, dados, format="json").status_code, 403)
        self.assertEqual(self.client_de(self.estranho).post(self.url, dados, format="json").status_code, 404)  # outra empresa
        self.assertEqual(self.client_de(self.empresa).post(self.url, dados, format="json").status_code, 200)
        # E a identidade de uma empresa nunca aparece para quem é de outra.
        self.assertEqual(self.client_de(self.estranho).get(f"/api/companies/{self.company.pk}/").status_code, 404)
        self.assertEqual([c["id"] for c in self.client_de(self.estranho).get("/api/companies/").json()["results"]], [self.outra.pk])

    def test_duas_cores_obrigatorias_formato_e_nome(self):
        c = self.client_de(self.empresa)
        for dados in ({"cor_principal": "#112233"}, {"cor_contraste": "#112233"}):
            self.assertEqual(c.post(self.url, dados, format="json").status_code, 400)
        self.assertEqual(c.post(self.url, {"cor_principal": "azul", "cor_contraste": "#112233"}, format="json").status_code, 400)
        self.assertEqual(c.post(self.url, {"cor_principal": "#12345", "cor_contraste": "#112233"}, format="json").status_code, 400)
        self.assertEqual(c.post(self.url, {"nome": "x" * 31}, format="json").status_code, 400)
        self.assertEqual(c.post(self.url, {"nome": "  Meu   Escritório "}, format="json").status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual((self.company.marca_nome, self.company.marca_cor_principal), ("Meu Escritório", ""))

    def test_logo_e_redimensionado_substituido_e_removido(self):
        c = self.client_de(self.empresa)
        r = c.post(self.url, {"nome": "A", "logo": self.png()}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["identidade_visual"]["logo_url"].endswith(f"/media/marcas/{self.company.pk}.png"))
        self.company.refresh_from_db()
        from PIL import Image
        self.assertLessEqual(max(Image.open(self.company.marca_logo.path).size), 256)
        # Reenviar sem logo mantém o atual; remover_logo tira.
        c.post(self.url, {"nome": "B"}, format="multipart")
        self.company.refresh_from_db()
        self.assertTrue(self.company.marca_logo)
        c.post(self.url, {"nome": "B", "remover_logo": "1"}, format="multipart")
        self.company.refresh_from_db()
        self.assertFalse(self.company.marca_logo)

    def test_logo_invalido_e_grande_demais_sao_recusados(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        c = self.client_de(self.empresa)
        falso = SimpleUploadedFile("logo.png", b"nao e imagem", content_type="image/png")
        self.assertEqual(c.post(self.url, {"logo": falso}, format="multipart").status_code, 400)
        gif = self.png(formato="GIF", nome="logo.gif")
        self.assertEqual(c.post(self.url, {"logo": gif}, format="multipart").status_code, 400)
        grande = SimpleUploadedFile("logo.png", b"0" * (2 * 1024 * 1024 + 1), content_type="image/png")
        self.assertEqual(c.post(self.url, {"logo": grande}, format="multipart").status_code, 400)

    def test_restaurar_volta_ao_padrao_conecta(self):
        c = self.client_de(self.empresa)
        c.post(self.url, {"nome": "A", "cor_principal": "#112233", "cor_contraste": "#445566", "logo": self.png()}, format="multipart")
        r = c.post(self.url, {"restaurar": "1"}, format="json")
        self.assertEqual(r.json()["identidade_visual"], {"nome": "", "logo_url": None, "cor_principal": None, "cor_contraste": None})

    def test_conta_do_agente_nao_acessa(self):
        from django.contrib.auth.models import Group
        agente = get_user_model().objects.create_user(username="agente.marca", is_staff=True)
        agente.groups.add(Group.objects.get_or_create(name="agente")[0])
        self.company.members.add(agente)
        self.assertEqual(self.client_de(agente).post(self.url, {"nome": "X"}, format="json").status_code, 403)


class MotivoDaDesqualificacaoTests(TestCase):
    """Popup de Desqualificados: motivo de cada lead desqualificado no resumo do Dashboard."""
    def test_motivos_por_causa_e_vazio_para_os_demais(self):
        from .services import resumo_dashboard
        company = Company.objects.create(name="Motivo Teste")
        mk = lambda n, **kw: Lead.objects.create(company=company, contact=f"+55859999300{n}", bot_closed=True, **kw)
        mk(1, temperature="Desqualificado", desfecho="desqualificado", urgencia_detalhe={"motivo": "fora_de_escopo"})
        mk(2, temperature="Desqualificado", desfecho="desqualificado", urgencia_detalhe={"motivo": "sem_resposta"})
        mk(3, temperature="Desqualificado", desfecho="desqualificado", urgencia_detalhe={"score": 1.5, "notas": {"a": 1}})
        mk(4, temperature="Desconfiado", urgencia_detalhe={"score": 4.2})
        mk(5, temperature="Quente")
        r = resumo_dashboard(company)
        motivos = {a["contact"][-1]: a["motivo_desqualificacao"] for a in r["atendimentos"]}
        self.assertEqual(motivos, {
            "1": "Fora de escopo",
            "2": "Sem resposta após 3 repetições da mesma pergunta",
            "3": "Classificado como Desqualificado (média 1.5)",
            "4": "Classificado como Desconfiado (média 4.2)",
            "5": "",
        })


class OrcamentoDeTempoDaVozTests(TestCase):
    """A geração de voz (TTS) precisa terminar, ou cair para texto, antes de a ponte desistir do /incoming/ (19 s)."""
    def test_limite_de_sintese_deixa_folga_para_o_texto_de_reserva(self):
        from . import audio
        self.assertLessEqual(audio.TTS_TIMEOUT_SEGUNDOS, 8)
        # síntese + conversão (no máximo o mesmo limite, já descontado o tempo da síntese) + folga de processamento
        self.assertLess(audio.TTS_TIMEOUT_SEGUNDOS * 2 + 2, 19)

    def test_voz_que_trava_cai_para_texto_sem_derrubar_a_resposta(self):
        from unittest import mock
        from .services import aplicar_audio
        company = Company.objects.create(name="Voz Teste", allow_transcription=True, mensagens_audio=True)
        resultado = {"action": "TEXTO", "content": "Resposta livre longa", "question_id": "conversa", "event_id": None}
        with mock.patch("crm.audio.gerar_tts", side_effect=TimeoutError()):
            r = aplicar_audio(company, resultado, lambda p: p)
        self.assertEqual((r["action"], r["content"]), ("TEXTO", "Resposta livre longa"))
        self.assertIn("audio_erro", r)



class LembreteDeContinuidadeTests(TestCase):
    """24h sem resposta -> lembrete (texto + pergunta pendente) no horário da empresa; 24h depois, sem retorno, apaga."""
    def setUp(self):
        from django.contrib.auth.models import Group
        from rest_framework.authtoken.models import Token
        self.company = Company.objects.create(name="Lembrete Ltda")
        seed_roteiro_padrao(self.company)
        Question.objects.filter(company=self.company, question_id="nome").update(text="Qual seu nome, por favor?")
        self.agora = timezone.now()
        self.agente = get_user_model().objects.create_user("agente.lembrete", password="x")
        self.agente.groups.add(Group.objects.get_or_create(name="agente")[0])
        self.company.members.add(self.agente)
        self.api = APIClient()
        self.api.force_authenticate(self.agente)

    def lead(self, contact="+5585900001111", horas=25, **extra):
        quando = self.agora - timedelta(hours=horas)
        return Lead.objects.create(company=self.company, contact=contact, state="nome", name="Ana", last_contact=quando, **extra)

    def reservar(self, **kw):
        from .services import reservar_lembretes
        return reservar_lembretes(self.company, self.agora, **kw)

    def test_depois_de_24h_reserva_duas_mensagens_uma_unica_vez(self):
        lead = self.lead()
        self.lead("+5585900002222", horas=23)
        itens = self.reservar()
        self.assertEqual([i["lead_id"] for i in itens], [str(lead.pk)])
        textos = [m["content"] for m in itens[0]["mensagens"]]
        self.assertEqual(len(textos), 2)
        self.assertIn("Ana", textos[0])
        self.assertIn("Lembrete Ltda", textos[0])
        self.assertEqual(textos[1], "Qual seu nome, por favor?")
        self.assertEqual(self.reservar(), [])  # idempotente: um lembrete por lead
        self.assertEqual(lead.events.get(marker="LEMBRETE").delivery, "PENDING")

    def test_horario_definido_pela_empresa_adia_para_a_primeira_ocorrencia(self):
        from datetime import time
        from .services import horario_do_lembrete
        ultimo = timezone.make_aware(datetime(2026, 3, 10, 14, 0))
        self.assertEqual(horario_do_lembrete(ultimo), ultimo + timedelta(hours=24))
        self.assertEqual(horario_do_lembrete(ultimo, time(9, 0)), timezone.make_aware(datetime(2026, 3, 12, 9, 0)))
        self.assertEqual(horario_do_lembrete(ultimo, time(15, 30)), timezone.make_aware(datetime(2026, 3, 11, 15, 30)))
        self.assertEqual(horario_do_lembrete(ultimo, time(14, 0)), timezone.make_aware(datetime(2026, 3, 11, 14, 0)))

    def test_reserva_respeita_o_horario_configurado(self):
        local = timezone.localtime(self.agora)
        Question.objects.filter(company=self.company, question_id="lembrete").update(horario_envio=(local + timedelta(hours=3)).time().replace(second=0, microsecond=0))
        self.lead(horas=25)
        self.assertEqual(self.reservar(), [])  # 24h cumpridas, mas o horário escolhido ainda não chegou
        Question.objects.filter(company=self.company, question_id="lembrete").update(horario_envio=(local - timedelta(minutes=30)).time().replace(second=0, microsecond=0))
        self.assertEqual(len(self.reservar()), 1)

    def test_lembrete_desligado_ou_sem_texto_nao_reserva_e_mantem_a_regra_de_24h(self):
        from .services import apagar_triagens_abandonadas
        self.lead(horas=25)
        Question.objects.filter(company=self.company, question_id="lembrete").update(habilitada=False)
        self.assertEqual(self.reservar(), [])
        self.assertEqual(apagar_triagens_abandonadas(self.agora), 1)

    def test_funciona_com_etapa_inicial_ligada(self):
        self.lead(horas=25)
        Company.objects.filter(pk=self.company.pk).update(etapa_inicial=True)
        self.company.refresh_from_db()
        itens = self.reservar()
        self.assertEqual(len(itens), 1)
        self.assertEqual(len(itens[0]["mensagens"]), 1)  # só o lembrete: a pergunta não é de SPIN

    def test_entrega_confirmada_marca_o_prazo_e_falha_nao_apaga_o_lead(self):
        lead = self.lead()
        evento_id = self.reservar()[0]["event_id"]
        r = self.api.post(f"/api/companies/{self.company.pk}/delivery/", {"event_id": evento_id, "status": "SENT"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        lead.refresh_from_db()
        self.assertIsNotNone(lead.lembrete_enviado_em)
        outro = self.lead("+5585900003333")
        falha_id = self.reservar()[0]["event_id"]
        r = self.api.post(f"/api/companies/{self.company.pk}/delivery/", {"event_id": falha_id, "status": "FAILED"}, format="json")
        self.assertEqual(r.json(), {"delivery": "FAILED"})
        self.assertTrue(Lead.objects.filter(pk=outro.pk).exists())

    def test_sem_retorno_apaga_24h_depois_do_lembrete_e_resposta_do_cliente_adia(self):
        from .services import apagar_triagens_abandonadas
        lead = self.lead(horas=49)
        Lead.objects.filter(pk=lead.pk).update(lembrete_enviado_em=self.agora - timedelta(hours=23))
        Event.objects.create(lead=lead, message_id=f"lembrete-{lead.pk}", marker="LEMBRETE", delivery="SENT", result={})
        self.assertEqual(apagar_triagens_abandonadas(self.agora), 0)  # lembrado há 23h: ainda dentro do prazo
        self.assertEqual(apagar_triagens_abandonadas(self.agora + timedelta(hours=2)), 1)
        # Cliente respondeu depois do lembrete: o prazo passa a contar da resposta.
        outro = self.lead("+5585900004444", horas=10)
        Lead.objects.filter(pk=outro.pk).update(lembrete_enviado_em=self.agora - timedelta(hours=40))
        Event.objects.create(lead=outro, message_id=f"lembrete-{outro.pk}", marker="LEMBRETE", delivery="SENT", result={})
        self.assertEqual(apagar_triagens_abandonadas(self.agora), 0)

    def test_lembrete_que_nunca_saiu_nao_deixa_o_lead_para_sempre(self):
        from .services import apagar_triagens_abandonadas
        sem_tentativa = self.lead(horas=73)
        tentado = self.lead("+5585900005555", horas=49)
        Event.objects.create(lead=tentado, message_id=f"lembrete-{tentado.pk}", marker="LEMBRETE", delivery="FAILED", result={})
        espera = self.lead("+5585900006666", horas=30)
        self.assertEqual(apagar_triagens_abandonadas(self.agora), 2)
        self.assertTrue(Lead.objects.filter(pk=espera.pk).exists())
        self.assertFalse(Lead.objects.filter(pk=sem_tentativa.pk).exists())

    def test_endpoint_so_para_a_conta_do_agente_e_nao_aparece_no_roteiro_do_agente(self):
        self.lead()
        url = f"/api/companies/{self.company.pk}/agente/lembretes/"
        humano = get_user_model().objects.create_user("humano.lembrete", password="x", is_staff=True)
        self.company.members.add(humano)
        c = APIClient(); c.force_authenticate(humano)
        self.assertEqual(c.post(url).status_code, 403)
        r = self.api.post(url)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()["lembretes"]), 1)
        self.assertNotIn("lembrete", [i["question_id"] for i in contexto_agente(self.company)["fora_do_fluxo"]])

    def test_horario_so_no_lembrete_e_historico_inclui_as_mensagens(self):
        from .services import historico_da_conversa
        staff = get_user_model().objects.create_user("emp.lembrete", password="x", is_staff=True)
        self.company.members.add(staff)
        c = APIClient(); c.force_authenticate(staff)
        q = Question.objects.get(company=self.company, question_id="lembrete")
        r = c.patch(f"/api/questions/{q.pk}/?company={self.company.pk}", {"horario_envio": "09:30"}, format="json")
        self.assertEqual((r.status_code, r.json()["horario_envio"]), (200, "09:30:00"))
        outra = Question.objects.get(company=self.company, question_id="encerramento")
        self.assertEqual(c.patch(f"/api/questions/{outra.pk}/?company={self.company.pk}", {"horario_envio": "09:30"}, format="json").status_code, 400)
        Question.objects.filter(pk=q.pk).update(horario_envio=None)
        lead = self.lead()
        evento_id = self.reservar()[0]["event_id"]
        self.api.post(f"/api/companies/{self.company.pk}/delivery/", {"event_id": evento_id, "status": "SENT"}, format="json")
        textos = [m["texto"] for m in historico_da_conversa(lead) if m["quem"] == "agente"]
        self.assertEqual(len(textos), 2)


class TendenciaComNaoProsseguiramTests(TestCase):
    def test_atendimentos_por_mes_somam_os_que_nao_prosseguiram(self):
        from .models import ContagemDiaria
        from .services import resumo_dashboard
        company = Company.objects.create(name="Tendência Ltda")
        hoje = timezone.localdate()
        Lead.objects.create(company=company, contact="+5585900007001", name="A")
        ContagemDiaria.objects.create(company=company, data=hoje, novas=1, nao_prosseguiram=3)
        mes = hoje.strftime("%Y-%m")
        r = resumo_dashboard(company)
        self.assertEqual(dict(r["por_mes"])[mes], 4)
        self.assertEqual(r["total"], 4)
        # Com filtro de área as apagadas não existem mais como lead: não entram nem no total nem na tendência.
        r = resumo_dashboard(company, area="Qualquer")
        self.assertEqual(dict(r["por_mes"]).get(mes, 0), 0)

    def test_resumo_traz_leads_por_temperatura(self):
        from .services import resumo_dashboard
        company = Company.objects.create(name="Temp Ltda")
        for i, t in enumerate(["Quente", "Quente", "Frio", "", "Desconfiado"]):
            Lead.objects.create(company=company, contact=f"+558590000800{i}", temperature=t)
        r = resumo_dashboard(company)
        self.assertEqual(r["por_temperatura"], {"Desqualificado": 0, "Desconfiado": 1, "Frio": 1, "Qualificado": 0, "Quente": 2})


class NotasSoDaSpinDaAreaTests(TestCase):
    def test_fluxo_classico_ignora_notas_de_spin_de_outra_area(self):
        from .services import _aplicar_notas_urgencia
        company = Company.objects.create(name="Spin Área Ltda")
        seed_roteiro_padrao(company)
        consumidor = Area.objects.create(company=company, name="Consumidor")
        trabalhista = Area.objects.create(company=company, name="Trabalhista")
        alta = Variavel.objects.create(company=company, name="Alta", peso=10)
        baixa = Variavel.objects.create(company=company, name="Baixa", peso=2)
        Question.objects.create(company=company, question_id="cons_situacao", area=consumidor, text="?", variavel=baixa, etapa_spin="situacao")
        Question.objects.create(company=company, question_id="trab_situacao", area=trabalhista, text="?", variavel=alta, etapa_spin="situacao")
        Question.objects.create(company=company, question_id="fixa_renda", text="?", variavel=baixa)
        lead = Lead.objects.create(company=company, contact="+5585900008001", especialidade="Consumidor")
        fields, erro = _aplicar_notas_urgencia(lead, company, {"notas": {"cons_situacao": 8, "trab_situacao": 0, "fixa_renda": 6}})
        self.assertIsNone(erro)
        self.assertEqual(set(lead.urgencia_detalhe["notas"]) - {"_detalhamento"}, {"cons_situacao", "fixa_renda"})
        # Só nota de outra área: nada para calcular.
        outro = Lead.objects.create(company=company, contact="+5585900008002", especialidade="Consumidor")
        _, erro = _aplicar_notas_urgencia(outro, company, {"notas": {"trab_situacao": 9}})
        self.assertIsNone(erro)
        self.assertEqual(outro.urgencia_detalhe, {})


class ClassificacaoCortesERegraTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Cortes Ltda")
        seed_roteiro_padrao(self.company)
        self.staff = get_user_model().objects.create_user("emp-cortes", password="x", is_staff=True)
        self.company.members.add(self.staff)
        self.api = APIClient(); self.api.force_authenticate(self.staff)
        self.url = f"/api/companies/{self.company.pk}/"

    def test_faixas_padrao_e_cortes_da_empresa(self):
        from .services import faixas_da_empresa, calcular_urgencia
        self.assertEqual([(a, b) for a, b, _ in faixas_da_empresa(self.company)], [(0, 3), (3, 5), (5, 7), (7, 9), (9, None)])
        self.company.classificacao_cortes = [2, 4, 6, 8]
        faixas = faixas_da_empresa(self.company)
        # Mesma média 8,5: no padrão é Qualificado; com cortes flexíveis é Quente.
        self.assertEqual(calcular_urgencia({"a": 8.5}, {"a": 5})[1], "Qualificado")
        self.assertEqual(calcular_urgencia({"a": 8.5}, {"a": 5}, faixas)[1], "Quente")

    def test_patch_valida_e_grava_cortes_e_regra(self):
        r = self.api.patch(self.url, {"classificacao_cortes": [2, 4, 6, 8.5], "classificacao_regra": "  Prazo judicial pesa mais.  "}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.company.refresh_from_db()
        self.assertEqual(self.company.classificacao_cortes, [2.0, 4.0, 6.0, 8.5])
        self.assertEqual(self.company.classificacao_regra, "Prazo judicial pesa mais.")
        for ruim in ([5, 4, 6, 8], [1, 2, 3], [0, 3, 5, 7], [3, 5, 7, 10], ["a", 2, 3, 4], [3, 3.05, 7, 9]):
            self.assertEqual(self.api.patch(self.url, {"classificacao_cortes": ruim}, format="json").status_code, 400, ruim)
        self.assertEqual(self.api.patch(self.url, {"classificacao_regra": "x" * 1501}, format="json").status_code, 400)

    def test_contexto_do_agente_traz_faixas_da_empresa_e_a_regra(self):
        Company.objects.filter(pk=self.company.pk).update(classificacao_cortes=[2, 4, 6, 8], classificacao_regra="Benefício cortado = nota alta.")
        self.company.refresh_from_db()
        ctx = contexto_agente(self.company)
        self.assertEqual([(f["min"], f["max_exclusivo"]) for f in ctx["faixas_urgencia"]], [(0, 2), (2, 4), (4, 6), (6, 8), (8, None)])
        self.assertEqual(ctx["regra_classificacao"], "Benefício cortado = nota alta.")

    def test_classificado_usa_os_cortes_da_empresa(self):
        from .services import _aplicar_notas_urgencia
        Variavel.objects.filter(company=self.company, builtin=True).update(peso=0)
        q = Question.objects.get(company=self.company, question_id="situacao")
        Company.objects.filter(pk=self.company.pk).update(classificacao_cortes=[2, 4, 6, 8])
        self.company.refresh_from_db()
        lead = Lead.objects.create(company=self.company, contact="+5585900009100")
        fields, erro = _aplicar_notas_urgencia(lead, self.company, {"notas": {"situacao": 8.5}})
        self.assertIsNone(erro)
        self.assertEqual(fields["temperatura"], "Quente")


class DespachoEspecialPelaEmpresaTests(TestCase):
    def test_empresa_sem_responsavel_marca_origem_e_dashboard_mostra_rotulo(self):
        from .services import despachar_situacao_especial, resumo_dashboard
        company = Company.objects.create(name="Esp Ltda")
        empresa = get_user_model().objects.create_user("emp-esp", password="x", is_staff=True)
        atendente = get_user_model().objects.create_user("at-esp", password="x")
        company.members.add(empresa, atendente)
        sem_dono = Lead.objects.create(company=company, contact="+5585900009201", name="A", situacao_especial="acompanhamento", bot_closed=True)
        com_dono = Lead.objects.create(company=company, contact="+5585900009202", name="B", situacao_especial="acompanhamento", bot_closed=True, owner=atendente)
        self.assertIsNone(despachar_situacao_especial(sem_dono.pk, empresa))
        self.assertIsNone(despachar_situacao_especial(com_dono.pk, empresa))
        sem_dono.refresh_from_db(); com_dono.refresh_from_db()
        self.assertTrue(sem_dono.despachado_pela_empresa)
        self.assertIsNone(sem_dono.owner_id)
        self.assertFalse(com_dono.despachado_pela_empresa)
        self.assertEqual(com_dono.owner_id, atendente.pk)
        r = resumo_dashboard(company)
        donos = {c["name"]: c["owner"] for c in r["concluidos"]}
        self.assertEqual(donos["A"], "Despachado pela Empresa")
        self.assertNotEqual(donos["B"], "Despachado pela Empresa")
        # Não vira atendente no desempenho.
        self.assertTrue(all(o["owner_id"] != empresa.pk for o in r["por_owner"]))


class KanbanAPartirDeTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Kanban Ltda")
        seed_roteiro_padrao(self.company)
        self.staff = get_user_model().objects.create_user("emp-kb", password="x", is_staff=True)
        self.company.members.add(self.staff)
        self.api = APIClient(); self.api.force_authenticate(self.staff)

    def test_padrao_mantem_desqualificado_e_desconfiado_fora(self):
        from .services import fora_do_kanban
        self.assertEqual(self.company.classificacao_kanban_a_partir_de, 2)
        self.assertEqual(fora_do_kanban(self.company), {"Desqualificado", "Desconfiado"})
        self.company.classificacao_kanban_a_partir_de = 0
        self.assertEqual(fora_do_kanban(self.company), set())
        self.company.classificacao_kanban_a_partir_de = 4
        self.assertEqual(fora_do_kanban(self.company), {"Desqualificado", "Desconfiado", "Frio", "Qualificado"})

    def test_patch_valida_o_indice(self):
        url = f"/api/companies/{self.company.pk}/"
        self.assertEqual(self.api.patch(url, {"classificacao_kanban_a_partir_de": 3}, format="json").status_code, 200)
        for ruim in (5, -1, "x"):
            self.assertEqual(self.api.patch(url, {"classificacao_kanban_a_partir_de": ruim}, format="json").status_code, 400, ruim)

    def test_subir_o_limite_conclui_leads_abertos_sem_responsavel_e_poupa_os_assumidos(self):
        atendente = get_user_model().objects.create_user("at-kb", password="x")
        self.company.members.add(atendente)
        solto = Lead.objects.create(company=self.company, contact="+5585900009301", name="Solto", temperature="Frio", bot_closed=True)
        assumido = Lead.objects.create(company=self.company, contact="+5585900009302", name="Assumido", temperature="Frio", bot_closed=True, owner=atendente, mode="HUMANO", etapa_atendimento="negociacao")
        quente = Lead.objects.create(company=self.company, contact="+5585900009303", name="Quente", temperature="Quente", bot_closed=True)
        r = self.api.patch(f"/api/companies/{self.company.pk}/", {"classificacao_kanban_a_partir_de": 3}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        for l in (solto, assumido, quente):
            l.refresh_from_db()
        self.assertEqual(solto.desfecho, "desqualificado")
        self.assertEqual(assumido.desfecho, "")
        self.assertEqual(quente.desfecho, "")

    def test_classificado_respeita_o_limite_da_empresa(self):
        from .services import _aplicar_notas_urgencia, fora_do_kanban
        # Qualificado (7-9) fora do Kanban quando o limite é Quente; Desconfiado dentro quando o limite é 0.
        self.company.classificacao_kanban_a_partir_de = 4
        self.assertIn("Qualificado", fora_do_kanban(self.company))
        self.company.classificacao_kanban_a_partir_de = 0
        self.assertNotIn("Desconfiado", fora_do_kanban(self.company))

    def test_dashboard_categoriza_pelo_limite_da_empresa(self):
        from .services import resumo_dashboard
        Lead.objects.create(company=self.company, contact="+5585900009311", name="D", temperature="Desconfiado", bot_closed=True)
        self.assertEqual(resumo_dashboard(self.company)["status"]["desqualificado"], 1)
        self.assertEqual(resumo_dashboard(self.company)["status"]["aguardando"], 0)
        Company.objects.filter(pk=self.company.pk).update(classificacao_kanban_a_partir_de=0)
        self.company.refresh_from_db()
        r = resumo_dashboard(self.company)
        self.assertEqual((r["status"]["desqualificado"], r["status"]["aguardando"]), (0, 1))


class ImpactoDaClassificacaoTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Impacto Ltda")
        seed_roteiro_padrao(self.company)
        self.staff = get_user_model().objects.create_user("emp-imp", password="x", is_staff=True)
        self.atendente = get_user_model().objects.create_user("at-imp", password="x")
        self.company.members.add(self.staff, self.atendente)
        self.api = APIClient(); self.api.force_authenticate(self.staff)
        self.url = f"/api/companies/{self.company.pk}/classificacao/impacto/"
        mk = lambda i, media, temp, **kw: Lead.objects.create(
            company=self.company, contact=f"+558590000950{i}", name=f"L{i}", temperature=temp, bot_closed=True,
            urgencia_detalhe={"score": media, "temperatura_calculada": temp}, **kw)
        self.quente = mk(1, 9.4, "Quente", priority="Alta")
        self.qualif = mk(2, 7.6, "Qualificado", priority="Média")
        self.frio = mk(3, 5.8, "Frio", priority="Baixa")
        self.espera = mk(4, 5.2, "Frio", etapa_atendimento="espera")
        self.negociando = mk(5, 5.2, "Frio", etapa_atendimento="negociacao", owner=self.atendente, mode="HUMANO")

    def impacto(self, **corpo):
        return self.api.post(self.url, corpo, format="json")

    def test_simulacao_lista_so_classificados_que_sairiam_e_nao_grava_nada(self):
        r = self.impacto(classificacao_cortes=[3, 6, 8, 9])  # Frio vira Desconfiado (média 5,8 < 6): sai do Kanban
        self.assertEqual(r.status_code, 200, r.content)
        dados = r.json()
        self.assertEqual(dados["total"], 2)  # 1 sai do Kanban + 1 troca de classificação e continua
        self.assertEqual([a["name"] for a in dados["alteradas"]], ["L2"])
        self.assertEqual((dados["alteradas"][0]["de"], dados["alteradas"][0]["para"]), ("Qualificado", "Frio"))
        item = dados["afetadas"][0]
        self.assertEqual((item["name"], item["de"], item["para"], item["media"]), ("L3", "Frio", "Desconfiado", 5.8))
        self.assertEqual(dados["reclassificadas"], 1)  # Qualificado (7,6) vira Frio: continua no Kanban
        self.frio.refresh_from_db()
        self.assertEqual((self.frio.temperature, self.frio.desfecho), ("Frio", ""))  # simulação não grava

    def test_em_espera_e_em_negociacao_nunca_aparecem(self):
        r = self.impacto(classificacao_cortes=[3, 6, 8, 9])
        nomes = {a["name"] for a in r.json()["afetadas"]}
        self.assertNotIn("L4", nomes)
        self.assertNotIn("L5", nomes)

    def test_limite_do_kanban_tambem_afeta(self):
        r = self.impacto(classificacao_cortes=[3, 5, 7, 9], classificacao_kanban_a_partir_de=3)  # Frio sai
        self.assertEqual([a["name"] for a in r.json()["afetadas"]], ["L3"])
        self.assertEqual(r.json()["alteradas"], [])

    def test_sem_efeito_retorna_vazio_e_valida_entrada(self):
        self.assertEqual(self.impacto(classificacao_cortes=[3, 5, 7, 9]).json()["total"], 0)  # nada muda: sem alerta
        self.assertEqual(self.impacto(classificacao_cortes=[5, 4, 6, 8]).status_code, 400)
        self.assertEqual(self.impacto().status_code, 400)
        atendente = APIClient(); atendente.force_authenticate(self.atendente)
        self.assertEqual(atendente.post(self.url, {"classificacao_cortes": [3, 5, 7, 9]}, format="json").status_code, 403)

    def test_salvar_reclassifica_classificados_e_conclui_os_que_saem_do_kanban(self):
        r = self.api.patch(f"/api/companies/{self.company.pk}/", {"classificacao_cortes": [3, 6, 8, 9]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        for l in (self.quente, self.qualif, self.frio, self.espera, self.negociando):
            l.refresh_from_db()
        self.assertEqual((self.frio.temperature, self.frio.desfecho), ("Desconfiado", "desqualificado"))
        self.assertEqual((self.qualif.temperature, self.qualif.priority, self.qualif.desfecho), ("Frio", "Baixa", ""))
        self.assertEqual((self.quente.temperature, self.quente.priority), ("Quente", "Alta"))
        self.assertEqual((self.espera.temperature, self.espera.desfecho), ("Frio", ""))  # em espera: intacta
        self.assertEqual((self.negociando.temperature, self.negociando.desfecho), ("Frio", ""))


class CobrancasPrecosETesteTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("adm-cob", password="x")
        self.api = APIClient(); self.api.force_authenticate(self.admin)
        self.empresa = get_user_model().objects.create_user("emp-cob", password="x", is_staff=True)
        self.company = Company.objects.create(name="Cobrança Ltda")
        self.company.members.add(self.empresa)

    def test_valores_iniciais_e_so_superusuario(self):
        r = self.api.get("/api/admin-precos/")
        self.assertEqual(r.status_code, 200, r.content)
        itens = {i["item"]: i for i in r.json()["itens"]}
        self.assertEqual({k: v["valor"] for k, v in itens.items()}, {"implantacao": "5900.00", "base": "890.00", "empresa_adicional": "890.00", "agente_adicional": "400.00", "piloto": "2900.00"})
        comum = APIClient(); comum.force_authenticate(self.empresa)
        self.assertEqual(comum.get("/api/admin-precos/").status_code, 403)
        self.assertEqual(comum.post("/api/admin-precos/", {}, format="json").status_code, 403)

    def test_alterar_valor_cria_linha_com_vigencia_sem_apagar_a_anterior(self):
        from datetime import date, timedelta
        futura = (date.today() + timedelta(days=30)).isoformat()
        r = self.api.post("/api/admin-precos/", {"item": "base", "valor": "990", "vigente_desde": futura, "escopo": "reajuste"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        base = {i["item"]: i for i in r.json()["itens"]}["base"]
        self.assertEqual(base["valor"], "890.00")  # ainda não vigente: o de hoje continua valendo
        self.assertEqual(base["proximo"]["valor"], "990.00")
        self.assertEqual(r.json()["historico"][0]["por"], self.admin.username)
        hoje = date.today().isoformat()
        r = self.api.post("/api/admin-precos/", {"item": "agente_adicional", "valor": "450,50", "vigente_desde": hoje, "escopo": "novos"}, format="json")
        self.assertEqual({i["item"]: i for i in r.json()["itens"]}["agente_adicional"]["valor"], "450.50")
        from .models import PrecoCobranca
        self.assertEqual(PrecoCobranca.objects.filter(item="agente_adicional").count(), 2)  # a antiga continua no histórico

    def test_validacoes_do_preco(self):
        corpo = {"item": "base", "valor": "100", "vigente_desde": "2026-12-01", "escopo": "novos"}
        for troca in ({"item": "xyz"}, {"valor": "abc"}, {"valor": "-5"}, {"vigente_desde": "amanhã"}, {"escopo": "outro"}, {"vigente_desde": "2026-01-01"}):
            self.assertEqual(self.api.post("/api/admin-precos/", {**corpo, **troca}, format="json").status_code, 400, troca)

    def test_teste_ligar_prorrogar_converter(self):
        url = f"/api/admin-companies/{self.company.pk}/teste/"
        r = self.api.post(url, {"em_teste": True, "inicio": "2026-10-12", "dias": 30}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        dados = r.json()
        self.assertEqual((dados["em_teste"], dados["dias"], dados["fim"]), (True, 30, "2026-11-11"))
        r = self.api.post(url + "prorrogar/", {"dias": 15}, format="json")
        self.assertEqual((r.json()["dias"], r.json()["fim"]), (45, "2026-11-26"))
        r = self.api.post(url + "converter/", format="json")
        self.assertEqual((r.json()["em_teste"], r.json()["situacao"]), (False, "Contrato ativo"))
        self.assertEqual(self.api.post(url + "converter/", format="json").status_code, 400)  # já não está em teste
        self.assertEqual(self.api.post(url + "prorrogar/", {"dias": 15}, format="json").status_code, 400)

    def test_teste_desligar_validar_e_lista_traz_a_situacao(self):
        url = f"/api/admin-companies/{self.company.pk}/teste/"
        self.assertEqual(self.api.post(url, {"em_teste": True, "dias": 0}, format="json").status_code, 400)
        self.api.post(url, {"em_teste": True, "dias": 10}, format="json")
        lista = self.api.get("/api/admin-companies/").json()["results"]
        self.assertTrue(next(c for c in lista if c["id"] == self.company.pk)["teste"]["em_teste"])
        self.api.post(url, {"em_teste": False}, format="json")
        self.company.refresh_from_db()
        self.assertFalse(self.company.em_teste)
        comum = APIClient(); comum.force_authenticate(self.empresa)
        self.assertEqual(comum.post(url, {"em_teste": True}, format="json").status_code, 403)

    def test_tabela_conta_empresas_em_teste_fora_da_base(self):
        from .services import tabela_de_precos
        Company.objects.create(name="Piloto Ltda", em_teste=True)
        itens = {i["item"]: i for i in tabela_de_precos()["itens"]}
        self.assertEqual((itens["piloto"]["em_uso"], itens["base"]["em_uso"]), (1, 1))
