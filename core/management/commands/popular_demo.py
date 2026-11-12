"""Cria dados fictícios para conhecer o sistema.

Todas as contas usam a SENHA_PADRAO e já estão liberadas (sem troca obrigatória).
Contas criadas: orientador 'demo.orientador', coordenadora 'paula.lins' (Enfermagem),
supervisores 'ana.rocha' e 'carlos.mendes',
estagiários 'maria.souza', 'joao.lima', 'beatriz.alves', 'pedro.costa', 'larissa.freitas', 'rafael.nunes'.
Também cria duas candidaturas de concedentes aguardando análise na captação.
"""
import random
from datetime import date, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import (
    Agendamento, Candidatura, Configuracao, VagaCandidatura, Curso, DiaSemEstagio, Escala, Estagio, LocalEstagio, Mensagem, Registro, Usuario,
)
from core.services import criar_usuario, turma_para
from core.validators import _dv, formatar_cnpj, formatar_cpf


def cpf_ficticio(base):
    d = f"{base:09d}"
    d += _dv(d, range(10, 1, -1))
    d += _dv(d, range(11, 1, -1))
    return formatar_cpf(d)


def cnpj_ficticio(base):
    d = f"{base:08d}0001"
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d += _dv(d, p1)
    d += _dv(d, [6] + p1)
    return formatar_cnpj(d)


class Command(BaseCommand):
    help = "Popula o banco com dados de demonstração"

    @transaction.atomic
    def handle(self, **_):
        if Usuario.objects.filter(username="demo.orientador").exists():
            raise CommandError("Dados de demonstração já existem.")
        random.seed(42)
        hoje = timezone.localdate()

        def conta(nome, papel, **kw):
            u = criar_usuario(nome, papel, **kw)
            u.deve_trocar_senha = False
            u.save()
            return u

        ori = conta("Demo Orientador", Usuario.Papel.ORIENTADOR, telefone="(85) 98888-0000")
        config = Configuracao.atual()
        if not config.nome_escola:
            config.nome_escola, config.municipio_escola = "EEEP Escola de Demonstração", "Fortaleza"
            config.save()
        info = Curso.objects.get_or_create(nome="Técnico em Informática", defaults={"carga_horaria": 300, "horas_por_dia_padrao": 8})[0]
        enf = Curso.objects.get_or_create(nome="Técnico em Enfermagem", defaults={"carga_horaria": 600, "horas_por_dia_padrao": 4})[0]
        l1 = LocalEstagio.objects.create(
            nome="Prefeitura — Núcleo de TI", razao_social="Prefeitura Municipal de Demonstração", tipo_instituicao="PUBLICA",
            atividade="Administração pública municipal", cnpj=cnpj_ficticio(11222333), matriz_filial="MATRIZ",
            endereco="Rua Major Facundo", numero="500", bairro="Centro", cidade="Fortaleza", cep="60025-100",
            telefone="(85) 3100-0000", link_mapa="https://maps.google.com/?q=Fortaleza",
            representante_nome="Helena Prado Matos", representante_email="gabinete@exemplo.gov.br",
            representante_cpf=cpf_ficticio(123456780), representante_documento="RG 2000000001 SSP/CE",
        )
        l2 = LocalEstagio.objects.create(
            nome="Hospital Municipal", razao_social="Hospital Municipal de Demonstração", tipo_instituicao="PUBLICA",
            cnpj=cnpj_ficticio(44555666), endereco="Av. Bezerra de Menezes", numero="1200", bairro="São Gerardo",
            cidade="Fortaleza", telefone="(85) 3200-0000",
        )
        ana = conta("Ana Beatriz Rocha", Usuario.Papel.SUPERVISOR, concedente=l1, cargo="Coordenadora de TI", telefone="(85) 99999-1111")
        carlos = conta("Carlos Mendes", Usuario.Papel.SUPERVISOR, concedente=l2, cargo="Enfermeiro chefe", telefone="(85) 99999-2222")

        inicio = hoje - timedelta(days=40)
        inicio -= timedelta(days=inicio.weekday())  # segunda-feira
        mudanca = hoje + timedelta(days=(7 - hoje.weekday()) % 7 or 7)  # próxima segunda
        alunos = [
            ("Maria da Silva Souza", info, l1, ana, "3º A"), ("João Pedro Lima", info, l1, ana, "3º A"),
            ("Beatriz Alves", info, l1, ana, "3º A"), ("Pedro Henrique Costa", info, l1, ana, "3º A"),
            ("Larissa Freitas", enf, l2, carlos, "3º B"), ("Rafael Nunes", enf, l2, carlos, "3º B"),
        ]
        DiaSemEstagio.objects.create(data=inicio + timedelta(days=14), descricao="Feriado municipal", orientador=ori)
        estagios = []
        for i, (nome, curso, local, sup, turma) in enumerate(alunos):
            u = conta(nome, Usuario.Papel.ESTAGIARIO, matricula=f"2024{1000 + i}", cpf=cpf_ficticio(987654300 + i))
            e = Estagio.objects.create(estagiario=u, orientador=ori, supervisor=sup, curso=curso, local=local,
                                       turma=turma_para(curso, turma, inicio.year),
                                       data_inicio=inicio, data_fim=inicio + timedelta(days=200))
            horas = curso.horas_por_dia_padrao
            dias_iniciais = [0, 1] if curso == info else [2, 3]  # Informática: seg/ter · Enfermagem: qua/qui
            # Informática: 8h em dois turnos (com intervalo) · Enfermagem: 4h à tarde
            turnos = ({"horario_entrada": time(7), "saida_intervalo": time(11), "volta_intervalo": time(13),
                       "horario_saida": time(17)} if curso == info else {"horario_entrada": time(13), "horario_saida": time(17)})
            Escala.objects.create(estagio=e, vigente_desde=inicio, dias=",".join(map(str, dias_iniciais)), criado_por=ori,
                                  horas_por_dia=horas, **turnos)
            Escala.objects.create(estagio=e, vigente_desde=mudanca, dias="0,1,2,3,4", criado_por=ori, horas_por_dia=horas, **turnos)
            estagios.append(e)
            feriado = inicio + timedelta(days=14)
            dia = inicio
            while dia <= hoje:
                if dia.weekday() in dias_iniciais and dia != feriado:
                    sorteio = random.random()
                    recente = (hoje - dia).days <= 3
                    if dia == hoje and i % 2 == 1:
                        Registro.objects.create(estagio=e, data=dia, situacao="PRESENTE", horas=horas,
                                                hora_chegada=time(6, 55) if curso == info else time(12, 55), registrado_por=u)
                    elif dia == hoje:
                        pass
                    elif sorteio < 0.08 and not recente:
                        pass  # dia sem registro
                    elif sorteio < 0.16:
                        Registro.objects.create(estagio=e, data=dia, situacao="AUSENCIA", horas=0, registrado_por=u,
                                                motivo="Consulta médica", confirmacao="CONFIRMADA" if not recente else "PENDENTE")
                    else:
                        pontos = ({"hora_chegada": time(6, 50 + random.randint(0, 9)), "saida_intervalo": time(11),
                                   "volta_intervalo": time(13), "hora_saida": time(17)} if curso == info else
                                  {"hora_chegada": time(12, 50 + random.randint(0, 9)), "hora_saida": time(17)})
                        r = Registro.objects.create(
                            estagio=e, data=dia, situacao="PRESENTE", horas=horas, registrado_por=u, **pontos,
                            diario=random.choice(["", "", "Ajudei na manutenção de computadores.", "Acompanhei a equipe no atendimento.",
                                                  "Organizei a documentação do setor."]),
                        )
                        if not recente:
                            r.confirmar(sup, "CONFIRMADA")
                            r.save()
                dia += timedelta(days=1)

        Mensagem.objects.create(estagio=estagios[0], autor=estagios[0].estagiario, texto="Professor, preciso levar algum documento na visita?")
        Mensagem.objects.create(estagio=estagios[0], autor=ori, texto="Só a folha de frequência assinada. Até lá!")
        a1 = Agendamento.objects.create(tipo="VISITA", status="AGENDADO", orientador=ori, solicitante=ori, local=l1,
                                        data_hora=timezone.now() + timedelta(days=3), assunto="Visita de acompanhamento — Núcleo de TI")
        a1.estagios.set(estagios[:4])
        a2 = Agendamento.objects.create(tipo="CONVERSA", modalidade="ONLINE", status="SOLICITADO", orientador=ori,
                                        solicitante=carlos, data_sugerida="Quinta à tarde", assunto="Conversar sobre a escala da Larissa")
        a2.estagios.set([estagios[4]])
        coord = conta("Paula Lins", Usuario.Papel.COORDENADOR, telefone="(85) 98888-3333")
        coord.cursos_coordenados.set([enf])
        config.captacao_aberta = True
        config.save()
        for nome, razao, cnpj_base, vagas, contato in [
            ("Ótica Visão Clara", "Visão Clara Comércio de Óticas LTDA", 22333444, {info: 2}, "Jorge Amaral"),
            ("Clínica Bem Viver", "Bem Viver Serviços de Saúde LTDA", 55666777, {enf: 3, info: 1}, "Sônia Ribeiro"),
        ]:
            cand = Candidatura.objects.create(
                ano=config.ano_captacao_efetivo, nome=nome, razao_social=razao, cnpj=cnpj_ficticio(cnpj_base),
                tipo_instituicao="PRIVADA", endereco="Av. Santos Dumont", numero="1000", bairro="Aldeota",
                cidade="Fortaleza", contato_nome=contato, contato_telefone="(85) 99999-0000",
                atividades="Atendimento ao público, organização de documentos e apoio às rotinas do setor.",
                turnos="MANHA,TARDE", horario="07h às 11h e 13h às 17h", supervisor_nome=f"{contato} Filho",
                supervisor_telefone="(85) 99999-0001",
            )
            for curso, n in vagas.items():
                VagaCandidatura.objects.create(candidatura=cand, curso=curso, quantidade=n)
        self.stdout.write(self.style.SUCCESS(f"Demonstração criada. Mudança de escala (seg/ter → seg-sex) em {mudanca:%d/%m/%Y}."))
