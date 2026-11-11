from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Agendamento, Curso, Documento, Escala, Estagio, LocalEstagio, Notificacao, Registro, Usuario
from .services import criar_usuario, gerar_username, resumo_horas, status_periodo

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
        self.sup = _ativo(criar_usuario("Sérgio Supervisor", Usuario.Papel.SUPERVISOR, local=self.local))
        self.curso = Curso.objects.create(nome="Informática", carga_horaria=100, horas_por_dia_padrao=4)
        self.aluno = _ativo(criar_usuario("Maria da Silva Souza", Usuario.Papel.ESTAGIARIO))
        self.est = Estagio.objects.create(estagiario=self.aluno, orientador=self.ori, supervisor=self.sup,
                                          curso=self.curso, local=self.local, data_inicio=date(2026, 11, 2))
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
            "nomes": "Ana Clara Lima\nBruno Dias; 2024999", "curso": self.curso.pk, "local": self.local.pk,
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
