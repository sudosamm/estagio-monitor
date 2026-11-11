"""Cria dados fictícios para conhecer o sistema.

Todas as contas usam a SENHA_PADRAO e já estão liberadas (sem troca obrigatória).
Contas criadas: orientador 'demo.orientador', supervisores 'ana.rocha' e 'carlos.mendes',
estagiários 'maria.souza', 'joao.lima', 'beatriz.alves', 'pedro.costa', 'larissa.freitas', 'rafael.nunes'.
"""
import random
from datetime import date, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import (
    Agendamento, Curso, DiaSemEstagio, Escala, Estagio, LocalEstagio, Mensagem, Registro, Usuario,
)
from core.services import criar_usuario


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

        ori = conta("Demo Orientador", Usuario.Papel.ORIENTADOR)
        info = Curso.objects.get_or_create(nome="Técnico em Informática", defaults={"carga_horaria": 300, "horas_por_dia_padrao": 4})[0]
        enf = Curso.objects.get_or_create(nome="Técnico em Enfermagem", defaults={"carga_horaria": 600, "horas_por_dia_padrao": 6})[0]
        l1 = LocalEstagio.objects.create(nome="Prefeitura — Núcleo de TI", endereco="Rua Major Facundo, 500", bairro="Centro",
                                         cidade="Fortaleza", telefone="(85) 3100-0000", link_mapa="https://maps.google.com/?q=Fortaleza")
        l2 = LocalEstagio.objects.create(nome="Hospital Municipal", endereco="Av. Bezerra de Menezes, 1200", bairro="São Gerardo",
                                         cidade="Fortaleza", telefone="(85) 3200-0000")
        ana = conta("Ana Beatriz Rocha", Usuario.Papel.SUPERVISOR, local=l1, cargo="Coordenadora de TI", telefone="(85) 99999-1111")
        carlos = conta("Carlos Mendes", Usuario.Papel.SUPERVISOR, local=l2, cargo="Enfermeiro chefe", telefone="(85) 99999-2222")

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
            u = conta(nome, Usuario.Papel.ESTAGIARIO, matricula=f"2024{1000 + i}")
            e = Estagio.objects.create(estagiario=u, orientador=ori, supervisor=sup, curso=curso, local=local, turma=turma,
                                       data_inicio=inicio, data_fim=inicio + timedelta(days=200))
            horas = curso.horas_por_dia_padrao
            dias_iniciais = [0, 1] if curso == info else [2, 3]  # Informática: seg/ter · Enfermagem: qua/qui
            Escala.objects.create(estagio=e, vigente_desde=inicio, dias=",".join(map(str, dias_iniciais)), horario_entrada=time(13), criado_por=ori,
                                  horario_saida=time(13 + int(horas)), horas_por_dia=horas)
            Escala.objects.create(estagio=e, vigente_desde=mudanca, dias="0,1,2,3,4", horario_entrada=time(13), criado_por=ori,
                                  horario_saida=time(13 + int(horas)), horas_por_dia=horas)
            estagios.append(e)
            feriado = inicio + timedelta(days=14)
            dia = inicio
            while dia <= hoje:
                if dia.weekday() in dias_iniciais and dia != feriado:
                    sorteio = random.random()
                    recente = (hoje - dia).days <= 3
                    if dia == hoje and i % 2 == 1:
                        Registro.objects.create(estagio=e, data=dia, situacao="PRESENTE", horas=horas, hora_chegada=time(12, 55),
                                                registrado_por=u)
                    elif dia == hoje:
                        pass
                    elif sorteio < 0.08 and not recente:
                        pass  # dia sem registro
                    elif sorteio < 0.16:
                        Registro.objects.create(estagio=e, data=dia, situacao="AUSENCIA", horas=0, registrado_por=u,
                                                motivo="Consulta médica", confirmacao="CONFIRMADA" if not recente else "PENDENTE")
                    else:
                        r = Registro.objects.create(
                            estagio=e, data=dia, situacao="PRESENTE", horas=horas, hora_chegada=time(12, 50 + random.randint(0, 9)),
                            hora_saida=time(13 + int(horas)), registrado_por=u,
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
        self.stdout.write(self.style.SUCCESS(f"Demonstração criada. Mudança de escala (seg/ter → seg-sex) em {mudanca:%d/%m/%Y}."))
