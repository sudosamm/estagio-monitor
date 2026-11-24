from datetime import date, datetime, timedelta
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
        """Conta antiga, criada quando todas recebiam a senha padrão: só entra com ACEITAR_SENHA_PADRAO (emergência)."""
        novo = criar_usuario("Novo Aluno", Usuario.Papel.ESTAGIARIO)
        novo.set_password("senha-teste-1")
        novo.save()
        self.assertFalse(self.client.login(username="novo.aluno", password="senha-teste-1"))
        with self.settings(ACEITAR_SENHA_PADRAO=True):
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

    def test_qualquer_carga_diaria(self):
        for horas, saida, esperado in (("7", "16:00", 7), ("5", "14:00", 5), ("5,5", "14:30", Decimal("5.5"))):
            form = EscalaForm(data=self._dados(horas_por_dia=horas, horario_saida=saida))
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.dados_escala()["horas_por_dia"], esperado)

    def test_horas_calculadas_pelos_horarios(self):
        form = EscalaForm(data=self._dados(horas_por_dia="", horario_saida="16:00"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.dados_escala()["horas_por_dia"], 7)
        form = EscalaForm(data=self._dados(horas_por_dia="", horario_entrada="13:00", saida_intervalo="",
                                           volta_intervalo="", horario_saida="18:00"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.dados_escala()["horas_por_dia"], 5)

    def test_sem_horas_nem_horarios(self):
        form = EscalaForm(data=self._dados(horas_por_dia="", horario_entrada="", saida_intervalo="", volta_intervalo="",
                                           horario_saida=""))
        self.assertFalse(form.is_valid())
        self.assertIn("Informe as horas por dia", str(form.errors))

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
        outro_sup = _ativo(criar_usuario("Selma Duarte", Usuario.Papel.SUPERVISOR,
                                         concedente=LocalEstagio.objects.create(nome="Outra Empresa")))
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
             f"curso_{self.curso.pk}": "on", f"vaga_{self.curso.pk}": "2", "supervisor_nome": "Marta Amaral",
             "supervisor_telefone": "(85) 98888-7777", "consentimento": "on", "preenchido_por": "REPRESENTANTE",
             "contato_email": "jorge@paoquente.test", "senha1": "Girassol#Azul27", "senha2": "Girassol#Azul27",
             "aceite_termos": "on"}
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
        r = self.client.post(reverse("candidatura_publica"), self._dados(**{f"vaga_{self.curso.pk}": "",
                                                                            f"curso_{self.curso.pk}": ""}))
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
        self.assertFalse(ana.has_usable_password())  # sem senha até o primeiro acesso
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


    def test_importacao_com_horas_livres_ou_pelos_horarios(self):
        from .importacao import Opcoes, importar

        base = {"curso": "Informática", "data_inicio": "01/09/2026", "concedente_nome": "Empresa X",
                "supervisor_nome": "Sérgio Supervisor"}
        linhas = [(2, {**base, "estagiario_nome": "Ana Sete", "horas_por_dia": "7"}),
                  (3, {**base, "estagiario_nome": "Bia Cinco", "entrada": "13:00", "saida": "18:00"}),
                  (4, {**base, "estagiario_nome": "Caio Sem Horas"})]
        r = importar(linhas, Opcoes(orientador=self.ori, dias=[0]), self.ori, confirmar=True)
        self.assertIn("horas_por_dia: informe", r.erros[0][1])
        r = importar(linhas[:2], Opcoes(orientador=self.ori, dias=[0], horas_por_dia=None), self.ori, confirmar=True)
        self.assertTrue(r.confirmado, r.erros)
        horas = dict(Escala.objects.filter(estagio__estagiario__nome_completo__in=["Ana Sete", "Bia Cinco"])
                     .values_list("estagio__estagiario__nome_completo", "horas_por_dia"))
        self.assertEqual(horas, {"Ana Sete": 7, "Bia Cinco": 5})


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
            estagiarios=[["João Pedro Matos", 100000037, None, "", "", "", "Informática", "3º A", 2024, date(2026, 8, 24), None, 40,
                          "seg-qua", 4, None, None, None, None, "Escola Nova Esperança", None],
                         ["Lia Gomes Torres", "", None, "", "", "", "Informática", "3º A", 2024, date(2026, 8, 24), None, None,
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


@override_settings(MEDIA_ROOT=settings.BASE_DIR / "data" / "teste-anexos")
class AtestadoTests(Base):
    def setUp(self):
        super().setUp()
        import shutil

        self.addCleanup(shutil.rmtree, settings.BASE_DIR / "data" / "teste-anexos", ignore_errors=True)

    def _foto(self, nome="atestado.png"):
        buf = io.BytesIO()
        Image.new("RGB", (3000, 2000), "white").save(buf, "PNG")
        return SimpleUploadedFile(nome, buf.getvalue(), content_type="image/png")

    def _enviar(self, quem=None, **kw):
        self.entrar(quem or self.aluno)
        dados = {"tipo": "ATESTADO", "data_inicio": "2026-11-09", "data_fim": "2026-11-10", "arquivo": self._foto()}
        dados.update(kw)
        return self.client.post(reverse("enviar_atestado", args=[self.est.pk]), dados, follow=True)

    def test_envio_poe_os_dias_em_analise(self):
        from .models import Justificativa

        r = self._enviar(motivo="Gripe")
        self.assertContains(r, "2 dias aguardando análise")
        j = Justificativa.objects.get()
        self.assertEqual((j.status, j.dias), ("PENDENTE", ["2026-11-09", "2026-11-10"]))
        self.assertTrue(j.arquivo.name.endswith(".jpg"))  # foto convertida (sem metadados) e reduzida
        with Image.open(j.arquivo.path) as img:
            self.assertEqual(max(img.size), 2000)
        regs = Registro.objects.filter(estagio=self.est).order_by("data")
        self.assertEqual([(r.situacao, r.confirmacao, r.justificativa_id) for r in regs],
                         [("AUSENCIA", "PENDENTE", j.pk)] * 2)
        self.assertEqual(Notificacao.objects.filter(usuario__in=[self.sup, self.ori], link=j.get_absolute_url()).count(), 2)

    def test_supervisor_aceita(self):
        from .models import Justificativa

        self._enviar()
        j = Justificativa.objects.get()
        self.entrar(self.sup)
        self.assertContains(self.client.get(reverse("painel_supervisor")), "Atestados para analisar")
        self.assertEqual(self.client.get(reverse("atestado_arquivo", args=[j.pk]))["Content-Type"], "image/jpeg")
        self.client.post(reverse("decidir_atestado", args=[j.pk]), {"acao": "aceitar"})
        j.refresh_from_db()
        self.assertEqual(j.status, "ACEITA")
        h = resumo_horas(self.est)
        self.assertEqual((h["faltas"], h["ausencias"]), (0, 2))
        self.assertEqual(set(Registro.objects.values_list("confirmacao", flat=True)), {"CONFIRMADA"})

    def test_recusa_exige_motivo_e_vira_falta(self):
        from .models import Justificativa

        self._enviar(data_fim="2026-11-16")  # 9, 10 (passados) e 16 (futuro)
        j = Justificativa.objects.get()
        self.assertEqual(len(j.dias), 3)
        self.entrar(self.ori)
        r = self.client.post(reverse("decidir_atestado", args=[j.pk]), {"acao": "recusar"}, follow=True)
        self.assertContains(r, "escreva o motivo")
        self.client.post(reverse("decidir_atestado", args=[j.pk]), {"acao": "recusar", "parecer": "Data rasurada"})
        j.refresh_from_db()
        self.assertEqual(j.status, "RECUSADA")
        self.assertEqual(list(Registro.objects.order_by("data").values_list("data", "situacao")),
                         [(date(2026, 11, 9), "FALTA"), (date(2026, 11, 10), "FALTA")])
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto__contains="Data rasurada").exists())

    def test_justifica_falta_ja_lancada(self):
        Registro.objects.create(estagio=self.est, data=date(2026, 11, 9), situacao=Registro.Situacao.FALTA,
                                confirmacao=Registro.Confirmacao.CONFIRMADA)
        self._enviar(data_fim="")
        reg = Registro.objects.get(data=date(2026, 11, 9))
        self.assertEqual((reg.situacao, reg.confirmacao), ("AUSENCIA", "PENDENTE"))

    def test_periodo_sem_dia_de_estagio(self):
        r = self._enviar(data_inicio="2026-11-14", data_fim="2026-11-15")
        self.assertContains(r, "Nenhum dia de estágio nesse período")

    def test_arquivo_invalido_e_pdf(self):
        from .models import Justificativa

        r = self._enviar(arquivo=SimpleUploadedFile("a.txt", b"texto qualquer", content_type="text/plain"))
        self.assertContains(r, "Formato não reconhecido")
        self._enviar(arquivo=SimpleUploadedFile("a.pdf", b"%PDF-1.4 conteudo", content_type="application/pdf"))
        self.assertTrue(Justificativa.objects.get().arquivo.name.endswith(".pdf"))

    def test_escola_registra_ja_aceito(self):
        from .models import Justificativa

        self._enviar(quem=self.ori)
        self.assertEqual(Justificativa.objects.get().status, "ACEITA")
        self.assertEqual(resumo_horas(self.est)["ausencias"], 2)

    def test_so_a_escola_quando_configurado(self):
        from .models import Justificativa

        c = Configuracao.atual()
        c.atestados_supervisor = False
        c.save()
        self._enviar()
        j = Justificativa.objects.get()
        self.entrar(self.sup)
        self.assertEqual(self.client.get(reverse("atestado_detalhe", args=[j.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("atestado_arquivo", args=[j.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("painel_supervisor")), "Atestados para analisar")
        reg = Registro.objects.first()
        self.client.post(reverse("validar_registro", args=[reg.pk]), {"acao": "confirmar"})
        reg.refresh_from_db()
        self.assertEqual(reg.confirmacao, "PENDENTE")
        self.client.post(reverse("confirmar_lote"), {"registros": [reg.pk]})
        reg.refresh_from_db()
        self.assertEqual(reg.confirmacao, "PENDENTE")
        self.entrar(self.ori)
        self.assertContains(self.client.get(reverse("atestados")), "Maria da Silva Souza")
        self.assertContains(self.client.get(reverse("painel")), "1 atestado")

    def test_outros_nao_veem(self):
        from .models import Justificativa

        self._enviar()
        j = Justificativa.objects.get()
        outro = _ativo(criar_usuario("Outro Aluno", Usuario.Papel.ESTAGIARIO))
        self.entrar(outro)
        self.assertEqual(self.client.get(reverse("atestado_arquivo", args=[j.pk])).status_code, 403)

    def test_confirmar_o_dia_aceita_o_atestado(self):
        from .models import Justificativa

        self._enviar()
        self.entrar(self.sup)
        reg = Registro.objects.first()
        self.client.post(reverse("validar_registro", args=[reg.pk]), {"acao": "confirmar"})
        self.assertEqual(Justificativa.objects.get().status, "ACEITA")


class RevogarPresencaTests(Base):
    def setUp(self):
        super().setUp()
        self.dia = date(2026, 11, 10)
        self.reg = Registro.objects.create(estagio=self.est, data=self.dia, situacao=Registro.Situacao.PRESENTE,
                                           horas=4, confirmacao=Registro.Confirmacao.CONFIRMADA)
        self.url = reverse("estagio_dia", args=[self.est.pk, "2026-11-10"])

    def test_supervisor_remove_presenca_confirmada(self):
        self.entrar(self.sup)
        self.assertContains(self.client.get(self.url), "Revogar esta presença")
        r = self.client.post(self.url, {"r-destino": "remover", "r-motivo": ""})
        self.assertContains(r, "obrigatório")
        self.client.post(self.url, {"r-destino": "remover", "r-motivo": "Marcou e foi embora antes de começar"})
        self.assertFalse(Registro.objects.filter(pk=self.reg.pk).exists())
        h = HistoricoRegistro.objects.filter(data=self.dia).latest("em")
        self.assertEqual(h.acao, "REVOGOU")
        self.assertIn(["Motivo", "—", "Marcou e foi embora antes de começar"], h.mudancas)
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto__contains="revogou a presença").exists())
        self.assertEqual(resumo_horas(self.est)["cumpridas"], 0)

    def test_orientador_troca_por_ausencia_justificada_ou_falta(self):
        self.entrar(self.ori)
        self.client.post(self.url, {"r-destino": "ausencia", "r-motivo": "Passou mal e foi dispensado"})
        self.reg.refresh_from_db()
        self.assertEqual((self.reg.situacao, self.reg.confirmacao, self.reg.horas), ("AUSENCIA", "CONFIRMADA", 0))
        self.reg.situacao = Registro.Situacao.PRESENTE
        self.reg.horas = 4
        self.reg.save()
        self.client.post(self.url, {"r-destino": "falta", "r-motivo": "Não compareceu"})
        self.reg.refresh_from_db()
        self.assertEqual(self.reg.situacao, "FALTA")

    def test_estagiario_so_desfaz_antes_da_confirmacao(self):
        self.entrar(self.aluno)
        self.assertNotContains(self.client.get(self.url), "Revogar esta presença")
        self.client.post(self.url, {"r-destino": "remover", "r-motivo": "engano"})
        self.assertTrue(Registro.objects.filter(pk=self.reg.pk).exists())
        Registro.objects.filter(pk=self.reg.pk).update(confirmacao=Registro.Confirmacao.PENDENTE)
        r = self.client.get(self.url)
        self.assertContains(r, "Revogar esta presença")
        self.assertNotContains(r, "Trocar por falta")
        self.client.post(self.url, {"r-destino": "falta", "r-motivo": "engano"})  # opção não permitida
        self.assertTrue(Registro.objects.filter(pk=self.reg.pk, situacao="PRESENTE").exists())
        self.client.post(self.url, {"r-destino": "remover", "r-motivo": "Marquei no dia errado"})
        self.assertFalse(Registro.objects.filter(pk=self.reg.pk).exists())


@override_settings(MEDIA_ROOT=settings.BASE_DIR / "data" / "teste-anexos")
class PastaDocumentosTests(Base):
    def setUp(self):
        super().setUp()
        import shutil

        from .models import TipoDocumento

        self.addCleanup(shutil.rmtree, settings.BASE_DIR / "data" / "teste-anexos", ignore_errors=True)
        TipoDocumento.objects.all().delete()
        self.tce = TipoDocumento.objects.create(nome="TCE assinado", momento="INICIO", prazo_dias=5)
        self.plano = TipoDocumento.objects.create(nome="Plano de atividades", momento="INICIO", prazo_dias=30,
                                                  quem_envia="SUPERVISOR")
        self.relatorio = TipoDocumento.objects.create(nome="Relatório final", momento="FIM", prazo_dias=10)

    def _pasta(self):
        from .pasta import pasta_do_estagio

        return {i.tipo.nome: i.codigo for i in pasta_do_estagio(self.est)}

    def _arquivo(self):
        return SimpleUploadedFile("tce.pdf", b"%PDF-1.4 termo", content_type="application/pdf")

    def test_situacao_por_prazo(self):
        # início 02/11; hoje 11/11: TCE (5 dias) atrasado, plano (30 dias) pendente, relatório só no fim
        self.assertEqual(self._pasta(), {"TCE assinado": "atrasado", "Plano de atividades": "pendente",
                                         "Relatório final": "depois"})
        self.est.data_fim = date(2026, 11, 10)
        self.est.save()
        self.assertEqual(self._pasta()["Relatório final"], "pendente")

    def test_estagiario_envia_e_orientador_confere(self):
        from .models import Documento

        self.entrar(self.aluno)
        r = self.client.get(self.est.get_absolute_url())
        self.assertContains(r, "você precisa enviar")
        self.assertContains(r, "TCE assinado (atrasado)")
        self.assertNotContains(r, "Plano de atividades (")  # é o supervisor quem envia
        self.client.post(reverse("enviar_para_pasta", args=[self.est.pk, self.tce.pk]), {"arquivo": self._arquivo()})
        doc = Documento.objects.get(tipo=self.tce)
        self.assertEqual(doc.situacao, "ENVIADO")
        self.assertEqual(self._pasta()["TCE assinado"], "enviado")
        self.assertTrue(Notificacao.objects.filter(usuario=self.ori, texto__contains="para conferência").exists())
        self.entrar(self.ori)
        self.assertContains(self.client.get(reverse("pasta_geral")), "Para conferir")
        r = self.client.post(reverse("conferir_documento", args=[doc.pk]), {"acao": "recusar"}, follow=True)
        self.assertContains(r, "escreva o que precisa ser corrigido")
        self.client.post(reverse("conferir_documento", args=[doc.pk]), {"acao": "recusar", "parecer": "Falta assinatura"})
        self.assertEqual(self._pasta()["TCE assinado"], "recusado")
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto__contains="Falta assinatura").exists())
        self.entrar(self.aluno)
        self.client.post(reverse("enviar_para_pasta", args=[self.est.pk, self.tce.pk]), {"arquivo": self._arquivo()})
        self.entrar(self.ori)
        novo = Documento.objects.filter(tipo=self.tce).latest("criado_em")
        self.client.post(reverse("conferir_documento", args=[novo.pk]), {"acao": "aprovar"})
        self.assertEqual(self._pasta()["TCE assinado"], "conferido")

    def test_escola_envia_ja_conferido_e_supervisor_ve_o_que_falta(self):
        self.entrar(self.ori)
        self.client.post(reverse("enviar_para_pasta", args=[self.est.pk, self.tce.pk]), {"arquivo": self._arquivo()})
        self.assertEqual(self._pasta()["TCE assinado"], "conferido")
        self.entrar(self.sup)
        r = self.client.get(reverse("painel_supervisor"))
        self.assertContains(r, "Documentos que a escola precisa de você")
        self.assertContains(r, "Plano de atividades")
        from .models import Documento

        doc = Documento.objects.get(tipo=self.tce)
        self.assertEqual(self.client.post(reverse("conferir_documento", args=[doc.pk]), {"acao": "aprovar"}).status_code, 403)

    def test_outro_estagiario_nao_envia(self):
        outro = _ativo(criar_usuario("Outro Aluno", Usuario.Papel.ESTAGIARIO))
        self.entrar(outro)
        r = self.client.post(reverse("enviar_para_pasta", args=[self.est.pk, self.tce.pk]), {"arquivo": self._arquivo()})
        self.assertEqual(r.status_code, 403)

    def test_tipo_de_outro_curso_nao_aparece(self):
        outro_curso = Curso.objects.create(nome="Enfermagem", carga_horaria=100)
        self.plano.curso = outro_curso
        self.plano.save()
        self.assertNotIn("Plano de atividades", self._pasta())

    def test_relatorio_e_resumo_mostram_atrasados(self):
        from .acompanhamento import resumo_semanal

        self.entrar(self.ori)
        r = self.client.get(reverse("relatorio_turma", args=[self.turma.pk]))
        self.assertIn("documentos da pasta atrasados: TCE assinado", dict(r.context["atencao"])[self.est])
        self.assertEqual([i.tipo.nome for _, i in resumo_semanal(self.ori)["secoes"]["docs_atrasados"]], ["TCE assinado"])

    def test_cadastro_de_tipos(self):
        self.entrar(self.ori)
        self.client.post(reverse("tipos_documento"), {"nome": "Seguro contra acidentes", "momento": "INICIO",
                                                      "prazo_dias": "10", "quem_envia": "ESCOLA", "obrigatorio": "on",
                                                      "ativo": "on", "ordem": "5"})
        self.assertIn("Seguro contra acidentes", self._pasta())
        self.entrar(self.sup)
        self.assertEqual(self.client.get(reverse("tipos_documento")).status_code, 403)

    def test_entregue_em_papel_individual_e_em_lote(self):
        outro = _ativo(criar_usuario("Ana Lote", Usuario.Papel.ESTAGIARIO))
        e2 = Estagio.objects.create(estagiario=outro, orientador=self.ori, curso=self.curso, turma=self.turma,
                                    data_inicio=date(2026, 9, 1))
        self.entrar(self.ori)
        self.client.post(reverse("entregue_em_papel", args=[self.est.pk, self.plano.pk]))
        self.assertEqual(self._pasta()["Plano de atividades"], "conferido")
        self.client.post(reverse("entregue_em_papel_lote"), {"tipo": self.tce.pk, "estagios": [self.est.pk, e2.pk]})
        self.assertEqual(self._pasta()["TCE assinado"], "conferido")
        from .pasta import pasta_do_estagio

        self.assertEqual({i.tipo.nome: i.codigo for i in pasta_do_estagio(e2)}["TCE assinado"], "conferido")
        self.assertContains(self.client.get(self.est.get_absolute_url() + "?aba=arquivos"), "Em papel, na escola")
        self.entrar(self.aluno)
        r = self.client.post(reverse("entregue_em_papel", args=[self.est.pk, self.relatorio.pk]))
        self.assertEqual(r.status_code, 403)


@override_settings(VAPID_ARQUIVO=settings.BASE_DIR / "data" / "teste-vapid.pem", PUSH_ATIVO=True)
class PushTests(Base):
    INSC = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc123", "keys": {"p256dh": "BPk" + "x" * 80, "auth": "y" * 22}}

    def setUp(self):
        super().setUp()
        from . import push

        push._vapid = None
        self.addCleanup(lambda: (settings.BASE_DIR / "data" / "teste-vapid.pem").unlink(missing_ok=True))
        self.addCleanup(setattr, push, "_vapid", None)

    def _inscrever(self, user=None):
        import json

        self.entrar(user or self.aluno)
        return self.client.post(reverse("push_inscrever"), json.dumps(self.INSC), content_type="application/json")

    def test_chave_publica_gerada_e_guardada(self):
        self.entrar(self.aluno)
        chave = self.client.get(reverse("push_chave")).json()["chave"]
        self.assertEqual(len(chave), 87)  # 65 bytes em base64url
        self.assertTrue((settings.BASE_DIR / "data" / "teste-vapid.pem").exists())
        from . import push

        push._vapid = None
        self.assertEqual(self.client.get(reverse("push_chave")).json()["chave"], chave)  # mesma chave depois

    def test_inscrever_e_cancelar(self):
        import json

        from .models import InscricaoPush

        self.assertEqual(self._inscrever().json(), {"ok": True})
        self._inscrever()  # repetir não duplica
        self.assertEqual(InscricaoPush.objects.get().usuario, self.aluno)
        r = self.client.post(reverse("push_inscrever"), json.dumps({"endpoint": "http://x"}), content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.client.post(reverse("push_cancelar"), json.dumps({"endpoint": self.INSC["endpoint"]}),
                         content_type="application/json")
        self.assertFalse(InscricaoPush.objects.exists())

    def test_notificar_envia_ao_celular(self):
        import json

        from .services import notificar

        self._inscrever()
        with mock.patch("pywebpush.webpush") as wp, self.captureOnCommitCallbacks(execute=True):
            notificar([self.aluno, self.sup], "Sua presença foi confirmada.", "/estagios/1/")
        self.assertEqual(wp.call_count, 1)  # só o aluno ativou
        args, kw = wp.call_args
        self.assertEqual(args[0]["endpoint"], self.INSC["endpoint"])
        payload = json.loads(kw["data"])
        n = Notificacao.objects.get(usuario=self.aluno)
        self.assertEqual(payload["texto"], "Sua presença foi confirmada.")
        self.assertEqual(payload["url"], reverse("notificacao_abrir", args=[n.pk]))

    def test_inscricao_expirada_e_removida(self):
        from pywebpush import WebPushException

        from .models import InscricaoPush
        from .services import notificar

        self._inscrever()
        resposta = mock.Mock(status_code=410)
        with mock.patch("pywebpush.webpush", side_effect=WebPushException("gone", response=resposta)), \
                self.captureOnCommitCallbacks(execute=True):
            notificar([self.aluno], "Teste")
        self.assertFalse(InscricaoPush.objects.exists())

    def test_botao_de_teste(self):
        self._inscrever()
        with mock.patch("pywebpush.webpush") as wp:
            r = self.client.post(reverse("push_teste"))
        self.assertEqual(r.json(), {"ok": True, "enviados": 1})
        self.assertEqual(wp.call_count, 1)


@override_settings(EMAIL_ATIVO=True, SITE_URL="https://estagio.exemplo.br")
class ComunicadoTests(Base):
    def test_aviso_para_a_turma(self):
        from django.core import mail

        from .models import Comunicado

        self.aluno.email = "maria@exemplo.br"
        self.aluno.save()
        outra_turma = Turma.objects.create(curso=self.curso, nome="3º B", ano_ingresso=2024, ano_estagio=2026)
        fora = _ativo(criar_usuario("Fora da Turma", Usuario.Papel.ESTAGIARIO))
        Estagio.objects.create(estagiario=fora, orientador=self.ori, curso=self.curso, turma=outra_turma,
                               data_inicio=date(2026, 11, 2))
        self.entrar(self.ori)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(reverse("comunicados"), {
                "para": "estagiarios", "turma": self.turma.pk, "titulo": "Relatório até sexta",
                "texto": "Pessoal, o relatório parcial deve ser entregue até sexta-feira, dia 20."}, follow=True)
        self.assertContains(r, "Aviso enviado para 1 pessoa")
        c = Comunicado.objects.get()
        self.assertEqual(list(c.destinatarios.all()), [self.aluno])
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto="Paula: Relatório até sexta").exists())
        self.assertFalse(Notificacao.objects.filter(usuario=fora).exists())
        self.assertIn("entregue até sexta-feira", mail.outbox[0].body)
        self.entrar(self.aluno)
        self.assertContains(self.client.get(c.get_absolute_url()), "dia 20")
        self.assertContains(self.client.get(reverse("meus_comunicados")), "Relatório até sexta")
        self.entrar(fora)
        self.assertEqual(self.client.get(c.get_absolute_url()).status_code, 403)

    def test_aviso_para_supervisores(self):
        self.entrar(self.ori)
        self.client.post(reverse("comunicados"), {"para": "supervisores", "titulo": "Visitas na próxima semana",
                                                  "texto": "Vou visitar as concedentes."})
        self.assertTrue(Notificacao.objects.filter(usuario=self.sup).exists())
        self.assertFalse(Notificacao.objects.filter(usuario=self.aluno).exists())

    def test_sem_destinatarios_e_permissao(self):
        outro_local = LocalEstagio.objects.create(nome="Ninguém Aqui")
        self.entrar(self.ori)
        r = self.client.post(reverse("comunicados"), {"para": "estagiarios", "local": outro_local.pk, "titulo": "X",
                                                      "texto": "Y"})
        self.assertContains(r, "Ninguém recebe com esses filtros")
        self.entrar(self.aluno)
        self.assertEqual(self.client.get(reverse("comunicados")).status_code, 403)


class MenuSecoesTests(Base):
    def test_gestor_ve_secoes_com_contador_e_item_ativo(self):
        from .models import Justificativa

        Justificativa.objects.create(estagio=self.est, data_inicio=QUARTA, data_fim=QUARTA, arquivo="x.pdf")
        self.entrar(self.ori)
        menu = self.client.get(reverse("atestados")).context["MENU"]
        secoes = {s["rotulo"]: s for s in menu["secoes"]}
        self.assertEqual(list(secoes), ["Acompanhamento", "Comunicação", "Cadastros"])
        acomp = secoes["Acompanhamento"]
        self.assertTrue(acomp["ativo"])
        self.assertEqual(acomp["contador"], 1)
        self.assertEqual([i["rotulo"] for i in acomp["itens"] if i["ativo"]], ["Atestados"])

    def test_coordenador_nao_ve_o_que_nao_pode(self):
        coord = _ativo(criar_usuario("Carla Coord", Usuario.Papel.COORDENADOR))
        self.entrar(coord)
        menu = self.client.get(reverse("painel")).context["MENU"]
        rotulos = [i["rotulo"] for s in menu["secoes"] for i in s["itens"]]
        self.assertNotIn("Agenda de visitas", rotulos)
        self.assertNotIn("Arquivos gerais", rotulos)
        self.assertIn("Recessos", rotulos)

    def test_estagiario_mantem_barra_simples(self):
        self.entrar(self.aluno)
        r = self.client.get(self.est.get_absolute_url())
        self.assertNotIn("MENU", r.context)
        self.assertContains(r, "Meu estágio")


class IndicadoresTests(Base):
    def test_frequencia_por_semana_e_por_turma(self):
        from .indicadores import calcular

        # escala seg/ter desde 02/11; hoje (mock) quarta 11/11 → dias previstos: 02, 03, 09, 10
        Registro.objects.create(estagio=self.est, data=date(2026, 11, 2), situacao=Registro.Situacao.PRESENTE, horas=4,
                                confirmacao=Registro.Confirmacao.CONFIRMADA)
        Registro.objects.create(estagio=self.est, data=date(2026, 11, 3), situacao=Registro.Situacao.PRESENTE, horas=4)
        Registro.objects.create(estagio=self.est, data=date(2026, 11, 9), situacao=Registro.Situacao.AUSENCIA,
                                confirmacao=Registro.Confirmacao.CONFIRMADA)
        d = calcular(self.ori, 2026, semanas=4)
        self.assertEqual(d["geral"]["frequencia"], 50.0)  # 2 presenças em 4 dias previstos
        semanas = {s["semana"]: s for s in d["tendencia"]}
        self.assertEqual((semanas["2026-11-02"]["taxa"], semanas["2026-11-09"]["avisadas"], semanas["2026-11-09"]["faltas"]),
                         (100.0, 1, 1))
        self.assertIsNone(semanas["2026-10-19"]["taxa"])
        turma = d["turmas"][0]
        self.assertEqual((turma["ativos"], turma["frequencia"], turma["com_visita"]), (1, 50.0, 0.0))
        self.assertEqual(d["situacoes"], [{"rotulo": "Em andamento", "n": 1, "pct": 100.0}])

    def test_pagina_e_permissoes(self):
        self.entrar(self.ori)
        r = self.client.get(reverse("indicadores"), {"semanas": "12", "curso": self.curso.pk})
        self.assertContains(r, "Frequência semana a semana")
        self.assertContains(r, "dados-tendencia")
        self.assertEqual(r.context["semanas"], 12)
        outro = Curso.objects.create(nome="Enfermagem", carga_horaria=100)
        self.assertContains(self.client.get(reverse("indicadores"), {"curso": outro.pk}), "Nenhum estagiário ativo")
        self.entrar(self.sup)
        self.assertEqual(self.client.get(reverse("indicadores")).status_code, 403)


class FeedbackSupervisorTests(Base):
    NOTAS = {"assiduidade": "5", "responsabilidade": "4", "iniciativa": "", "relacionamento": "5", "qualidade": "4",
             "aprendizado": "4", "pontos_fortes": "Atenciosa", "melhorar": "Pedir ajuda mais cedo",
             "reservado": "Comentou que pensa em desistir", "visivel_estagiario": "on"}

    def test_supervisor_da_feedback_e_estagiario_ve_sem_o_reservado(self):
        from .models import Feedback

        self.entrar(self.sup)
        self.assertContains(self.client.get(reverse("painel_supervisor")), "Feedback de novembro de 2026")
        self.client.post(reverse("dar_feedback", args=[self.est.pk]), self.NOTAS)
        f = Feedback.objects.get()
        self.assertEqual((f.mes, f.iniciativa, f.media), (date(2026, 11, 1), None, 4.4))
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto__contains="feedback de novembro").exists())
        self.assertTrue(Notificacao.objects.filter(usuario=self.ori, texto__contains="média 4,4").exists())
        self.client.post(reverse("dar_feedback", args=[self.est.pk]), {**self.NOTAS, "assiduidade": "3"})
        self.assertEqual(Feedback.objects.count(), 1)  # o mesmo mês é atualizado
        self.entrar(self.aluno)
        r = self.client.get(self.est.get_absolute_url() + "?aba=feedback")
        self.assertContains(r, "Pedir ajuda mais cedo")
        self.assertNotContains(r, "pensa em desistir")
        self.entrar(self.ori)
        self.assertContains(self.client.get(self.est.get_absolute_url() + "?aba=feedback"), "pensa em desistir")

    def test_oculto_e_vazio(self):
        from .models import Feedback

        self.entrar(self.sup)
        r = self.client.post(reverse("dar_feedback", args=[self.est.pk]), {})
        self.assertContains(r, "Dê ao menos uma nota")
        self.client.post(reverse("dar_feedback", args=[self.est.pk]), {"qualidade": "2", "melhorar": "Atenção aos prazos"})
        self.assertFalse(Feedback.objects.get().visivel_estagiario)
        self.entrar(self.aluno)
        self.assertNotContains(self.client.get(self.est.get_absolute_url() + "?aba=feedback"), "Atenção aos prazos")

    def test_so_o_supervisor_do_estagio_e_mes_fechado(self):
        outro = _ativo(criar_usuario("Outro Supervisor", Usuario.Papel.SUPERVISOR, concedente=self.local))
        self.entrar(outro)
        self.assertEqual(self.client.get(reverse("dar_feedback", args=[self.est.pk])).status_code, 403)
        self.entrar(self.ori)
        self.assertEqual(self.client.get(reverse("dar_feedback", args=[self.est.pk])).status_code, 403)
        from .models import Feedback

        self.entrar(self.sup)
        self.client.post(reverse("dar_feedback", args=[self.est.pk]) + "?mes=2026-09", {"qualidade": "5"})
        self.assertEqual(Feedback.objects.get().mes, date(2026, 11, 1))  # setembro já fechou: vale o mês atual

    def test_lembrete_do_dia_20_uma_vez(self):
        from datetime import datetime

        from .feedback import disparar_lembrete

        tz = timezone.get_current_timezone()
        self.assertEqual(disparar_lembrete(datetime(2026, 11, 19, 10, tzinfo=tz)), 0)
        self.assertEqual(disparar_lembrete(datetime(2026, 11, 20, 8, tzinfo=tz)), 1)
        self.assertTrue(Notificacao.objects.filter(usuario=self.sup, texto__contains="Falta o feedback de novembro").exists())
        self.assertEqual(disparar_lembrete(datetime(2026, 11, 25, 8, tzinfo=tz)), 0)

    def test_quadro_indicadores_e_pontos_de_atencao(self):
        from .indicadores import calcular

        self.entrar(self.sup)
        self.client.post(reverse("dar_feedback", args=[self.est.pk]), {"qualidade": "2", "assiduidade": "2"})
        self.entrar(self.ori)
        r = self.client.get(reverse("feedback_geral"))
        self.assertEqual(r.context["baixos"], 1)
        self.assertContains(r, "nota-media baixa")
        r = self.client.get(reverse("relatorio_turma", args=[self.turma.pk]))
        self.assertTrue(any("abaixo de “bom”" in m for m in dict(r.context["atencao"])[self.est]))
        d = calcular(self.ori, 2026)
        self.assertEqual((d["geral"]["feedback"], d["geral"]["feedback_mes"]), (2.0, 100.0))


@override_settings(MEDIA_ROOT=settings.BASE_DIR / "data" / "teste-anexos")
class EncerramentoTests(Base):
    def setUp(self):
        super().setUp()
        import shutil

        self.addCleanup(shutil.rmtree, settings.BASE_DIR / "data" / "teste-anexos", ignore_errors=True)
        self.est.horas_anteriores = 100  # cumpriu a carga (100h)
        self.est.save()
        self.aluno2 = _ativo(criar_usuario("Bruno Incompleto", Usuario.Papel.ESTAGIARIO))
        self.est2 = Estagio.objects.create(estagiario=self.aluno2, orientador=self.ori, supervisor=self.sup,
                                           curso=self.curso, turma=self.turma, local=self.local,
                                           data_inicio=date(2026, 11, 2))
        c = Configuracao.atual()
        c.ano_referencia = 2026
        c.save()

    def test_diagnostico_e_encerramento_padrao(self):
        self.entrar(self.ori)
        r = self.client.get(reverse("encerramento"), {"ano": 2026})
        self.assertEqual(([e for e, _ in r.context["d"]["concluidos"]], [e for e, _ in r.context["d"]["incompletos"]]),
                         ([self.est], [self.est2]))
        self.client.post(reverse("encerramento"), {"acao": "encerrar", "ano": 2026, "desativar_contas": "on",
                                                   "inativar_turmas": "on", "avancar_ano": "on"})
        self.est.refresh_from_db(); self.est2.refresh_from_db(); self.aluno.refresh_from_db(); self.turma.refresh_from_db()
        self.assertEqual((self.est.ativo, self.est2.ativo, self.aluno.is_active), (False, True, False))
        self.assertTrue(self.turma.ativa)  # Bruno continua ativo na turma
        self.assertEqual(Configuracao.atual().ano_referencia, 2027)
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto__contains="foi encerrado").exists())

    def test_encerrar_todos_e_desfazer(self):
        from .models import Encerramento

        self.entrar(self.ori)
        self.client.post(reverse("encerramento"), {"acao": "encerrar", "ano": 2026, "incluir_incompletos": "on",
                                                   "desativar_contas": "on", "desativar_supervisores": "on",
                                                   "inativar_turmas": "on", "avancar_ano": "on"})
        self.turma.refresh_from_db(); self.sup.refresh_from_db()
        self.assertEqual((self.turma.ativa, self.sup.is_active), (False, False))
        e = Encerramento.objects.get()
        self.client.post(reverse("encerramento"), {"acao": "desfazer", "encerramento": e.pk})
        for o in (self.est, self.est2, self.aluno, self.sup, self.turma):
            o.refresh_from_db()
        self.assertEqual((self.est.ativo, self.est2.ativo, self.aluno.is_active, self.sup.is_active, self.turma.ativa),
                         (True, True, True, True, True))
        self.assertEqual(Configuracao.atual().ano_referencia, 2026)
        e.refresh_from_db()
        self.assertIsNotNone(e.desfeito_em)

    def test_anonimizacao_depois_do_prazo(self):
        from datetime import datetime

        from .encerramento import anonimizar, candidatos_anonimizacao
        from .models import Documento, Feedback, Justificativa, Mensagem

        antiga = Turma.objects.create(curso=self.curso, nome="3º A", ano_ingresso=2017, ano_estagio=2019)
        velho = _ativo(criar_usuario("Antônio Antigo", Usuario.Papel.ESTAGIARIO, cpf="001.000.000-37",
                                     email="antonio@exemplo.br"))
        e = Estagio.objects.create(estagiario=velho, orientador=self.ori, supervisor=self.sup, curso=self.curso,
                                   turma=antiga, local=self.local, data_inicio=date(2019, 3, 1), ativo=False)
        Registro.objects.create(estagio=e, data=date(2019, 3, 4), situacao=Registro.Situacao.AUSENCIA,
                                motivo="Consulta no psiquiatra", horas=0)
        Registro.objects.create(estagio=e, data=date(2019, 3, 5), situacao=Registro.Situacao.PRESENTE, horas=4,
                                diario="Conheci a equipe")
        Mensagem.objects.create(estagio=e, autor=velho, texto="Meu telefone novo é 85 99999-0000")
        Justificativa.objects.create(estagio=e, data_inicio=date(2019, 3, 4), data_fim=date(2019, 3, 4),
                                     arquivo=SimpleUploadedFile("a.pdf", b"%PDF-1.4"), motivo="CID F41")
        Documento.objects.create(titulo="TCE", arquivo=SimpleUploadedFile("t.pdf", b"%PDF-1.4"), estagio=e,
                                 orientador=self.ori, enviado_por=velho)
        Feedback.objects.create(estagio=e, mes=date(2019, 3, 1), qualidade=4, reservado="Problemas em casa")
        self.assertEqual(candidatos_anonimizacao(self.ori), [e])  # 2019 + 5 anos < 2026; os de 2026 ficam
        self.entrar(self.ori)
        r = self.client.post(reverse("encerramento"), {"acao": "anonimizar", "confirmacao": "sim"}, follow=True)
        self.assertContains(r, "digite ANONIMIZAR")
        self.client.post(reverse("encerramento"), {"acao": "anonimizar", "confirmacao": "anonimizar"})
        velho.refresh_from_db()
        self.assertEqual((velho.cpf, velho.email, velho.is_active, velho.has_usable_password()), ("", "", False, False))
        self.assertTrue(velho.nome_completo.startswith("Estagiário anonimizado"))
        self.assertFalse(Registro.objects.filter(estagio=e).exclude(motivo="", diario="").exists())
        self.assertEqual(sum(Registro.objects.filter(estagio=e).values_list("horas", flat=True)), 4)  # horas ficam
        self.assertFalse(Mensagem.objects.filter(estagio=e).exists())
        self.assertFalse(Documento.objects.filter(estagio=e).exists())
        j = Justificativa.objects.get(estagio=e)
        self.assertEqual((j.arquivo.name, j.motivo), ("", ""))
        f = Feedback.objects.get(estagio=e)
        self.assertEqual((f.reservado, f.qualidade), ("", 4))
        self.assertEqual(candidatos_anonimizacao(self.ori), [])
        self.est.refresh_from_db()
        self.assertEqual(self.est.estagiario.nome_completo, "Maria da Silva Souza")  # estágios recentes intactos

    def test_so_quem_tem_permissao(self):
        coord = _ativo(criar_usuario("Carla Coord", Usuario.Papel.COORDENADOR))
        for u in (coord, self.sup, self.aluno):
            self.entrar(u)
            self.assertEqual(self.client.get(reverse("encerramento")).status_code, 403)


class CheckinQRTests(Base):
    def setUp(self):
        super().setUp()
        Escala.objects.filter(estagio=self.est).update(dias="0,1,2,3,4")

    def _token(self, sup=None):
        from . import qrcheckin

        return qrcheckin.gerar(sup or self.sup)

    def test_supervisor_ve_o_qr_e_estagiario_marca_ja_confirmado(self):
        self.entrar(self.sup)
        self.assertContains(self.client.get(reverse("qr_supervisor")), "QR code de presença")
        d = self.client.get(reverse("qr_novo")).json()
        self.assertTrue(d["svg"].startswith("<svg"))
        self.entrar(self.aluno)
        r = self.client.get(reverse("checkin_qr", args=[self._token()]), follow=True)
        self.assertContains(r, "Sérgio Supervisor está confirmando")
        self.assertContains(r, "Marcar entrada")
        self.client.post(reverse("checkin_qr_confirmar"), {"acao": "entrada"})
        reg = Registro.objects.get(estagio=self.est, data=QUARTA)
        self.assertEqual((reg.situacao, reg.confirmacao, reg.confirmado_por), ("PRESENTE", "CONFIRMADA", self.sup))
        self.assertTrue(HistoricoRegistro.objects.filter(registro=reg, acao="QRCODE").exists())
        # o mesmo QR não serve de novo: cada marcação pede um código novo
        self.assertContains(self.client.get(reverse("checkin_qr_confirmar")), "Escaneie o QR code")
        self.client.get(reverse("checkin_qr", args=[self._token()]))
        r = self.client.get(reverse("checkin_qr_confirmar"))
        self.assertContains(r, "Marcar saída")
        self.assertNotContains(r, "Marcar entrada")
        self.client.post(reverse("checkin_qr_confirmar"), {"acao": "hora_saida"})
        reg.refresh_from_db()
        self.assertIsNotNone(reg.hora_saida)
        self.entrar(self.sup)
        self.assertEqual(self.client.get(reverse("qr_novo")).json()["marcados"][0]["nome"], "Maria da Silva Souza")

    def test_qr_expirado_ou_falso(self):
        from unittest import mock as m

        self.entrar(self.aluno)
        r = self.client.get(reverse("checkin_qr", args=["falso"]))
        self.assertEqual(r.status_code, 410)
        token = self._token()
        with m.patch("django.core.signing.time.time", return_value=__import__("time").time() + 120):
            self.assertEqual(self.client.get(reverse("checkin_qr", args=[token])).status_code, 410)

    def test_qr_de_outro_supervisor(self):
        outro = _ativo(criar_usuario("Olga Outra", Usuario.Papel.SUPERVISOR, concedente=self.local))
        self.entrar(self.aluno)
        r = self.client.get(reverse("checkin_qr", args=[self._token(outro)]), follow=True)
        self.assertContains(r, "não é seu supervisor")
        self.assertFalse(Registro.objects.exists())

    def test_sem_login_entra_e_continua(self):
        r = self.client.get(reverse("checkin_qr", args=[self._token()]))
        self.assertIn(reverse("login"), r["Location"])
        self.entrar(self.aluno)  # o login mantém a sessão (e o QR lido)
        self.assertContains(self.client.get(reverse("checkin_qr_confirmar")), "Marcar entrada")

    def test_so_supervisor_gera(self):
        self.entrar(self.aluno)
        self.assertEqual(self.client.get(reverse("qr_novo")).status_code, 403)


class TemaTests(Base):
    def test_preferencia_vai_para_a_pagina_e_troca_pelo_menu(self):
        self.entrar(self.ori)
        r = self.client.get(reverse("painel"))
        self.assertContains(r, 'data-preferencia="auto"')
        self.assertContains(r, 'name="tema" value="ESCURO"')
        r = self.client.post(reverse("trocar_tema"), {"tema": "ESCURO"}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(r.json(), {"tema": "escuro"})
        r = self.client.get(reverse("painel"))
        self.assertContains(r, 'data-preferencia="escuro" data-tema="escuro"')
        self.client.post(reverse("trocar_tema"), {"tema": "ROXO"})  # valor inválido é ignorado
        self.ori.refresh_from_db()
        self.assertEqual(self.ori.tema, "ESCURO")
        r = self.client.post(reverse("trocar_tema"), {"tema": "CLARO"}, HTTP_REFERER="https://outro-site.com/x")
        self.assertEqual(r["Location"], "/")  # não volta para outro site

    def test_administrador_desliga_o_tema_escuro(self):
        self.ori.tema = "ESCURO"
        self.ori.save()
        c = Configuracao.atual()
        c.tema_escuro = False
        c.save()
        self.entrar(self.ori)
        r = self.client.get(reverse("painel"))
        self.assertContains(r, 'data-preferencia="claro" data-tema="claro"')
        self.assertNotContains(r, 'name="tema" value="ESCURO"')
        self.client.post(reverse("trocar_tema"), {"tema": "AUTO"})
        self.ori.refresh_from_db()
        self.assertEqual(self.ori.tema, "ESCURO")  # sem mudar enquanto estiver desligado

    def test_opcao_no_admin_e_nas_configuracoes(self):
        self.ori.is_superuser = self.ori.is_staff = True
        self.ori.save()
        self.entrar(self.ori)
        self.assertContains(self.client.get(reverse("admin:core_configuracao_change", args=[Configuracao.atual().pk])),
                            "Permitir o tema escuro")
        self.assertContains(self.client.get(reverse("configuracoes")), "Permitir o tema escuro")

    def test_visitante_segue_o_aparelho(self):
        self.assertContains(self.client.get(reverse("login")), 'data-preferencia="auto"')


class AvaliacoesSICETests(Base):
    MES = "2026-11"

    def _liberar(self, **kw):
        c = Configuracao.atual()
        c.avaliacoes_abertas = True
        for k, v in kw.items():
            setattr(c, k, v)
        c.save()

    def _respostas(self, tipo):
        from .models import PerguntaAvaliacao

        dados = {}
        for p in PerguntaAvaliacao.objects.filter(avaliacao=tipo, ativa=True):
            dados[f"p{p.pk}"] = p.lista_opcoes[0] if p.resposta == "ESCOLHA" else f"Resposta para {p.enunciado}"
        return dados

    def test_perguntas_iguais_ao_sice(self):
        from .models import PerguntaAvaliacao

        auto = list(PerguntaAvaliacao.objects.filter(avaliacao="AUTO").values_list("enunciado", "limite"))
        self.assertEqual(auto[0], ("O que aprendi", 1000))
        self.assertEqual(auto[-1][0], "Contribuição para melhorar a empresa")
        orient = list(PerguntaAvaliacao.objects.filter(avaliacao="ORIENTADOR").values_list("enunciado", flat=True))
        self.assertEqual((orient[0], orient[11], orient[12]),
                         ("Realizou orientações antes do início do estágio", "Mediação", "Observações/Sugestões"))

    def test_fechada_ate_liberar(self):
        self.entrar(self.aluno)
        r = self.client.get(reverse("responder_avaliacao", args=["auto", self.MES]), follow=True)
        self.assertContains(r, "ainda não foram liberadas")

    def test_mes_fora_do_estagio(self):
        self._liberar()
        self.entrar(self.aluno)
        self.assertEqual(self.client.get(reverse("responder_avaliacao", args=["auto", "2026-09"])).status_code, 404)

    def test_rascunho_concluir_e_copiar(self):
        from .models import Avaliacao

        self._liberar(sice_url="https://sice.exemplo.ce.gov.br/")
        self.entrar(self.aluno)
        self.assertContains(self.client.get(self.est.get_absolute_url()), "falta 1 mês")
        self.assertContains(self.client.get(reverse("minhas_avaliacoes")), "Novembro/2026")
        url = reverse("responder_avaliacao", args=["orientador", self.MES])
        dados = self._respostas("ORIENTADOR")
        primeira = next(iter(dados))
        r = self.client.post(url, {primeira: dados[primeira], "acao": "concluir"})
        self.assertContains(r, "Responda esta pergunta para concluir")
        self.client.post(url, {primeira: dados[primeira], "acao": "salvar"})
        av = Avaliacao.objects.get()
        self.assertEqual((av.mes, av.concluida_em), (date(2026, 11, 1), None))
        r = self.client.post(url, {**dados, "acao": "concluir"}, follow=True)
        self.assertContains(r, "copiar as respostas para o SICE")
        self.assertContains(r, "<strong>NOV</strong>", html=False)
        self.assertContains(r, "PAULA ORIENTADORA")  # campo “Orientador” do SICE
        self.assertContains(r, "Selecione: <strong>SIM</strong>", html=False)
        self.assertContains(r, "https://sice.exemplo.ce.gov.br/")
        self.client.post(reverse("copiar_avaliacao", args=["orientador", self.MES]), {"acao": "feito"})
        av.refresh_from_db()
        self.assertIsNotNone(av.copiada_sice_em)

    def test_avaliacao_do_orientador_e_anonima_para_ele(self):
        from .models import Avaliacao

        self._liberar()
        av = Avaliacao.objects.create(estagio=self.est, tipo="ORIENTADOR", respostas={}, concluida_em=timezone.now(),
                                      mes=date(2026, 11, 1))
        auto = Avaliacao.objects.create(estagio=self.est, tipo="AUTO", respostas={}, concluida_em=timezone.now(),
                                        mes=date(2026, 11, 1))
        self.entrar(self.ori)
        self.assertEqual(self.client.get(reverse("ver_avaliacao", args=[av.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("ver_avaliacao", args=[auto.pk])).status_code, 200)
        self.ori.is_superuser = True  # nem sendo administrador ele lê a avaliação sobre si mesmo
        self.ori.save()
        self.assertEqual(self.client.get(reverse("ver_avaliacao", args=[av.pk])).status_code, 403)
        coord = _ativo(criar_usuario("Carla Coord", Usuario.Papel.COORDENADOR))
        self.entrar(coord)
        self.assertEqual(self.client.get(reverse("ver_avaliacao", args=[av.pk])).status_code, 200)
        self.entrar(self.sup)
        self.assertEqual(self.client.get(reverse("ver_avaliacao", args=[auto.pk])).status_code, 403)

    def test_orientador_recebe_respostas_juntas_sem_nomes(self):
        from .models import Avaliacao, PerguntaAvaliacao

        self.assertEqual(set(PerguntaAvaliacao.objects.filter(avaliacao="ORIENTADOR", resposta="ESCOLHA")
                             .values_list("opcoes", flat=True)), {"SIM\nNÃO"})
        itens = list(PerguntaAvaliacao.objects.filter(avaliacao="ORIENTADOR"))
        obs = itens[-1]
        alunos = []
        for i, nome in enumerate(["Ana Um", "Beto Dois", "Caio Três"]):
            u = _ativo(criar_usuario(nome, Usuario.Papel.ESTAGIARIO))
            e = Estagio.objects.create(estagiario=u, orientador=self.ori, curso=self.curso, turma=self.turma,
                                       data_inicio=date(2026, 11, 2))
            resp = {str(p.pk): ("SIM" if i else "NÃO") for p in itens if p.resposta == "ESCOLHA"}
            resp[str(obs.pk)] = f"Comentário {i}"
            Avaliacao.objects.create(estagio=e, tipo="ORIENTADOR", respostas=resp, concluida_em=timezone.now(),
                                     mes=date(2026, 11, 1))
            alunos.append(u)
        self.entrar(self.ori)
        r = self.client.get(reverse("avaliacoes_sobre_mim"))
        self.assertContains(r, "SIM 2 (67%)")
        self.assertContains(r, "Comentário 1")
        for u in alunos:
            self.assertNotContains(r, u.nome_completo)
        Avaliacao.objects.filter(estagio__estagiario=alunos[0]).delete()  # só 2 pessoas: não mostra
        self.assertContains(self.client.get(reverse("avaliacoes_sobre_mim")), "daria para saber quem respondeu")

    def test_orientador_nao_e_avisado_de_quem_o_avaliou(self):
        self._liberar()
        self.entrar(self.aluno)
        self.client.post(reverse("responder_avaliacao", args=["orientador", self.MES]),
                         {**self._respostas("ORIENTADOR"), "acao": "concluir"})
        self.assertFalse(Notificacao.objects.filter(usuario=self.ori, texto__contains="avaliação do orientador").exists())

    def test_perguntas_editaveis_e_lembrete(self):
        from .models import PerguntaAvaliacao

        self._liberar()
        self.entrar(self.ori)
        r = self.client.post(reverse("perguntas_avaliacao"), {"avaliacao": "AUTO", "enunciado": "Turno do estágio",
                                                              "resposta": "ESCOLHA", "opcoes": "Manhã", "ordem": 9,
                                                              "obrigatoria": "on", "ativa": "on"})
        self.assertContains(r, "pelo menos duas opções")
        self.client.post(reverse("perguntas_avaliacao"), {"avaliacao": "AUTO", "enunciado": "Turno do estágio",
                                                          "resposta": "ESCOLHA", "opcoes": "Manhã\nTarde", "ordem": 9,
                                                          "obrigatoria": "on", "ativa": "on"})
        self.assertTrue(PerguntaAvaliacao.objects.filter(enunciado="Turno do estágio").exists())
        self.client.post(reverse("avisar_avaliacoes"))
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto__contains="novembro de 2026").exists())
        self.entrar(self.aluno)
        self.assertContains(self.client.get(reverse("responder_avaliacao", args=["auto", self.MES])), "Tarde")

    def test_lembrete_mensal_do_dia_20(self):
        from datetime import datetime

        from .avaliacoes import disparar_lembrete

        self._liberar()
        tz = timezone.get_current_timezone()
        self.assertEqual(disparar_lembrete(datetime(2026, 11, 19, 9, tzinfo=tz)), 0)
        self.assertEqual(disparar_lembrete(datetime(2026, 11, 20, 9, tzinfo=tz)), 1)
        self.assertEqual(disparar_lembrete(datetime(2026, 11, 24, 9, tzinfo=tz)), 0)

    def test_frequencia_mes_a_mes_como_no_sice(self):
        from .services import frequencia_mensal

        Registro.objects.create(estagio=self.est, data=date(2026, 11, 2), situacao=Registro.Situacao.PRESENTE, horas=4,
                                confirmacao=Registro.Confirmacao.CONFIRMADA)
        Registro.objects.create(estagio=self.est, data=date(2026, 11, 3), situacao=Registro.Situacao.PRESENTE, horas=4,
                                confirmacao=Registro.Confirmacao.CONFIRMADA)
        linhas = frequencia_mensal(self.est)
        self.assertEqual([(l["dias"], l["horas"], l["acumulado"], l["pct"]) for l in linhas], [(2, 8, 8, 8.0)])
        self.entrar(self.aluno)
        self.assertContains(self.client.get(self.est.get_absolute_url() + "?aba=registros"), "Frequência Detalhada")

class NovidadesTests(Base):
    def _velho(self, u):
        u.novidades_vistas = "2000.01.01"
        u.save()
        return u

    def test_cada_papel_ve_so_o_seu(self):
        from . import novidades

        aluno = [i["texto"] for v in novidades.para(self.aluno) for i in v["itens"]]
        sup = [i["texto"] for v in novidades.para(self.sup) for i in v["itens"]]
        self.assertTrue(any("Avaliações mensais do SICE" in t for t in aluno))
        self.assertFalse(any("QR code de presença: mostre" in t for t in aluno))
        self.assertTrue(any("QR code de presença: mostre" in t for t in sup))
        self.assertFalse(any("Encerramento do ano" in t for t in sup))
        self.ori.is_superuser = True
        self.ori.save()
        tudo = [i for v in novidades.para(self.ori) for i in v["itens"]]
        self.assertEqual(len(tudo), sum(len(v.itens) for v in novidades.VERSOES))  # admin vê tudo
        self.assertTrue(any(i["publico"] == ["Supervisores"] for i in tudo))  # com a indicação do público

    def test_popup_aparece_e_ver_a_cada_atualizacao(self):
        self._velho(self.aluno)
        self.entrar(self.aluno)
        r = self.client.get(self.est.get_absolute_url())
        self.assertContains(r, "O que há de novo")
        self.assertContains(r, "Avaliações mensais do SICE")
        self.client.post(reverse("novidades_visto"), {"acao": "sempre"}, HTTP_X_REQUESTED_WITH="fetch")
        self.aluno.refresh_from_db()
        from .novidades import ultima_versao

        self.assertEqual((self.aluno.novidades_vistas, self.aluno.novidades_popup), (ultima_versao(), True))
        self.assertNotContains(self.client.get(self.est.get_absolute_url()), 'id="novidades-popup"')

    def test_nao_mostrar_novamente(self):
        from unittest import mock as m

        from . import novidades

        self._velho(self.aluno)
        self.entrar(self.aluno)
        self.client.post(reverse("novidades_visto"), {"acao": "nunca"})
        self.aluno.refresh_from_db()
        self.assertFalse(self.aluno.novidades_popup)
        nova = novidades.Versao("2099.01.01", "Futuro", ((novidades.TODOS, "Algo novo"),))
        with m.patch.object(novidades, "VERSOES", (nova,) + novidades.VERSOES):
            self.assertNotContains(self.client.get(self.est.get_absolute_url()), 'id="novidades-popup"')
            r = self.client.get(reverse("novidades"))
            self.assertContains(r, "Algo novo")  # a página continua mostrando tudo

    def test_conta_nova_comeca_em_dia(self):
        novo = _ativo(criar_usuario("Nina Nova", Usuario.Papel.ESTAGIARIO))
        from .novidades import ultima_versao

        self.assertEqual(novo.novidades_vistas, ultima_versao())


@override_settings(EMAIL_ATIVO=True, MEDIA_ROOT=settings.BASE_DIR / "data" / "teste-anexos")
class SugestoesTests(Base):
    def setUp(self):
        super().setUp()
        import shutil

        self.addCleanup(shutil.rmtree, settings.BASE_DIR / "data" / "teste-anexos", ignore_errors=True)
        c = Configuracao.atual()
        c.email_sugestoes = "equipe@exemplo.br"
        c.save()

    def test_envia_por_email_com_anexos(self):
        from django.core import mail

        from .models import Sugestao

        self.aluno.email = "maria@exemplo.br"
        self.aluno.save()
        self.entrar(self.aluno)
        r = self.client.get(reverse("sugestoes"), HTTP_REFERER="http://testserver/estagios/1/")
        self.assertContains(r, 'value="Maria da Silva Souza"')
        foto = SimpleUploadedFile("print.png", b"\x89PNG fake", content_type="image/png")
        pdf = SimpleUploadedFile("erro.pdf", b"%PDF-1.4", content_type="application/pdf")
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(reverse("sugestoes"), {"tipo": "ERRO", "nome": "Maria", "email": "maria@exemplo.br",
                                                        "mensagem": "O botão de presença não funciona.",
                                                        "pagina": "/estagios/1/", "anexos": [foto, pdf]}, follow=True)
        self.assertContains(r, "Mensagem enviada")
        s = Sugestao.objects.get()
        self.assertEqual((s.usuario, s.anexos.count()), (self.aluno, 2))
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual((m.to, m.reply_to), (["equipe@exemplo.br"], ["maria@exemplo.br"]))
        self.assertIn("Erro ou problema", m.subject)
        self.assertIn("/estagios/1/", m.body)
        self.assertEqual(sorted(a[0] for a in m.attachments), ["erro.pdf", "print.png"])
        s.refresh_from_db()
        self.assertIsNotNone(s.enviada_em)

    def test_visitante_sem_login_e_robo(self):
        from django.core import mail

        from .models import Sugestao

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("sugestoes"), {"tipo": "ERRO", "nome": "Visitante", "mensagem": "Não consigo entrar."})
            self.client.post(reverse("sugestoes"), {"tipo": "ERRO", "nome": "Robô", "mensagem": "spam", "site": "x"})
        self.assertEqual(list(Sugestao.objects.values_list("nome", flat=True)), ["Visitante"])
        self.assertIn("visitante", mail.outbox[0].body)

    def test_arquivo_proibido_e_limite(self):
        from .models import Sugestao

        self.entrar(self.aluno)
        r = self.client.post(reverse("sugestoes"), {"tipo": "OUTRO", "nome": "M", "mensagem": "x",
                                                    "anexos": [SimpleUploadedFile("virus.exe", b"MZ")]})
        self.assertContains(r, "tipo de arquivo não aceito")
        for _ in range(5):
            self.client.post(reverse("sugestoes"), {"tipo": "OUTRO", "nome": "M", "mensagem": "x"})
        r = self.client.post(reverse("sugestoes"), {"tipo": "OUTRO", "nome": "M", "mensagem": "x"})
        self.assertContains(r, "várias mensagens na última hora")
        self.assertEqual(Sugestao.objects.count(), 5)

    def test_anexo_so_para_admin(self):
        from .models import AnexoSugestao, Sugestao

        s = Sugestao.objects.create(nome="X", mensagem="Y")
        a = AnexoSugestao.objects.create(sugestao=s, arquivo=SimpleUploadedFile("a.pdf", b"%PDF"), nome_original="a.pdf")
        self.entrar(self.aluno)
        self.assertEqual(self.client.get(reverse("anexo_sugestao", args=[a.pk])).status_code, 403)
        self.ori.is_superuser = True
        self.ori.save()
        self.entrar(self.ori)
        self.assertEqual(self.client.get(reverse("anexo_sugestao", args=[a.pk])).status_code, 200)


class AcompanhamentoVisitaTests(Base):
    def _respostas(self):
        from .avaliacoes import perguntas

        dados = {"v-data": "2026-11-10", "v-observacoes": "nada a declarar", "v-intervencoes": "",
                 "v-observacoes_atitudinal": "bom comportamento", "v-intervencoes_atitudinal": "conversa sobre prazos"}
        for p in perguntas("PRATICA", self.curso.pk)[1:]:  # a primeira atividade fica em branco
            dados[f"r-p{p.pk}"] = "Realizou Sem Auxílio"
        for p in perguntas("ATITUDINAL"):
            dados[f"r-p{p.pk}"] = p.lista_opcoes[0]
        return dados

    def test_perguntas_do_sice(self):
        from .models import PerguntaAvaliacao

        atitudinais = PerguntaAvaliacao.objects.filter(avaliacao="ATITUDINAL")
        self.assertEqual(atitudinais.count(), 23)
        self.assertEqual(set(atitudinais.values_list("opcoes", "obrigatoria")), {
            ("Sempre (100%)\nFrequentemente (70-90%)\nAlgumas Vezes (40-60%)\nRaramente (10-30%)\nNunca (0%)", False)})
        self.assertTrue(atitudinais.filter(enunciado="APRESENTA EQUILIBRIO EMOCIAL").exists())  # texto do SICE
        # o curso “Informática” do teste recebeu as 13 atividades práticas do relatório do SICE
        praticas = PerguntaAvaliacao.objects.filter(avaliacao="PRATICA", curso=self.curso)
        self.assertEqual(praticas.count(), 13)
        self.assertEqual(set(praticas.values_list("opcoes", "obrigatoria")),
                         {("Observou\nRealizou Com Auxílio\nRealizou Sem Auxílio", False)})

    def test_atividades_de_desenvolvimento_de_sistemas(self):
        import importlib

        from django.apps import apps as registro

        from .models import PerguntaAvaliacao
        from .sice import PRATICA_DESENVOLVIMENTO_SISTEMAS

        ds = Curso.objects.create(nome="Técnico em Desenvolvimento de Sistemas", carga_horaria=300)
        qs = PerguntaAvaliacao.objects.filter(avaliacao="PRATICA", curso=ds).order_by("ordem")
        self.assertEqual(qs.count(), 162)  # lista do “Atividade Sugerida” do SICE
        self.assertEqual(qs.first().enunciado, "Aplicar modelo MVC como padrão de desenvolvimento de software")
        self.assertEqual(set(qs.values_list("obrigatoria", flat=True)), {False})
        # a migração, num banco que já tinha parte da lista colada à mão, só completa o que falta
        qs.exclude(enunciado__in=PRATICA_DESENVOLVIMENTO_SISTEMAS[:2]).delete()
        qs.filter(enunciado=PRATICA_DESENVOLVIMENTO_SISTEMAS[0]).update(enunciado=PRATICA_DESENVOLVIMENTO_SISTEMAS[0].upper())
        PerguntaAvaliacao.objects.create(avaliacao="PRATICA", curso=ds, enunciado="ATIVIDADE PRÓPRIA", ordem=3)
        mig = importlib.import_module("core.migrations.0036_pratica_desenvolvimento_sistemas")
        mig.criar(registro, None)
        self.assertEqual(qs.count(), 163)
        textos = [t.lower() for t in qs.values_list("enunciado", flat=True)]  # o iexact do SQLite ignora acentos
        self.assertEqual(textos.count(PRATICA_DESENVOLVIMENTO_SISTEMAS[0].lower()), 1)
        self.assertTrue(qs.filter(enunciado="ATIVIDADE PRÓPRIA").exists())
        mig.criar(registro, None)  # rodar de novo não duplica
        self.assertEqual(qs.count(), 163)
        # o formulário da visita traz a busca quando a lista é longa
        self.est.curso = ds
        self.est.save()
        self.entrar(self.ori)
        r = self.client.get(reverse("acompanhamento_novo", args=[self.est.pk]))
        self.assertContains(r, "data-buscar-atividade")
        self.assertContains(r, "de 163 atividades incluídas")

    def test_orientador_preenche_na_visita_e_estagiario_ve(self):
        from .models import AcompanhamentoVisita

        ag = Agendamento.objects.create(orientador=self.ori, solicitante=self.ori, local=self.local, assunto="Visita",
                                        status=Agendamento.Status.REALIZADO, data_hora=timezone.now())
        ag.estagios.add(self.est)
        self.entrar(self.ori)
        self.assertContains(self.client.get(ag.get_absolute_url()), "Acompanhamento de visita (SICE)")
        url = reverse("acompanhamento_novo", args=[self.est.pk]) + f"?visita={ag.pk}"
        r = self.client.post(url, {"v-data": "2026-11-10", "v-observacoes": "ok"})
        self.assertContains(r, "Faltam respostas")  # as Observações da parte atitudinal são obrigatórias
        r = self.client.post(url, self._respostas(), follow=True)
        ac = AcompanhamentoVisita.objects.get()
        self.assertEqual((ac.agendamento, ac.data), (ag, date(2026, 11, 10)))
        self.assertNotContains(r, "REALIZAR A INSTALAÇÃO DOS DRIVERS")  # ficou em branco: não entra no SICE
        self.assertContains(r, "inclua só estas 12 atividades")
        self.assertContains(r, "<strong>Realizou Sem Auxílio</strong>", html=False)
        self.assertContains(r, "conversa sobre prazos")
        self.assertContains(r, "Data da Visita")
        self.assertContains(r, "Sempre (100%)")
        self.assertContains(r, "MARIA DA SILVA SOUZA")
        self.client.post(reverse("acompanhamento_sice", args=[ac.pk]), {"acao": "feito"})
        ac.refresh_from_db()
        self.assertIsNotNone(ac.lancado_sice_em)
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto__contains="acompanhamento da visita").exists())
        self.entrar(self.aluno)
        self.assertContains(self.client.get(reverse("acompanhamento_ver", args=[ac.pk])), "nada a declarar")
        self.assertEqual(self.client.get(reverse("acompanhamento_sice", args=[ac.pk])).status_code, 403)
        self.entrar(self.sup)
        self.assertEqual(self.client.get(reverse("acompanhamento_ver", args=[ac.pk])).status_code, 403)

    def test_colar_varias_atividades(self):
        from .models import PerguntaAvaliacao

        enf = Curso.objects.create(nome="Enfermagem", carga_horaria=100)
        self.entrar(self.ori)
        self.client.post(reverse("perguntas_avaliacao"), {
            "acao": "colar", "c-curso": enf.pk,
            "c-atividades": "AFERIR PRESSÃO ARTERIAL\n\n  aferir pressão arterial \nREALIZAR CURATIVO SIMPLES"})
        qs = PerguntaAvaliacao.objects.filter(avaliacao="PRATICA", curso=enf).order_by("ordem")
        self.assertEqual(list(qs.values_list("enunciado", flat=True)), ["AFERIR PRESSÃO ARTERIAL", "REALIZAR CURATIVO SIMPLES"])
        self.client.post(reverse("perguntas_avaliacao"), {"acao": "colar", "c-curso": enf.pk, "c-substituir": "on",
                                                          "c-atividades": "ADMINISTRAR MEDICAMENTOS"})
        self.assertEqual(list(qs.filter(ativa=True).values_list("enunciado", flat=True)), ["ADMINISTRAR MEDICAMENTOS"])


class SegurancaTests(Base):
    def _login(self, senha, usuario="maria.souza", ip="10.0.0.1"):
        return self.client.post(reverse("login"), {"username": usuario, "password": senha}, REMOTE_ADDR=ip)

    def test_limite_de_tentativas_de_login(self):
        from .models import TentativaLogin

        self.aluno.set_password("Senha#Certa9")
        self.aluno.save()
        for i in range(5):
            self.assertContains(self._login(f"errada{i}"), "Usuário ou senha incorretos.")
        r = self._login("Senha#Certa9")  # bloqueado: nem a senha certa entra agora
        self.assertContains(r, "Muitas tentativas")
        self.assertNotIn("_auth_user_id", self.client.session)
        Usuario.objects.filter(pk=self.aluno.pk).update(is_staff=True)  # o /admin/ entra pela mesma tela
        r = self.client.get(reverse("admin:login") + "?next=/admin/")
        self.assertRedirects(r, reverse("login") + "?next=/admin/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/admin/login/?next=//evil.example/").url, reverse("login") + "?next=/admin/")
        self.assertNotIn("_auth_user_id", self.client.session)
        # de outro IP a pessoa ainda entra (o atacante não trava a conta de ninguém com poucas tentativas)
        self.assertEqual(self._login("Senha#Certa9", ip="10.0.0.2").status_code, 302)
        self.assertFalse(TentativaLogin.objects.filter(username="maria.souza").exists())  # entrou: zera

    def test_limite_por_ip_para_varios_usuarios(self):
        from .seguranca import LIMITE_IP

        for i in range(LIMITE_IP):
            self._login("x", usuario=f"chute{i}")
        self.aluno.set_password("Senha#Certa9")
        self.aluno.save()
        self.assertContains(self._login("Senha#Certa9"), "Muitas tentativas")

    def test_senha_nova_nao_pode_ser_fraca_nem_a_padrao(self):
        novo = criar_usuario("Novo Aluno", Usuario.Papel.ESTAGIARIO)
        self.entrar(novo)
        for fraca in ("senha-teste-1", "12345678", "password", "abc12"):
            r = self.client.post(reverse("trocar_senha"), {"old_password": "senha-teste-1", "new_password1": fraca,
                                                           "new_password2": fraca})
            self.assertEqual(r.status_code, 200, fraca)
        novo.refresh_from_db()
        self.assertTrue(novo.deve_trocar_senha)

    def test_arquivo_com_script_nao_entra_nem_abre_no_navegador(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        self.entrar(self.aluno)
        self.client.post(reverse("enviar_documento", args=[self.est.pk]),
                         {"titulo": "X", "categoria": "FREQUENCIA", "arquivo": SimpleUploadedFile("x.svg", svg)})
        self.assertFalse(Documento.objects.exists())
        # um SVG que já estava salvo (enviado antes da correção) baixa, não abre como página
        doc = Documento.objects.create(titulo="Antigo", estagio=self.est, orientador=self.ori, enviado_por=self.aluno,
                                       arquivo=SimpleUploadedFile("y.svg", svg), nome_original="y.svg")
        self.entrar(self.ori)
        r = self.client.get(reverse("baixar_documento", args=[doc.pk]))
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertEqual(r["Content-Type"], "application/octet-stream")
        self.assertIn("sandbox", r["Content-Security-Policy"])
        doc.arquivo.delete(save=False)

    def test_foto_so_para_quem_tem_motivo(self):
        from django.core.files.base import ContentFile

        outro = _ativo(criar_usuario("Joana Alvo Lima", Usuario.Papel.ESTAGIARIO))
        outro.foto.save("j.jpg", ContentFile(b"\xff\xd8\xff"))
        self.entrar(self.aluno)  # colega de outro estágio: não vê
        self.assertEqual(self.client.get(reverse("foto_usuario", args=[outro.pk])).status_code, 404)
        self.entrar(self.ori)  # gestão vê
        self.assertEqual(self.client.get(reverse("foto_usuario", args=[outro.pk])).status_code, 200)
        self.aluno.foto.save("m.jpg", ContentFile(b"\xff\xd8\xff"))
        self.entrar(self.sup)  # o supervisor do estágio vê a do estagiário
        self.assertEqual(self.client.get(reverse("foto_usuario", args=[self.aluno.pk])).status_code, 200)
        outro.foto.delete(save=False)
        self.aluno.foto.delete(save=False)

    def test_ajuda_do_campo_nao_vira_html(self):
        self.local.nome = '<img src=x onerror="alert(1)">'
        self.local.save()
        self.entrar(self.ori)
        r = self.client.get(reverse("trocar_supervisor", args=[self.est.pk]))
        self.assertNotContains(r, '<img src=x onerror="alert(1)">', html=False)


class PrimeiroAcessoTests(Base):
    def _nascimento(self, nome, data, ip="10.0.0.1"):
        return self.client.post(reverse("primeiro_acesso"), {"modo": "nascimento", "nome": nome, "nascimento": data},
                                REMOTE_ADDR=ip)

    def _codigo(self, usuario, codigo, ip="10.0.0.1"):
        return self.client.post(reverse("primeiro_acesso"), {"modo": "codigo", "usuario": usuario, "codigo": codigo},
                                REMOTE_ADDR=ip)

    def _criar_senha(self, senha="Minha#Senha9"):
        return self.client.post(reverse("primeiro_acesso_senha"), {"new_password1": senha, "new_password2": senha,
                                                                   "aceito": "1"})

    def _codigo_da_tela(self, resposta):
        import re

        return re.search(r'class="codigo-acesso">([A-Z0-9]{4}-[A-Z0-9]{4})<', resposta.content.decode()).group(1)

    def test_estagiario_cria_a_senha_com_nome_e_nascimento(self):
        novo = criar_usuario("Joana D'Arc Araújo Lima", Usuario.Papel.ESTAGIARIO, data_nascimento=date(2008, 4, 26))
        self.assertFalse(novo.has_usable_password())
        self.assertContains(self._nascimento("joana d'arc araujo lima", "27/04/2008"), "Não encontramos")
        self.assertContains(self._nascimento("Joana Lima", "26/04/2008"), "Não encontramos")  # nome incompleto
        r = self._nascimento("  JOANA D'ARC ARAUJO   LIMA ", "26042008")  # sem acento, maiúsculas e sem barras
        self.assertRedirects(r, reverse("primeiro_acesso_senha"), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("primeiro_acesso_senha")), novo.username)
        self.assertEqual(self._criar_senha("12345678").status_code, 200)  # senha fraca não passa
        self.assertRedirects(self._criar_senha(), reverse("inicio"), fetch_redirect_response=False)
        novo.refresh_from_db()
        self.assertFalse(novo.deve_trocar_senha)
        self.assertTrue(novo.check_password("Minha#Senha9"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), novo.pk)
        # depois de ativada, o primeiro acesso não abre mais a conta
        self.client.logout()
        self.assertContains(self._nascimento("Joana D'Arc Araújo Lima", "26/04/2008"), "Não encontramos")

    def test_supervisor_nao_entra_por_nascimento(self):
        criar_usuario("Ana Rocha Lima", Usuario.Papel.SUPERVISOR, data_nascimento=date(1990, 1, 2))
        self.assertContains(self._nascimento("Ana Rocha Lima", "02/01/1990"), "Não encontramos")

    def test_limite_de_tentativas_do_primeiro_acesso(self):
        from .seguranca import LIMITE_1O_CHAVE_DIA

        criar_usuario("Pedro Henrique Sales", Usuario.Papel.ESTAGIARIO, data_nascimento=date(2008, 1, 1))
        for i in range(LIMITE_1O_CHAVE_DIA):  # de IPs diferentes: o limite é pelo nome, por um dia inteiro
            self._nascimento("Pedro Henrique Sales", f"{i + 2:02d}/01/2008", ip=f"10.0.1.{i}")
        r = self._nascimento("Pedro Henrique Sales", "01/01/2008", ip="10.0.2.1")
        self.assertContains(r, "Muitas tentativas")
        self.assertNotIn("primeiro_acesso", self.client.session)

    def test_supervisor_usa_codigo_de_uso_unico_gerado_pela_gestao(self):
        novo = criar_usuario("Rita de Cássia Moura", Usuario.Papel.SUPERVISOR, concedente=self.local, criado_por=self.ori)
        self.entrar(self.ori)
        r = self.client.post(reverse("redefinir_senha", args=[novo.pk]))
        codigo = self._codigo_da_tela(r)
        self.assertNotIn(codigo.replace("-", ""), Usuario.objects.get(pk=novo.pk).codigo_acesso)  # só o resumo fica salvo
        self.client.logout()
        self.assertContains(self._codigo(novo.username, "AAAA-BBBB"), "Não encontramos")
        r = self._codigo(novo.username.upper(), codigo.lower().replace("-", " "))
        self.assertRedirects(r, reverse("primeiro_acesso_senha"), fetch_redirect_response=False)
        self._criar_senha()
        novo.refresh_from_db()
        self.assertEqual((novo.deve_trocar_senha, novo.codigo_acesso), (False, ""))
        self.client.logout()
        self.assertContains(self._codigo(novo.username, codigo), "Não encontramos")  # vale uma vez só

    def test_codigo_vencido_nao_entra(self):
        from .seguranca import gerar_codigo

        novo = criar_usuario("Lucas Prado Neto", Usuario.Papel.SUPERVISOR, concedente=self.local)
        codigo = gerar_codigo(novo)
        Usuario.objects.filter(pk=novo.pk).update(codigo_acesso_validade=timezone.now() - timedelta(minutes=1))
        self.assertContains(self._codigo(novo.username, codigo), "Não encontramos")

    def test_senha_padrao_antiga_nao_abre_conta_pendente(self):
        antigo = criar_usuario("Conta Antiga Silva", Usuario.Papel.ESTAGIARIO)
        antigo.set_password(settings.SENHA_PADRAO)
        antigo.save()
        r = self.client.post(reverse("login"), {"username": antigo.username, "password": settings.SENHA_PADRAO})
        self.assertContains(r, "A senha inicial deixou de valer")
        self.assertContains(r, reverse("primeiro_acesso"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_folha_de_primeiro_acesso_da_lista_de_contas(self):
        com = criar_usuario("Bia Torres Melo", Usuario.Papel.ESTAGIARIO, criado_por=self.ori, data_nascimento=date(2008, 5, 5))
        sem = criar_usuario("Davi Nunes Costa", Usuario.Papel.ESTAGIARIO, criado_por=self.ori)
        self.entrar(self.ori)
        lista = self.client.get(reverse("usuarios"), {"situacao": "pendentes"})
        self.assertContains(lista, "Davi Nunes Costa")
        self.assertNotContains(lista, self.aluno.nome_completo)  # já ativou
        r = self.client.post(reverse("codigos_lote"), {"papel": "ESTAGIARIO", "q": ""})
        com.refresh_from_db()
        sem.refresh_from_db()
        self.assertEqual(com.codigo_acesso, "")
        self.assertNotEqual(sem.codigo_acesso, "")
        self.assertContains(r, "nome completo + data de nascimento")
        self.assertEqual(r.content.decode().count('class="codigo-acesso"'), 1)

    def test_importacao_completa_nascimento_de_quem_ja_tem_estagio(self):
        self.ori.is_superuser = True
        self.ori.save()
        self.entrar(self.ori)
        csv_ = ("estagiario_nome;estagiario_nascimento;curso;data_inicio;concedente_nome;supervisor_nome\n"
                f"{self.aluno.nome_completo.upper()};03/11/2008;Informática;02/11/2026;Empresa X;Sérgio Supervisor\n")
        arquivo = SimpleUploadedFile("t.csv", csv_.encode(), "text/csv")
        r = self.client.post(reverse("importar_csv"), {
            "etapa": "previa", "arquivo": arquivo, "orientador": self.ori.pk, "dias": ["0"], "horas_por_dia": "4",
            "carga_cursos_novos": "300"})
        self.assertContains(r, "data de nascimento")
        self.client.post(reverse("importar_csv"), {"etapa": "confirmar"})
        self.aluno.refresh_from_db()
        self.assertEqual(self.aluno.data_nascimento, date(2008, 11, 3))
        self.assertEqual(self.aluno.estagios.count(), 1)

    def test_cadastro_em_lote_aceita_nascimento_e_matricula(self):
        self.entrar(self.ori)
        self.client.post(reverse("criar_estagiarios"), {
            "nomes": "Caio Mendes Rocha; 2024001; 15/03/2008", "turma": self.turma.pk, "local": self.local.pk,
            "supervisor": self.sup.pk, "data_inicio": "2026-11-16", "dias": ["0"], "horas_por_dia": "4"})
        caio = Usuario.objects.get(nome_completo="Caio Mendes Rocha")
        self.assertEqual((caio.matricula, caio.data_nascimento), ("2024001", date(2008, 3, 15)))

    def test_legenda_mostra_feriado_listrado(self):
        self.entrar(self.aluno)
        self.assertContains(self.client.get(self.est.get_absolute_url()), 'class="chave-sem-estagio"')


class PresencasNaImportacaoTests(Base):
    def test_dias_ja_cumpridos_entram_como_presenca_confirmada(self):
        from .models import DiaSemEstagio, Registro

        self.ori.is_superuser = True
        self.ori.save()
        DiaSemEstagio.objects.create(data=date(2026, 11, 2), descricao="Finados", orientador=self.ori,
                                     abrangencia=DiaSemEstagio.Abrangencia.TODOS)
        self.entrar(self.ori)
        csv_ = ("estagiario_nome;curso;curso_carga_horaria;data_inicio;horas_anteriores;presencas_desde;dias;"
                "concedente_nome;supervisor_nome\n"
                "Lara Nunes Viana;Técnico em Finanças;250;24/08/2026;96;02/11/2026;seg,ter,qua;Empresa X;Sérgio Supervisor\n")
        dados = {"etapa": "previa", "arquivo": SimpleUploadedFile("f.csv", csv_.encode(), "text/csv"),
                 "orientador": self.ori.pk, "dias": ["0", "1", "2", "3", "4"], "horas_por_dia": "5",
                 "acompanhamento_desde": "2026-11-11", "carga_cursos_novos": "300"}
        r = self.client.post(reverse("importar_csv"), dados)
        # hoje (mock) é qua 11/11: 02/11 é feriado; ter 03, qua 04, seg 09, ter 10 = 4 dias até ontem
        self.assertEqual(r.context["resultado"].presencas, 4)
        self.client.post(reverse("importar_csv"), {"etapa": "confirmar"})
        est = Estagio.objects.get(estagiario__nome_completo="Lara Nunes Viana")
        self.assertEqual(est.curso.carga_horaria, 250)
        self.assertEqual(est.acompanhamento_desde, date(2026, 11, 2))
        regs = est.registros.order_by("data")
        self.assertEqual([r.data.day for r in regs], [3, 4, 9, 10])
        self.assertTrue(all(r.confirmacao == Registro.Confirmacao.CONFIRMADA and r.horas == 5 for r in regs))
        self.assertEqual(resumo_horas(est)["cumpridas"], 96 + 20)

    def test_presencas_desde_nao_pode_ser_futuro_nem_antes_do_inicio(self):
        from .importacao import Opcoes, importar

        base = {"estagiario_nome": "Rui Prado Lima", "curso": "Informática", "concedente_nome": "Empresa X",
                "supervisor_nome": "Sérgio Supervisor", "data_inicio": "02/11/2026"}
        for desde in ("11/11/2026", "01/11/2026"):
            r = importar([(2, {**base, "presencas_desde": desde})], Opcoes(orientador=self.ori, dias=[0], horas_por_dia=Decimal(4)),
                         self.ori)
            self.assertIn("presencas_desde", r.erros[0][1])


class ContasAntigasTests(Base):
    def test_senha_antiga_nao_abre_mesmo_se_a_senha_padrao_mudar(self):
        antigo = criar_usuario("Conta Antiga Lima", Usuario.Papel.SUPERVISOR, concedente=self.local)
        antigo.set_password("estagio123")  # resumo guardado quando a conta foi criada
        antigo.save()
        with self.settings(SENHA_PADRAO="outra-senha-nova"):
            self.assertFalse(self.client.login(username=antigo.username, password="estagio123"))
        self.assertFalse(self.client.login(username=antigo.username, password="estagio123"))
        # ativada (senha própria): entra normalmente
        Usuario.objects.filter(pk=antigo.pk).update(deve_trocar_senha=False)
        self.assertTrue(self.client.login(username=antigo.username, password="estagio123"))

    def test_admin_criado_pelo_terminal_entra(self):
        adm = Usuario.objects.create_superuser("admin.terminal", "", "Senha#Forte77")
        self.assertTrue(adm.deve_trocar_senha)
        self.assertTrue(self.client.login(username="admin.terminal", password="Senha#Forte77"))

    def test_folha_com_codigo_nao_fica_em_cache(self):
        novo = criar_usuario("Nina Prado Leal", Usuario.Papel.SUPERVISOR, concedente=self.local, criado_por=self.ori)
        self.entrar(self.ori)
        r = self.client.post(reverse("redefinir_senha", args=[novo.pk]))
        self.assertIn("no-store", r["Cache-Control"])


class PermissoesDeAcessoTests(Base):
    def test_quem_pode_gerar_codigo(self):
        outro_ori = _ativo(criar_usuario("Otto Orientador", Usuario.Papel.ORIENTADOR))
        coord = _ativo(criar_usuario("Cora Coordenadora", Usuario.Papel.COORDENADOR))
        for u in (self.aluno, self.sup):
            self.client.force_login(u)
            r = self.client.post(reverse("codigos_lote"), {})
            self.assertEqual(r.status_code, 403, (u, r.get("Location")))
        for u, alvo, esperado in [
            (outro_ori, self.aluno, 403), (outro_ori, self.sup, 403), (outro_ori, self.ori, 403),
            (coord, self.ori, 403), (self.aluno, self.sup, 403), (self.sup, self.aluno, 403), (self.ori, self.sup, 200),
        ]:
            self.client.force_login(u)
            r = self.client.post(reverse("redefinir_senha", args=[alvo.pk]))
            self.assertEqual(r.status_code, esperado, (u, alvo))
        self.client.force_login(outro_ori)
        r = self.client.post(reverse("codigos_lote"), {"papel": "", "q": ""}, follow=True)
        self.assertNotContains(r, "codigo-acesso")

    def test_csrf_e_sessao_do_primeiro_acesso(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        self.assertEqual(c.post(reverse("primeiro_acesso"), {"modo": "nascimento", "nome": "x", "nascimento": "01/01/2008"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("primeiro_acesso_senha")).status_code, 302)
        s = self.client.session
        s["primeiro_acesso"] = {"uid": self.aluno.pk, "ate": 9e12}  # conta já ativada: não serve
        s.save()
        self.assertEqual(self.client.get(reverse("primeiro_acesso_senha")).status_code, 302)

    def test_outro_orientador_nao_troca_supervisor_alheio(self):
        outro_ori = _ativo(criar_usuario("Otto Orientador", Usuario.Papel.ORIENTADOR))
        self.client.force_login(outro_ori)
        self.assertEqual(self.client.get(reverse("ativacao_usuario", args=[self.sup.pk])).status_code, 403)
        self.client.force_login(self.ori)
        self.assertEqual(self.client.get(reverse("ativacao_usuario", args=[self.sup.pk])).status_code, 200)


class NivelDoDiaTests(Base):
    def _reg(self, dia, confirmacao="PENDENTE", **horarios):
        from datetime import time as t
        from .models import Registro

        campos = {k: t(*v) for k, v in horarios.items()}
        return Registro.objects.create(estagio=self.est, data=dia, situacao="PRESENTE", horas=4, confirmacao=confirmacao,
                                       **campos)

    def test_nivel_sobe_a_cada_horario(self):
        from .services import status_periodo

        Escala.objects.filter(estagio=self.est).update(saida_intervalo="11:00", volta_intervalo="13:00")
        self._reg(date(2026, 11, 2), hora_chegada=(7,))
        self._reg(date(2026, 11, 3), hora_chegada=(7,), saida_intervalo=(11,))
        self._reg(date(2026, 11, 9), hora_chegada=(7,), saida_intervalo=(11,), volta_intervalo=(13,))
        self._reg(date(2026, 11, 10), hora_chegada=(7,), saida_intervalo=(11,), volta_intervalo=(13,), hora_saida=(17,))
        self._reg(date(2026, 10, 27))  # só as horas, sem horário: conta como completo
        dias = {d.data: d for d in status_periodo(self.est, date(2026, 10, 27), date(2026, 11, 10))}
        self.assertEqual([dias[date(2026, 11, n)].nivel for n in (2, 3, 9, 10)], [25, 50, 75, 100])
        self.assertEqual(dias[date(2026, 11, 3)].horarios, (2, 4))
        self.assertEqual(dias[date(2026, 10, 27)].nivel, 100)

    def test_sem_intervalo_sao_dois_horarios(self):
        from .services import status_periodo

        self._reg(date(2026, 11, 2), hora_chegada=(7,))
        self.assertEqual(status_periodo(self.est, date(2026, 11, 2), date(2026, 11, 2))[0].nivel, 50)

    def test_calendario_mostra_agua_e_grama(self):
        self._reg(date(2026, 11, 2), hora_chegada=(7,))
        self._reg(date(2026, 11, 3), confirmacao="CONFIRMADA", hora_chegada=(7,))
        self.entrar(self.aluno)
        r = self.client.get(self.est.get_absolute_url() + "?aba=visao&mes=2026-11")
        self.assertContains(r, 'class="nivel agua"')
        self.assertContains(r, 'class="nivel grama"')
        self.assertContains(r, "--nivel:50%")
        self.assertContains(r, "1 de 2 horários (50%)")


@override_settings(EMAIL_ATIVO=True)
class EmailDeContaTests(Base):
    def setUp(self):
        super().setUp()
        from django.core import mail

        self.mail = mail

    def _link(self, msg):
        import re

        return re.search(r"https?://[^\s]+", msg.body).group(0).replace("http://testserver", "")

    def _confirmar(self, user, email="maria@example.com"):
        Usuario.objects.filter(pk=user.pk).update(email=email, email_confirmado_em=timezone.now())

    def test_cadastrar_e_confirmar_email(self):
        self.entrar(self.aluno)
        self.assertContains(self.client.get(reverse("estagio_detalhe", args=[self.est.pk])), "Cadastre seu e-mail")
        self.client.post(reverse("perfil"), {"email": "maria@example.com", "avisos_email": "on", "novidades_popup": "on"})
        self.assertEqual(len(self.mail.outbox), 1)
        self.assertIn("Confirme seu e-mail", self.mail.outbox[0].subject)
        link = self._link(self.mail.outbox[0])
        self.client.get(link)
        self.aluno.refresh_from_db()
        self.assertIsNotNone(self.aluno.email_confirmado_em)
        self.assertIn("E-mail cadastrado", self.mail.outbox[1].subject)
        self.assertNotContains(self.client.get(reverse("estagio_detalhe", args=[self.est.pk])), "Confirme seu e-mail")
        # trocar o e-mail (por ela ou pela gestão) pede confirmação de novo; o link antigo não vale para o novo
        self.aluno.email = "outro@example.com"
        self.aluno.save()
        self.assertIsNone(self.aluno.email_confirmado_em)
        self.client.get(link)
        self.aluno.refresh_from_db()
        self.assertIsNone(self.aluno.email_confirmado_em)

    def test_esqueci_minha_senha(self):
        self._confirmar(self.aluno)
        r = self.client.post(reverse("esqueci_senha"), {"identificador": "MARIA@example.com"}, REMOTE_ADDR="10.1.1.1")
        self.assertContains(r, "Se houver uma conta")
        self.assertEqual(len(self.mail.outbox), 1)
        link = self._link(self.mail.outbox[0])
        r = self.client.get(link)  # o Django troca o código da URL pela sessão
        r = self.client.post(r["Location"], {"new_password1": "Nova#Senha2026", "new_password2": "Nova#Senha2026"})
        self.assertRedirects(r, reverse("login"), fetch_redirect_response=False)
        self.assertTrue(self.client.login(username="maria.souza", password="Nova#Senha2026"))
        self.assertIn("Sua senha foi alterada", self.mail.outbox[-1].subject)
        self.client.logout()
        self.assertEqual(self.client.get(link).status_code, 200)  # link usado não vale mais
        self.assertContains(self.client.get(link, follow=True), "não vale mais")

    def test_esqueci_sem_email_confirmado_nao_envia_nem_revela(self):
        Usuario.objects.filter(pk=self.aluno.pk).update(email="maria@example.com")
        r1 = self.client.post(reverse("esqueci_senha"), {"identificador": "maria.souza"}, REMOTE_ADDR="10.1.1.2")
        r2 = self.client.post(reverse("esqueci_senha"), {"identificador": "nao.existe"}, REMOTE_ADDR="10.1.1.2")
        self.assertEqual(len(self.mail.outbox), 0)
        self.assertContains(r1, "Se houver uma conta")
        self.assertContains(r2, "Se houver uma conta")

    def test_limite_de_pedidos_de_senha(self):
        self._confirmar(self.aluno)
        for i in range(5):
            self.client.post(reverse("esqueci_senha"), {"identificador": "maria.souza"}, REMOTE_ADDR=f"10.2.0.{i}")
        self.assertEqual(len(self.mail.outbox), 3)

    def test_avisos_de_tentativas_e_bloqueio(self):
        self.aluno.set_password("Senha#Certa9")
        self.aluno.save()
        self._confirmar(self.aluno)
        for i in range(5):
            r = self.client.post(reverse("login"), {"username": "maria.souza", "password": f"x{i}"}, REMOTE_ADDR="10.3.0.1")
        assuntos = [m.subject for m in self.mail.outbox]
        self.assertEqual(len(assuntos), 2, assuntos)
        self.assertIn("Tentativas de entrar", assuntos[0])
        self.assertIn("bloqueado", assuntos[1])
        r = self.client.post(reverse("login"), {"username": "maria.souza", "password": "x"}, REMOTE_ADDR="10.3.0.1")
        self.assertContains(r, reverse("pedir_ajuda") + "?usuario=maria.souza")
        # criar senha nova pelo e-mail desbloqueia
        self.client.post(reverse("esqueci_senha"), {"identificador": "maria.souza"}, REMOTE_ADDR="10.3.0.1")
        r = self.client.get(self._link(self.mail.outbox[-1]))
        self.client.post(r["Location"], {"new_password1": "Nova#Senha2026", "new_password2": "Nova#Senha2026"})
        r = self.client.post(reverse("login"), {"username": "maria.souza", "password": "Nova#Senha2026"}, REMOTE_ADDR="10.3.0.1")
        self.assertEqual(r.status_code, 302)

    def test_pedido_de_ajuda_ao_administrador(self):
        from .models import Notificacao

        adm = _ativo(criar_usuario("Ana Admin Lima", Usuario.Papel.ORIENTADOR, email="adm@example.com"))
        Usuario.objects.filter(pk=adm.pk).update(is_superuser=True)
        dados = {"usuario": "maria.souza\nBcc: x@y.z", "nome": "Maria Souza", "contato": "(85) 9999-0000",
                 "mensagem": "Fui bloqueada."}
        r = self.client.post(reverse("pedir_ajuda"), dados, REMOTE_ADDR="10.4.0.1")
        self.assertContains(r, "Pedido enviado")
        self.assertTrue(Notificacao.objects.filter(usuario=adm, texto__contains="Maria Souza").exists())
        self.assertEqual(self.mail.outbox[0].to, ["adm@example.com"])
        self.assertNotIn("\n", self.mail.outbox[0].subject)
        for _ in range(2):
            self.client.post(reverse("pedir_ajuda"), dados, REMOTE_ADDR="10.4.0.1")
        self.assertContains(self.client.post(reverse("pedir_ajuda"), dados, REMOTE_ADDR="10.4.0.1"), "Aguarde a resposta")
        self.client.post(reverse("pedir_ajuda"), {**dados, "site": "spam"}, REMOTE_ADDR="10.4.0.9")  # robô
        self.assertEqual(Notificacao.objects.filter(usuario=adm).count(), 3)

    def test_administrador_edita_os_textos(self):
        from .models import ModeloEmail

        self.entrar(self.ori)
        self.assertEqual(self.client.get(reverse("modelos_email")).status_code, 403)
        Usuario.objects.filter(pk=self.ori.pk).update(is_superuser=True)
        self.assertContains(self.client.get(reverse("modelos_email")), "Redefinição de senha")
        url = reverse("modelo_email", args=["REDEFINIR_SENHA"])
        r = self.client.post(url, {"assunto": "Senha {sistema}", "corpo": "Oi {nome} {xyz}", "ativo": "on"})
        self.assertContains(r, "{xyz}")
        r = self.client.post(url, {"assunto": "Senha {sistema}", "corpo": "Oi {nome}", "ativo": "on"})
        self.assertContains(r, "{link}")
        r = self.client.post(url, {"assunto": "Senha nova", "corpo": "Oi {nome}, use {link}", "ativo": "on", "acao": "previa"})
        self.assertContains(r, "exemplo-de-link")
        self.client.post(url, {"assunto": "Senha nova", "corpo": "Oi {nome}, use {link}", "ativo": "on"})
        self.assertTrue(ModeloEmail.objects.filter(tipo="REDEFINIR_SENHA").exists())
        self._confirmar(self.aluno)
        self.client.logout()
        self.client.post(reverse("esqueci_senha"), {"identificador": "maria.souza"}, REMOTE_ADDR="10.5.0.1")
        self.assertEqual(self.mail.outbox[-1].subject, "Senha nova")
        self.assertTrue(self.mail.outbox[-1].body.startswith("Oi Maria, use http"))
        ModeloEmail.objects.filter(tipo="REDEFINIR_SENHA").update(ativo=False)
        n = len(self.mail.outbox)
        self.client.post(reverse("esqueci_senha"), {"identificador": "maria.souza"}, REMOTE_ADDR="10.5.0.2")
        self.assertEqual(len(self.mail.outbox), n)


class CargaEmLoteTests(Base):
    def test_lote_da_o_mesmo_resultado_que_um_por_um(self):
        from datetime import time as t

        from .models import DiaPlanejado, DiaSemEstagio, Registro
        from .services import preparar_lote, resumo_horas, status_periodo

        self.local.cidade = "Fortaleza"
        self.local.save()
        DiaSemEstagio.objects.create(data=date(2026, 11, 3), descricao="Feriado municipal", orientador=self.ori,
                                     abrangencia=DiaSemEstagio.Abrangencia.MUNICIPIO, municipio="Fortaleza")
        DiaSemEstagio.objects.create(data=date(2026, 11, 16), descricao="Evento da escola", orientador=self.ori,
                                     abrangencia=DiaSemEstagio.Abrangencia.ESCOLA, curso=self.curso)
        DiaSemEstagio.objects.create(data=date(2026, 11, 17), descricao="Recesso de outra escola", orientador=self.sup,
                                     abrangencia=DiaSemEstagio.Abrangencia.ESCOLA)
        Registro.objects.create(estagio=self.est, data=date(2026, 11, 2), situacao="PRESENTE", horas=4,
                                confirmacao="CONFIRMADA", hora_chegada=t(7))
        Registro.objects.create(estagio=self.est, data=date(2026, 11, 9), situacao="FALTA")
        Registro.objects.create(estagio=self.est, data=date(2026, 11, 10), situacao="PRESENTE", horas=4)
        DiaPlanejado.objects.create(estagio=self.est, data=date(2026, 11, 20), horas=3)
        inicio, fim = date(2026, 11, 1), date(2026, 12, 31)
        sozinho = Estagio.objects.get(pk=self.est.pk)
        esperado = ([(s.data, s.codigo, s.motivo_sem_estagio) for s in status_periodo(sozinho, inicio, fim)], resumo_horas(sozinho))
        em_lote = preparar_lote(Estagio.objects.filter(pk=self.est.pk).select_related("curso", "local"), inicio)[0]
        with self.assertNumQueries(0):
            obtido = ([(s.data, s.codigo, s.motivo_sem_estagio) for s in status_periodo(em_lote, inicio, fim)], resumo_horas(em_lote))
        self.assertEqual(obtido, esperado)

    def test_painel_nao_cresce_com_o_numero_de_estagiarios(self):
        self.entrar(self.ori)
        self.client.get(reverse("painel"))
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as antes:
            self.client.get(reverse("painel"))
        for i in range(8):
            aluno = _ativo(criar_usuario(f"Aluno Extra{i} Lima", Usuario.Papel.ESTAGIARIO))
            e = Estagio.objects.create(estagiario=aluno, orientador=self.ori, supervisor=self.sup, curso=self.curso,
                                       turma=self.turma, local=self.local, data_inicio=date(2026, 11, 2))
            Escala.objects.create(estagio=e, vigente_desde=date(2026, 11, 2), dias="0,1", horas_por_dia=4)
        with CaptureQueriesContext(connection) as depois:
            self.client.get(reverse("painel"))
        self.assertLessEqual(len(depois), len(antes) + 2)


class PainelAgendaTests(Base):
    def test_calendario_do_mes_no_painel(self):
        from django.utils import timezone as tz

        from .models import Agendamento, DiaSemEstagio

        DiaSemEstagio.objects.create(data=date(2026, 11, 20), descricao="Consciência Negra", orientador=self.ori,
                                     abrangencia=DiaSemEstagio.Abrangencia.TODOS)
        a = Agendamento.objects.create(tipo="VISITA", status="AGENDADO", orientador=self.ori, solicitante=self.ori,
                                       assunto="Visita à Empresa X", data_hora=tz.make_aware(datetime(2026, 11, 12, 9)))
        a.estagios.add(self.est)
        self.est.data_fim = date(2026, 11, 27)
        self.est.save()
        Usuario.objects.filter(pk=self.aluno.pk).update(data_nascimento=date(2008, 11, 25))
        self.entrar(self.ori)
        r = self.client.get(reverse("painel") + "?mes=2026-11&dia=2026-11-12")
        dias = r.context["dias_json"]
        self.assertEqual(dias["2026-11-20"]["feriados"], ["Consciência Negra"])
        self.assertEqual(dias["2026-11-12"]["eventos"][0]["hora"], "09:00")
        self.assertIn("Visita à Empresa X", dias["2026-11-12"]["eventos"][0]["texto"])
        self.assertIn("termo", {e["tipo"] for e in dias["2026-11-27"]["eventos"]})
        self.assertIn("Aniversário de Maria da Silva Souza (18 anos)", [e["texto"] for e in dias["2026-11-25"]["eventos"]])
        self.assertEqual(dias["2026-11-09"]["sem_registro"], 1)  # segunda passada, sem registro (hoje é qua 11/11)
        self.assertContains(r, "Agendar neste dia")
        self.assertContains(r, f'{reverse("novo_agendamento")}?data=2026-11-12')
        self.assertEqual(self.client.get(reverse("painel") + "?mes=abc").status_code, 200)

    def test_ficha_do_estagiario_e_preenchimento_do_agendamento(self):
        self.local.endereco, self.local.cidade = "Rua A", "Itapipoca"
        self.local.save()
        self.entrar(self.ori)
        r = self.client.get(reverse("ficha_estagio", args=[self.est.pk]))
        dados = r.json()
        self.assertEqual(dados["local_id"], self.local.pk)
        self.assertIn("2026-11-16", dados["dias"])  # segunda (escala seg e ter)
        self.assertNotIn("2026-11-18", dados["dias"])  # quarta: fora da escala
        self.assertIn("Abrir no mapa", dados["html"])
        self.assertIn("Sérgio Supervisor", dados["html"])
        r = self.client.get(reverse("novo_agendamento") + "?data=2026-11-16")
        self.assertEqual(r.context["form"].initial["data_hora"], datetime(2026, 11, 16, 8, 0))
        self.assertTemplateUsed(r, "core/agendamento_form.html")
        for u in (self.aluno, self.sup, _ativo(criar_usuario("Otto Orientador", Usuario.Papel.ORIENTADOR))):
            self.client.force_login(u)
            self.assertIn(self.client.get(reverse("ficha_estagio", args=[self.est.pk])).status_code, (403, 404))


class OpiniaoTests(Base):
    def test_botao_e_envio_de_opiniao(self):
        from .models import Notificacao, Sugestao

        adm = _ativo(criar_usuario("Ana Admin Lima", Usuario.Papel.ORIENTADOR))
        Usuario.objects.filter(pk=adm.pk).update(is_superuser=True)
        self.entrar(self.aluno)
        self.assertContains(self.client.get(self.est.get_absolute_url()), "Sua opinião")
        r = self.client.post(reverse("enviar_opiniao"), {"tipo": "SUGESTAO", "pagina": "/x/"}, HTTP_ACCEPT="application/json")
        self.assertEqual(r.status_code, 400)  # nem nota nem comentário
        r = self.client.post(reverse("enviar_opiniao"), {"nota": "5", "tipo": "ELOGIO", "pagina": self.est.get_absolute_url()},
                             HTTP_ACCEPT="application/json")
        self.assertEqual(r.json(), {"ok": True})
        s = Sugestao.objects.get()
        self.assertEqual((s.nota, s.usuario, s.pagina), (5, self.aluno, self.est.get_absolute_url()))
        self.assertFalse(Notificacao.objects.filter(usuario=adm).exists())  # elogio não incomoda o sino
        self.client.post(reverse("enviar_opiniao"), {"nota": "1", "tipo": "ERRO", "mensagem": "Travou", "pagina": "https://mal.example/"})
        self.assertTrue(Notificacao.objects.filter(usuario=adm, texto__contains="Travou").exists())
        self.assertEqual(Sugestao.objects.latest("pk").pagina, reverse("inicio"))  # volta só para o próprio site
        self.entrar(self.ori)
        self.assertNotContains(self.client.get(reverse("painel")), "data-abrir-opiniao")  # gestão não vê o botão
        self.assertEqual(self.client.get(reverse("opinioes")).status_code, 403)
        self.client.force_login(Usuario.objects.get(pk=adm.pk))
        r = self.client.get(reverse("opinioes"))
        self.assertContains(r, "Travou")
        self.assertEqual(r.context["media"], 3)
        self.client.post(reverse("marcar_opiniao", args=[s.pk]))
        s.refresh_from_db()
        self.assertTrue(s.resolvida)

    def test_botao_some_fora_do_periodo_de_testes(self):
        from .models import Configuracao

        c = Configuracao.atual()
        c.periodo_testes = False
        c.save()
        self.entrar(self.aluno)
        self.assertNotContains(self.client.get(self.est.get_absolute_url()), "data-abrir-opiniao")


# ---------------------------------------------------------------- termos, privacidade e dados pessoais


class TermosTests(Base):
    def test_paginas_publicas(self):
        self.assertContains(self.client.get(reverse("privacidade")), "LGPD")
        self.assertContains(self.client.get(reverse("termos")), "Termos de Uso")
        self.assertContains(self.client.get(reverse("login")), reverse("privacidade"))

    @override_settings(EXIGIR_ACEITE_TERMOS=True)
    def test_aceite_obrigatorio_uma_vez(self):
        from .models import RegistroAcao
        from .termos import VERSAO

        self.entrar(self.aluno)
        url = self.est.get_absolute_url()
        r = self.client.get(url)
        self.assertRedirects(r, f"{reverse('aceitar_termos')}?next={url}", fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("privacidade")).status_code, 200)  # dá para ler antes de aceitar
        self.assertContains(self.client.post(reverse("aceitar_termos") + f"?next={url}", {"next": url}), "marque")
        r = self.client.post(reverse("aceitar_termos"), {"aceito": "1", "next": url})
        self.assertRedirects(r, url, fetch_redirect_response=False)
        self.aluno.refresh_from_db()
        self.assertEqual(self.aluno.termos_versao, VERSAO)
        self.assertTrue(RegistroAcao.objects.filter(usuario=self.aluno, tipo="TERMOS").exists())
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_baixar_meus_dados(self):
        import json

        from .models import RegistroAcao

        Registro.objects.create(estagio=self.est, data=date(2026, 11, 9), situacao=Registro.Situacao.PRESENTE,
                                horas=4, diario="Configurei a rede")
        self.entrar(self.aluno)
        r = self.client.get(reverse("baixar_meus_dados"))
        self.assertIn("attachment", r["Content-Disposition"])
        dados = json.loads(r.content)
        self.assertEqual(dados["conta"]["nome_completo"], "Maria da Silva Souza")
        self.assertEqual(dados["estagios"][0]["registros"][0]["como_foi_o_dia"], "Configurei a rede")
        self.assertTrue(RegistroAcao.objects.filter(usuario=self.aluno, tipo="DADOS").exists())


# ---------------------------------------------------------------- verificação em duas etapas


class DoisFatoresTests(Base):
    SENHA = "Senha#Forte9"

    def setUp(self):
        super().setUp()
        self.ori.set_password(self.SENHA)
        self.ori.save()

    def _codigo(self, segredo, deslocamento=0):
        import time

        from . import dois_fatores as df

        return df._codigo(segredo, int(time.time() // 30) + deslocamento)

    def _ligar(self):
        from . import dois_fatores as df

        segredo = df.novo_segredo()
        import time

        codigos = df.ativar(self.ori, segredo, int(time.time() // 30))
        return segredo, codigos

    def _login(self, **extra):
        return self.client.post(reverse("login"), {"username": self.ori.username, "password": self.SENHA}, **extra)

    def test_ligar_pela_tela(self):
        self.entrar(self.ori)
        r = self.client.get(reverse("dois_fatores"))
        self.assertContains(r, "<svg")
        segredo = self.client.session["dois_fatores_novo"]
        self.assertContains(self.client.post(reverse("dois_fatores"), {"acao": "ativar", "codigo": "000000"}), "incorreto")
        r = self.client.post(reverse("dois_fatores"), {"acao": "ativar", "codigo": self._codigo(segredo)})
        self.assertContains(r, "códigos de recuperação")
        self.ori.refresh_from_db()
        self.assertTrue(self.ori.dois_fatores_ativo)
        self.assertEqual(len(self.ori.codigos_recuperacao), 8)

    def test_entrar_pede_o_codigo(self):
        import time

        from . import dois_fatores as df

        T = float(int(time.time()) // 30 * 30)  # início do passo atual: o teste não depende do segundo em que roda
        segredo = df.novo_segredo()
        df.ativar(self.ori, segredo, int(T // 30))
        r = self._login()
        self.assertRedirects(r, reverse("verificar_dois_fatores"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        with mock.patch("core.dois_fatores.time.time", return_value=T + 5):
            self.assertContains(self.client.post(reverse("verificar_dois_fatores"), {"codigo": "123456"}), "incorreto")
            # o código do passo em que a verificação foi ligada já foi usado
            self.assertContains(self.client.post(reverse("verificar_dois_fatores"),
                                                 {"codigo": df._codigo(segredo, int(T // 30))}), "incorreto")
        with mock.patch("core.dois_fatores.time.time", return_value=T + 35):
            r = self.client.post(reverse("verificar_dois_fatores"), {"codigo": df._codigo(segredo, int(T // 30) + 1)})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.ori.pk)

    def test_codigo_de_recuperacao_vale_uma_vez(self):
        _, codigos = self._ligar()
        self._login()
        r = self.client.post(reverse("verificar_dois_fatores"), {"codigo": codigos[0].lower()})
        self.assertEqual(r.status_code, 302)
        self.client.logout()
        self._login()
        self.assertContains(self.client.post(reverse("verificar_dois_fatores"), {"codigo": codigos[0]}), "incorreto")
        self.ori.refresh_from_db()
        self.assertEqual(len(self.ori.codigos_recuperacao), 7)

    def test_aparelho_confiavel_e_bloqueio(self):
        from . import dois_fatores as df

        _, codigos = self._ligar()
        self._login()
        r = self.client.post(reverse("verificar_dois_fatores"), {"codigo": codigos[0], "confiar": "1"})
        self.assertIn(df.COOKIE_APARELHO, r.cookies)
        biscoito = r.cookies[df.COOKIE_APARELHO].value
        self.client.logout()
        self.client.cookies[df.COOKIE_APARELHO] = biscoito
        self.assertRedirects(self._login(), reverse("inicio"), fetch_redirect_response=False)  # não pede de novo
        self.client.logout()
        self._login()
        for _ in range(df.LIMITE_FALHAS):
            self.client.post(reverse("verificar_dois_fatores"), {"codigo": "000000"})
        r = self.client.post(reverse("verificar_dois_fatores"), {"codigo": codigos[1]})
        self.assertRedirects(r, reverse("login"), fetch_redirect_response=False)  # bloqueado: nem o certo vale
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_escola_exige_da_gestao(self):
        c = Configuracao.atual()
        c.exigir_dois_fatores = True
        c.save()
        self.entrar(self.ori)
        self.assertRedirects(self.client.get(reverse("estagios_lista")),
                             f"{reverse('dois_fatores')}?next={reverse('estagios_lista')}", fetch_redirect_response=False)
        self.entrar(self.aluno)  # estagiário não precisa
        self.assertEqual(self.client.get(self.est.get_absolute_url()).status_code, 200)

    def test_novo_primeiro_acesso_zera_a_verificacao(self):
        from .seguranca import liberar_primeiro_acesso

        self._ligar()
        liberar_primeiro_acesso(self.ori)
        self.ori.refresh_from_db()
        self.assertFalse(self.ori.dois_fatores_ativo)
        self.assertEqual(self.ori.codigos_recuperacao, [])


# ---------------------------------------------------------------- avisos de erro e registro de ações


class AlertaErroTests(Base):
    def setUp(self):
        super().setUp()
        self.admin = _ativo(Usuario.objects.create_superuser("admin", "admin@example.com", "Senha#Admin9",
                                                             nome_completo="Ana Admin"))

    def _erro(self, caminho="/painel/"):
        import logging

        from django.test import RequestFactory

        try:
            1 / 0
        except ZeroDivisionError:
            logging.getLogger("django.request").error("Internal Server Error: %s", caminho, exc_info=True,
                                                      extra={"request": RequestFactory().get(caminho)})

    @override_settings(EMAIL_ATIVO=True)
    def test_erro_registra_e_avisa_sem_repetir(self):
        from django.core import mail

        from .models import ErroSistema

        self._erro()
        self._erro()
        erro = ErroSistema.objects.get()
        self.assertEqual((erro.tipo, erro.ocorrencias, erro.caminho), ("ZeroDivisionError", 2, "/painel/"))
        self.assertIn("core/tests.py", erro.origem)
        self.assertEqual(Notificacao.objects.filter(usuario=self.admin, link=reverse("erros_sistema")).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("ZeroDivisionError", mail.outbox[0].subject)

    def test_tela_so_do_administrador(self):
        from .models import ErroSistema

        self._erro()
        self.entrar(self.ori)
        self.assertEqual(self.client.get(reverse("erros_sistema")).status_code, 403)
        self.entrar(self.admin)
        self.assertContains(self.client.get(reverse("erros_sistema")), "ZeroDivisionError")
        erro = ErroSistema.objects.get()
        self.client.post(reverse("marcar_erro", args=[erro.pk]), {"ver": "abertos"})
        erro.refresh_from_db()
        self.assertTrue(erro.resolvido)
        self._erro()  # voltou a acontecer: reabre
        erro.refresh_from_db()
        self.assertFalse(erro.resolvido)


class AuditoriaTests(Base):
    def test_entrada_e_senha_errada(self):
        from .models import RegistroAcao

        self.ori.set_password("Senha#Forte9")
        self.ori.save()
        self.client.post(reverse("login"), {"username": self.ori.username, "password": "errada"})
        self.client.post(reverse("login"), {"username": "Senha#Forte9", "password": "x"})  # senha no campo errado
        self.client.post(reverse("login"), {"username": self.ori.username, "password": "Senha#Forte9"},
                         HTTP_USER_AGENT="Mozilla/5.0 (Linux; Android 14) Chrome/130.0 Mobile Safari/537.36")
        tipos = list(RegistroAcao.objects.order_by("pk").values_list("tipo", "usuario"))
        self.assertEqual(tipos, [("LOGIN_FALHOU", self.ori.pk), ("LOGIN", self.ori.pk)])
        self.assertEqual(RegistroAcao.objects.get(tipo="LOGIN").aparelho, "Chrome no Android")
        self.assertFalse(RegistroAcao.objects.filter(quem__contains="Senha#").exists())

    def test_acoes_da_gestao_e_downloads(self):
        from .models import RegistroAcao

        self.entrar(self.ori)
        self.client.post(reverse("redefinir_senha", args=[self.sup.pk]))
        a = RegistroAcao.objects.get(tipo="GESTAO")
        self.assertEqual((a.descricao, a.alvo, a.usuario), ("Gerou código de primeiro acesso", str(self.sup), self.ori))
        self.client.get(reverse("exportar_estagios"))
        self.assertTrue(RegistroAcao.objects.filter(tipo="DADOS", descricao__contains="planilha").exists())
        self.client.post(reverse("trocar_tema"), {"tema": "ESCURO"})  # preferência não entra
        self.assertEqual(RegistroAcao.objects.filter(tipo="GESTAO").count(), 1)

    def test_tela_so_do_administrador(self):
        admin = _ativo(Usuario.objects.create_superuser("admin", "a@example.com", "Senha#Admin9", nome_completo="Ana Admin"))
        self.entrar(self.ori)
        self.assertEqual(self.client.get(reverse("registro_acoes")).status_code, 403)
        self.entrar(admin)
        self.client.post(reverse("redefinir_senha", args=[self.sup.pk]))
        self.assertContains(self.client.get(reverse("registro_acoes") + "?tipo=GESTAO&q=Sérgio"), "Gerou código")


# ---------------------------------------------------------------- lembrete de fim de expediente


class LembreteExpedienteTests(Base):
    def setUp(self):
        super().setUp()
        from datetime import time as hora

        Escala.objects.create(estagio=self.est, vigente_desde=date(2026, 11, 9), dias="0,1,2", horas_por_dia=4,
                              horario_entrada=hora(8), horario_saida=hora(12))

    def _rodar(self, h, m=0):
        from .lembretes import disparar_lembretes_expediente

        return disparar_lembretes_expediente(timezone.make_aware(datetime(2026, 11, 11, h, m)))

    @override_settings(EMAIL_ATIVO=True)
    def test_lembra_uma_vez_depois_da_saida(self):
        from django.core import mail

        self.aluno.email = "maria@example.com"
        self.aluno.save()
        self.assertEqual(self._rodar(12, 30), 0)  # ainda dentro da hora de tolerância
        self.assertEqual(self._rodar(13, 5), 1)
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto__contains="ainda não marcou").exists())
        self.assertEqual(self._rodar(14), 0)  # um por dia
        self.assertEqual(len(mail.outbox), 0)  # só sino e celular

    def test_falta_a_saida(self):
        from datetime import time as hora

        Registro.objects.create(estagio=self.est, data=QUARTA, situacao=Registro.Situacao.PRESENTE, horas=4,
                                hora_chegada=hora(8))
        self.assertEqual(self._rodar(13, 5), 1)
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto__contains="saída").exists())

    def test_nao_lembra_quando_nao_precisa(self):
        from datetime import time as hora

        DiaSemEstagio.objects.create(data=QUARTA, descricao="Feriado", abrangencia=DiaSemEstagio.Abrangencia.TODOS,
                                     orientador=self.ori)
        self.assertEqual(self._rodar(13, 5), 0)
        DiaSemEstagio.objects.all().delete()
        self.aluno.lembrete_expediente = False
        self.aluno.save()
        self.assertEqual(self._rodar(13, 5), 0)
        self.aluno.lembrete_expediente = True
        self.aluno.save()
        Registro.objects.create(estagio=self.est, data=QUARTA, situacao=Registro.Situacao.PRESENTE, horas=4,
                                hora_chegada=hora(8), hora_saida=hora(12))
        self.assertEqual(self._rodar(13, 5), 0)
        self.assertEqual(self._rodar(22, 30), 0)


# ---------------------------------------------------------------- link “Confirmar todas” e resumo do mês


@override_settings(EMAIL_ATIVO=True, SITE_URL="https://estagio.example")
class ConfirmacaoLinkTests(Base):
    def setUp(self):
        super().setUp()
        self.sup.email = "sergio@example.com"
        self.sup.telefone = "(85) 98888-7777"
        self.sup.save()
        self.r1 = Registro.objects.create(estagio=self.est, data=date(2026, 11, 9), situacao=Registro.Situacao.PRESENTE,
                                          horas=4)
        self.r2 = Registro.objects.create(estagio=self.est, data=date(2026, 11, 10), situacao=Registro.Situacao.PRESENTE,
                                          horas=4)

    def _semanal(self, quando):
        from .confirmacao import disparar_confirmacoes

        return disparar_confirmacoes(timezone.make_aware(quando))

    def _codigo_do_email(self):
        import re

        from django.core import mail

        return re.search(r"/s/([\w-]+)/", mail.outbox[-1].body).group(1)

    def test_email_semanal_uma_vez_no_dia_escolhido(self):
        from django.core import mail

        c = Configuracao.atual()
        c.dia_confirmacao = 2  # quarta
        c.save()
        self.assertEqual(self._semanal(datetime(2026, 11, 11, 13)), 0)  # antes das 14h
        self.assertEqual(self._semanal(datetime(2026, 11, 11, 15)), 1)
        self.assertEqual(self._semanal(datetime(2026, 11, 11, 16)), 0)
        self.assertIn("2 presença(s)", mail.outbox[0].subject)
        self.assertIn("Maria da Silva Souza", mail.outbox[0].body)

    def test_nao_dispara_atrasado_no_dia_da_atualizacao(self):
        self.assertEqual(self._semanal(datetime(2026, 11, 24, 15)), 0)  # terça; o dia é sexta

    def test_abrir_nao_confirma_e_o_botao_confirma_uma_vez(self):
        from .confirmacao import enviar_email

        enviar_email(self.sup)
        url = reverse("confirmar_por_link", args=[self._codigo_do_email()])
        r = self.client.get(url)
        self.assertContains(r, "Maria da Silva Souza")
        self.assertEqual(r["Referrer-Policy"], "no-referrer")
        self.r1.refresh_from_db()
        self.assertEqual(self.r1.confirmacao, Registro.Confirmacao.PENDENTE)
        self.assertContains(self.client.post(url), "2 presenças confirmadas")
        self.r1.refresh_from_db()
        self.assertEqual((self.r1.confirmacao, self.r1.confirmado_por), (Registro.Confirmacao.CONFIRMADA, self.sup))
        self.assertTrue(HistoricoRegistro.objects.filter(acao=HistoricoRegistro.Acao.LINK).exists())
        self.assertContains(self.client.post(url), "já foi usado")
        self.assertContains(self.client.get(reverse("confirmar_por_link", args=["inventado"])), "Link inválido")

    def test_link_vencido_ou_de_outro_supervisor(self):
        from .confirmacao import enviar_email
        from .models import LinkConfirmacao

        enviar_email(self.sup)
        url = reverse("confirmar_por_link", args=[self._codigo_do_email()])
        outro = _ativo(criar_usuario("Outro Supervisor", Usuario.Papel.SUPERVISOR, concedente=self.local))
        Estagio.objects.filter(pk=self.est.pk).update(supervisor=outro)
        self.assertContains(self.client.get(url), "Nada para confirmar")
        LinkConfirmacao.objects.update(expira_em=timezone.now() - timedelta(minutes=1))
        self.assertContains(self.client.get(url), "venceu")

    def test_escola_pede_pelo_whatsapp(self):
        from .models import LinkConfirmacao

        self.entrar(self.ori)
        self.assertContains(self.client.get(reverse("painel")), "Supervisores com presenças para confirmar")
        r = self.client.post(reverse("pedir_confirmacao", args=[self.sup.pk]), {"canal": "whatsapp"})
        self.assertTrue(r.url.startswith("https://wa.me/5585988887777?text="))
        self.assertEqual(LinkConfirmacao.objects.get().canal, "WHATSAPP")
        outra = _ativo(criar_usuario("Olga Outra", Usuario.Papel.ORIENTADOR))
        self.entrar(outra)
        self.assertEqual(self.client.post(reverse("pedir_confirmacao", args=[self.sup.pk]), {"canal": "email"}).status_code, 403)

    def test_resumo_do_mes(self):
        from django.core import mail

        from .confirmacao import disparar_resumo_mensal

        self.assertEqual(disparar_resumo_mensal(timezone.make_aware(datetime(2026, 11, 24, 9))), 0)
        self.assertEqual(disparar_resumo_mensal(timezone.make_aware(datetime(2026, 12, 1, 6))), 0)  # antes das 7h
        self.assertEqual(disparar_resumo_mensal(timezone.make_aware(datetime(2026, 12, 1, 8))), 1)
        self.assertEqual(disparar_resumo_mensal(timezone.make_aware(datetime(2026, 12, 2, 8))), 0)
        corpo = mail.outbox[-1].body
        self.assertIn("novembro de 2026", mail.outbox[-1].subject)
        self.assertIn("Maria da Silva Souza: 2 presença(s), 8h no mês", corpo)
        self.assertIn("2 para você confirmar", corpo)


# ---------------------------------------------------------------- equipe da concedente e substituições


class EquipeTests(Base):
    def setUp(self):
        super().setUp()
        self.resp = _ativo(criar_usuario("Rita Responsável", Usuario.Papel.SUPERVISOR, concedente=self.local))
        self.resp.concedentes_geridas.add(self.local)
        self.colega = _ativo(criar_usuario("Carlos Colega", Usuario.Papel.SUPERVISOR, concedente=self.local))
        self.reg = Registro.objects.create(estagio=self.est, data=date(2026, 11, 10), situacao=Registro.Situacao.PRESENTE,
                                           horas=4)
        self.url = reverse("equipe_concedente", args=[self.local.pk])

    def _substituir(self, inicio=QUARTA, fim=None, titular=None):
        return self.client.post(self.url, {"acao": "substituir", "s-substituto": self.colega.pk,
                                           "s-titular": (titular or self.sup).pk, "s-inicio": inicio.isoformat(),
                                           "s-fim": (fim or inicio + timedelta(days=5)).isoformat(), "s-motivo": "férias"})

    def test_responsavel_cadastra_a_equipe(self):
        self.entrar(self.resp)
        self.assertRedirects(self.client.get(reverse("minha_equipe")), self.url, fetch_redirect_response=False)
        r = self.client.post(self.url, {"acao": "adicionar", "m-nome_completo": "Joana Auxiliar", "m-cargo": "Técnica"})
        self.assertContains(r, 'class="codigo-acesso"')
        nova = Usuario.objects.get(nome_completo="Joana Auxiliar")
        self.assertEqual((nova.papel, nova.criado_por, list(nova.concedentes.all())),
                         (Usuario.Papel.SUPERVISOR, self.resp, [self.local]))

    def test_responsavel_ve_e_confirma_sem_ver_mensagens(self):
        self.entrar(self.resp)
        url = self.est.get_absolute_url()
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertNotContains(self.client.get(url + "?aba=mensagens"), "Dúvidas e mensagens")
        self.assertEqual(self.client.post(reverse("enviar_mensagem", args=[self.est.pk]), {"texto": "oi"}).status_code, 403)
        self.client.post(reverse("validar_registro", args=[self.reg.pk]), {"acao": "confirmar"})
        self.reg.refresh_from_db()
        self.assertEqual(self.reg.confirmacao, Registro.Confirmacao.CONFIRMADA)

    def test_substituto_so_no_periodo(self):
        from .models import Substituicao

        self.entrar(self.colega)
        self.assertEqual(self.client.get(self.est.get_absolute_url()).status_code, 403)
        self.entrar(self.resp)
        self._substituir(inicio=QUARTA + timedelta(days=1))  # começa amanhã
        self.entrar(self.colega)
        self.assertEqual(self.client.get(self.est.get_absolute_url()).status_code, 403)
        self.entrar(self.resp)
        self._substituir()
        s = Substituicao.objects.get(inicio=QUARTA)
        self.assertTrue(Notificacao.objects.filter(usuario=self.colega, texto__contains="Você pode confirmar").exists())
        self.entrar(self.colega)
        self.assertContains(self.client.get(reverse("painel_supervisor")), "substituindo")
        self.client.post(reverse("confirmar_lote"), {"registros": [self.reg.pk]})
        self.reg.refresh_from_db()
        self.assertEqual((self.reg.confirmacao, self.reg.confirmado_por), (Registro.Confirmacao.CONFIRMADA, self.colega))
        self.assertEqual(self.client.get(self.est.get_absolute_url() + "?aba=escalas").status_code, 200)  # cai na visão
        self.entrar(self.resp)
        self.client.post(self.url, {"acao": "revogar", "id": s.pk})
        self.entrar(self.colega)
        self.assertEqual(self.client.get(self.est.get_absolute_url()).status_code, 403)

    def test_regras_da_substituicao(self):
        from .models import Substituicao

        self.entrar(self.resp)
        self.assertContains(self._substituir(fim=QUARTA - timedelta(days=1)), "antes da inicial")
        self.assertContains(self._substituir(fim=QUARTA + timedelta(days=120)), "no máximo")
        self.assertContains(self._substituir(titular=self.colega), "si mesma")
        self.assertFalse(Substituicao.objects.exists())

    def test_supervisor_indica_quem_confirma(self):
        from .models import Substituicao

        self.entrar(self.sup)
        self.assertContains(self.client.get(reverse("painel_supervisor")), "Vou me ausentar")
        self.client.post(reverse("indicar_substituto"), {"concedente": self.local.pk, "s-substituto": self.colega.pk,
                                                         "s-inicio": "2026-11-11", "s-fim": "2026-11-20"})
        s = Substituicao.objects.get()
        self.assertEqual((s.titular, s.substituto, s.criada_por), (self.sup, self.colega, self.sup))

    def test_limites_do_responsavel(self):
        outra = LocalEstagio.objects.create(nome="Empresa Y")
        resp2 = _ativo(criar_usuario("Roberto Outro", Usuario.Papel.SUPERVISOR, concedente=outra))
        resp2.concedentes_geridas.add(outra)
        self.entrar(resp2)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.sup.concedentes.add(outra)  # supervisor que também é de outra concedente: só a escola mexe na conta
        self.entrar(self.resp)
        r = self.client.post(self.url, {"acao": "codigo", "id": self.sup.pk}, follow=True)
        self.assertContains(r, "peça à escola")
        r = self.client.post(self.url, {"acao": "desativar", "id": self.colega.pk})
        self.colega.refresh_from_db()
        self.assertFalse(self.colega.is_active)
        self.assertEqual(self.client.post(self.url, {"acao": "responsavel", "id": self.colega.pk}).status_code, 403)

    def test_captacao_cria_o_responsavel(self):
        from .services import aprovar_candidatura

        cand = Candidatura.objects.create(ano=2027, nome="Loja Z", contato_nome="Paulo Gerente",
                                          contato_telefone="85 99999-0000", atividades="Atendimento")
        local, _, _ = aprovar_candidatura(cand, self.ori, "nova", criar_responsavel=True)
        resp = cand._responsavel
        self.assertEqual(list(resp.concedentes_geridas.all()), [local])
        self.assertTrue(resp.gere_concedente)


# ---------------------------------------------------------------- roteiro de visitas e busca rápida


class RoteiroBuscaTests(Base):
    def test_roteiro_do_dia(self):
        self.entrar(self.ori)
        r = self.client.get(reverse("roteiro") + "?data=2026-11-16")  # segunda: dia de estágio
        self.assertContains(r, "Empresa X")
        self.assertContains(r, "nunca visitada")
        self.assertContains(r, f"estagios={self.est.pk}")
        self.assertContains(self.client.get(reverse("roteiro") + "?data=2026-11-11"), "Nenhum estagiário")  # quarta
        self.entrar(self.sup)
        self.assertEqual(self.client.get(reverse("roteiro")).status_code, 403)

    def test_agendar_varios_com_hora(self):
        self.entrar(self.ori)
        r = self.client.get(reverse("novo_agendamento") + f"?estagios={self.est.pk}&data=2026-11-16&hora=09:30")
        self.assertEqual(r.context["form"].initial["data_hora"], datetime(2026, 11, 16, 9, 30))
        self.assertEqual(r.context["form"].initial["estagios"], [self.est])

    def test_busca_rapida(self):
        self.entrar(self.ori)
        grupos = self.client.get(reverse("buscar") + "?q=MARIA souza").json()["grupos"]
        self.assertEqual(grupos[0]["itens"][0]["titulo"], "Maria da Silva Souza")
        nomes = [i["titulo"] for g in self.client.get(reverse("buscar") + "?q=sergio").json()["grupos"] for i in g["itens"]]
        self.assertIn("Sérgio Supervisor", nomes)  # sem acento também acha
        self.assertEqual(self.client.get(reverse("buscar") + "?q=m").json(), {"grupos": []})
        outra = _ativo(criar_usuario("Olga Outra", Usuario.Papel.ORIENTADOR))
        self.entrar(outra)
        grupos = self.client.get(reverse("buscar") + "?q=maria").json()["grupos"]
        self.assertFalse(any(g["nome"] == "Estagiários" for g in grupos))
        self.entrar(self.sup)
        self.assertEqual(self.client.get(reverse("buscar") + "?q=maria").status_code, 403)


class SessaoAparelhoTests(Base):
    SENHA = "Senha#Forte9"
    UA_CHROME = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36"
    UA_FIREFOX = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"

    def setUp(self):
        super().setUp()
        self.ori.set_password(self.SENHA)
        self.ori.save()

    def _cliente(self, ua=UA_CHROME):
        from django.test import Client

        c = Client(HTTP_USER_AGENT=ua)
        r = c.post(reverse("login"), {"username": self.ori.username, "password": self.SENHA})
        self.assertEqual(r.status_code, 302)
        c.get(reverse("perfil"))  # o navegador devolve o cookie do aparelho: a sessão fica presa a ele
        return c

    def test_login_registra_aparelho_e_lista(self):
        from .models import SessaoAparelho

        c = self._cliente()
        rec = SessaoAparelho.objects.get(usuario=self.ori)
        self.assertEqual(rec.aparelho, "Chrome no Android")
        self.assertIn("aparelho", c.cookies)
        r = c.get(reverse("acessos"))
        self.assertContains(r, "Chrome no Android")
        self.assertContains(r, "este aparelho")
        self.assertContains(r, "Entrou no sistema")

    def test_cookie_copiado_para_outro_navegador_encerra_a_sessao(self):
        from django.test import Client

        from .models import RegistroAcao, SessaoAparelho

        c = self._cliente()
        ladrao = Client(HTTP_USER_AGENT=self.UA_FIREFOX)
        for nome in ("sessionid", "aparelho"):
            ladrao.cookies[nome] = c.cookies[nome].value
        r = ladrao.get(reverse("painel"))
        self.assertRedirects(r, reverse("login"), fetch_redirect_response=False)
        self.assertFalse(SessaoAparelho.objects.filter(usuario=self.ori).exists())
        self.assertTrue(RegistroAcao.objects.filter(usuario=self.ori, tipo="SESSAO_RECUSADA").exists())
        self.assertTrue(Notificacao.objects.filter(usuario=self.ori, texto__contains="outro").exists())
        # a sessão acabou no servidor: o aparelho original também precisa entrar de novo
        self.assertEqual(c.get(reverse("painel")).status_code, 302)

    def test_versao_para_computador_do_celular_nao_desconecta(self):
        c = self._cliente()
        desktop = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        self.assertEqual(c.get(reverse("painel"), HTTP_USER_AGENT=desktop).status_code, 200)
        iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/131.0 Mobile/15E148 Safari/604.1"
        mac = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
        i = self._cliente(iphone)
        self.assertEqual(i.get(reverse("painel"), HTTP_USER_AGENT=mac).status_code, 200)
        self.assertEqual(c.get(reverse("painel"), HTTP_USER_AGENT=self.UA_FIREFOX).status_code, 302)

    def test_sem_o_cookie_do_aparelho_encerra(self):
        c = self._cliente()
        del c.cookies["aparelho"]
        self.assertEqual(c.get(reverse("painel")).status_code, 302)
        self.assertEqual(c.get(reverse("painel")).status_code, 302)

    def test_sair_com_o_cookie_copiado_desconecta_o_original(self):
        from django.test import Client

        c = self._cliente()
        copia = Client(HTTP_USER_AGENT=self.UA_CHROME)
        for nome in ("sessionid", "aparelho"):
            copia.cookies[nome] = c.cookies[nome].value
        copia.post(reverse("logout"))
        self.assertEqual(c.get(reverse("painel")).status_code, 302)

    def test_desconectar_outro_aparelho_e_todos(self):
        from .models import SessaoAparelho

        a = self._cliente()
        b = self._cliente(self.UA_FIREFOX)
        self.assertEqual(SessaoAparelho.objects.filter(usuario=self.ori).count(), 2)
        rec_b = SessaoAparelho.objects.get(usuario=self.ori, aparelho__startswith="Firefox")
        a.post(reverse("acessos"), {"acao": "desconectar", "id": rec_b.pk})
        self.assertEqual(b.get(reverse("painel")).status_code, 302)
        self.assertEqual(a.get(reverse("painel")).status_code, 200)
        b = self._cliente(self.UA_FIREFOX)
        a.post(reverse("acessos"), {"acao": "outros"})
        self.assertEqual(b.get(reverse("painel")).status_code, 302)
        self.assertEqual(SessaoAparelho.objects.filter(usuario=self.ori).count(), 1)

    def test_trocar_senha_desconecta_os_outros(self):
        a = self._cliente()
        b = self._cliente(self.UA_FIREFOX)
        r = a.post(reverse("trocar_senha"), {"old_password": self.SENHA, "new_password1": "Outra#Senha77",
                                             "new_password2": "Outra#Senha77"}, follow=True)
        self.assertContains(r, "1 outro(s) aparelho(s)")
        self.assertEqual(a.get(reverse("painel")).status_code, 200)
        self.assertEqual(b.get(reverse("painel")).status_code, 302)

    def test_sessao_antiga_e_adotada_e_presa_ao_navegador(self):
        from django.test import Client

        from .models import SessaoAparelho

        c = self._cliente()
        s = c.session
        for k in ("_ap_id", "_ap_chave", "_ap_ass", "_ap_cookie", "_ap_visto"):
            s.pop(k, None)
        s.save()
        SessaoAparelho.objects.all().delete()
        del c.cookies["aparelho"]
        self.assertEqual(c.get(reverse("painel")).status_code, 200)  # adotada, sem desconectar
        self.assertEqual(SessaoAparelho.objects.filter(usuario=self.ori).count(), 1)
        outro = Client(HTTP_USER_AGENT=self.UA_FIREFOX)
        outro.cookies["sessionid"] = c.cookies["sessionid"].value
        self.assertEqual(outro.get(reverse("painel")).status_code, 302)

    def test_desativar_a_conta_desconecta(self):
        from django.test import Client

        c = Client(HTTP_USER_AGENT=self.UA_CHROME)
        self.sup.set_password(self.SENHA)
        self.sup.save()
        c.post(reverse("login"), {"username": self.sup.username, "password": self.SENHA})
        self.assertEqual(c.get(reverse("painel_supervisor")).status_code, 200)
        self.est.supervisor = None
        self.est.save()
        self.sup.is_active = False
        self.sup.save()
        self.sup.is_active = True
        self.sup.save()
        self.assertEqual(c.get(reverse("painel_supervisor")).status_code, 302)  # reativada não volta sozinha

    def test_gestao_desconecta_de_todos_os_aparelhos(self):
        from .models import SessaoAparelho

        self.sup.set_password(self.SENHA)
        self.sup.save()
        from django.test import Client

        c = Client(HTTP_USER_AGENT=self.UA_CHROME)
        c.post(reverse("login"), {"username": self.sup.username, "password": self.SENHA})
        self.entrar(self.ori)
        self.client.post(reverse("desconectar_usuario", args=[self.sup.pk]))
        self.assertEqual(c.get(reverse("painel_supervisor")).status_code, 302)
        self.assertFalse(SessaoAparelho.objects.filter(usuario=self.sup).exists())

    def test_entrar_com_email(self):
        self.ori.email = "paula@escola.test"
        self.ori.save()
        r = self.client.post(reverse("login"), {"username": "Paula@Escola.test", "password": self.SENHA})
        self.assertEqual(r.status_code, 302)
        self.client.logout()
        _ativo(criar_usuario("Paula Outra", Usuario.Papel.ORIENTADOR, email="paula@escola.test"))
        r = self.client.post(reverse("login"), {"username": "paula@escola.test", "password": self.SENHA})
        self.assertEqual(r.status_code, 200)  # e-mail de duas contas: não adivinha qual


@override_settings(EMAIL_ATIVO=True, SITE_URL="https://estagio.exemplo.br")
class ConfirmacaoCadastroTests(Base):
    def setUp(self):
        super().setUp()
        self.ori.is_superuser = True
        self.ori.save()
        self.novo = criar_usuario("Carla Mendes", Usuario.Papel.SUPERVISOR, self.ori, concedente=self.local,
                                  email="carla@empresa.test")

    def _link(self, msg):
        import re

        return re.search(r"https?://[^/\s]+(/email/confirmar/\S+/)", msg.body).group(1)

    def test_link_confirma_e_leva_a_criar_a_senha(self):
        from django.core import mail

        self.entrar(self.ori)
        r = self.client.post(reverse("pedir_confirmacao_email", args=[self.novo.pk]), follow=True)
        self.assertContains(r, "Pedido de confirmação enviado")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("criar a sua senha", mail.outbox[0].body)
        self.assertIn("carla.mendes", mail.outbox[0].body)
        self.client.logout()
        r = self.client.get(self._link(mail.outbox[0]), follow=True)
        self.assertContains(r, "Agora crie a sua senha")
        self.novo.refresh_from_db()
        self.assertIsNotNone(self.novo.email_confirmado_em)
        url = r.redirect_chain[-1][0]
        r = self.client.post(url, {"new_password1": "Ipe#Amarelo33", "new_password2": "Ipe#Amarelo33"})
        self.novo.refresh_from_db()
        self.assertFalse(self.novo.deve_trocar_senha)
        self.assertEqual(self.client.post(reverse("login"), {"username": "carla@empresa.test",
                                                             "password": "Ipe#Amarelo33"}).status_code, 302)

    def test_em_lote_pula_quem_recebeu_ha_pouco(self):
        from django.core import mail

        outro = criar_usuario("Davi Lopes", Usuario.Papel.SUPERVISOR, self.ori, concedente=self.local,
                              email="davi@empresa.test")
        outro.confirmacao_enviada_em = timezone.now()
        outro.save()
        self.entrar(self.ori)
        r = self.client.get(reverse("usuarios") + "?situacao=email")
        self.assertContains(r, "Carla Mendes")
        self.assertNotContains(r, "Sérgio Supervisor")  # sem e-mail
        r = self.client.post(reverse("confirmacao_lote"), {"papel": "", "q": ""}, follow=True)
        self.assertContains(r, "enviado para 1 conta")
        self.assertEqual([m.to for m in mail.outbox], [["carla@empresa.test"]])

    def test_orientador_sem_vinculo_nao_libera_o_acesso_de_quem_nao_entrou(self):
        orientadora = _ativo(criar_usuario("Rosa Lima", Usuario.Papel.ORIENTADOR))
        self.entrar(orientadora)
        self.assertEqual(self.client.post(reverse("pedir_confirmacao_email", args=[self.novo.pk])).status_code, 403)


class CandidaturaComContaTests(Base):
    def setUp(self):
        super().setUp()
        cfg = Configuracao.atual()
        cfg.captacao_aberta, cfg.ano_captacao = True, 2027
        cfg.save()
        self.fechado = Curso.objects.create(nome="Enfermagem", na_captacao=False)

    def _dados(self, **kw):
        d = {"tipo_concedente": "PJ", "razao_social": "Loja Bela Vista LTDA", "nome": "Bela Vista", "uf": "CE",
             "contato_nome": "Helena Prado", "contato_telefone": "(85) 99876-0000", "contato_email": "helena@bela.test",
             "preenchido_por": "AUTORIZADO", "atividades": "Atendimento", f"curso_{self.curso.pk}": "on",
             f"vaga_{self.curso.pk}": "3", "senha1": "Cajueiro#Doce42", "senha2": "Cajueiro#Doce42",
             "aceite_termos": "on", "consentimento": "on"}
        d.update(kw)
        return d

    def test_cria_conta_que_so_ve_a_candidatura(self):
        r = self.client.post(reverse("candidatura_publica"), self._dados())
        cand = Candidatura.objects.get()
        conta = cand.conta
        self.assertContains(r, conta.username)
        self.assertEqual((conta.papel, conta.deve_trocar_senha, conta.email), (Usuario.Papel.SUPERVISOR, False,
                                                                              "helena@bela.test"))
        self.assertTrue(conta.check_password("Cajueiro#Doce42"))
        self.assertTrue(conta.termos_versao)
        self.assertEqual(cand.preenchido_por, "AUTORIZADO")
        self.assertFalse(conta.vinculado_a_concedente)
        r = self.client.get(reverse("inicio"), follow=True)
        self.assertContains(r, "Aguardando a análise")
        self.assertRedirects(self.client.get(reverse("painel_supervisor")), reverse("minhas_candidaturas"),
                             fetch_redirect_response=False)
        cfg = Configuracao.atual()
        cfg.banco_talentos_habilitado = True
        cfg.save()
        self.assertEqual(self.client.get(reverse("banco_talentos")).status_code, 403)

    def test_cursos_por_caixa_de_selecao(self):
        r = self.client.get(reverse("candidatura_publica"))
        self.assertContains(r, self.curso.nome)
        self.assertNotContains(r, "Enfermagem")
        r = self.client.post(reverse("candidatura_publica"), self._dados(**{f"vaga_{self.curso.pk}": ""}))
        self.assertContains(r, "Informe quantas vagas")
        self.client.post(reverse("candidatura_publica"), self._dados(**{f"vaga_{self.fechado.pk}": "5"}))
        self.assertEqual([(v.curso, v.quantidade) for v in VagaCandidatura.objects.all()], [(self.curso, 3)])

    def test_altera_enquanto_pendente_e_trava_depois_de_aprovada(self):
        self.client.post(reverse("candidatura_publica"), self._dados())
        cand = Candidatura.objects.get()
        dados = self._dados(**{f"vaga_{self.curso.pk}": "5"})
        r = self.client.post(reverse("editar_candidatura", args=[cand.pk]), dados, follow=True)
        self.assertContains(r, "Cadastro atualizado")
        cand.refresh_from_db()
        self.assertEqual(cand.total_vagas, 5)
        self.assertIsNotNone(cand.alterada_em)
        conta = cand.conta
        self.entrar(self.ori)
        self.client.post(cand.get_absolute_url(), {"acao": "aprovar", "a-destino": "nova", "a-criar_responsavel": "on"})
        cand.refresh_from_db()
        conta = Usuario.objects.get(pk=conta.pk)
        self.assertEqual(list(conta.concedentes_geridas.all()), [cand.local])
        self.assertTrue(conta.vinculado_a_concedente)
        self.assertTrue(Notificacao.objects.filter(usuario=conta, texto__contains="aprovado").exists())
        self.entrar(conta)
        r = self.client.post(reverse("editar_candidatura", args=[cand.pk]), self._dados(**{f"vaga_{self.curso.pk}": "9"}),
                             follow=True)
        self.assertContains(r, "não mudam mais")
        self.assertEqual(Candidatura.objects.get().total_vagas, 5)
        r = self.client.get(reverse("minha_candidatura", args=[cand.pk]))
        self.assertContains(r, "Cadastro aprovado")
        self.assertContains(r, "Cadastrar a equipe")

    def test_escola_preenche_pela_concedente_mesmo_fechada(self):
        cfg = Configuracao.atual()
        cfg.captacao_aberta = False
        cfg.save()
        self.entrar(self.ori)
        dados = self._dados()
        for k in ("senha1", "senha2", "aceite_termos", "preenchido_por"):
            dados.pop(k)
        r = self.client.post(reverse("candidatura_publica"), dados)
        cand = Candidatura.objects.get()
        self.assertRedirects(r, cand.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((cand.preenchido_por, cand.cadastrada_por, cand.conta), ("ESCOLA", self.ori, None))
        self.assertFalse(Usuario.objects.filter(email="helena@bela.test").exists())

    def test_supervisor_com_conta_manda_pela_conta_e_estagiario_nao(self):
        self.entrar(self.sup)
        dados = self._dados()
        for k in ("senha1", "senha2", "aceite_termos"):
            dados.pop(k)
        self.client.post(reverse("candidatura_publica"), dados)
        self.assertEqual(Candidatura.objects.get().conta, self.sup)
        self.entrar(self.aluno)
        self.assertContains(self.client.get(reverse("candidatura_publica")), "conectado como estagiário")

    def test_configuracoes_escolhem_os_cursos(self):
        self.ori.is_superuser = True
        self.ori.save()
        self.entrar(self.ori)
        from .forms import ConfiguracaoForm

        form = ConfiguracaoForm(instance=Configuracao.atual())
        dados = {k: v for k, v in form.initial.items() if v is not None and k not in ("logo_folha", "cursos_captacao")}
        for k, v in list(dados.items()):
            if v is True:
                dados[k] = "on"
            elif v is False:
                dados.pop(k)
            elif hasattr(v, "isoformat"):
                dados[k] = v.isoformat()
        dados["cursos_captacao"] = [self.fechado.pk]
        r = self.client.post(reverse("configuracoes"), dados)
        self.assertEqual(r.status_code, 302, getattr(r, "context", {}) and r.context["form"].errors)
        self.assertEqual(list(Curso.objects.filter(na_captacao=True)), [self.fechado])


class AgendamentoRapidoTests(Base):
    SEGUNDA = date(2026, 11, 16)

    def test_planejar_pula_almoco_e_compromissos(self):
        from datetime import time as hora

        from .views.roteiro import paradas_do_dia, planejar

        local2 = LocalEstagio.objects.create(nome="Empresa Y")
        aluna = _ativo(criar_usuario("Joana Prado", Usuario.Papel.ESTAGIARIO))
        e2 = Estagio.objects.create(estagiario=aluna, orientador=self.ori, curso=self.curso, local=local2,
                                    data_inicio=date(2026, 11, 2))
        Escala.objects.create(estagio=e2, vigente_desde=date(2026, 11, 2), dias="0,1", horas_por_dia=4)
        paradas = paradas_do_dia(self.ori, self.SEGUNDA)
        self.assertEqual(len(paradas), 2)
        tz = timezone.get_current_timezone()
        ocupado = (timezone.make_aware(datetime(2026, 11, 16, 13, 0), tz),
                   timezone.make_aware(datetime(2026, 11, 16, 13, 30), tz))
        plano = planejar(paradas, self.SEGUNDA, hora(11, 0), 45, 20, [ocupado],
                         agora=timezone.make_aware(datetime(2026, 11, 10, 9, 0), tz))
        horarios = [(timezone.localtime(i["inicio"]).strftime("%H:%M"), timezone.localtime(i["fim"]).strftime("%H:%M"))
                    for i in plano]
        # 11:00–11:45; a segunda cairia 12:05 (almoço) → 13:00, que está ocupado → 13:30
        self.assertEqual(horarios, [("11:00", "11:45"), ("13:30", "14:15")])

    def test_previa_e_criacao(self):
        self.entrar(self.ori)
        dados = {"data": self.SEGUNDA.isoformat(), "inicio": "08:00", "duracao": "30", "deslocamento": "15",
                 "locais": [self.local.pk]}
        r = self.client.post(reverse("agendamento_rapido"), {**dados, "acao": "previa"})
        self.assertContains(r, "Agenda proposta")
        self.assertContains(r, "08:00")
        self.assertFalse(Agendamento.objects.exists())
        r = self.client.post(reverse("agendamento_rapido"), {**dados, "acao": "criar"})
        ag = Agendamento.objects.get()
        self.assertEqual((ag.status, ag.duracao, ag.local, list(ag.estagios.all())),
                         (Agendamento.Status.AGENDADO, 30, self.local, [self.est]))
        self.assertEqual(timezone.localtime(ag.data_hora).strftime("%d/%m %H:%M"), "16/11 08:00")
        self.assertTrue(Notificacao.objects.filter(usuario=self.aluno, texto__contains="Visita agendada").exists())
        r = self.client.get(reverse("roteiro") + f"?data={self.SEGUNDA.isoformat()}")
        self.assertContains(r, "visita marcada 08:00")


class EquipeContatoEFolhaTests(Base):
    def test_responsavel_atualiza_contato_da_equipe(self):
        chefe = _ativo(criar_usuario("Lara Chefe", Usuario.Papel.SUPERVISOR, concedente=self.local))
        chefe.concedentes_geridas.add(self.local)
        self.entrar(chefe)
        self.client.post(reverse("equipe_concedente", args=[self.local.pk]),
                         {"acao": "contato", "id": self.sup.pk, "telefone": "(85) 91234-5678",
                          "email": "sergio@empresa.test", "cargo": "Gerente"})
        self.sup.refresh_from_db()
        self.assertEqual((self.sup.telefone, self.sup.email, self.sup.cargo),
                         ("(85) 91234-5678", "sergio@empresa.test", "Gerente"))

    def test_rodape_da_folha_liga_e_desliga(self):
        self.entrar(self.ori)
        url = reverse("folha_frequencia", args=[self.est.pk]) + "?mes=2026-11"
        self.assertContains(self.client.get(url), "Emitida em")
        cfg = Configuracao.atual()
        cfg.mostrar_codigo_folha = False
        cfg.save()
        self.assertNotContains(self.client.get(url), "Emitida em")


class DiasDaImportacaoTests(Base):
    """Turma que ia só segunda e terça e passou a ir de segunda a sexta: a importação lança as presenças pela escala de
    cada dia, e o que já foi lançado errado pode ser conferido e retirado."""

    def setUp(self):
        super().setUp()
        self.ori.is_superuser = True
        self.ori.save()
        self.entrar(self.ori)

    def _importar(self, **extra):
        csv_ = ("estagiario_nome;curso;data_inicio;horas_anteriores;presencas_desde;concedente_nome;supervisor_nome\n"
                "Lara Nunes Viana;Informática;24/08/2026;96;03/11/2026;Empresa X;Sérgio Supervisor\n")
        dados = {"etapa": "previa", "arquivo": SimpleUploadedFile("f.csv", csv_.encode(), "text/csv"),
                 "orientador": self.ori.pk, "dias": ["0", "1"], "horas_por_dia": "8",
                 "acompanhamento_desde": "2026-11-11", "carga_cursos_novos": "300", **extra}
        r = self.client.post(reverse("importar_csv"), dados)
        self.client.post(reverse("importar_csv"), {"etapa": "confirmar"})
        return r, Estagio.objects.get(estagiario__nome_completo="Lara Nunes Viana")

    def test_mudanca_de_dias_na_importacao(self):
        r, est = self._importar(mudanca_desde="2026-11-09", dias_depois=["0", "1", "2", "3", "4"])
        self.assertContains(r, "Seg, Ter; a partir de 09/11/2026: Segunda a sexta")
        self.assertContains(r, "de 03/11/2026 até 10/11/2026")
        self.assertEqual([(e.vigente_desde, e.dias) for e in est.escalas.order_by("vigente_desde")],
                         [(date(2026, 8, 24), "0,1"), (date(2026, 11, 9), "0,1,2,3,4")])
        # hoje (mock) é qua 11/11: ter 03 (seg/ter); qua 04 a sex 06 ficam de fora; seg 09 e ter 10 (nova escala)
        self.assertEqual([x.data.day for x in est.registros.order_by("data")], [3, 9, 10])

    def test_mudanca_sem_os_dias_novos_e_recusada(self):
        dados = {"etapa": "previa", "arquivo": SimpleUploadedFile("f.csv", b"estagiario_nome;curso;data_inicio\n", "text/csv"),
                 "orientador": self.ori.pk, "dias": ["0"], "horas_por_dia": "8", "carga_cursos_novos": "300",
                 "mudanca_desde": "2026-11-09"}
        self.assertContains(self.client.post(reverse("importar_csv"), dados), "Escolha os dias de estágio a partir da mudança")

    def test_conferir_e_retirar_presencas_importadas_fora_da_escala(self):
        from .models import Escala, HistoricoRegistro

        _, est = self._importar(dias=["0", "1", "2", "3", "4"])  # importada como segunda a sexta (o engano)
        self.assertEqual([x.data.day for x in est.registros.order_by("data")], [3, 4, 5, 6, 9, 10])
        # corrige os dias: seg/ter desde o início (data anterior ao início ajusta a primeira escala) e seg-sex de 09/11
        for dias, desde in ((["0", "1"], "2026-08-01"), (["0", "1", "2", "3", "4"], "2026-11-09")):
            self.client.post(reverse("escala_lote"), {"vigente_desde": desde, "dias": dias, "estagios": [est.pk]})
        self.assertEqual([(e.vigente_desde, e.dias) for e in Escala.objects.filter(estagio=est).order_by("vigente_desde")],
                         [(date(2026, 8, 24), "0,1"), (date(2026, 11, 9), "0,1,2,3,4")])
        r = self.client.get(reverse("escala_lote"))
        self.assertContains(r, "Presenças da importação fora dos dias de estágio")
        self.assertEqual([x.data.day for x in r.context["fora"][0][1]], [4, 5, 6])
        # presença que alguém já ajustou não entra na conferência
        ajustada = est.registros.get(data=date(2026, 11, 6))
        ajustada.obs_supervisor = "Veio para repor."
        ajustada.save()
        ids = [x.pk for x in est.registros.filter(data__in=[date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6)])]
        r = self.client.post(reverse("remover_importadas_fora"), {"registros": ids}, follow=True)
        self.assertContains(r, "2 presença(s) retirada(s) de 1 estagiário(s)")
        self.assertEqual([x.data.day for x in est.registros.order_by("data")], [3, 6, 9, 10])
        self.assertEqual(HistoricoRegistro.objects.filter(estagio=est, acao=HistoricoRegistro.Acao.REVOGOU).count(), 2)
        self.assertTrue(Notificacao.objects.filter(usuario=est.estagiario, texto__contains="04/11, 05/11").exists())
        self.assertNotContains(self.client.get(reverse("escala_lote")), "Retirar")

    def test_supervisor_nao_retira(self):
        self.entrar(self.sup)
        self.assertEqual(self.client.post(reverse("remover_importadas_fora"), {"registros": [1]}).status_code, 403)
