from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

import io

from PIL import Image

from .forms import EscalaForm
from .models import (
    Agendamento, AvisoExterno, Candidatura, Configuracao, VagaCandidatura, Curso, DiaPlanejado, DiaSemEstagio, Documento, Escala, Estagio, ImpressaoFrequencia,
    FolhaEnviada, HistoricoRegistro, LocalEstagio, Notificacao, Registro, TrocaSupervisor, Turma, Usuario,
)
from .services import criar_usuario, gerar_username, linhas_folha, resumo_horas, status_periodo
from .validators import cnpj_valido, cpf_valido

QUARTA = date(2026, 11, 11)


def _ativo(user):
    user.deve_trocar_senha = False
    user.save()
    return user


@override_settings(SENHA_PADRAO="senha-teste-1")
class Base(TestCase):
    def setUp(self):
        self.ori = _ativo(criar_usuario("Paula Orientadora", Usuario.Papel.ORIENTADOR))
        self.local = LocalEstagio.objects.create(nome="Empresa X")
        self.sup = _ativo(criar_usuario("Sérgio Supervisor", Usuario.Papel.SUPERVISOR, concedente=self.local))
        self.curso = Curso.objects.create(nome="Informática", carga_horaria=100, horas_por_dia_padrao=4)
        self.turma = Turma.objects.create(curso=self.curso, nome="3º A", ano_ingresso=2024, ano_estagio=2026)
        self.aluno = _ativo(criar_usuario("Maria da Silva Souza", Usuario.Papel.ESTAGIARIO))
        self.est = Estagio.objects.create(estagiario=self.aluno, orientador=self.ori, supervisor=self.sup,
                                          curso=self.curso, turma=self.turma, local=self.local, data_inicio=date(2026, 11, 2))
        Escala.objects.create(estagio=self.est, vigente_desde=date(2026, 11, 2), dias="0,1", horas_por_dia=4)
        patcher = mock.patch("django.utils.timezone.localdate", return_value=QUARTA)
        patcher.start()
        self.addCleanup(patcher.stop)

    def entrar(self, user):
        self.client.force_login(user)


class ContasTests(Base):
    def test_username_primeiro_ultimo_sem_acento(self):
        self.assertEqual(self.aluno.username, "maria.souza")
        self.assertEqual(gerar_username("Maria Clara Souza"), "maria.souza2")
        self.assertEqual(gerar_username("José Ávila Conceição"), "jose.conceicao")

    def test_troca_de_senha_obrigatoria(self):
        novo = criar_usuario("Novo Aluno", Usuario.Papel.ESTAGIARIO)
        self.assertTrue(self.client.login(username="novo.aluno", password="senha-teste-1"))
        self.assertRedirects(self.client.get("/painel/"), reverse("trocar_senha"), fetch_redirect_response=False)
        r = self.client.post(reverse("trocar_senha"), {"old_password": "senha-teste-1", "new_password1": "Outra#Senha9",
                                                       "new_password2": "Outra#Senha9"})
        self.assertEqual(r.status_code, 302)
        novo.refresh_from_db()
        self.assertFalse(novo.deve_trocar_senha)

    def test_cadastro_em_lote_cria_contas_estagios_e_escalas(self):
        self.entrar(self.ori)
        r = self.client.post(reverse("criar_estagiarios"), {
            "nomes": "Ana Clara Lima\nBruno Dias; 2024999", "turma": self.turma.pk, "local": self.local.pk,
            "supervisor": self.sup.pk, "data_inicio": "2026-11-16", "dias": ["0", "1", "2", "3", "4"], "horas_por_dia": "4",
        })
        self.assertContains(r, "ana.lima")
        self.assertContains(r, "bruno.dias")
        bruno = Usuario.objects.get(username="bruno.dias")
        self.assertEqual(bruno.matricula, "2024999")
        self.assertTrue(bruno.deve_trocar_senha)
        self.assertEqual(bruno.estagios.get().escalas.get().dias, "0,1,2,3,4")

    def test_estagiario_nao_acessa_area_do_orientador(self):
        self.entrar(self.aluno)
        self.assertEqual(self.client.get(reverse("painel")).status_code, 403)
        self.assertEqual(self.client.get(reverse("criar_estagiarios")).status_code, 403)


class EscalaEStatusTests(Base):
    def test_mudanca_de_escala_a_partir_de_data(self):
        # seg/ter até 15/11, depois seg-sex
        Escala.objects.create(estagio=self.est, vigente_desde=date(2026, 11, 16), dias="0,1,2,3,4", horas_por_dia=4)
        dias = {s.data: s for s in status_periodo(self.est, date(2026, 11, 9), date(2026, 11, 20))}
        self.assertTrue(dias[date(2026, 11, 10)].previsto)       # terça antes
        self.assertFalse(dias[date(2026, 11, 12)].previsto)      # quinta antes
        self.assertTrue(dias[date(2026, 11, 19)].previsto)       # quinta depois
        self.assertEqual(dias[date(2026, 11, 9)].codigo, "sem_registro")

    def test_escala_em_lote(self):
        self.entrar(self.ori)
        self.client.post(reverse("escala_lote"), {"estagios": [self.est.pk], "vigente_desde": "2026-11-16",
                                                  "dias": ["0", "1", "2", "3", "4"], "horas_por_dia": "4"})
        self.assertEqual(self.est.escalas.count(), 2)
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto__contains="16/11").exists())


class FluxoDiarioTests(Base):
    def setUp(self):
        super().setUp()
        Escala.objects.create(estagio=self.est, vigente_desde=QUARTA, dias="0,1,2", horas_por_dia=4)

    def test_estagiario_marca_presenca_e_supervisor_confirma(self):
        self.entrar(self.aluno)
        self.client.post(reverse("marcar_presenca", args=[self.est.pk]), {"diario": "Configurei redes"})
        reg = Registro.objects.get(estagio=self.est, data=QUARTA)
        self.assertEqual(reg.situacao, Registro.Situacao.PRESENTE)
        self.assertEqual(reg.confirmacao, Registro.Confirmacao.PENDENTE)
        self.assertEqual(reg.diario, "Configurei redes")
        self.assertTrue(Notificacao.objects.filter(usuario=self.sup).exists())
        # horas pendentes ainda não contam como cumpridas
        self.assertEqual(resumo_horas(self.est)["cumpridas"], Decimal(0))

        self.entrar(self.sup)
        self.client.post(reverse("confirmar_lote"), {"registros": [reg.pk]})
        reg.refresh_from_db()
        self.assertEqual(reg.confirmacao, Registro.Confirmacao.CONFIRMADA)
        self.assertEqual(reg.confirmado_por, self.sup)
        self.assertEqual(resumo_horas(self.est)["cumpridas"], Decimal(4))

    def test_ausencia_informada(self):
        self.entrar(self.aluno)
        self.client.post(reverse("informar_ausencia", args=[self.est.pk]), {"data": "2026-11-16", "motivo": "Consulta"})
        reg = Registro.objects.get(data=date(2026, 11, 16))
        self.assertEqual(reg.situacao, Registro.Situacao.AUSENCIA)
        self.assertTrue(Notificacao.objects.filter(usuario=self.ori, texto__contains="Consulta").exists())

    def test_supervisor_lanca_dia_esquecido(self):
        self.entrar(self.sup)
        url = reverse("estagio_dia", args=[self.est.pk, "2026-11-10"])
        self.client.post(url, {"l-situacao": "PRESENTE", "l-horas": "4", "l-confirmacao": "CONFIRMADA"})
        reg = Registro.objects.get(data=date(2026, 11, 10))
        self.assertEqual(reg.confirmacao, Registro.Confirmacao.CONFIRMADA)

    def test_outro_estagiario_nao_ve_o_estagio(self):
        outro = _ativo(criar_usuario("Outro Aluno", Usuario.Papel.ESTAGIARIO))
        self.entrar(outro)
        self.assertEqual(self.client.get(self.est.get_absolute_url()).status_code, 403)
        self.assertEqual(self.client.post(reverse("marcar_presenca", args=[self.est.pk])).status_code, 403)


class AgendaEArquivosTests(Base):
    def test_estagiario_solicita_visita_e_orientador_agenda(self):
        self.entrar(self.aluno)
        self.client.post(reverse("novo_agendamento"), {"tipo": "VISITA", "modalidade": "PRESENCIAL", "assunto": "Dúvida",
                                                       "estagios": [self.est.pk]})
        ag = Agendamento.objects.get()
        self.assertEqual(ag.status, Agendamento.Status.SOLICITADO)
        self.assertEqual(ag.orientador, self.ori)
        self.entrar(self.ori)
        self.client.post(ag.get_absolute_url(), {"tipo": "VISITA", "modalidade": "PRESENCIAL", "status": "AGENDADO",
                                                 "data_hora": "2026-11-18T14:00", "estagios": [self.est.pk], "assunto": "Dúvida"})
        ag.refresh_from_db()
        self.assertEqual(ag.status, Agendamento.Status.AGENDADO)
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto__contains="18/11").exists())

    @override_settings(MEDIA_ROOT=str(settings.DATA_DIR / "anexos-testes"))
    def test_arquivo_so_para_quem_pode(self):
        self.entrar(self.ori)
        arq = SimpleUploadedFile("frequencia.pdf", b"%PDF-1.4 teste", content_type="application/pdf")
        self.client.post(reverse("enviar_documento", args=[self.est.pk]),
                         {"titulo": "Frequência outubro", "categoria": "FREQUENCIA", "arquivo": arq})
        doc = Documento.objects.get()
        self.entrar(self.aluno)
        self.assertEqual(self.client.get(reverse("baixar_documento", args=[doc.pk])).status_code, 200)
        self.entrar(_ativo(criar_usuario("Intruso Silva", Usuario.Papel.ESTAGIARIO)))
        self.assertEqual(self.client.get(reverse("baixar_documento", args=[doc.pk])).status_code, 403)
        doc.arquivo.delete()


class TurnosTests(Base):
    def _dados(self, **kw):
        d = {"vigente_desde": "2026-11-16", "dias": ["0", "1"], "horas_por_dia": "8", "horario_entrada": "07:00",
             "saida_intervalo": "11:00", "volta_intervalo": "13:00", "horario_saida": "17:00"}
        d.update(kw)
        return d

    def test_escala_de_8h_com_intervalo(self):
        form = EscalaForm(data=self._dados())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.dados_escala()["saida_intervalo"].hour, 11)

    def test_horarios_que_nao_somam_a_carga(self):
        form = EscalaForm(data=self._dados(horario_saida="16:00"))
        self.assertFalse(form.is_valid())
        self.assertIn("somam 7h", str(form.errors))
        form = EscalaForm(data=self._dados(volta_intervalo=""))
        self.assertFalse(form.is_valid())

    def test_estagiario_registra_intervalo_e_saida(self):
        from datetime import time

        Escala.objects.create(estagio=self.est, vigente_desde=QUARTA, dias="2", horas_por_dia=8, horario_entrada=time(7),
                              saida_intervalo=time(11), volta_intervalo=time(13), horario_saida=time(17))
        self.entrar(self.aluno)
        self.client.post(reverse("marcar_presenca", args=[self.est.pk]))
        r = self.client.get(self.est.get_absolute_url())
        self.assertContains(r, "Saí para o intervalo")
        for ponto in ("saida_intervalo", "volta_intervalo", "hora_saida"):
            self.client.post(reverse("registrar_saida", args=[self.est.pk]), {"ponto": ponto})
        reg = Registro.objects.get(estagio=self.est, data=QUARTA)
        self.assertTrue(reg.saida_intervalo and reg.volta_intervalo and reg.hora_saida)
        self.assertEqual(reg.horas, 8)


class PrevisaoTests(Base):
    """Escala seg/ter 4h desde 02/11, curso de 100h, hoje = quarta 11/11."""

    def test_ausencia_adia_e_dia_extra_antecipa(self):
        inicial = resumo_horas(self.est)["previsao_termino"]
        self.entrar(self.aluno)
        r = self.client.post(reverse("informar_ausencia", args=[self.est.pk]),
                             {"data": "2026-11-16", "motivo": "Evento da escola"}, follow=True)
        adiada = resumo_horas(self.est)["previsao_termino"]
        self.assertGreater(adiada, inicial)
        self.assertContains(r, "Previsão de término adiada")

        self.client.post(reverse("estagio_dia", args=[self.est.pk, "2026-11-12"]),
                         {"planejar": "salvar", "p-horas": "8", "p-motivo": "Reposição"})
        self.assertTrue(DiaPlanejado.objects.filter(estagio=self.est, data=date(2026, 11, 12), horas=8).exists())
        self.assertLess(resumo_horas(self.est)["previsao_termino"], adiada)
        dia = status_periodo(self.est, date(2026, 11, 12), date(2026, 11, 12))[0]
        self.assertTrue(dia.previsto and dia.extra)
        self.assertTrue(Notificacao.objects.filter(usuario=self.sup, texto__contains="12/11").exists())

    def test_cancelar_ausencia_futura(self):
        self.entrar(self.aluno)
        self.client.post(reverse("informar_ausencia", args=[self.est.pk]), {"data": "2026-11-16", "motivo": "Prova"})
        self.client.post(reverse("estagio_dia", args=[self.est.pk, "2026-11-16"]), {"planejar": "cancelar_ausencia"})
        self.assertFalse(Registro.objects.filter(data=date(2026, 11, 16)).exists())

    def test_nao_planeja_dia_passado(self):
        self.entrar(self.aluno)
        self.client.post(reverse("estagio_dia", args=[self.est.pk, "2026-11-05"]), {"planejar": "salvar", "p-horas": "4"})
        self.assertFalse(DiaPlanejado.objects.exists())

    def test_termo_nao_limita_e_calendario_para_no_fim_previsto(self):
        self.est.data_fim = date(2026, 11, 20)
        self.est.save()
        h = resumo_horas(self.est)
        self.assertTrue(h["apos_termo"])
        self.assertGreater(h["dias_restantes"], 0)
        depois = status_periodo(self.est, h["previsao_termino"] + timedelta(days=7), h["previsao_termino"] + timedelta(days=7),
                                limite=h["previsao_termino"])[0]
        self.assertEqual(depois.codigo, "fora")


class FolhaFrequenciaTests(Base):
    def test_abertura_impressao_e_quem_ve_o_registro(self):
        self.entrar(self.aluno)
        r = self.client.get(reverse("folha_frequencia", args=[self.est.pk]) + "?mes=2026-11")
        self.assertContains(r, "FREQUÊNCIA DE ESTÁGIO")
        log = ImpressaoFrequencia.objects.get()
        self.assertEqual((log.usuario, log.mes), (self.aluno, date(2026, 11, 1)))
        self.assertContains(r, log.codigo)
        self.assertEqual(self.client.post(reverse("marcar_impressao"), {"codigo": log.codigo}).status_code, 204)
        log.refresh_from_db()
        self.assertEqual(log.impressoes, 1)
        # o estagiário não vê o registro
        self.assertNotContains(self.client.get(self.est.get_absolute_url()), "Folhas de frequência")
        self.assertEqual(self.client.get(reverse("frequencias")).status_code, 403)

        self.entrar(self.sup)
        self.assertEqual(self.client.post(reverse("marcar_impressao"), {"codigo": log.codigo}).status_code, 400)
        self.assertContains(self.client.get(self.est.get_absolute_url()), "Folhas de frequência")
        r = self.client.get(reverse("frequencias") + "?mes=2026-11")
        self.assertContains(r, "Imprimiu")
        r = self.client.get(reverse("frequencias") + f"?codigo={log.codigo.lower()}")
        self.assertContains(r, "Emitida por")

    def test_linhas_com_feriado_e_fim_de_semana(self):
        DiaSemEstagio.objects.create(data=date(2026, 11, 20), descricao="Consciência Negra", orientador=self.ori)
        linhas = linhas_folha(self.est, 2026, 11)
        self.assertEqual(len(linhas), 30)
        self.assertEqual(linhas[19]["feriado"], "Consciência Negra")
        self.assertTrue(linhas[19]["cinza"])
        self.assertTrue(linhas[7]["cinza"])       # domingo 08/11
        self.assertFalse(linhas[9]["cinza"])      # terça 10/11
        self.assertEqual(linhas[9]["dia_semana"], "Terça")


class ConcedenteEPerfilTests(Base):
    def test_validadores(self):
        self.assertTrue(cpf_valido("529.982.247-25"))
        self.assertFalse(cpf_valido("111.111.111-11"))
        self.assertTrue(cnpj_valido("11.222.333/0001-81"))
        self.assertFalse(cnpj_valido("11.222.333/0001-80"))

    def test_cadastro_de_concedente_com_supervisores(self):
        self.entrar(self.ori)
        dados = {"tipo_concedente": "PJ", "nome": "Clínica Vida", "razao_social": "Clínica Vida LTDA",
                 "tipo_instituicao": "PRIVADA", "cnpj": "11222333000181", "cep": "60025100", "uf": "ce",
                 "novos_supervisores": "Rita de Cássia Lopes; (85) 98888-1111"}
        r = self.client.post(reverse("local_novo"), {**dados, "cnpj": "11222333000180"})
        self.assertContains(r, "CNPJ inválido")
        r = self.client.post(reverse("local_novo"), dados)
        self.assertContains(r, "rita.lopes")
        local = LocalEstagio.objects.get(nome="Clínica Vida")
        self.assertEqual((local.cnpj, local.cep, local.uf), ("11.222.333/0001-81", "60025-100", "CE"))
        self.assertEqual(list(Usuario.objects.get(username="rita.lopes").concedentes.all()), [local])

    @override_settings(MEDIA_ROOT=str(settings.DATA_DIR / "anexos-testes"))
    def test_foto_de_perfil_recortada(self):
        buf = io.BytesIO()
        Image.new("RGB", (1200, 800), "red").save(buf, "PNG")
        self.entrar(self.aluno)
        r = self.client.post(reverse("perfil"), {"foto": SimpleUploadedFile("eu.png", buf.getvalue(), "image/png"),
                                                 "email": "", "telefone": "", "cpf": "529.982.247-25"})
        self.assertEqual(r.status_code, 302)
        self.aluno.refresh_from_db()
        with self.aluno.foto.open("rb") as f:
            self.assertEqual(Image.open(f).size, (400, 400))
        self.assertEqual(self.client.get(self.aluno.foto_url).status_code, 200)
        self.aluno.foto.delete()

    def test_cpf_invalido_no_perfil(self):
        self.entrar(self.aluno)
        r = self.client.post(reverse("perfil"), {"email": "", "telefone": "", "cpf": "123.456.789-00"})
        self.assertContains(r, "CPF inválido")

    def test_banco_de_talentos_liga_e_desliga(self):
        outro_sup = _ativo(criar_usuario("Selma Duarte", Usuario.Papel.SUPERVISOR))
        self.entrar(outro_sup)
        self.assertEqual(self.client.get(reverse("banco_talentos")).status_code, 404)
        cfg = Configuracao.atual()
        cfg.banco_talentos_habilitado = cfg.curriculos_habilitados = True
        cfg.save()
        self.assertNotContains(self.client.get(reverse("banco_talentos")), self.aluno.nome_completo)
        self.aluno.perfil_visivel, self.aluno.habilidades = True, "Excel, redes"
        self.aluno.save()
        r = self.client.get(reverse("banco_talentos") + "?q=excel")
        self.assertContains(r, self.aluno.nome_completo)
        self.entrar(self.aluno)
        self.assertEqual(self.client.get(reverse("banco_talentos")).status_code, 403)
        self.assertContains(self.client.get(reverse("perfil")), "Perfil profissional")


class CoordenadorTests(Base):
    def setUp(self):
        super().setUp()
        self.enf = Curso.objects.create(nome="Enfermagem", carga_horaria=200)
        self.coord = _ativo(criar_usuario("Paula Lins", Usuario.Papel.COORDENADOR))
        self.coord.cursos_coordenados.set([self.curso])
        aluna = _ativo(criar_usuario("Rita Enfermeira", Usuario.Papel.ESTAGIARIO))
        self.outro = Estagio.objects.create(estagiario=aluna, orientador=self.ori, curso=self.enf, data_inicio=date(2026, 11, 2))

    def test_ve_so_os_cursos_que_coordena(self):
        self.entrar(self.coord)
        self.assertEqual(self.client.get(reverse("painel")).status_code, 200)
        r = self.client.get(reverse("estagios_lista"))
        self.assertContains(r, self.aluno.nome_completo)
        self.assertNotContains(r, "Rita Enfermeira")
        self.assertEqual(self.client.get(self.est.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(self.outro.get_absolute_url()).status_code, 403)

    def test_nao_agenda_nem_muda_horarios(self):
        self.entrar(self.coord)
        for url in (reverse("agendamentos"), reverse("novo_agendamento"), reverse("escala_lote"),
                    reverse("dias_sem_estagio"), reverse("documentos_gerais")):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        r = self.client.post(reverse("nova_escala", args=[self.est.pk]),
                             {"vigente_desde": "2026-11-16", "dias": ["0"], "horas_por_dia": "4"})
        self.assertEqual(r.status_code, 403)
        r = self.client.get(self.est.get_absolute_url() + "?aba=escalas")
        self.assertNotContains(r, "Mudar dias a partir de uma data")
        self.assertNotContains(self.client.get(reverse("painel")), "Agendar visita")

    def test_cadastra_estagiarios_escolhendo_o_orientador(self):
        self.entrar(self.coord)
        r = self.client.post(reverse("criar_estagiarios"), {
            "nomes": "Caio Prado", "turma": self.turma.pk, "orientador": self.ori.pk, "data_inicio": "2026-11-16",
            "local": self.local.pk, "supervisor": self.sup.pk,
            "dias": ["0"], "horas_por_dia": "4"})
        self.assertContains(r, "caio.prado")
        self.assertEqual(Usuario.objects.get(username="caio.prado").estagios.get().orientador, self.ori)

    def test_administrador_cria_coordenador(self):
        self.ori.is_superuser = True
        self.ori.save()
        self.entrar(self.ori)
        r = self.client.post(reverse("criar_coordenador"), {"nome": "Lia Moura", "cursos": [self.enf.pk]})
        self.assertContains(r, "lia.moura")
        lia = Usuario.objects.get(username="lia.moura")
        self.assertTrue(lia.is_coordenador)
        self.assertEqual(list(lia.cursos_coordenados.all()), [self.enf])


class CaptacaoTests(Base):
    def _dados(self, **kw):
        d = {"tipo_concedente": "PJ", "razao_social": "Padaria Pão Quente LTDA", "nome": "Pão Quente", "uf": "CE",
             "cnpj": "11.222.333/0001-81", "contato_nome": "Jorge Amaral", "contato_telefone": "(85) 99876-5432",
             "contato_whatsapp": "on", "atividades": "Atendimento e caixa", "turnos": ["MANHA"],
             f"vaga_{self.curso.pk}": "2", "supervisor_nome": "Marta Amaral", "supervisor_telefone": "(85) 98888-7777",
             "consentimento": "on"}
        d.update(kw)
        return d

    def abrir(self):
        cfg = Configuracao.atual()
        cfg.captacao_aberta, cfg.ano_captacao = True, 2027
        cfg.save()

    def test_pagina_publica_fechada_e_aberta(self):
        r = self.client.get(reverse("candidatura_publica"))
        self.assertContains(r, "não estão abertas")
        self.abrir()
        r = self.client.post(reverse("candidatura_publica"), self._dados(**{f"vaga_{self.curso.pk}": ""}))
        self.assertContains(r, "pelo menos um curso")
        r = self.client.post(reverse("candidatura_publica"), self._dados())
        cand = Candidatura.objects.get()
        self.assertContains(r, cand.protocolo)
        self.assertEqual((cand.ano, cand.turnos, cand.total_vagas), (2027, "MANHA", 2))
        self.assertTrue(Notificacao.objects.filter(usuario=self.ori, texto__contains="Pão Quente").exists())

    def test_robo_preenchendo_campo_oculto_e_barrado(self):
        self.abrir()
        self.client.post(reverse("candidatura_publica"), self._dados(site="http://spam"))
        self.assertFalse(Candidatura.objects.exists())

    def test_aprovar_cria_concedente_supervisor_e_aviso(self):
        self.abrir()
        self.client.post(reverse("candidatura_publica"), self._dados())
        cand = Candidatura.objects.get()
        self.entrar(self.ori)
        r = self.client.post(cand.get_absolute_url(), {"acao": "aprovar", "a-destino": "nova", "a-criar_supervisor": "on"},
                             follow=True)
        cand.refresh_from_db()
        self.assertEqual(cand.status, Candidatura.Status.APROVADA)
        self.assertEqual(cand.local.cnpj, "11.222.333/0001-81")
        sup = Usuario.objects.get(username="marta.amaral")
        self.assertEqual((sup.papel, list(sup.concedentes.all())), (Usuario.Papel.SUPERVISOR, [cand.local]))
        aviso = AvisoExterno.objects.get()
        self.assertIn("aprovado", aviso.mensagem)
        self.assertIn("marta.amaral", aviso.mensagem)
        self.assertTrue(aviso.whatsapp_url.startswith("https://wa.me/5585998765432?text="))
        self.assertContains(r, "wa.me/5585998765432")
        self.client.post(reverse("aviso_enviado", args=[aviso.pk]), {"canal": "WHATSAPP", "mensagem": "Texto final"})
        aviso.refresh_from_db()
        self.assertEqual((aviso.status, aviso.mensagem, aviso.enviado_por), ("ENVIADO", "Texto final", self.ori))

    def test_aprovar_atualizando_concedente_existente(self):
        existente = LocalEstagio.objects.create(nome="Pão Quente", cnpj="11.222.333/0001-81")
        self.abrir()
        self.client.post(reverse("candidatura_publica"), self._dados(bairro="Centro"))
        cand = Candidatura.objects.get()
        self.entrar(self.ori)
        r = self.client.get(cand.get_absolute_url())
        self.assertContains(r, "Já existe uma concedente parecida")
        self.client.post(cand.get_absolute_url(), {"acao": "aprovar", "a-destino": str(existente.pk)})
        existente.refresh_from_db()
        self.assertEqual((existente.bairro, LocalEstagio.objects.filter(nome="Pão Quente").count()), ("Centro", 1))

    def test_recusar_e_visao_do_coordenador(self):
        self.abrir()
        self.client.post(reverse("candidatura_publica"), self._dados())
        cand = Candidatura.objects.get()
        outro_curso = Curso.objects.create(nome="Enfermagem")
        coord = _ativo(criar_usuario("Lia Moura", Usuario.Papel.COORDENADOR))
        coord.cursos_coordenados.set([outro_curso])
        self.entrar(coord)
        self.assertEqual(self.client.get(cand.get_absolute_url()).status_code, 403)
        self.assertNotContains(self.client.get(reverse("captacao") + "?ano=2027"), "Pão Quente")
        coord.cursos_coordenados.add(self.curso)
        coord = Usuario.objects.get(pk=coord.pk)
        self.entrar(coord)
        self.client.post(cand.get_absolute_url(), {"acao": "recusar", "r-parecer": "Sem vagas no curso este ano."})
        cand.refresh_from_db()
        self.assertEqual(cand.status, Candidatura.Status.RECUSADA)
        self.assertIn("Sem vagas", AvisoExterno.objects.get().mensagem)
        self.entrar(self.aluno)
        self.assertEqual(self.client.get(reverse("captacao")).status_code, 403)


class ImportacaoCSVTests(Base):
    CAB = ("estagiario_nome;estagiario_cpf;curso;data_inicio;horas_anteriores;dias;concedente_nome;concedente_razao_social;"
           "concedente_cnpj;concedente_cidade;supervisor_nome;supervisor_telefone\n")

    def setUp(self):
        super().setUp()
        self.ori.is_superuser = True
        self.ori.save()
        self.entrar(self.ori)

    def _csv(self, linhas):
        return SimpleUploadedFile("tce.csv", ("﻿" + self.CAB + "\n".join(linhas)).encode("utf-8"), "text/csv")

    def _enviar(self, linhas, **extra):
        dados = {"etapa": "previa", "arquivo": self._csv(linhas), "orientador": self.ori.pk, "dias": ["0", "1"],
                 "horas_por_dia": "8", "horario_entrada": "07:00", "saida_intervalo": "11:00", "volta_intervalo": "13:00",
                 "horario_saida": "17:00", "acompanhamento_desde": "2026-11-11", "carga_cursos_novos": "400",
                 "completar_concedentes": "on"}
        dados.update(extra)
        return self.client.post(reverse("importar_csv"), dados)

    LINHAS = [
        "ANA BEATRIZ CASTRO FERNANDES;529.982.247-25;TÉCNICO EM DESENVOLVIMENTO DE SISTEMAS;24/08/2026;160;;"
        "CEI - JOANA DARC LEITE;SECRETARIA DA EDUCAÇÃO;30.017.109/0001-00;GENERAL SAMPAIO;GEISA MARIA MARTINS ARAUJO;(85) 3357-1081",
        "CAIO BRENO DUARTE PIRES;111.444.777-35;TÉCNICO EM DESENVOLVIMENTO DE SISTEMAS;24/08/2026;;seg-sex;"
        "ESCOLA JOSÉ BEZERRA FILHO;SECRETARIA DA EDUCAÇÃO;30.017.109/0001-00;GENERAL SAMPAIO;FRANCISCA SAMARA OLIVEIRA SILVA;",
        "MARIA ELOISA RODRIGUES MAGALHAES;;TÉCNICO EM DESENVOLVIMENTO DE SISTEMAS;01/09/2026;;;"
        "ESCOLA JOSÉ BEZERRA FILHO;SECRETARIA DA EDUCAÇÃO;30.017.109/0001-00;GENERAL SAMPAIO;FRANCISCA SAMARA OLIVEIRA SILVA;",
    ]

    def test_previa_nao_grava_e_confirmacao_cria_tudo(self):
        r = self._enviar(self.LINHAS)
        self.assertContains(r, "Confirmar importação")
        self.assertContains(r, "ana.fernandes")
        self.assertFalse(Usuario.objects.filter(username="ana.fernandes").exists())  # prévia desfeita

        r = self.client.post(reverse("importar_csv"), {"etapa": "confirmar"})
        self.assertContains(r, "ana.fernandes")
        ana = Usuario.objects.get(username="ana.fernandes")
        self.assertEqual((ana.nome_completo, ana.cpf), ("Ana Beatriz Castro Fernandes", "529.982.247-25"))
        self.assertTrue(ana.check_password("senha-teste-1"))
        est = ana.estagios.get()
        self.assertEqual((est.horas_anteriores, est.acompanhamento_desde, est.orientador), (160, date(2026, 11, 11), self.ori))
        esc = est.escalas.get()
        self.assertEqual((esc.dias, esc.horas_por_dia, esc.saida_intervalo.hour), ("0,1", 8, 11))
        self.assertEqual(Usuario.objects.get(username="caio.pires").estagios.get().escalas.get().dias, "0,1,2,3,4")
        # mesma razão social/CNPJ, unidades diferentes -> duas concedentes; supervisor repetido -> um só
        self.assertEqual(LocalEstagio.objects.filter(cnpj="30.017.109/0001-00").count(), 2)
        self.assertEqual(Usuario.objects.filter(nome_completo="Francisca Samara Oliveira Silva").count(), 1)
        self.assertEqual(Usuario.objects.get(username="geisa.araujo").telefone, "(85) 3357-1081")
        self.assertEqual(Curso.objects.get(nome__icontains="desenvolvimento").carga_horaria, 400)
        # dias antes do acompanhamento não ficam "sem registro"
        dia = status_periodo(est, date(2026, 11, 9), date(2026, 11, 9))[0]
        self.assertEqual(dia.codigo, "fora")

    def test_reenviar_o_mesmo_arquivo_nao_duplica(self):
        self._enviar(self.LINHAS)
        self.client.post(reverse("importar_csv"), {"etapa": "confirmar"})
        r = self._enviar(self.LINHAS)
        self.assertContains(r, "já tem estágio ativo")
        self.client.post(reverse("importar_csv"), {"etapa": "confirmar"})
        self.assertEqual(Estagio.objects.filter(estagiario__username="ana.fernandes").count(), 1)
        self.assertEqual(LocalEstagio.objects.filter(cnpj="30.017.109/0001-00").count(), 2)

    def test_erros_por_linha_e_cpf_repetido(self):
        linhas = [self.LINHAS[0], self.LINHAS[0],
                  "SÓNOME;;CURSO X;24/08/2026;;;Unidade;;11.111.111/1111-11;;;",
                  "JOAO SILVA;;CURSO X;32/13/2026;;;Unidade;;;;;"]
        r = self._enviar(linhas)
        self.assertContains(r, "repetido no arquivo")
        self.assertContains(r, "informe nome e sobrenome")
        self.assertContains(r, "data inválida")
        self.assertNotContains(r, "Confirmar importação")

    def test_so_administrador(self):
        self.ori.is_superuser = False
        self.ori.save()
        self.assertEqual(self.client.get(reverse("importar_csv")).status_code, 403)

    def test_modelo_csv(self):
        r = self.client.get(reverse("importar_csv") + "?modelo=1")
        self.assertIn("estagiario_nome;estagiario_cpf", r.content.decode("utf-8-sig"))


class HorariosDaConcedenteTests(Base):
    """Os horários são definidos pelo supervisor; o estagiário informa os horários do dia e o supervisor confirma."""

    HORARIO = {"horario_entrada": "07:30", "saida_intervalo": "11:30", "volta_intervalo": "13:30", "horario_saida": "17:30"}

    def test_supervisor_define_dias_e_horarios(self):
        self.entrar(self.sup)
        r = self.client.post(reverse("nova_escala", args=[self.est.pk]),
                             {"vigente_desde": "2026-11-16", "dias": ["0", "1", "2"], "horas_por_dia": "8", **self.HORARIO})
        self.assertEqual(r.status_code, 302)
        esc = self.est.escalas.get(vigente_desde=date(2026, 11, 16))
        self.assertEqual((esc.horario_entrada.hour, esc.horario_entrada.minute, esc.dias), (7, 30, "0,1,2"))
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto__contains="07:30").exists())
        self.assertTrue(Notificacao.objects.filter(usuario=self.ori, texto__contains="07:30").exists())
        # supervisor de outra concedente não mexe
        outro = _ativo(criar_usuario("Selma Duarte", Usuario.Papel.SUPERVISOR))
        self.entrar(outro)
        r = self.client.post(reverse("nova_escala", args=[self.est.pk]),
                             {"vigente_desde": "2026-11-17", "dias": ["0"], "horas_por_dia": "4"})
        self.assertEqual(r.status_code, 403)

    def test_supervisor_em_lote_e_orientador_so_muda_os_dias(self):
        self.entrar(self.sup)
        r = self.client.get(reverse("painel_supervisor"))
        self.assertContains(r, "sem horário definido")
        self.client.post(reverse("escala_lote"), {"estagios": [self.est.pk], "vigente_desde": "2026-11-11",
                                                  "dias": ["0", "1"], "horas_por_dia": "8", **self.HORARIO})
        self.assertNotContains(self.client.get(reverse("painel_supervisor")), "sem horário definido")

        self.entrar(self.ori)
        r = self.client.get(reverse("escala_lote"))
        self.assertNotContains(r, 'name="horario_entrada"')
        self.client.post(reverse("escala_lote"), {"estagios": [self.est.pk], "vigente_desde": "2026-11-16",
                                                  "dias": ["0", "1", "2", "3", "4"]})
        nova = self.est.escalas.get(vigente_desde=date(2026, 11, 16))
        self.assertEqual((nova.dias, nova.horas_por_dia, nova.horario_entrada.minute, nova.horario_saida.hour),
                         ("0,1,2,3,4", 8, 30, 17))

    def test_estagiario_informa_horarios_e_horas_sao_calculadas(self):
        self.entrar(self.aluno)
        url = reverse("estagio_dia", args=[self.est.pk, "2026-11-10"])
        self.assertContains(self.client.get(url), "Meus horários neste dia")
        self.client.post(url, {"h-hora_chegada": "07:30", "h-saida_intervalo": "11:30", "h-volta_intervalo": "13:00",
                               "h-hora_saida": "16:30"})
        reg = Registro.objects.get(estagio=self.est, data=date(2026, 11, 10))
        self.assertEqual((reg.situacao, reg.confirmacao, reg.horas), ("PRESENTE", "PENDENTE", Decimal("7.50")))
        self.assertTrue(Notificacao.objects.filter(usuario=self.sup, texto__contains="07:30").exists())
        # depois de confirmado, o estagiário não muda mais
        reg.confirmar(self.sup, Registro.Confirmacao.CONFIRMADA)
        reg.save()
        self.assertNotContains(self.client.get(url), "Meus horários neste dia")
        # mais de 7 dias atrás: só o supervisor/orientador lança
        self.assertNotContains(self.client.get(reverse("estagio_dia", args=[self.est.pk, "2026-11-02"])),
                               "Meus horários neste dia")

    def test_intervalo_incompleto_e_ordem(self):
        self.entrar(self.aluno)
        url = reverse("estagio_dia", args=[self.est.pk, "2026-11-10"])
        r = self.client.post(url, {"h-hora_chegada": "08:00", "h-saida_intervalo": "12:00", "h-hora_saida": "17:00"})
        self.assertContains(r, "saída e a volta do intervalo")
        r = self.client.post(url, {"h-hora_chegada": "14:00", "h-hora_saida": "12:00"})
        self.assertContains(r, "em ordem")
        self.assertFalse(Registro.objects.exists())

    def test_saida_pelo_botao_calcula_horas(self):
        from datetime import time

        reg = Registro.objects.create(estagio=self.est, data=QUARTA, situacao="PRESENTE", horas=4,
                                      hora_chegada=time(0, 0), registrado_por=self.aluno)
        self.entrar(self.aluno)
        self.client.post(reverse("registrar_saida", args=[self.est.pk]), {"ponto": "hora_saida"})
        reg.refresh_from_db()
        self.assertIsNotNone(reg.hora_saida)
        self.assertEqual(reg.horas, reg.calcular_horas())

    def test_lancamento_do_supervisor_calcula_pelos_horarios(self):
        self.entrar(self.sup)
        self.client.post(reverse("estagio_dia", args=[self.est.pk, "2026-11-10"]), {
            "l-situacao": "PRESENTE", "l-horas": "4", "l-hora_chegada": "08:00", "l-saida_intervalo": "12:00",
            "l-volta_intervalo": "13:00", "l-hora_saida": "15:00", "l-confirmacao": "CONFIRMADA"})
        self.assertEqual(Registro.objects.get(data=date(2026, 11, 10)).horas, Decimal("6.00"))


class SupervisorDaConcedenteTests(Base):
    """Todo estagiário tem supervisor, e o supervisor tem de estar cadastrado na concedente do estágio."""

    def setUp(self):
        super().setUp()
        self.outro_local = LocalEstagio.objects.create(nome="Empresa Y")
        self.sup_y = _ativo(criar_usuario("Yara Supervisora", Usuario.Papel.SUPERVISOR, concedente=self.outro_local))
        self.entrar(self.ori)

    def _editar(self, **kw):
        dados = {"turma": self.turma.pk, "local": self.local.pk, "supervisor": self.sup.pk, "data_inicio": "2026-11-02",
                 "horas_anteriores": "0", "ativo": "on"}
        dados.update(kw)
        return self.client.post(reverse("editar_estagio", args=[self.est.pk]), dados)

    def test_estagio_nao_aceita_supervisor_de_outra_concedente(self):
        r = self._editar(supervisor=self.sup_y.pk)
        self.assertContains(r, "não é supervisor(a) de Empresa X")
        self.est.refresh_from_db()
        self.assertEqual(self.est.supervisor, self.sup)
        # depois de cadastrada também na Empresa X, pode
        self.sup_y.concedentes.add(self.local)
        self.assertEqual(self._editar(supervisor=self.sup_y.pk).status_code, 302)
        self.est.refresh_from_db()
        self.assertEqual(self.est.supervisor, self.sup_y)

    def test_supervisor_e_concedente_obrigatorios(self):
        r = self._editar(supervisor="")
        self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse("criar_estagiarios"), {
            "nomes": "Lia Souza", "turma": self.turma.pk, "local": self.local.pk, "supervisor": self.sup_y.pk,
            "data_inicio": "2026-11-16", "dias": ["0"], "horas_por_dia": "4"})
        self.assertContains(r, "não é supervisor(a) de Empresa X")
        self.assertFalse(Usuario.objects.filter(username="lia.souza").exists())

    def test_vincular_supervisor_a_outra_concedente_e_nao_desvincular_com_estagio_ativo(self):
        self.client.post(reverse("local_editar", args=[self.local.pk]),
                         {"tipo_concedente": "PJ", "nome": "Empresa X", "uf": "CE", "vincular_supervisores": [self.sup_y.pk]})
        self.assertEqual(set(self.sup_y.concedentes.all()), {self.local, self.outro_local})
        r = self.client.post(reverse("editar_usuario", args=[self.sup.pk]), {
            "nome_completo": self.sup.nome_completo, "concedentes": [self.outro_local.pk], "is_active": "on"})
        self.assertContains(r, "há estagiários ativos supervisionados")
        self.assertEqual(list(self.sup.concedentes.all()), [self.local])

    def test_importacao_vincula_supervisor_a_concedente(self):
        from .importacao import Opcoes, importar

        linhas = [(2, {"estagiario_nome": "Rui Lopes", "curso": "Informática", "data_inicio": "01/09/2026",
                       "concedente_nome": "Empresa Y", "supervisor_nome": "Sérgio Supervisor"}),
                  (3, {"estagiario_nome": "Ivo Lopes", "curso": "Informática", "data_inicio": "01/09/2026",
                       "concedente_nome": "Empresa Z"})]
        r = importar(linhas, Opcoes(orientador=self.ori, dias=[0], horas_por_dia=Decimal(4)), self.ori, confirmar=True)
        self.assertIn("supervisor_nome: obrigatório", r.erros[0][1])
        r = importar(linhas[:1], Opcoes(orientador=self.ori, dias=[0], horas_por_dia=Decimal(4)), self.ori, confirmar=True)
        self.assertTrue(r.confirmado)
        self.assertEqual([(s, l) for s, l in r.supervisores_vinculados], [(self.sup, self.outro_local)])
        self.assertEqual(set(self.sup.concedentes.all()), {self.local, self.outro_local})
        self.assertEqual(Usuario.objects.filter(nome_completo="Sérgio Supervisor").count(), 1)


class TurmasPorAnoTests(Base):
    """A turma de 2024 estagia em 2026: as listas mostram as turmas do ano de referência."""

    def setUp(self):
        super().setUp()
        self.turma_25 = Turma.objects.create(curso=self.curso, nome="3º A", ano_ingresso=2025, ano_estagio=2027)
        aluno = _ativo(criar_usuario("Davi Futuro", Usuario.Papel.ESTAGIARIO))
        self.est_27 = Estagio.objects.create(estagiario=aluno, orientador=self.ori, supervisor=self.sup, curso=self.curso,
                                             turma=self.turma_25, local=self.local, data_inicio=date(2026, 11, 2))
        self.entrar(self.ori)

    def test_lista_puxa_o_ano_de_referencia_e_troca_de_ano(self):
        Configuracao.objects.update_or_create(pk=1, defaults={"ano_referencia": 2026})
        r = self.client.get(reverse("estagios_lista"))
        self.assertContains(r, self.aluno.nome_completo)
        self.assertNotContains(r, "Davi Futuro")
        r = self.client.get(reverse("estagios_lista") + "?ano=2027")
        self.assertContains(r, "Davi Futuro")
        self.assertNotContains(r, self.aluno.nome_completo)
        # a escolha fica na sessão
        self.assertContains(self.client.get(reverse("painel")), "Davi Futuro")
        r = self.client.get(reverse("estagios_lista") + "?ano=todos")
        self.assertContains(r, "Davi Futuro")
        self.assertContains(r, self.aluno.nome_completo)

    def test_repetir_turmas_para_o_ano_seguinte_com_o_mesmo_nome(self):
        self.client.post(reverse("turmas"), {"acao": "repetir", "de": "2027"})
        nova = Turma.objects.get(ano_estagio=2028)
        self.assertEqual((nova.nome, nova.ano_ingresso, nova.curso), ("3º A", 2026, self.curso))

    def test_cadastro_em_lote_pega_o_curso_da_turma(self):
        self.client.post(reverse("criar_estagiarios"), {
            "nomes": "Ana Clara Lima", "turma": self.turma_25.pk, "local": self.local.pk, "supervisor": self.sup.pk,
            "data_inicio": "2026-11-16", "dias": ["0"], "horas_por_dia": "4"})
        e = Usuario.objects.get(username="ana.lima").estagios.get()
        self.assertEqual((e.turma, e.curso), (self.turma_25, self.curso))

    def test_importacao_cria_a_turma_do_ano(self):
        from .importacao import Opcoes, importar

        linhas = [(2, {"estagiario_nome": "Rui Lopes", "curso": "Informática", "turma": "3º B", "data_inicio": "01/09/2026",
                       "concedente_nome": "Empresa X", "supervisor_nome": "Sérgio Supervisor"})]
        r = importar(linhas, Opcoes(orientador=self.ori, dias=[0], horas_por_dia=Decimal(4)), self.ori, confirmar=True)
        self.assertTrue(r.confirmado, r.erros)
        t = Usuario.objects.get(nome_completo="Rui Lopes").estagios.get().turma
        self.assertEqual((t.nome, t.ano_ingresso, t.ano_estagio), ("3º B", 2024, 2026))


class TrocaSupervisorTests(Base):
    def setUp(self):
        super().setUp()
        self.sup2 = _ativo(criar_usuario("Sônia Substituta", Usuario.Papel.SUPERVISOR, concedente=self.local))

    def test_supervisor_nao_pode_ser_retirado_sem_outro_no_lugar(self):
        from django.core.exceptions import ValidationError
        from django.db.models import ProtectedError

        self.est.supervisor = None
        with self.assertRaises(ValidationError):
            self.est.full_clean()
        with self.assertRaises(ProtectedError):
            self.sup.delete()

    def test_orientador_troca_e_fica_no_historico(self):
        self.entrar(self.ori)
        r = self.client.post(reverse("trocar_supervisor", args=[self.est.pk]), {"novo": self.sup2.pk, "motivo": "férias"})
        self.assertEqual(r.status_code, 302)
        self.est.refresh_from_db()
        self.assertEqual(self.est.supervisor, self.sup2)
        t = TrocaSupervisor.objects.get()
        self.assertEqual((t.anterior, t.novo, t.feita_por), (self.sup, self.sup2, self.ori))
        self.assertTrue(Notificacao.objects.filter(usuario=self.sup2).exists())

    def test_supervisor_e_estagiario_nao_trocam(self):
        for u in (self.sup, self.aluno):
            self.entrar(u)
            self.assertEqual(self.client.get(reverse("trocar_supervisor", args=[self.est.pk])).status_code, 403)

    def test_desativar_supervisor_exige_substituto(self):
        self.entrar(self.ori)
        url = reverse("ativacao_usuario", args=[self.sup.pk])
        r = self.client.post(url, {})
        self.assertEqual(r.status_code, 200)
        self.sup.refresh_from_db()
        self.assertTrue(self.sup.is_active)
        self.client.post(url, {f"sub_{self.est.pk}": self.sup2.pk})
        self.sup.refresh_from_db()
        self.est.refresh_from_db()
        self.assertFalse(self.sup.is_active)
        self.assertEqual(self.est.supervisor, self.sup2)
        self.assertTrue(TrocaSupervisor.objects.filter(anterior=self.sup, novo=self.sup2).exists())


class AtivacaoTests(Base):
    def test_desativar_e_reativar_estagiario(self):
        self.entrar(self.ori)
        self.client.post(reverse("ativacao_usuario", args=[self.aluno.pk]))
        self.aluno.refresh_from_db()
        self.est.refresh_from_db()
        self.assertFalse(self.aluno.is_active)
        self.assertFalse(self.est.ativo)
        self.client.logout()
        self.assertFalse(self.client.login(username=self.aluno.username, password="senha-teste-1"))
        self.entrar(self.ori)
        self.client.post(reverse("ativacao_usuario", args=[self.aluno.pk]), {"reativar_estagio": "1"})
        self.aluno.refresh_from_db()
        self.est.refresh_from_db()
        self.assertTrue(self.aluno.is_active and self.est.ativo)

    def test_concedente_com_estagio_ativo_nao_desativa(self):
        self.entrar(self.ori)
        self.client.post(reverse("ativacao_local", args=[self.local.pk]), {"contas": "1"})
        self.local.refresh_from_db()
        self.assertTrue(self.local.ativa)
        self.est.ativo = False
        self.est.save()
        self.client.post(reverse("ativacao_local", args=[self.local.pk]), {"contas": "1"})
        self.local.refresh_from_db()
        self.sup.refresh_from_db()
        self.assertFalse(self.local.ativa)
        self.assertFalse(self.sup.is_active)  # só atuava nessa concedente
        r = self.client.get(reverse("criar_estagiarios"))
        self.assertNotContains(r, ">Empresa X<")
        self.client.post(reverse("ativacao_local", args=[self.local.pk]), {"contas": "1"})
        self.local.refresh_from_db()
        self.sup.refresh_from_db()
        self.assertTrue(self.local.ativa and self.sup.is_active)


class FolhasDoOrientadorTests(Base):
    def _pdf(self):
        return SimpleUploadedFile("frequencia novembro.pdf", b"%PDF-1.4 teste", content_type="application/pdf")

    @override_settings(MEDIA_ROOT=settings.BASE_DIR / "data" / "anexos-testes")
    def test_orientador_envia_e_estagiario_so_baixa_quando_desligado(self):
        self.entrar(self.ori)
        self.client.post(reverse("frequencias"), {"acao": "config", "estagiarios_emitem_folha": "0"})
        self.assertFalse(Configuracao.atual().estagiarios_emitem_folha)
        r = self.client.post(reverse("frequencias"), {"acao": "enviar", "mes": "2026-11", "turma": self.turma.pk,
                                                       "arquivo": self._pdf()})
        self.assertEqual(r.status_code, 302)
        folha = FolhaEnviada.objects.get()
        self.assertEqual(folha.mes, date(2026, 11, 1))

        self.entrar(self.aluno)
        r = self.client.get(reverse("folha_frequencia", args=[self.est.pk]))
        self.assertRedirects(r, reverse("minhas_folhas", args=[self.est.pk]), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("minhas_folhas", args=[self.est.pk])), "Novembro de 2026")
        r = self.client.get(reverse("baixar_folha", args=[folha.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4 teste")
        self.assertTrue(ImpressaoFrequencia.objects.filter(folha_enviada=folha, usuario=self.aluno).exists())
        # outro estagiário (outra turma) não baixa
        outro = _ativo(criar_usuario("Leo Alheio", Usuario.Papel.ESTAGIARIO))
        self.entrar(outro)
        self.assertEqual(self.client.get(reverse("baixar_folha", args=[folha.pk])).status_code, 403)
        folha.arquivo.delete(save=False)

    def test_emissao_em_lote_uma_folha_por_estagiario(self):
        aluno2 = _ativo(criar_usuario("Lia Souza", Usuario.Papel.ESTAGIARIO))
        Estagio.objects.create(estagiario=aluno2, orientador=self.ori, supervisor=self.sup, curso=self.curso,
                               turma=self.turma, local=self.local, data_inicio=date(2026, 11, 2))
        self.entrar(self.ori)
        r = self.client.get(reverse("folhas_lote") + f"?mes=2026-11&turma={self.turma.pk}")
        self.assertEqual(r.content.decode().count('class="folha"'), 2)
        self.assertEqual(ImpressaoFrequencia.objects.filter(usuario=self.ori).count(), 2)
        codigos = list(ImpressaoFrequencia.objects.values_list("codigo", flat=True))
        self.client.post(reverse("marcar_impressao"), {"codigo": codigos})
        self.assertEqual(ImpressaoFrequencia.objects.filter(impressoes=1).count(), 2)

    def test_coordenador_nao_emite_nem_envia(self):
        coord = _ativo(criar_usuario("Paula Lins", Usuario.Papel.COORDENADOR))
        self.entrar(coord)
        self.assertEqual(self.client.get(reverse("folhas_lote") + "?mes=2026-11").status_code, 403)
        self.assertNotContains(self.client.get(reverse("frequencias")), "Enviar folha para os estagiários")


class FeriadosMunicipaisTests(Base):
    """Feriado municipal vale para quem estagia em concedente daquele município; nacional vale para todos."""

    def setUp(self):
        super().setUp()
        self.local.cidade = "General Sampaio"
        self.local.save()
        self.outro_local = LocalEstagio.objects.create(nome="Empresa Y", cidade="Fortaleza")
        sup_y = _ativo(criar_usuario("Yara Supervisora", Usuario.Papel.SUPERVISOR, concedente=self.outro_local))
        aluno = _ativo(criar_usuario("Davi Capital", Usuario.Papel.ESTAGIARIO))
        self.est_fortaleza = Estagio.objects.create(estagiario=aluno, orientador=self.ori, supervisor=sup_y, curso=self.curso,
                                                    turma=self.turma, local=self.outro_local, data_inicio=date(2026, 11, 2))
        self.entrar(self.ori)

    def test_feriado_municipal_so_no_municipio_da_concedente_e_repete_todo_ano(self):
        r = self.client.post(reverse("dias_sem_estagio"), {
            "acao": "adicionar", "abrangencia": "MUNICIPIO", "municipio": "GENERAL SAMPAIO - CE", "data": "2025-11-23",
            "descricao": "Aniversário da cidade", "anual": "on"})
        self.assertEqual(r.status_code, 302)
        from .services import dias_sem_estagio

        self.assertEqual(dias_sem_estagio(self.est, date(2026, 11, 1), date(2026, 11, 30)),
                         {date(2026, 11, 23): "Aniversário da cidade"})
        self.assertEqual(dias_sem_estagio(self.est_fortaleza, date(2026, 11, 1), date(2026, 11, 30)), {})
        linha = linhas_folha(self.est, 2026, 11)[22]
        self.assertEqual((linha["feriado"], linha["cinza"]), ("Aniversário da cidade", True))
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto__contains="General Sampaio").exists())
        self.assertFalse(Notificacao.objects.filter(usuario=self.est_fortaleza.estagiario).exists())

    def test_municipio_obrigatorio_e_aviso_de_municipio_sem_feriado(self):
        r = self.client.post(reverse("dias_sem_estagio"), {"acao": "adicionar", "abrangencia": "MUNICIPIO",
                                                            "data": "2026-11-23", "descricao": "X"})
        self.assertContains(r, "Informe o município do feriado.")
        r = self.client.get(reverse("dias_sem_estagio"))
        self.assertContains(r, "ainda sem feriado municipal")
        self.assertContains(r, "Fortaleza")

    def test_feriados_nacionais_do_ano_valem_para_todos(self):
        r = self.client.get(reverse("dias_sem_estagio") + "?aba=nacionais&ano=2026")
        self.assertContains(r, "Paixão de Cristo")
        self.client.post(reverse("dias_sem_estagio") + "?aba=nacionais", {
            "acao": "nacionais", "ano": "2026", "f": ["2026-11-20", "2026-04-03"]})
        self.assertEqual(DiaSemEstagio.objects.filter(abrangencia="TODOS").count(), 2)
        from .services import dias_sem_estagio

        for e in (self.est, self.est_fortaleza):
            self.assertEqual(dias_sem_estagio(e, date(2026, 11, 1), date(2026, 11, 30)),
                             {date(2026, 11, 20): "Consciência Negra"})

    def test_evento_da_escola_continua_so_do_orientador(self):
        outro_ori = _ativo(criar_usuario("Otto Orientador", Usuario.Papel.ORIENTADOR))
        DiaSemEstagio.objects.create(data=date(2026, 11, 27), descricao="Feira de ciências", orientador=outro_ori)
        from .services import dias_sem_estagio

        self.assertEqual(dias_sem_estagio(self.est, date(2026, 11, 1), date(2026, 11, 30)), {})


ICS_EXEMPLO = """BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
DTSTART;VALUE=DATE:20261123\r
DTEND;VALUE=DATE:20261124\r
SUMMARY:Anivers\u00e1rio da\r
  cidade\r
RRULE:FREQ=YEARLY\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART;VALUE=DATE:20261228\r
DTEND;VALUE=DATE:20270101\r
SUMMARY:Recesso de fim de ano\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART;VALUE=DATE:20260510\r
SUMMARY:Dia das M\u00e3es\r
DESCRIPTION:Observ\u00e2ncia\r
END:VEVENT\r
END:VCALENDAR\r
"""


class ImportarCalendarioTests(Base):
    def setUp(self):
        super().setUp()
        self.local.cidade = "General Sampaio"
        self.local.save()
        self.entrar(self.ori)

    def _enviar(self, conteudo, nome, **campos):
        dados = {"etapa": "previa", "abrangencia": "MUNICIPIO", "municipio": "General Sampaio", "ano": "2026",
                 "arquivo": SimpleUploadedFile(nome, conteudo.encode("utf-8"))}
        dados.update(campos)
        return self.client.post(reverse("importar_feriados"), dados)

    def test_ics_com_previa_e_importacao(self):
        r = self._enviar(ICS_EXEMPLO, "cidade.ics")
        self.assertContains(r, "Aniversário da cidade")
        self.assertContains(r, "data comemorativa, não é feriado")
        self.assertEqual(DiaSemEstagio.objects.count(), 0)  # prévia não grava
        itens = r.context["itens"]
        self.assertEqual([(i.anual, i.dias, i.marcado) for i in itens], [(True, 1, True), (False, 4, True), (False, 1, False)])
        self.client.post(reverse("importar_feriados"), {"etapa": "confirmar", "i": ["0", "1"]})
        self.assertEqual(DiaSemEstagio.objects.filter(origem="importado").count(), 5)
        from .services import dias_sem_estagio

        dias = dias_sem_estagio(self.est, date(2027, 11, 1), date(2027, 11, 30))
        self.assertEqual(dias, {date(2027, 11, 23): "Aniversário da cidade"})
        self.assertIn(date(2026, 12, 30), dias_sem_estagio(self.est, date(2026, 12, 1), date(2026, 12, 31)))

    def test_csv_com_tipos_dd_mm_e_erros(self):
        csv_txt = ("data;descricao;ate;tipo;municipio;anual\n"
                   "23/11;Aniversário;;municipal;GENERAL SAMPAIO - CE;\n"
                   "02/02/2027;Recesso;06/02/2027;escola;;\n"
                   "31/02/2027;Data errada;;nacional;;\n"
                   "10/10/2026;Sem cidade;;municipal;;\n")
        r = self._enviar(csv_txt, "cal.csv", municipio="")
        self.assertEqual(len(r.context["itens"]), 2)
        self.assertEqual(len(r.context["erros"]), 2)
        self.client.post(reverse("importar_feriados"), {"etapa": "confirmar", "i": ["0", "1"]})
        aniv = DiaSemEstagio.objects.get(descricao="Aniversário")
        self.assertTrue(aniv.anual)
        self.assertEqual(aniv.municipio_chave, "general sampaio")
        self.assertEqual(DiaSemEstagio.objects.filter(descricao="Recesso", abrangencia="ESCOLA").count(), 5)

    def test_substituir_importacao_anterior_sem_apagar_manual(self):
        DiaSemEstagio.objects.create(data=date(2026, 9, 1), descricao="Manual", abrangencia="MUNICIPIO",
                                     municipio="General Sampaio", orientador=self.ori)
        self._enviar("data;descricao\n15/08/2026;Padroeira\n", "a.csv")
        self.client.post(reverse("importar_feriados"), {"etapa": "confirmar", "i": ["0"]})
        self._enviar("data;descricao\n16/08/2026;Padroeira (corrigido)\n", "b.csv", substituir="on")
        self.client.post(reverse("importar_feriados"), {"etapa": "confirmar", "i": ["0"]})
        self.assertEqual(sorted(DiaSemEstagio.objects.values_list("descricao", flat=True)),
                         ["Manual", "Padroeira (corrigido)"])


class HistoricoRegistroTests(Base):
    def test_guarda_quando_marcou_e_para_qual_horario_mudou(self):
        self.entrar(self.aluno)
        with mock.patch("django.utils.timezone.localtime") as agora:
            from datetime import datetime as dt

            agora.return_value = timezone.make_aware(dt(2026, 11, 11, 7, 58))
            self.client.post(reverse("marcar_presenca", args=[self.est.pk]))
        h = HistoricoRegistro.objects.get()
        self.assertEqual((h.usuario, h.acao), (self.aluno, "ENTRADA"))
        self.assertIn(["Entrada", "—", "07:58"], h.mudancas)
        # depois digita outros horários
        self.client.post(reverse("estagio_dia", args=[self.est.pk, "2026-11-11"]), {
            "h-hora_chegada": "07:30", "h-hora_saida": "11:30"})
        ultimo = HistoricoRegistro.objects.first()
        self.assertEqual(ultimo.acao, "DIGITOU")
        self.assertIn(["Entrada", "07:58", "07:30"], ultimo.mudancas)
        self.assertIn(["Saída", "—", "11:30"], ultimo.mudancas)
        # o supervisor confirma e vê o histórico do dia
        self.entrar(self.sup)
        reg = Registro.objects.get()
        self.client.post(reverse("validar_registro", args=[reg.pk]), {"acao": "confirmar"})
        self.assertEqual(HistoricoRegistro.objects.first().acao, "VALIDACAO")
        r = self.client.get(reverse("estagio_dia", args=[self.est.pk, "2026-11-11"]))
        self.assertContains(r, "digitou os horários")
        self.assertContains(r, "07:58 → <strong>07:30</strong>")

    def test_ausencia_cancelada_fica_no_historico(self):
        self.entrar(self.aluno)
        self.client.post(reverse("informar_ausencia", args=[self.est.pk]), {"data": "2026-11-16", "motivo": "Consulta"})
        self.client.post(reverse("estagio_dia", args=[self.est.pk, "2026-11-16"]), {"planejar": "cancelar_ausencia"})
        self.assertFalse(Registro.objects.exists())
        self.assertEqual(list(HistoricoRegistro.objects.values_list("acao", flat=True)), ["CANCELOU", "AUSENCIA"])


class RecessoConcedenteTests(Base):
    def setUp(self):
        super().setUp()
        self.outro_local = LocalEstagio.objects.create(nome="Empresa Y")
        sup_y = _ativo(criar_usuario("Yara Supervisora", Usuario.Papel.SUPERVISOR, concedente=self.outro_local))
        aluno = _ativo(criar_usuario("Davi Outro", Usuario.Papel.ESTAGIARIO))
        self.est_y = Estagio.objects.create(estagiario=aluno, orientador=self.ori, supervisor=sup_y, curso=self.curso,
                                            turma=self.turma, local=self.outro_local, data_inicio=date(2026, 11, 2))

    def test_orientador_cadastra_periodo_que_vale_so_para_a_concedente(self):
        self.entrar(self.ori)
        r = self.client.post(reverse("recessos"), {"acao": "adicionar", "concedente": self.local.pk,
                                                   "data": "2026-12-21", "ate": "2026-12-31", "descricao": "Férias coletivas"})
        self.assertEqual(r.status_code, 302)
        from .services import dias_sem_estagio

        dias = dias_sem_estagio(self.est, date(2026, 12, 1), date(2026, 12, 31))
        self.assertEqual(len(dias), 11)
        self.assertEqual(dias_sem_estagio(self.est_y, date(2026, 12, 1), date(2026, 12, 31)), {})
        self.assertEqual(linhas_folha(self.est, 2026, 12)[21]["feriado"], "Férias coletivas")
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto__contains="recesso").exists())
        self.assertFalse(Notificacao.objects.filter(usuario=self.est_y.estagiario).exists())
        # a lista mostra um período só, e remover apaga o período inteiro
        r = self.client.get(reverse("recessos"))
        self.assertContains(r, "21/12/2026 a 31/12/2026")
        ids = ",".join(str(i) for i in DiaSemEstagio.objects.values_list("pk", flat=True))
        self.client.post(reverse("recessos"), {"excluir": ids})
        self.assertFalse(DiaSemEstagio.objects.exists())

    def test_supervisor_so_cadastra_na_propria_concedente(self):
        self.entrar(self.sup)
        r = self.client.post(reverse("recessos"), {"acao": "adicionar", "concedente": self.outro_local.pk,
                                                   "data": "2026-12-21", "descricao": "Recesso"})
        self.assertEqual(r.status_code, 200)  # Empresa Y não está entre as opções dele
        self.assertFalse(DiaSemEstagio.objects.exists())
        self.client.post(reverse("recessos"), {"acao": "adicionar", "concedente": self.local.pk,
                                               "data": "2026-12-21", "descricao": "Recesso"})
        self.assertEqual(DiaSemEstagio.objects.get().concedente, self.local)
        outro = DiaSemEstagio.objects.create(data=date(2026, 12, 22), descricao="X", abrangencia="CONCEDENTE",
                                             concedente=self.outro_local, orientador=self.ori)
        self.client.post(reverse("recessos"), {"excluir": str(outro.pk)})
        self.assertTrue(DiaSemEstagio.objects.filter(pk=outro.pk).exists())
        self.entrar(self.aluno)
        self.assertEqual(self.client.get(reverse("recessos")).status_code, 403)

    def test_importa_recesso_por_nome_da_concedente(self):
        self.entrar(self.ori)
        csv_txt = ("data;descricao;ate;tipo;concedente\n"
                   "21/12/2026;Férias coletivas;23/12/2026;concedente;empresa x\n"
                   "21/12/2026;Recesso;;concedente;Empresa Inexistente\n")
        r = self.client.post(reverse("importar_feriados"), {
            "etapa": "previa", "abrangencia": "MUNICIPIO", "ano": "2026",
            "arquivo": SimpleUploadedFile("r.csv", csv_txt.encode())})
        self.assertEqual(len(r.context["itens"]), 1)
        self.assertIn("não encontrada", r.context["erros"][0][1])
        self.client.post(reverse("importar_feriados"), {"etapa": "confirmar", "i": ["0"]})
        self.assertEqual(DiaSemEstagio.objects.filter(abrangencia="CONCEDENTE", concedente=self.local).count(), 3)


class PWATests(Base):
    def test_manifesto_e_service_worker(self):
        r = self.client.get("/manifest.webmanifest")
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/manifest+json", r["Content-Type"])
        dados = r.json()
        self.assertEqual(dados["display"], "standalone")
        self.assertTrue(any(i["purpose"] == "maskable" for i in dados["icons"]))
        sw = self.client.get("/sw.js")
        self.assertEqual(sw["Service-Worker-Allowed"], "/")
        self.assertIn("/offline/", sw.content.decode())
        self.assertEqual(self.client.get("/offline/").status_code, 200)

    def test_livre_mesmo_com_troca_de_senha_pendente(self):
        self.aluno.deve_trocar_senha = True
        self.aluno.save()
        self.client.force_login(self.aluno)
        self.assertEqual(self.client.get("/sw.js").status_code, 200)
        self.assertEqual(self.client.get("/manifest.webmanifest").status_code, 200)
        self.assertContains(self.client.get(reverse("trocar_senha")), 'rel="manifest"')


class PlanilhaModeloTests(Base):
    def setUp(self):
        super().setUp()
        self.ori.is_superuser = True
        self.ori.save()
        self.entrar(self.ori)

    def _preencher(self, concedentes=(), supervisores=(), estagiarios=()):
        from openpyxl import load_workbook

        r = self.client.get(reverse("importar_csv") + "?modelo=xlsx")
        self.assertEqual(r.status_code, 200)
        wb = load_workbook(io.BytesIO(r.content))
        self.assertEqual(wb.sheetnames[:4], ["Leia-me", "Estagiários", "Concedentes", "Supervisores"])
        self.assertIn("Informática", [c.value for c in wb["Listas"]["A"]])  # cursos do sistema na lista
        for aba, linhas in (("Concedentes", concedentes), ("Supervisores", supervisores), ("Estagiários", estagiarios)):
            for i, valores in enumerate(linhas, start=2):
                for j, v in enumerate(valores, start=1):
                    wb[aba].cell(row=i, column=j, value=v)
        saida = io.BytesIO()
        wb.save(saida)
        return SimpleUploadedFile("cadastro.xlsx", saida.getvalue())

    def _enviar(self, arquivo):
        return self.client.post(reverse("importar_csv"), {
            "etapa": "previa", "arquivo": arquivo, "orientador": self.ori.pk, "dias": ["0", "1"], "horas_por_dia": "4",
            "carga_cursos_novos": "300", "completar_concedentes": "on"})

    def test_planilha_com_tres_abas(self):
        arquivo = self._preencher(
            concedentes=[["Escola Nova Esperança", "Secretaria da Educação", 7954480000179, "Pública", "Rua A", "10", "Centro",
                          "", "Itapipoca", "CE", 62500000],
                         ["Clínica Sem Estagiário", "", "", "Privada"]],
            supervisores=[["Rita de Cássia Lima", "Escola Nova Esperança", "(88) 99999-1111", "", "Coordenadora"],
                          ["Pedro Alves Sozinho", "Clínica Sem Estagiário"]],
            estagiarios=[["João Pedro Matos", 100000037, "", "", "", "Informática", "3º A", 2024, date(2026, 8, 24), None, 40,
                          "seg-qua", 4, None, None, None, None, "Escola Nova Esperança", None],
                         ["Lia Gomes Torres", "", "", "", "", "Informática", "3º A", 2024, date(2026, 8, 24), None, None,
                          "", "", None, None, None, None, "Escola Nova Esperança", "Rita de Cássia Lima"]],
        )
        r = self._enviar(arquivo)
        self.assertEqual(r.status_code, 200)
        res = r.context["resultado"]
        self.assertEqual(res.erros, [])
        self.assertEqual(len(res.linhas_ok), 2)
        self.assertEqual(len(res.concedentes_novas), 2)
        self.assertEqual(len(res.supervisores_novos), 2)
        self.assertFalse(Usuario.objects.filter(nome_completo="João Pedro Matos").exists())  # prévia não grava
        r = self.client.post(reverse("importar_csv"), {"etapa": "confirmar"})
        self.assertEqual(r.status_code, 200)
        joao = Usuario.objects.get(nome_completo="João Pedro Matos")
        self.assertEqual(joao.cpf, "001.000.000-37")  # zero à esquerda recuperado
        est = joao.estagios.get()
        self.assertEqual(est.supervisor.nome_completo, "Rita de Cássia Lima")  # único supervisor da concedente
        self.assertEqual(est.horas_anteriores, 40)
        self.assertEqual(est.escalas.get().dias, "0,1,2")
        escola = LocalEstagio.objects.get(nome="Escola Nova Esperança")
        self.assertEqual((escola.cnpj, escola.tipo_instituicao, escola.cep), ("07.954.480/0001-79", "PUBLICA", "62500-000"))
        pedro = Usuario.objects.get(nome_completo="Pedro Alves Sozinho")
        self.assertEqual(list(pedro.concedentes.values_list("nome", flat=True)), ["Clínica Sem Estagiário"])
        self.assertEqual(Usuario.objects.get(nome_completo="Rita de Cássia Lima").cargo, "Coordenadora")

    def test_erros_apontam_aba_e_linha(self):
        arquivo = self._preencher(
            supervisores=[["Rita de Cássia Lima", ""]],
            estagiarios=[["João Pedro Matos", "", "", "", "", "Informática", "", "", date(2026, 8, 24)]])
        r = self._enviar(arquivo)
        self.assertContains(r, "Supervisores, linha 2: escolha a concedente")
        arquivo = self._preencher(estagiarios=[["João", "", "", "", "", "Informática", "", "", "32/13/2026", None, None,
                                                "", "", None, None, None, None, "Empresa X", ""]])
        r = self._enviar(arquivo)
        msgs = dict(r.context["resultado"].erros)
        self.assertIn("Estagiários, linha 2", msgs)
        self.assertContains(r, "Estagiários, linha 2")


class RelatorioTurmaTests(Base):
    def test_relatorio_mostra_estagiarios_e_pontos_de_atencao(self):
        Registro.objects.create(estagio=self.est, data=date(2026, 11, 2), situacao=Registro.Situacao.FALTA)
        Registro.objects.create(estagio=self.est, data=date(2026, 11, 3), situacao=Registro.Situacao.FALTA)
        Registro.objects.create(estagio=self.est, data=date(2026, 11, 9), situacao=Registro.Situacao.FALTA)
        self.entrar(self.ori)
        r = self.client.get(reverse("relatorio_turma", args=[self.turma.pk]))
        self.assertContains(r, "Maria da Silva Souza")
        self.assertContains(r, "RELATÓRIO GERAL DE ESTÁGIO")
        self.assertEqual(r.context["tot"]["faltas"], 3)
        self.assertEqual(r.context["tot"]["sem_registro"], 1)  # terça 10/11 sem registro
        motivos = dict(r.context["atencao"])[self.est]
        self.assertIn("3 faltas", motivos)

    def test_so_gestor_ve(self):
        self.entrar(self.aluno)
        self.assertEqual(self.client.get(reverse("relatorio_turma", args=[self.turma.pk])).status_code, 403)
        self.entrar(self.sup)
        self.assertEqual(self.client.get(reverse("relatorio_turma", args=[self.turma.pk])).status_code, 403)


class CheckinLocalizacaoTests(Base):
    PERTO = {"geo_lat": "-3.731950", "geo_lng": "-38.526700", "geo_precisao": "20"}
    LONGE = {"geo_lat": "-3.760000", "geo_lng": "-38.526700", "geo_precisao": "20"}

    def setUp(self):
        super().setUp()
        self.local.latitude, self.local.longitude = Decimal("-3.731900"), Decimal("-38.526700")
        self.local.save()
        self.est.escalas.update(dias="0,1,2,3,4")
        self.entrar(self.aluno)

    def _modo(self, modo):
        c = Configuracao.atual()
        c.checkin_localizacao = modo
        c.save()

    def test_desligado_nao_guarda_localizacao(self):
        self.client.post(reverse("marcar_presenca", args=[self.est.pk]), self.LONGE)
        self.assertIsNone(Registro.objects.get(estagio=self.est).geo_entrada)

    def test_registrar_guarda_distancia_e_avisa_supervisor(self):
        self._modo("REGISTRAR")
        self.client.post(reverse("marcar_presenca", args=[self.est.pk]), self.LONGE)
        reg = Registro.objects.get(estagio=self.est)
        self.assertGreater(reg.geo_entrada["distancia"], 3000)
        self.assertTrue(reg.local_entrada["longe"])
        self.assertIn("longe", reg.local_entrada["texto"] + " longe")
        self.assertTrue(Notificacao.objects.filter(usuario=self.sup, texto__contains="km da concedente").exists())
        self.entrar(self.sup)
        self.assertContains(self.client.get(reverse("painel_supervisor")), "geo longe")

    def test_exigir_bloqueia_longe_e_sem_permissao(self):
        self._modo("EXIGIR")
        r = self.client.post(reverse("marcar_presenca", args=[self.est.pk]), self.LONGE, follow=True)
        self.assertContains(r, "Só é possível marcar presença no local")
        r = self.client.post(reverse("marcar_presenca", args=[self.est.pk]), {"geo_erro": "negada"}, follow=True)
        self.assertContains(r, "permita o acesso à localização")
        self.assertFalse(Registro.objects.filter(estagio=self.est).exists())
        self.client.post(reverse("marcar_presenca", args=[self.est.pk]), self.PERTO)
        reg = Registro.objects.get(estagio=self.est)
        self.assertLess(reg.geo_entrada["distancia"], 50)
        self.assertFalse(reg.local_entrada["longe"])
        # saída longe também é bloqueada
        r = self.client.post(reverse("registrar_saida", args=[self.est.pk]), {"ponto": "hora_saida", **self.LONGE}, follow=True)
        self.assertContains(r, "registrar a saída")
        reg.refresh_from_db()
        self.assertIsNone(reg.hora_saida)

    def test_exigir_sem_ponto_da_concedente_so_registra(self):
        self._modo("EXIGIR")
        self.local.latitude = self.local.longitude = None
        self.local.save()
        self.client.post(reverse("marcar_presenca", args=[self.est.pk]), self.LONGE)
        reg = Registro.objects.get(estagio=self.est)
        self.assertIsNone(reg.geo_entrada["distancia"])

    def test_coordenadas_do_link_do_mapa(self):
        from .services import coordenadas_do_link

        self.assertEqual(coordenadas_do_link("https://www.google.com/maps/place/X/@-3.1,-38.2,17z/data=!3d-3.7319!4d-38.5267"),
                         (Decimal("-3.731900"), Decimal("-38.526700")))
        self.assertIsNone(coordenadas_do_link("https://maps.app.goo.gl/abc"))


@override_settings(EMAIL_ATIVO=True, SITE_URL="https://estagio.exemplo.br")
class AvisosEmailTests(Base):
    def test_aviso_vai_por_email_para_quem_tem_email(self):
        from django.core import mail

        from .services import notificar

        self.sup.email = "sup@exemplo.br"
        self.sup.save()
        self.ori.email = "ori@exemplo.br"
        self.ori.avisos_email = False
        self.ori.save()
        with self.captureOnCommitCallbacks(execute=True):
            notificar([self.sup, self.ori, self.aluno], "Maria marcou presença hoje às 07:58.", "/supervisor/")
        self.assertEqual(Notificacao.objects.count(), 3)  # o sino recebe todos
        self.assertEqual(len(mail.outbox), 1)  # e-mail só para quem tem e não desligou
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["sup@exemplo.br"])
        self.assertIn("Maria marcou presença", msg.subject)
        self.assertIn("https://estagio.exemplo.br/supervisor/", msg.body)

    def test_desligado_na_configuracao(self):
        from django.core import mail

        from .services import notificar

        c = Configuracao.atual()
        c.avisos_email = False
        c.save()
        self.sup.email = "sup@exemplo.br"
        self.sup.save()
        with self.captureOnCommitCallbacks(execute=True):
            notificar([self.sup], "Teste")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_ATIVO=False)
    def test_sem_servidor_nao_envia(self):
        from django.core import mail

        from .services import notificar

        self.sup.email = "sup@exemplo.br"
        self.sup.save()
        with self.captureOnCommitCallbacks(execute=True):
            notificar([self.sup], "Teste")
        self.assertEqual(len(mail.outbox), 0)

    def test_email_de_teste_nas_configuracoes(self):
        from django.core import mail

        self.ori.is_superuser = True
        self.ori.email = "ori@exemplo.br"
        self.ori.save()
        self.entrar(self.ori)
        self.assertContains(self.client.get(reverse("configuracoes")), "Enviar e-mail de teste")
        r = self.client.post(reverse("configuracoes"), {"acao": "teste_email"}, follow=True)
        self.assertContains(r, "E-mail de teste enviado")
        self.assertEqual(mail.outbox[0].to, ["ori@exemplo.br"])


@override_settings(EMAIL_ATIVO=True, SITE_URL="https://estagio.exemplo.br")
class ResumoSemanalTests(Base):
    def setUp(self):
        super().setUp()
        self.ori.email = "ori@exemplo.br"
        self.ori.save()

    def test_resumo_lista_dias_sem_registro_e_faltas(self):
        from .acompanhamento import resumo_semanal

        Registro.objects.create(estagio=self.est, data=date(2026, 11, 9), situacao=Registro.Situacao.FALTA)
        d = resumo_semanal(self.ori)
        self.assertTrue(d["tem_algo"])
        self.assertEqual(d["secoes"]["sem_registro"], [(self.est, [date(2026, 11, 10)])])
        self.assertEqual(d["secoes"]["faltas"], [(self.est, [date(2026, 11, 9)])])

    def test_envia_so_para_gestores_com_algo_a_relatar(self):
        from django.core import mail

        from .acompanhamento import enviar_resumos

        outro = _ativo(criar_usuario("Otávio Sem Turma", Usuario.Papel.ORIENTADOR, email="otavio@exemplo.br"))
        desligou = _ativo(criar_usuario("Dora Desligada", Usuario.Papel.ORIENTADOR, email="dora@exemplo.br"))
        desligou.resumo_semanal = False
        desligou.save()
        self.aluno.email = "maria@exemplo.br"
        self.aluno.save()
        self.assertEqual(enviar_resumos(), 1)
        self.assertEqual(mail.outbox[0].to, ["ori@exemplo.br"])
        self.assertIn("SEM REGISTRO DE PRESENÇA", mail.outbox[0].body)
        self.assertIn("Maria da Silva Souza", mail.outbox[0].body)
        self.assertIn("https://estagio.exemplo.br/resumo/", mail.outbox[0].body)
        self.assertNotIn(outro.email, [m.to[0] for m in mail.outbox])

    def test_disparo_automatico_uma_vez_por_semana(self):
        from datetime import datetime

        from django.core import mail

        from .acompanhamento import disparar_resumo_se_preciso

        tz = timezone.get_current_timezone()
        segunda_cedo = datetime(2026, 11, 9, 5, 0, tzinfo=tz)
        segunda = datetime(2026, 11, 9, 8, 0, tzinfo=tz)
        Configuracao.atual()
        Configuracao.objects.filter(pk=1).update(resumo_enviado_em=datetime(2026, 11, 3, 9, 0, tzinfo=tz))
        self.assertFalse(disparar_resumo_se_preciso(segunda_cedo))  # antes das 6h vale a semana anterior
        self.assertTrue(disparar_resumo_se_preciso(segunda))
        self.assertEqual(len(mail.outbox), 1)
        self.assertFalse(disparar_resumo_se_preciso(segunda + timedelta(hours=3)))
        self.assertEqual(len(mail.outbox), 1)

    def test_desligado_nas_configuracoes(self):
        from .acompanhamento import disparar_resumo_se_preciso

        c = Configuracao.atual()
        c.resumo_semanal = False
        c.save()
        self.assertFalse(disparar_resumo_se_preciso())

    def test_pagina_do_resumo(self):
        from django.core import mail

        self.entrar(self.ori)
        r = self.client.get(reverse("resumo_semanal"))
        self.assertContains(r, "Sem registro de presença")
        self.assertContains(r, "Enviar para meu e-mail")
        self.client.post(reverse("resumo_semanal"), {"acao": "enviar"})
        self.assertEqual(mail.outbox[0].to, ["ori@exemplo.br"])
        self.entrar(self.aluno)
        self.assertEqual(self.client.get(reverse("resumo_semanal")).status_code, 403)

    def test_comando_mostrar(self):
        from io import StringIO

        from django.core.management import call_command

        saida = StringIO()
        call_command("enviar_resumo_semanal", "--mostrar", stdout=saida)
        self.assertIn("Resumo da semana", saida.getvalue())
        self.assertIn("Maria da Silva Souza", saida.getvalue())


class ExportacaoTests(Base):
    def test_planilha_com_os_estagiarios_filtrados(self):
        from openpyxl import load_workbook

        outro = _ativo(criar_usuario("Encerrado da Silva", Usuario.Papel.ESTAGIARIO))
        Estagio.objects.create(estagiario=outro, orientador=self.ori, curso=self.curso, turma=self.turma,
                               data_inicio=date(2026, 3, 2), ativo=False)
        Registro.objects.create(estagio=self.est, data=date(2026, 11, 2), situacao=Registro.Situacao.PRESENTE,
                                horas=4, confirmacao=Registro.Confirmacao.CONFIRMADA)
        self.entrar(self.ori)
        r = self.client.get(reverse("exportar_estagios"), {"turma": self.turma.pk, "formato": "xlsx"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])
        self.assertIn(".xlsx", r["Content-Disposition"])
        wb = load_workbook(io.BytesIO(r.content))
        self.assertEqual(wb.sheetnames, ["Resumo", "Estagiários", "Horas por mês", "Visitas e conversas"])
        nomes = [c.value for c in wb["Estagiários"]["A"][1:]]
        self.assertEqual(nomes, ["Maria da Silva Souza"])  # só os ativos, como na lista
        horas = wb["Horas por mês"]
        self.assertEqual(horas["C1"].value, "nov/2026")
        self.assertEqual(horas["C2"].value, 4.0)
        r = self.client.get(reverse("exportar_estagios"), {"situacao": "todos", "formato": "xlsx"})
        self.assertEqual(load_workbook(io.BytesIO(r.content))["Estagiários"].max_row, 3)

    def test_pdf_usa_o_mesmo_relatorio(self):
        self.entrar(self.ori)
        r = self.client.get(reverse("exportar_estagios"), {"curso": self.curso.pk, "formato": "pdf"})
        self.assertContains(r, "RELATÓRIO GERAL DE ESTÁGIO — INFORMÁTICA")
        self.assertContains(r, "Maria da Silva Souza")
        self.assertContains(r, "formato=xlsx")
        self.assertContains(self.client.get(reverse("estagios_lista")), "Planilha (.xlsx)")

    def test_so_gestor_exporta(self):
        self.entrar(self.aluno)
        self.assertEqual(self.client.get(reverse("exportar_estagios"), {"formato": "xlsx"}).status_code, 403)


class AgendaCalendarioTests(Base):
    def _agendar(self, status=Agendamento.Status.AGENDADO, assunto="Visita de acompanhamento"):
        a = Agendamento.objects.create(orientador=self.ori, solicitante=self.ori, local=self.local, status=status,
                                       data_hora=timezone.now() + timedelta(days=2), assunto=assunto)
        a.estagios.add(self.est)
        return a

    def test_link_secreto_traz_as_visitas(self):
        self._agendar()
        self._agendar(Agendamento.Status.SOLICITADO, "Pedido ainda sem data")
        self.entrar(self.ori)
        self.client.post(reverse("assinar_agenda"))
        self.ori.refresh_from_db()
        self.assertEqual(len(self.ori.token_agenda), 32)
        self.assertContains(self.client.get(reverse("assinar_agenda")), "Abrir no Google Agenda")
        self.client.logout()
        r = self.client.get(reverse("agenda_ics", args=[self.ori.token_agenda]))
        self.assertEqual(r["Content-Type"], "text/calendar; charset=utf-8")
        corpo = r.content.decode().replace("\r\n ", "")
        self.assertIn("SUMMARY:Visita de acompanhamento", corpo)
        self.assertIn("Maria da Silva Souza", corpo)
        self.assertIn("LOCATION:Empresa X", corpo)
        self.assertNotIn("Pedido ainda sem data", corpo)

    def test_supervisor_ve_as_visitas_dele(self):
        self._agendar()
        self.sup.token_agenda = "s" * 32
        self.sup.save()
        self.assertIn("Visita de acompanhamento", self.client.get(reverse("agenda_ics", args=["s" * 32])).content.decode())

    def test_novo_link_invalida_o_antigo(self):
        self.entrar(self.ori)
        self.client.post(reverse("assinar_agenda"))
        self.ori.refresh_from_db()
        antigo = self.ori.token_agenda
        self.client.post(reverse("assinar_agenda"), {"acao": "novo"})
        self.ori.refresh_from_db()
        self.assertNotEqual(antigo, self.ori.token_agenda)
        self.assertEqual(self.client.get(reverse("agenda_ics", args=[antigo])).status_code, 404)
        self.assertEqual(self.client.get(reverse("agenda_ics", args=["curto"])).status_code, 404)


class DeclaracaoTests(Base):
    def test_sem_horas_nao_emite(self):
        self.entrar(self.ori)
        r = self.client.get(reverse("declaracao_estagio", args=[self.est.pk]), follow=True)
        self.assertContains(r, "Ainda não há horas validadas")

    def test_declaracao_de_conclusao(self):
        self.est.horas_anteriores = 96
        self.est.save()
        Registro.objects.create(estagio=self.est, data=date(2026, 11, 3), situacao=Registro.Situacao.PRESENTE,
                                horas=4, confirmacao=Registro.Confirmacao.CONFIRMADA)
        self.aluno.cpf = "001.000.000-37"
        self.aluno.save()
        self.entrar(self.ori)
        r = self.client.get(reverse("declaracao_estagio", args=[self.est.pk]))
        self.assertContains(r, "DECLARAÇÃO DE CONCLUSÃO DE ESTÁGIO")
        self.assertContains(r, "MARIA DA SILVA SOUZA")
        self.assertContains(r, "001.000.000-37")
        self.assertContains(r, "no período de 02/11/2026 a 03/11/2026")
        self.assertContains(r, "carga horária total de <strong>100 horas</strong>", html=False)

    def test_declaracao_em_andamento(self):
        Registro.objects.create(estagio=self.est, data=date(2026, 11, 3), situacao=Registro.Situacao.PRESENTE,
                                horas=4, confirmacao=Registro.Confirmacao.CONFIRMADA)
        self.entrar(self.ori)
        r = self.client.get(reverse("declaracao_estagio", args=[self.est.pk]))
        self.assertContains(r, "realiza estágio curricular supervisionado")
        self.assertContains(r, "tendo cumprido até esta data <strong>4 horas</strong>", html=False)
        self.assertContains(self.client.get(reverse("estagio_detalhe", args=[self.est.pk])), "Declaração")

    def test_so_gestor_emite(self):
        Registro.objects.create(estagio=self.est, data=date(2026, 11, 3), situacao=Registro.Situacao.PRESENTE,
                                horas=4, confirmacao=Registro.Confirmacao.CONFIRMADA)
        for u in (self.aluno, self.sup):
            self.entrar(u)
            self.assertEqual(self.client.get(reverse("declaracao_estagio", args=[self.est.pk])).status_code, 403)
