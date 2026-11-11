# Estágio Monitor

Sistema de acompanhamento de estágio para **orientadores**, **supervisores** e **estagiários**: quem está no estágio hoje, quantas horas faltam, quais são os dias de estágio, visitas, dúvidas e arquivos, tudo num só lugar.

> É uma ferramenta de apoio. Os registros oficiais continuam no SICE.

## O que cada perfil faz

| Perfil | Pode |
|---|---|
| **Orientador** | Painel do dia (quem está presente, ausente ou ainda não marcou presença); cadastro de estagiários e supervisores em lote; carga horária por curso; dias de estágio com mudança a partir de uma data, individual ou em lote; feriados e recessos; agendar visitas e conversas; publicar arquivos; redefinir senhas; ajustar qualquer registro |
| **Supervisor** | Ver os seus estagiários no dia; confirmar ou contestar presenças (uma a uma ou em lote); lançar um dia que o estagiário esqueceu; pedir visita ou conversa; mensagens e arquivos |
| **Estagiário** | Marcar presença e saída; informar ausência (hoje, dias futuros ou até 7 dias atrás); anotar como foi o dia; calendário colorido e horas cumpridas com previsão de término; pedir visita ou conversa; tirar dúvidas; enviar e baixar arquivos |

Todos recebem **notificações** (o sino no topo) quando algo muda, por exemplo: presença marcada, ausência informada, escala alterada, visita agendada, mensagem ou arquivo novo.

### Contas
- Usuário gerado como `primeiro.ultimo` sem acentos (ex.: *Maria da Silva Souza* → `maria.souza`). Se já existir, recebe um número (`maria.souza2`).
- Todas as contas nascem com a `SENHA_PADRAO` e a pessoa **é obrigada a criar a própria senha** no primeiro acesso.
- O orientador pode voltar a senha de alguém para a padrão (em *Contas → Editar*).

### Mudança de dias (ex.: “a partir de 16/11, segunda a sexta”)
Em **Alterar dias**, escolha a data, os dias da semana e os estagiários (dá para filtrar por curso ou turma). O sistema guarda o histórico: os dias anteriores continuam valendo como antes, e a nova escala vale a partir da data escolhida. Estagiários e supervisores são avisados.

### Como as horas são contadas
- Só contam as horas de presenças **confirmadas pelo supervisor** (ou pelo orientador).
- Presenças aguardando confirmação aparecem listradas na barra de progresso.
- A previsão de término simula os próximos dias da escala, sem contar feriados e recessos.
- Para quem já tinha horas antes de começar a usar o sistema, preencha *Horas já cumpridas antes do sistema* na edição do estágio.

## Rodar no computador (desenvolvimento)

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python manage.py migrate
```

```bash
.venv/bin/python manage.py popular_demo
```

```bash
DEBUG=1 COOKIES_SEGUROS=0 .venv/bin/python manage.py runserver
```

Acesse http://localhost:8000. O comando `popular_demo` cria contas fictícias (a lista está no topo de `core/management/commands/popular_demo.py`), todas com a senha padrão.

Testes automatizados:

```bash
.venv/bin/python manage.py test core
```

## Colocar na VPS (Coolify + Cloudflare Tunnel)

O serviço sobe com **Gunicorn na porta 8000** dentro do container. O banco (SQLite) e os anexos ficam no volume `/data`, então **não se perdem** ao atualizar.

1. Suba este projeto para um repositório Git (privado).
2. No Coolify: **New Resource → Docker Compose** (ou *Dockerfile*) apontando para o repositório.
3. Em *Environment Variables*, cadastre as variáveis do `.env.example`. As principais:
   - `SECRET_KEY`: uma chave longa e aleatória
   - `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS`: o domínio que você vai usar no túnel
   - `SENHA_PADRAO`: a senha inicial das contas
   - `ADMIN_NOME`: seu nome completo, que cria o primeiro orientador administrador
4. Garanta que o volume `/data` é persistente. No modo Compose isso já vem configurado.
5. Faça o deploy. No Cloudflare Tunnel, aponte o hostname para `http://<host>:8000` (ou para a porta definida em `PORTA`).
6. Entre com o usuário gerado a partir de `ADMIN_NOME` (aparece no log do container) e a senha padrão. O sistema vai pedir para trocar a senha.

Para criar outros orientadores depois: entre como administrador → *Contas* → *+ Orientador*, ou pelo terminal do container:

```bash
python manage.py criar_orientador "Nome Completo"
```

### Backup
Tudo fica em `/data` (`db.sqlite3` e a pasta `anexos/`). Copiar esse volume já é um backup completo.

## Primeiros passos como orientador
1. **Cursos**: cadastre os cursos com a carga horária (ex.: Informática, 300h).
2. **Locais**: cadastre as concedentes (endereço, telefone, link do mapa).
3. **Contas → + Supervisores**: um por linha, vinculados ao local.
4. **Estagiários → Cadastrar estagiários**: cole os nomes (um por linha), escolha curso, local, supervisor, data de início e dias. Ao final aparece a lista de usuários para imprimir ou repassar.
5. **Feriados**: cadastre os dias sem estágio.

## Estrutura

```
core/models.py      Usuários, cursos, locais, estágios, escalas, registros, agenda, arquivos, mensagens
core/services.py    Regras: geração de usuário, status de cada dia, horas e previsão, notificações
core/views/         Telas por área (comum, estágio, orientador, supervisor, agenda)
templates/          HTML (visual inspirado no portal ce.gov.br)
static/             CSS e JS próprios, sem frameworks
```

## Ideias para as próximas versões
- Notificação por e-mail ou WhatsApp, além do sino
- Importar estagiários de uma planilha (CSV/Excel) exportada do SICE
- Check-in com geolocalização (confirmar que o estagiário está perto do local)
- Avaliação do estagiário pelo supervisor (formulário periódico)
- Relatório geral em PDF por turma
- Instalar como app no celular (PWA)
