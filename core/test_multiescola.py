"""Fundação multiescola (Etapa 1): isolamento entre as escolas fictícias A e B, papéis por escola, seletor,
administrador da plataforma × da escola, tarefas por escola e a migration de dados (contagens antes e depois).

Regra testada: quem é da escola A não vê, não busca, não edita e não baixa nada da escola B, nem por URL direta.
"""
from datetime import date, time

from django.core.files.base import ContentFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from escolas.escopo import EscopoAusente, escola_ativa, escola_unica, limpar_cache_escola_unica, todas_as_escolas
from escolas.models import Escola, VinculoEscola

from .models import (Agendamento, Candidatura, Configuracao, Curso, Documento, Escala, Estagio, Justificativa,
                     LocalEstagio, Registro, Turma, Usuario)
from .services import criar_usuario


def _ativo(user):
    user.deve_trocar_senha = False
    user.save()
    return user


def _montar_escola(nome_aluno, nome_local, sufixo):
    """Uma escola completa: orientador, supervisor, estagiário, curso, turma, concedente, estágio, registro,
    atestado, documento, agendamento e candidatura. Tudo fictício."""
    d = {}
    d["ori"] = _ativo(criar_usuario(f"Orientadora {sufixo} Teste", Usuario.Papel.ORIENTADOR))
    d["local"] = LocalEstagio.objects.create(nome=nome_local, cnpj=f"00.000.000/000{len(sufixo)}-0{len(sufixo)}")
    d["sup"] = _ativo(criar_usuario(f"Supervisor {sufixo} Teste", Usuario.Papel.SUPERVISOR, concedente=d["local"]))
    d["curso"] = Curso.objects.create(nome="Técnico em Informática")  # mesmo nome nas duas: unicidade por escola
    d["turma"] = Turma.objects.create(curso=d["curso"], nome="3º A", ano_ingresso=2024, ano_estagio=2026)
    d["aluno"] = _ativo(criar_usuario(nome_aluno, Usuario.Papel.ESTAGIARIO))
    d["est"] = Estagio.objects.create(estagiario=d["aluno"], orientador=d["ori"], supervisor=d["sup"], curso=d["curso"],
                                      turma=d["turma"], local=d["local"], data_inicio=date(2026, 8, 3))
    Escala.objects.create(estagio=d["est"], vigente_desde=date(2026, 8, 3), dias="0,1,2,3,4", horas_por_dia=4)
    d["reg"] = Registro.objects.create(estagio=d["est"], data=date(2026, 8, 4), situacao="PRESENTE", horas=4,
                                       hora_chegada=time(7))
    d["just"] = Justificativa(estagio=d["est"], data_inicio=date(2026, 8, 5), data_fim=date(2026, 8, 5), motivo="Consulta")
    d["just"].arquivo.save("atestado.pdf", ContentFile(b"%PDF ficticio"), save=False)
    d["just"].save()
    d["doc"] = Documento(titulo=f"Arquivo {sufixo}", orientador=d["ori"], enviado_por=d["ori"])
    d["doc"].arquivo.save("arquivo.pdf", ContentFile(b"%PDF ficticio"), save=False)
    d["doc"].save()
    d["ag"] = Agendamento.objects.create(tipo="VISITA", status="AGENDADO", orientador=d["ori"], solicitante=d["ori"],
                                         assunto=f"Visita {sufixo}")
    d["cand"] = Candidatura.objects.create(nome=f"Candidata {sufixo}", contato_nome=f"Contato {sufixo}",
                                           contato_email=f"contato{sufixo.lower()}@example.com", contato_telefone="(85) 90000-0000", ano=2027)
    return d


@override_settings(MEDIA_ROOT="/tmp/estagio-monitor-testes-multiescola")
class IsolamentoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.escola_a = escola_unica()
        cls.escola_b = Escola.objects.create(nome="Escola B Fictícia", slug="escola-b", situacao="ATIVA",
                                             rede=cls.escola_a.rede)
        Configuracao.objects.create(escola=cls.escola_b)
        with escola_ativa(cls.escola_a):
            cls.a = _montar_escola("Alice Aluna Alfa", "Concedente Alfa", "A")
            cls.admin_a = _ativo(criar_usuario("Admin Escola Alfa", Usuario.Papel.ORIENTADOR))
            VinculoEscola.objects.create(usuario=cls.admin_a, escola=cls.escola_a, papel="ADMIN")
        with escola_ativa(cls.escola_b):
            cls.b = _montar_escola("Bruno Aluno Beta", "Concedente Beta", "B")

    def entrar(self, user):
        self.client.force_login(user)

    # ------------------------------------------------------------------ mecanismo
    def test_falha_fechada_sem_escola(self):
        with self.assertRaises(EscopoAusente):
            Estagio.objects.count()
        with self.assertRaises(EscopoAusente):
            list(Registro.objects.all())  # filhas também (pelo estágio)
        self.assertEqual(Estagio.objects.todas_as_escolas().count(), 2)
        with escola_ativa(self.escola_a):
            self.assertEqual(list(Estagio.objects.all()), [self.a["est"]])
            self.assertEqual(list(Registro.objects.all()), [self.a["reg"]])
            self.assertEqual(list(Turma.objects.all()), [self.a["turma"]])
            self.assertEqual(self.a["curso"].estagios.count(), 1)  # gerenciador reverso também filtra
        with todas_as_escolas():
            self.assertEqual(Estagio.objects.count(), 2)

    def test_queryset_criado_antes_usa_a_escola_da_execucao(self):
        qs = Estagio.objects.all()  # criado sem escola: só resolve na execução
        with escola_ativa(self.escola_b):
            self.assertEqual(list(qs), [self.b["est"]])

    def test_configuracao_e_unicidade_por_escola(self):
        with escola_ativa(self.escola_a):
            cfg_a = Configuracao.atual()
        with escola_ativa(self.escola_b):
            cfg_b = Configuracao.atual()
        self.assertNotEqual(cfg_a.pk, cfg_b.pk)
        self.assertEqual((cfg_a.escola, cfg_b.escola), (self.escola_a, self.escola_b))
        self.assertEqual(self.a["curso"].nome, self.b["curso"].nome)  # o mesmo nome pode existir em cada escola

    def test_escola_gravada_pela_escola_em_uso(self):
        self.assertEqual(self.a["est"].escola, self.escola_a)
        self.assertEqual(self.b["est"].escola, self.escola_b)
        self.assertEqual(self.b["cand"].escola, self.escola_b)
        self.assertTrue(self.b["doc"].arquivo.name.startswith(f"escolas/{self.escola_b.pk}/documentos/"))
        self.assertNotIn("arquivo", self.b["doc"].arquivo.name.rsplit("/", 1)[-1])  # nome aleatório
        self.assertTrue(self.b["just"].arquivo.name.startswith(f"escolas/{self.escola_b.pk}/atestados/"))
        self.assertTrue(VinculoEscola.objects.filter(usuario=self.b["aluno"], escola=self.escola_b,
                                                     papel="ESTAGIARIO").exists())
        self.assertFalse(VinculoEscola.objects.filter(usuario=self.b["aluno"], escola=self.escola_a).exists())

    # ------------------------------------------------------------------ telas, por URL direta
    def test_url_direta_de_outra_escola_da_404(self):
        self.entrar(self.admin_a)
        self.assertEqual(self.client.get(reverse("estagio_detalhe", args=[self.a["est"].pk])).status_code, 200)
        b = self.b
        for nome, pk in [("estagio_detalhe", b["est"].pk), ("local_editar", b["local"].pk),
                         ("curso_editar", b["curso"].pk), ("editar_usuario", b["aluno"].pk),
                         ("editar_usuario", b["sup"].pk), ("captacao_detalhe", b["cand"].pk),
                         ("agendamento_detalhe", b["ag"].pk), ("baixar_documento", b["doc"].pk),
                         ("atestado_arquivo", b["just"].pk), ("relatorio_turma", b["turma"].pk)]:
            with self.subTest(tela=nome):
                r = self.client.get(reverse(nome, args=[pk]))
                self.assertIn(r.status_code, (403, 404), f"{nome} devolveu {r.status_code}")

    def test_listas_e_busca_so_da_escola(self):
        self.entrar(self.admin_a)
        for nome in ("painel", "locais", "usuarios", "captacao", "cursos"):
            with self.subTest(tela=nome):
                r = self.client.get(reverse(nome))
                self.assertEqual(r.status_code, 200)
                texto = r.content.decode()
                self.assertNotIn("Beta", texto)
        self.assertContains(self.client.get(reverse("painel")), "Alice")
        r = self.client.get(reverse("buscar"), {"q": "Beta"})
        self.assertNotIn("Beta", r.content.decode())
        r = self.client.get(reverse("buscar"), {"q": "Alfa"})
        self.assertIn("Alfa", r.content.decode())

    def test_exportacao_so_da_escola(self):
        from io import BytesIO

        self.entrar(self.admin_a)
        r = self.client.get(reverse("exportar_estagios"))
        self.assertEqual(r.status_code, 200)
        conteudo = b"".join(r.streaming_content) if r.streaming else r.content
        if conteudo[:2] == b"PK":  # .xlsx
            from openpyxl import load_workbook

            celulas = " ".join(str(c.value) for ws in load_workbook(BytesIO(conteudo)).worksheets
                               for row in ws.iter_rows() for c in row if c.value)
        else:
            celulas = conteudo.decode("utf-8", "ignore")
        self.assertIn("Alice", celulas)
        self.assertNotIn("Bruno", celulas)

    def test_supervisor_e_estagiario_nao_veem_a_outra_escola(self):
        self.entrar(self.a["sup"])
        self.assertIn(self.client.get(reverse("estagio_detalhe", args=[self.b["est"].pk])).status_code, (403, 404))
        self.entrar(self.b["aluno"])
        self.assertEqual(self.client.get(reverse("estagio_detalhe", args=[self.b["est"].pk])).status_code, 200)
        self.assertIn(self.client.get(reverse("estagio_detalhe", args=[self.a["est"].pk])).status_code, (403, 404))

    # ------------------------------------------------------------------ papéis, seletor e administradores
    def test_admin_da_escola_a_nao_e_admin_na_b_e_seletor(self):
        pessoa = self.admin_a
        with escola_ativa(self.escola_b):
            VinculoEscola.objects.create(usuario=pessoa, escola=self.escola_b, papel="ORIENTADOR")
        self.entrar(pessoa)
        r = self.client.get(reverse("painel"))
        self.assertContains(r, "seletor-escola")
        self.assertEqual(self.client.get(reverse("configuracoes")).status_code, 200)  # admin na A
        self.client.post(reverse("trocar_escola"), {"escola": self.escola_b.pk, "next": "/painel/"})
        self.assertEqual(self.client.get(reverse("configuracoes")).status_code, 403)  # na B é só orientador
        self.assertNotContains(self.client.get(reverse("painel")), "Alice")
        self.assertEqual(Usuario.objects.get(pk=pessoa.pk).is_superuser, False)  # nada disso foi gravado

    def test_seletor_so_com_duas_escolas_e_troca_protegida(self):
        self.entrar(self.a["ori"])
        self.assertNotContains(self.client.get(reverse("painel")), "seletor-escola")
        r = self.client.post(reverse("trocar_escola"), {"escola": self.escola_b.pk})
        self.assertEqual(r.status_code, 403)

    def test_admin_da_plataforma_separado_do_admin_da_escola(self):
        Usuario.objects.filter(pk=self.admin_a.pk).update(is_staff=True)
        self.entrar(Usuario.objects.get(pk=self.admin_a.pk))
        self.assertNotEqual(self.client.get("/admin/escolas/escola/").status_code, 200)  # admin da escola: não
        tecnico = Usuario.objects.create(username="tecnico.plataforma", nome_completo="Técnico Plataforma",
                                         is_superuser=True, is_staff=True, deve_trocar_senha=False)
        self.assertFalse(VinculoEscola.objects.filter(usuario=tecnico).exists())  # sem escola: só plataforma
        self.entrar(tecnico)
        r = self.client.get("/admin/escolas/escola/")
        self.assertContains(r, "Escola B Fictícia")

    def test_link_publico_confirmar_todas_trabalha_na_escola_do_link(self):
        from . import confirmacao

        with escola_ativa(self.escola_b):
            codigo = confirmacao.criar_link(self.b["sup"], [self.b["reg"]])
        r = self.client.get(reverse("confirmar_por_link", args=[codigo]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Bruno")
        self.assertNotContains(r, "Alice")

    def test_captacao_publica_pelo_caminho_da_escola(self):
        self.assertEqual(self.client.get("/seja-concedente/escola-b/").status_code, 200)
        self.assertEqual(self.client.get("/seja-concedente/nao-existe/").status_code, 404)

    def test_tarefas_periodicas_percorrem_as_escolas(self):
        from .tarefas import rodar_tarefas

        falhas = rodar_tarefas()
        self.assertEqual(set(falhas), {self.escola_a.slug, "escola-b", "plataforma"})
        self.assertEqual({k: v for k, v in falhas.items() if v}, {})

    def test_comando_tarefas_periodicas_espera_os_envios_em_segundo_plano(self):
        """As threads de e-mail são daemon: sem esperar, morreriam com o processo do Scheduled Task."""
        from io import StringIO
        from unittest import mock

        from django.core.management import call_command

        with mock.patch("core.threads.aguardar_threads", return_value=0) as aguardar:
            call_command("tarefas_periodicas", stdout=StringIO())
        aguardar.assert_called_once_with()


class MigrationMultiescolaTests(TransactionTestCase):
    """A migration de dados preserva as contagens, associa tudo à escola atual e é reversível."""

    serialized_rollback = True
    antes = [("core", "0047_escola_nas_entidades"), ("escolas", "0001_initial")]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        limpar_cache_escola_unica()
        super().tearDown()

    def _apps_em(self, alvo):
        executor = MigrationExecutor(connection)
        executor.migrate(alvo)
        executor.loader.build_graph()
        return executor.loader.project_state(alvo).apps

    def test_ida_e_volta_com_contagens(self):
        apps = self._apps_em(self.antes)
        Curso = apps.get_model("core", "Curso")
        Usuario_ = apps.get_model("core", "Usuario")
        Estagio_ = apps.get_model("core", "Estagio")
        Config = apps.get_model("core", "Configuracao")
        Config.objects.update_or_create(pk=1, defaults={"nome_escola": "EEEP Escola de Demonstração",
                                                        "municipio_escola": "Cidade Fictícia"})
        curso = Curso.objects.create(nome="Curso Fictício")
        ori = Usuario_.objects.create(username="ori.mig", nome_completo="Orientadora Mig", papel="ORIENTADOR",
                                      is_superuser=True)
        aluno = Usuario_.objects.create(username="aluno.mig", nome_completo="Aluno Mig", papel="ESTAGIARIO")
        Estagio_.objects.create(estagiario=aluno, orientador=ori, curso=curso, data_inicio=date(2026, 8, 3))
        contagem = {m._meta.label: m._base_manager.count() for m in apps.get_app_config("core").get_models()}

        apps = self._apps_em([("core", "0049_escola_obrigatoria")])
        Escola_ = apps.get_model("escolas", "Escola")
        self.assertEqual(Escola_.objects.count(), 1)
        escola = Escola_.objects.get()
        self.assertEqual((escola.nome, escola.municipio, escola.rede.sistema_oficial),
                         ("EEEP Escola de Demonstração", "Cidade Fictícia", "SICE"))
        depois = {m._meta.label: m._base_manager.count() for m in apps.get_app_config("core").get_models()}
        self.assertEqual(contagem, depois)
        for nome in ("Curso", "Estagio", "Configuracao"):
            self.assertFalse(apps.get_model("core", nome)._base_manager.filter(escola__isnull=True).exists(), nome)
        Vinculo = apps.get_model("escolas", "VinculoEscola")
        self.assertEqual(set(Vinculo.objects.filter(usuario__username="ori.mig").values_list("papel", flat=True)),
                         {"ORIENTADOR", "ADMIN"})
        self.assertEqual(set(Vinculo.objects.filter(usuario__username="aluno.mig").values_list("papel", flat=True)),
                         {"ESTAGIARIO"})

        apps = self._apps_em(self.antes)  # reversão
        de_volta = {m._meta.label: m._base_manager.count() for m in apps.get_app_config("core").get_models()}
        self.assertEqual(contagem, de_volta)
        self.assertEqual(apps.get_model("escolas", "Escola").objects.count(), 0)
        self.assertTrue(apps.get_model("core", "Curso")._base_manager.filter(escola__isnull=True).exists())
