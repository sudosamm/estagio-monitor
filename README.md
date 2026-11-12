# Estágio Monitor

Sistema de acompanhamento de estágio para **orientadores**, **supervisores** e **estagiários**: quem está no estágio hoje, quantas horas faltam, quais são os dias de estágio, visitas, dúvidas e arquivos, tudo num só lugar.

> É uma ferramenta de apoio. Os registros oficiais continuam no SICE.

## O que cada perfil faz

| Perfil | Pode |
|---|---|
| **Orientador** | Painel do dia (quem está presente, ausente ou ainda não marcou presença); cadastro de estagiários e supervisores em lote; cadastro completo de concedentes (mesmos campos da ficha da SEDUC); carga horária por curso; dias e horários de estágio (4, 6 ou 8 h, com intervalo) com mudança a partir de uma data, individual ou em lote; feriados e eventos da escola; quem abriu e imprimiu a folha de frequência; agendar visitas e conversas; publicar arquivos; redefinir senhas; ajustar qualquer registro |
| **Coordenador(a) de curso** | O mesmo que o orientador, só para os estágios dos cursos que coordena (sem curso marcado = todos): painel, estagiários, contas, concedentes, cursos, frequências e captação. **Não** agenda visitas, não muda dias/horários, não cadastra feriados e não publica arquivos gerais |
| **Supervisor** | Ver os seus estagiários no dia; confirmar ou contestar presenças (uma a uma ou em lote); lançar um dia que o estagiário esqueceu; ver quem imprimiu a folha de frequência; completar o próprio perfil; banco de talentos (quando aberto); pedir visita ou conversa; mensagens e arquivos |
| **Estagiário** | Marcar entrada, intervalo e saída; informar ausência (hoje, dias futuros ou até 7 dias atrás); planejar dias de reposição; ver a previsão de término mudar conforme preenche o calendário; imprimir a própria folha de frequência do mês; foto de perfil e, se habilitado, currículo; anotar como foi o dia; pedir visita ou conversa; tirar dúvidas; enviar e baixar arquivos |

Todos recebem **notificações** (o sino no topo) quando algo muda, por exemplo: presença marcada, ausência informada, escala alterada, visita agendada, mensagem ou arquivo novo.

### Contas
- Usuário gerado como `primeiro.ultimo` sem acentos (ex.: *Maria da Silva Souza* → `maria.souza`). Se já existir, recebe um número (`maria.souza2`).
- Todas as contas nascem com a `SENHA_PADRAO` e a pessoa **é obrigada a criar a própria senha** no primeiro acesso.
- O orientador pode voltar a senha de alguém para a padrão (em *Contas → Editar*).

### Dias e horários
- **Supervisor:** os horários são da concedente. Ele define dias, carga diária (4, 6 ou 8 h) e horários de cada estagiário, um por um (aba *Dias e horários* do estágio) ou vários de uma vez (*Dias e horários* no menu). O painel avisa quem ainda está sem horário definido.
- **Estagiário:** marca entrada, intervalo e saída pelos botões ou **digita os horários do dia**, como na folha de papel (até 7 dias atrás). As horas do dia são calculadas pelos horários, e o supervisor confirma.
- **Orientador:** muda só os **dias** em lote (ex.: “a partir de 16/11, segunda a sexta”). Cada estagiário mantém os horários que a concedente definiu.

### Mudança de dias (ex.: “a partir de 16/11, segunda a sexta”)
Em **Alterar dias**, escolha a data, os dias da semana e os estagiários (dá para filtrar por curso ou turma). O sistema guarda o histórico: os dias anteriores continuam valendo como antes, e a nova escala vale a partir da data escolhida. Estagiários e supervisores são avisados.

### Folha de frequência
Cada pessoa gera a folha do mês reproduzindo, medida a medida, a folha oficial da CEPAE/SEDUC: brasão, cabeçalho preenchido, fins de semana em cinza e feriados/eventos escritos na linha. O brasão padrão pode ser trocado em Configurações. A folha é só para impressão: não há botão de download.
- Toda abertura fica registrada, com o número de impressões (inclusive “Salvar como PDF”, que passa pela impressão do navegador).
- No rodapé sai um código. Em **Frequências**, o orientador e o supervisor buscam esse código para saber quem emitiu a folha e quando.
- O estagiário não vê nada desse registro.
- Escola, município, cabeçalho e logotipo da folha ficam em **Configurações** (menu do usuário, só para o administrador).

### Supervisor e concedente
Todo estágio precisa de **concedente** e **supervisor**, e o supervisor tem de estar **cadastrado nessa concedente**. Os formulários só mostram os supervisores da concedente escolhida e recusam outro.
- **Mais de uma concedente:** um supervisor pode estar em várias concedentes. Vincule-o na ficha da concedente, em “Vincular supervisor já cadastrado em outra concedente”, ou na edição da conta.
- **Desvincular:** não é possível tirar um supervisor de uma concedente onde ele ainda supervisiona estagiários ativos.
- **Na importação por CSV:** o supervisor de cada linha fica vinculado à concedente daquela linha. Se a mesma pessoa já existir em outra concedente, a prévia avisa para você conferir.

### Previsão de término
A previsão parte das horas que faltam e percorre a escala, pulando feriados e eventos da escola. Também entra o que o estagiário marca no calendário:
- **Ausência futura** (evento, prova, consulta): a previsão é adiada.
- **Dia extra / reposição**, inclusive em sábados ou feriados: a previsão é antecipada.

O sistema avisa na hora quanto a data mudou. A data de término do termo é só informativa: o calendário segue até o fim previsto.

### Perfil, foto e banco de talentos
Todos podem pôr foto no perfil. As fotos só aparecem para quem está logado.

Em **Configurações** existem dois interruptores:
- **Currículos:** libera para os estagiários o perfil profissional (apresentação, habilidades e currículo em PDF).
- **Banco de talentos:** mostra esses perfis aos supervisores das concedentes.

Só aparece no banco quem marcar “Mostrar meu perfil às concedentes”.

### Importação em massa (CSV)
Em **Contas → Importar CSV** (só administrador), envie um CSV com **uma linha por estagiário**: dados do estagiário, a concedente (unidade) e o supervisor dele. Clique em **Baixar modelo CSV** para ver todas as colunas.
- **Sem duplicar:** concedentes e supervisores que se repetem são cadastrados uma vez só. Órgãos com várias unidades no mesmo CNPJ viram uma concedente por nome de unidade.
- **Prévia:** primeiro aparece uma prévia com tudo o que será criado e os erros de cada linha, e nada é gravado até você confirmar.
- **Padrões:** dias e horários vazios no CSV usam os padrões escolhidos na tela.
- **Estágio já em andamento:** “Acompanhar no sistema a partir de” evita que os dias anteriores apareçam como sem registro. As horas já feitas vão na coluna `horas_anteriores`.
- **Reenvio:** reenviar o mesmo arquivo não duplica, porque estagiários com o mesmo CPF e estágio ativo são ignorados.

O arquivo gerado a partir dos TCEs fica em `importacao/`, pasta que não vai para o Git porque tem dados pessoais.

### Captação de concedentes
Em **Configurações**, abra a captação, escolha o ano letivo e, se quiser, um prazo. A página pública **/seja-concedente/** (link também na tela de login) recebe os cadastros:
- dados da ficha de concedente;
- vagas desejadas por curso;
- atividades, turnos, horário e benefícios;
- contato de quem preencheu e supervisor indicado.

Em **Captação**, o orientador ou o coordenador do curso vê o total de vagas por curso e analisa cada cadastro:
- **Aprovar:** cadastra a concedente (ou completa uma já existente com o mesmo CNPJ/nome) e cria a conta do supervisor indicado.
- **Recusar:** registra o motivo.

Nos dois casos o sistema prepara uma mensagem para a concedente. Por enquanto o envio é manual: um botão abre o WhatsApp ou o e-mail com o texto pronto, e depois se marca o aviso como enviado. Os avisos ficam guardados para um envio automático no futuro.

### Permissões
As permissões de cada papel ficam em uma tabela só, `PERMISSOES_POR_PAPEL` em `core/models.py`. Para tirar ou dar algo ao coordenador, basta editar o conjunto dele. O administrador pode tudo.

| Permissão | Orientador | Coordenador |
|---|---|---|
| Painel, estagiários, lançar/validar registros | ✔ | ✔ |
| Cadastrar estagiários | ✔ | ✔ (escolhe o orientador) |
| Contas, concedentes e cursos | ✔ | ✔ |
| Captação de concedentes | ✔ | ✔ |
| Frequências impressas | ✔ | ✔ |
| Agendar visitas | ✔ | — |
| Mudar dias em lote (cada um mantém seus horários) | ✔ | — |
| Feriados e eventos | ✔ | — |
| Arquivos gerais | ✔ | — |

Coordenadores são criados pelo administrador em **Contas → + Coordenador**.

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
3. Em *Environment Variables* (no modo Compose elas já aparecem listadas), preencha:
   - `SECRET_KEY`: uma chave longa e aleatória
   - `ALLOWED_HOSTS`: o domínio do túnel, sem `https://` (ex.: `estagio.seudominio.com.br`)
   - `CSRF_TRUSTED_ORIGINS`: o mesmo domínio, com `https://`
   - `SENHA_PADRAO`: a senha inicial das contas
   - `ADMIN_NOME`: seu nome completo, que cria o primeiro orientador administrador
   - `PORTA`: a porta livre do servidor que o túnel vai usar (ex.: `8010`)
4. Garanta que o volume `/data` é persistente. No modo Compose isso já vem configurado.
5. Faça o deploy. No Cloudflare Tunnel, aponte o hostname para `http://localhost:<PORTA>` (ou o IP da VPS, se o cloudflared rodar em outra máquina).
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
