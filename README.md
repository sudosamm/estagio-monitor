# Estágio Monitor

Sistema de acompanhamento de estágio para **orientadores**, **supervisores** e **estagiários**: quem está no estágio hoje, quantas horas faltam, quais são os dias de estágio, visitas, dúvidas e arquivos, tudo num só lugar.

> É uma ferramenta de apoio. Os registros oficiais continuam no SICE.

## O que cada perfil faz

| Perfil | Pode |
|---|---|
| **Orientador** | Painel do dia (quem está presente, ausente ou ainda não marcou presença); cadastro de estagiários e supervisores em lote; cadastro completo de concedentes (mesmos campos da ficha da SEDUC); carga horária por curso; dias e horários de estágio (qualquer carga diária: 4, 5, 7 h…, com intervalo) com mudança a partir de uma data, individual ou em lote; feriados e eventos da escola; quem abriu e imprimiu a folha de frequência; agendar visitas e conversas; publicar arquivos; redefinir senhas; ajustar qualquer registro |
| **Coordenador(a) de curso** | O mesmo que o orientador, só para os estágios dos cursos que coordena (sem curso marcado = todos): painel, estagiários, contas, concedentes, cursos, frequências e captação. **Não** agenda visitas, não muda dias/horários, não cadastra feriados e não publica arquivos gerais |
| **Supervisor** | Ver os seus estagiários no dia; confirmar ou contestar presenças (uma a uma ou em lote); lançar um dia que o estagiário esqueceu; ver quem imprimiu a folha de frequência; completar o próprio perfil; banco de talentos (quando aberto); pedir visita ou conversa; mensagens e arquivos |
| **Estagiário** | Marcar entrada, intervalo e saída; informar ausência (hoje, dias futuros ou até 7 dias atrás); planejar dias de reposição; ver a previsão de término mudar conforme preenche o calendário; imprimir a própria folha de frequência do mês; foto de perfil e, se habilitado, currículo; anotar como foi o dia; pedir visita ou conversa; tirar dúvidas; enviar e baixar arquivos |

Todos recebem **notificações** (o sino no topo) quando algo muda, por exemplo: presença marcada, ausência informada, escala alterada, visita agendada, mensagem ou arquivo novo. Com o servidor de e-mail configurado, os mesmos avisos vão também por **e-mail** (ver *Avisos por e-mail*).

### Menu da gestão
Para orientador, coordenação e administrador, a barra tem **Painel** e **Estagiários** soltos e três menus:
- **Acompanhamento:** indicadores, resumo da semana, agenda de visitas, frequências, feedback dos supervisores, atestados, pasta de documentos, alterar dias.
- **Comunicação:** avisos para a turma, arquivos gerais e, para o administrador, opiniões sobre o sistema.
- **Cadastros:** contas, concedentes, turmas e cursos, feriados e recessos, captação, banco de talentos, encerramento do ano.

O número de pendências (atestados para analisar, concedentes na captação) aparece no nome do menu e no item. Cada pessoa só vê o que tem permissão de usar. Estagiários e supervisores continuam com a barra simples.

### Painel do orientador (página inicial)
- **Calendário do mês** no topo, com setas para outros meses e “Hoje”. Cada dia mostra:
  - visitas e conversas com o horário (laranja e azul), solicitações que já têm data (amarelo);
  - fim do termo (vermelho), previsão de conclusão da carga horária (verde), início de estágio e aniversários dos estagiários;
  - feriados e recessos listrados;
  - uma bolinha vermelha com quantos estagiários ficaram **sem registro** naquele dia.
- Clicar num dia mostra tudo dele ao lado, sem recarregar, com o botão **Agendar neste dia** (abre o agendamento já com a data). No celular, o calendário mostra bolinhas coloridas no lugar dos textos.
- Abaixo continuam os números do dia, quem está no estágio hoje, solicitações, próximas visitas e presenças aguardando o supervisor.

### Agendar visita ou conversa
- A lista de estagiários tem **busca** (nome ou concedente) e “Só os marcados”.
- Ao marcar um estagiário, aparece ao lado a **ficha** dele: concedente com endereço, telefone e **Abrir no mapa**; supervisor com telefone e WhatsApp; dias e horários; próximos dias de estágio; horas e previsão de término; dias sem registro, presenças a validar e faltas; última e próxima visita; e quem mais estagia na mesma concedente (com botão para incluir na mesma visita).
- O sistema **preenche** o local, o assunto (“Visita de acompanhamento — Ana e Bruno”) e mostra os **dias de estágio em comum** de quem foi escolhido, para marcar com um toque. Nada do que você digitou é apagado.
- **Avisos** antes de salvar: quando o estagiário não tem estágio no dia escolhido (fora da escala, feriado ou depois do fim), e quando você já tem outro compromisso perto daquele horário.
- A página da visita mostra as mesmas fichas em “Dados para a visita”, para consultar no celular durante a visita.

### Roteiro de visitas e busca rápida
- **Acompanhamento → Roteiro de visitas** (ou “Roteiro de visitas do dia” no calendário do painel): para o dia escolhido, as concedentes que têm estagiário no local, com o horário, quem está lá, há quantos dias foi a última visita e se já há visita marcada.
- Com a localização cadastrada na concedente, as mais próximas entre si ficam juntas. Marque as paradas (até 10) e toque em **Abrir o roteiro no mapa**: o Google Maps traça o caminho a partir de onde você estiver. As que nunca tiveram visita, ou estão há mais de 30 dias sem, já vêm marcadas.
- **Agendar** em cada parada abre o agendamento com o dia, o horário de entrada e os estagiários daquela concedente.
- **Por município:** com concedentes em mais de uma cidade no dia, escolha o município e todas as dele vêm marcadas.
- **Agendamento rápido:** marque as concedentes, escolha a hora de começar, o tempo de cada visita e o deslocamento mínimo e toque em *Ver a agenda proposta*. O sistema ordena a rota (manhã antes da tarde, pelo horário dos estagiários; em cada turno, a mais próxima em seguida), espera o estagiário chegar, **não marca nada entre 12h e 13h** e pula os compromissos que você já tem no dia. Com a localização das concedentes, o deslocamento é estimado pela distância (o valor escolhido é o mínimo). A prévia avisa se alguma visita termina depois da saída do estagiário ou das 18h. *Criar e avisar* cria uma visita por concedente (com a duração escolhida) e avisa estagiários e supervisores; depois dá para mudar ou cancelar cada uma na agenda. Concedentes que já têm visita marcada no dia ficam de fora.
- Cada agendamento tem agora uma **duração** (vazio = padrão do tipo: visita 90 min, conversa 30, reunião 60), usada no aviso de conflito e no calendário do celular.
- **Busca rápida** (gestão): botão *Buscar* na barra, tecla `/` ou `Ctrl+K`. Acha estagiários (pelo nome, em qualquer ordem e sem acento), concedentes, supervisores e páginas do menu. ↑ ↓ e Enter abrem.

### Equipe da concedente e substituições
- Uma pessoa da concedente pode ser **responsável**: em **Concedentes → (concedente) → Equipe e substituições**, a escola marca *Tornar responsável*. Na captação, quem preencheu o cadastro já tem conta: ao aprovar, ela vira responsável (opção marcada por padrão). Cadastros antigos, sem conta, continuam com a opção de criar a conta do responsável; a folha com o código de acesso já sai pronta.
- O responsável entra como supervisor e ganha o menu **Equipe**: cadastra pessoas da equipe (recebe o código de primeiro acesso para entregar e, se tiver e-mail, a pessoa também recebe o link para confirmar e criar a senha), corrige telefone, e-mail e cargo de quem é da equipe (*Ações → Contato*), gera novo acesso para quem esqueceu a senha e desativa quem saiu. Só mexe nas contas que são apenas das concedentes que ele gere. Contas usadas em outra concedente ficam com a escola.
- **Permissão temporária (substituição):** o responsável, a escola ou o próprio supervisor (“Vou me ausentar”, no painel dele) indica quem confirma as presenças no lugar do supervisor, de uma data a outra (até 92 dias). Durante o período, o substituto vê esses estagiários no painel e confirma, contesta ou lança os dias. Mensagens, atestados, arquivos, feedback e horários continuam só com o supervisor titular e a escola. Pode ser encerrada a qualquer momento. Todos os envolvidos e os orientadores recebem aviso.
- O responsável vê os estagiários da própria concedente com as mesmas regras do substituto.

### Supervisor: “Confirmar todas” por e-mail ou WhatsApp e resumo do mês
- Uma vez por semana (dia escolhido em **Configurações**, a partir das 14h; padrão sexta), cada supervisor com presenças esperando recebe por e-mail a lista e um link **Confirmar todas**. O link abre a lista sem senha e confirma num botão, para que o antivírus do e-mail, que abre links sozinho, não confirme nada. Vale 7 dias e uma vez só, e só confirma o que ainda estiver pendente e ainda for daquele supervisor. Para contestar um dia, é preciso entrar no sistema.
- No painel do orientador, **Supervisores com presenças para confirmar** tem os botões **WhatsApp** (abre a conversa com a mensagem e um link novo prontos) e **E-mail**.
- No dia 1º de cada mês, a partir das 7h, cada supervisor recebe o **resumo do mês anterior**: presenças, horas, faltas, ausências, o que falta confirmar, total de horas e previsão de término de cada estagiário.
- Os textos ficam em **Configurações → E-mails automáticos** e as opções em **Configurações**.

### Lembrete de fim de expediente
Quem não marcou a presença, ou marcou a entrada e esqueceu a saída, recebe um aviso no celular e no sino algum tempo depois do horário de saída da escala (padrão: 60 minutos; ajuste em **Configurações**). Feriados, ausências informadas e quem já concluiu a carga horária não recebem. É no máximo um por dia, entre 7h e 22h, e não vai por e-mail. Cada estagiário pode desligar em **Meus dados**.

### Privacidade, termos e segurança da conta
- **Termos de Uso** e **Aviso de Privacidade** (LGPD) no rodapé de todas as páginas e na tela de entrada. Eles dizem quais dados existem, para quê, a base legal (Lei do Estágio, LGPD art. 7º, II e III, art. 11 e art. 14), quem vê, por quanto tempo, como são protegidos e os direitos de cada pessoa. O texto usa o nome da escola, o prazo de guarda e o contato configurados.
- No primeiro acesso, a pessoa marca que leu e concorda. Quem já usava o sistema vê a tela de aceite uma vez. Ao mudar algo importante no texto, troque `VERSAO` em `core/termos.py` e todos aceitam de novo.
- **Meus dados → Segurança e privacidade:** os últimos acessos e **Baixar meus dados** (cópia em JSON de tudo o que o sistema guarda sobre a pessoa).
- **Acessos e aparelhos** (*Meus dados → Ver todos os acessos e aparelhos*): a lista completa das entradas, saídas, senhas e códigos errados e sessões encerradas (data, aparelho e IP, 30 por página) e os **aparelhos conectados agora**, com *Desconectar* em cada um e *Desconectar os outros*.
- **Sessão presa ao aparelho:** cada login guarda o grupo do sistema (Windows; Android/Linux; Apple) e a família do navegador, além de um cookie próprio do aparelho (`aparelho`, separado do da sessão). Se o cookie de login aparecer em outro navegador ou sistema, ou sem o cookie do aparelho, a sessão é encerrada no servidor na hora (nos dois lugares, porque é a mesma sessão), a pessoa recebe aviso no sino e por e-mail e fica no registro (*Sessão usada em outro aparelho*). Sair ou desconectar vale no servidor: quem tiver uma cópia do cookie fica de fora. Trocar a senha desconecta os outros aparelhos; desativar a conta ou gerar novo primeiro acesso desconecta todos. Limite: quem copiar todos os cookies e imitar o mesmo navegador e sistema não é detectado por nenhum site; para isso existe a verificação em duas etapas. A “versão para computador” do celular não desconecta.
- Na gestão, *Contas → Editar → Desconectar de todos os aparelhos* (celular perdido ou roubado).
- **Entrar com o e-mail:** a tela de entrada aceita o usuário ou o e-mail, quando um único cadastro ativo usa aquele e-mail. Os limites de tentativas contam igual para os dois.
- **Verificação em duas etapas:** em **Meus dados**, para gestão e supervisores. Usa um app autenticador (Google ou Microsoft Authenticator, Authy, 2FAS…) e 8 códigos de recuperação de uso único. Dá para marcar “não pedir de novo neste aparelho por 30 dias”. Em **Configurações → Exigir verificação em duas etapas da gestão**, orientadores, coordenadores, administradores e responsáveis por concedentes precisam configurar no próximo acesso. Quem perdeu o celular pede um novo primeiro acesso, que zera a verificação. O `/admin/` entra pela mesma tela de login, com os mesmos limites.
- **Registro de ações** (*Sistema → Registro de ações*, administrador): entradas, senhas e códigos errados, mudanças feitas pela gestão e pelas concedentes (contas, códigos, estágios, horários, feriados, configurações, equipe), confirmações pelo link e downloads de dados pessoais (planilhas, relatórios, declarações, atestados, currículos). Guarda quem, o quê, sobre quem, quando, IP e aparelho, nunca o que foi digitado. Fica 1 ano.
- **Erros do sistema** (*Sistema → Erros do sistema*): toda página que dá erro e toda tarefa em segundo plano que falha (e-mails, resumos, lembretes) vira um aviso no sino e por e-mail ao administrador. O mesmo erro é agrupado e avisa de novo no máximo a cada 6 horas. Tem o detalhe técnico para quem cuida do código e o botão *Resolvido*.

### Período de testes: “Sua opinião”
- Com **Configurações → Sistema em período de testes** ligado (padrão), estagiários e supervisores veem o botão **Sua opinião** no canto da tela, em todas as páginas.
- Ele abre uma janela com uma nota (de 😍 a 😣), o assunto (sugestão, algo deu errado, elogio, dúvida) e um comentário opcional. A página onde a pessoa estava vai junto. Para mandar print, há o atalho para *Sugestões e erros*.
- Tudo fica em **Comunicação → Opiniões sobre o sistema** (administrador): nota média, distribuição das notas, quem mandou, páginas mais citadas, filtros e o botão **Resolvida**. Erros e notas 1 ou 2 também avisam o administrador no sino.

### Tema escuro
Além do visual claro dos portais do governo, há um tema escuro próprio, **“Noite no sertão”**. O fundo é verde-mata profundo, em vez de cinza. O amarelo do sol marca a aba e o campo em foco, e os botões ficam no verde do Ceará. A faixa verde, amarela e laranja do cabeçalho continua. Os contrastes foram conferidos: textos com pelo menos 4,5:1, bordas e gráficos com pelo menos 3:1.
- Cada pessoa escolhe no menu dela (foto, no canto): **Auto** (segue o modo do celular ou do computador), **Claro** ou **Escuro**. A troca é na hora e fica salva na conta.
- O administrador libera ou bloqueia a escolha em **Configurações** ou no **painel Django** (*Administração → Configurações do sistema → Permitir o tema escuro*). Bloqueado, o sistema fica sempre claro para todos.
- Folha de frequência, relatórios e declaração continuam brancos, porque são para imprimir.

### App no celular
O sistema pode ser **instalado como app** (PWA): ícone na tela inicial, abre em tela cheia, sem barra do navegador.
- **Android (Chrome):** menu do usuário → *Instalar no celular*, ou o aviso “Instalar app” do próprio Chrome.
- **iPhone (Safari):** Compartilhar → *Adicionar à Tela de Início*.
- O app não guarda páginas com dados pessoais no aparelho: só o visual (CSS, ícones). Sem internet, aparece uma tela “Sem conexão”, e a presença só é marcada online, com o horário do servidor.

### Calendário do estágio
- Cada dia é um “recipiente”: a cada horário que o estagiário marca (entrada, saída para o intervalo, volta e saída), a água sobe 25% (sem intervalo na escala, 50% por horário), com uma onda leve. O dia mostra a porcentagem até ficar completo.
- Confirmado pelo supervisor sem todos os horários, o dia vira grama até o nível em que estava. Completo e confirmado, fica todo verde.
- Presença lançada só com as horas (sem horário) conta como completa. Quem prefere menos movimento (opção do celular) vê o nível sem animação.

### Contas
- Usuário gerado como `primeiro.ultimo` sem acentos (ex.: *Maria da Silva Souza* → `maria.souza`). Se já existir, recebe um número (`maria.souza2`).
- **Não existe senha inicial.** As contas nascem sem senha, e cada pessoa cria a sua em **Primeiro acesso** (link na tela de login, `/primeiro-acesso/`):
  - **Estagiário:** nome completo (acentos e maiúsculas não importam) + data de nascimento. A data vem da importação (coluna `estagiario_nascimento`), do cadastro em lote (`Nome; matrícula; 26/04/2008`) ou de *Contas → Editar*.
  - **Supervisor, orientador, coordenador ou estagiário sem data de nascimento:** usuário + **código de uso único** (ex.: `K7PM-3QXD`), gerado pela gestão. Vale uma vez, por 30 dias, e só aparece na tela em que foi gerado: o sistema guarda apenas um resumo dele.
  - A folha impressa depois de criar contas (cadastro, importação) já traz o código de quem precisa. Para quem ainda não entrou, *Contas → Situação: Ainda não entraram → Folha de primeiro acesso* gera a folha de novo, com códigos novos.
  - Depois de criar a senha, o primeiro acesso fecha para aquela conta.
- **Esqueceu a senha:** em *Contas → Editar*, “Esqueceu a senha: novo primeiro acesso”. A senha atual deixa de valer e aparece um código novo.
- **Contas antigas** criadas com a `SENHA_PADRAO` e ainda não ativadas não entram mais por senha nenhuma (nem a antiga, mesmo que a `SENHA_PADRAO` do servidor mude): usam o primeiro acesso. Quem já criou a própria senha não é afetado. Em emergência, `ACEITAR_SENHA_PADRAO=1` faz a senha padrão voltar a valer para elas. Administrador criado pelo terminal (`createsuperuser`) entra normalmente.
- **Quem gera código:** o administrador, para qualquer conta; orientador e coordenador, para os estagiários que acompanham e para supervisores que eles cadastraram ou que supervisionam algum estagiário deles. O mesmo vale para desativar um supervisor que tenha estagiários de outro orientador (só o administrador). As telas com código não ficam no cache do navegador.
- **E-mail confirmado:** quem não tem e-mail confirmado vê uma faixa no topo pedindo para cadastrar. Ao salvar o e-mail em *Meus dados*, chega um link de confirmação (vale 3 dias). Trocar o e-mail, pela pessoa ou pela gestão, exige confirmar de novo; a gestão não consegue confirmar o e-mail de ninguém.
- **Pedir a confirmação do cadastro** (gestão): em *Contas → Editar*, o cartão **E-mail** mostra se está confirmado e tem *Enviar pedido de confirmação*. Em lote: *Contas → Situação: E-mail não confirmado → Enviar pedido de confirmação* (pula quem recebeu nas últimas 24 horas). Quem **ainda não entrou** no sistema cria a senha pelo mesmo link, sem o código no papel (o link de criar a senha vale 2 horas e uma vez só). Por isso vale a mesma regra de quem gera código, e convém conferir o e-mail antes de enviar. O texto fica em *E-mails automáticos → Confirmação de cadastro*.
- **Esqueci minha senha** (link na tela de entrada): informe o usuário ou o e-mail confirmado e chega um link para criar uma senha nova (vale 2 horas, uma vez só). A resposta é sempre a mesma, exista a conta ou não. Limite: 3 pedidos por conta e 10 por rede por hora. Criar a senha nova também desbloqueia o login.
- **Avisos de segurança por e-mail** (só para e-mail confirmado): na 3ª senha errada seguida (“alguém tentou entrar”), quando o acesso fica bloqueado e sempre que a senha muda.
- **Bloqueado ou sem acesso:** a tela de entrada mostra “Falar com o administrador”. O pedido (usuário, nome, contato e mensagem) chega no sino dos administradores e no e-mail deles. Limite: 3 pedidos por rede por hora.
- **Textos dos e-mails:** em *Configurações → Textos dos e-mails automáticos* (administrador), cada e-mail (confirmação, e-mail cadastrado, redefinição de senha, senha alterada, tentativas, bloqueio, pedido de ajuda) pode ser editado, pré-visualizado, testado, desligado ou voltar ao padrão. As variáveis vão entre chaves, ex.: `{nome}`, `{link}`.
- Sem servidor de e-mail configurado, nada disso é enviado: a faixa não aparece e “Esqueci minha senha” orienta a falar com o orientador.
- **Proteção do primeiro acesso:** 10 tentativas erradas com o mesmo nome (de qualquer lugar) param o primeiro acesso dele por 24 horas; 5 por nome no mesmo aparelho/rede e 60 por rede valem por 15 minutos.
- **Proteção do login:** depois de 5 senhas erradas para o mesmo usuário (no mesmo aparelho/rede), o login espera 15 minutos. Também há limite por usuário (20) e por rede (40) na mesma janela, inclusive no `/admin/`. Entrou certo, a contagem zera.
- **Senha nova:** pelo menos 8 caracteres, não pode ser só números, uma senha comum (ex.: `password`) nem a senha inicial.
- **Desativar/reativar** (em *Contas*): a pessoa deixa de entrar, mas o histórico fica guardado.
  - **Estagiário:** o estágio ativo é encerrado junto. Ao reativar, dá para reabrir o último estágio.
  - **Supervisor com estagiários ativos:** é preciso escolher um substituto da mesma concedente para cada um.
  - **Orientador com estágios ativos:** passe os estágios para outro orientador antes.

### Turmas e ano de referência
O curso é sempre o mesmo; o que muda é a **turma de cada ano**. A turma de 2024 estagia em 2026, a de 2025 em 2027, e assim por diante. Cada turma tem curso, nome (pode repetir todo ano, ex.: “3º A”), ano de ingresso e ano do estágio.
- **Ano de referência** (em *Turmas e cursos*; vazio = ano atual): as listas de estagiários, o painel, *Alterar dias* e *Frequências* mostram só as turmas que estagiam nesse ano. Cada pessoa pode olhar outro ano (ou todos) no seletor “Ano” das listas.
- **Turmas do ano seguinte:** o botão *Turmas de 2027* cria as turmas do próximo ano com os mesmos nomes.
- **No cadastro do estágio** escolhe-se a turma, e o curso vem dela.
- **Na importação:** a turma é criada a partir das colunas `curso`, `turma` e `ano_turma` (vazio = 2 anos antes do início do estágio).
- **Estágios antigos:** quem já estava cadastrado ganhou a turma do seu curso no ano em que começou.

### Dias e horários
- **Supervisor:** os horários são da concedente. Ele define dias, carga diária (qualquer valor, como 4, 5, 7 ou 5h30, ou calculada pelos horários de entrada, intervalo e saída) e horários de cada estagiário, um por um (aba *Dias e horários* do estágio) ou vários de uma vez (*Dias e horários* no menu). O painel avisa quem ainda está sem horário definido.
- **Estagiário:** marca entrada, intervalo e saída pelos botões ou **digita os horários do dia**, como na folha de papel (até 7 dias atrás). As horas do dia são calculadas pelos horários, e o supervisor confirma.
- **Orientador:** muda só os **dias** em lote (ex.: “a partir de 16/11, segunda a sexta”). Cada estagiário mantém os horários que a concedente definiu.

### Mudança de dias (ex.: “a partir de 16/11, segunda a sexta”)
Em **Alterar dias**, escolha a data, os dias da semana e os estagiários (dá para filtrar por curso ou turma). O sistema guarda o histórico: os dias anteriores continuam valendo como antes, e a nova escala vale a partir da data escolhida. Estagiários e supervisores são avisados. Uma data anterior ao início do estágio vale como “desde o início” (ajusta a primeira escala de cada um).
- **Presenças da importação fora dos dias de estágio** (no fim da mesma página): lista as presenças lançadas pela importação (`presencas_desde`) em dias que, pela escala atual, não são de estágio, e retira as listadas com um botão. Cada dia vai para o histórico do estágio com o motivo e o estagiário recebe um aviso no sino. Presenças que alguém já ajustou e dias extras planejados ficam de fora. Uso típico: a turma foi importada como “segunda a sexta” mas ia só segunda e terça até 14/11. Corrija os dias (seg/ter desde o início e seg-sex a partir de 15/11) e depois retire as presenças que sobrarem.

### Folha de frequência
Cada pessoa gera a folha do mês reproduzindo, medida a medida, a folha oficial da CEPAE/SEDUC: brasão, cabeçalho preenchido, fins de semana em cinza e feriados/eventos escritos na linha. O brasão padrão pode ser trocado em Configurações. A folha é só para impressão: não há botão de download.
- Toda abertura fica registrada, com o número de impressões (inclusive “Salvar como PDF”, que passa pela impressão do navegador).
- No rodapé sai “Emitida em … · cód. XXXX”. Em **Frequências**, o orientador e o supervisor buscam esse código para saber quem emitiu a folha e quando. Para a folha sair sem nada fora do modelo oficial, desligue **Configurações → Escola e folha de frequência → Imprimir a data de emissão e o código no rodapé da folha** (o registro de quem abriu e imprimiu continua).
- Os dados do supervisor (nome, telefone) saem do cadastro atual: o supervisor corrige em **Meus dados** (o painel dele mostra o cartão *Seus dados na folha de frequência*) e o responsável da concedente, na página da equipe. As próximas folhas já saem com o dado novo; folhas impressas ou enviadas em PDF não mudam.
- O estagiário não vê nada desse registro.
- Escola, município, cabeçalho e logotipo da folha ficam em **Configurações** (menu do usuário, só para o administrador).

Em **Frequências**, o orientador também:
- **Emite as folhas em lote:** de uma turma, de uma concedente ou de todos, uma por página, para imprimir de uma vez.
- **Decide quem emite:** com o botão “Só eu envio as folhas”, o estagiário deixa de emitir pelo sistema e só baixa a folha que o orientador enviar. “Deixar os estagiários emitirem” volta ao normal.
- **Envia a folha de um mês** (PDF ou imagem) para uma turma inteira ou para estagiários escolhidos. Eles recebem um aviso e baixam em *Folha de frequência*. A tabela mostra quem já baixou.

### Supervisor e concedente
Todo estágio precisa de **concedente** e **supervisor**, e o supervisor tem de estar **cadastrado nessa concedente**. Os formulários só mostram os supervisores da concedente escolhida e recusam outro.
- **Mais de uma concedente:** um supervisor pode estar em várias concedentes. Vincule-o na ficha da concedente, em “Vincular supervisor já cadastrado em outra concedente”, ou na edição da conta.
- **Desvincular:** não é possível tirar um supervisor de uma concedente onde ele ainda supervisiona estagiários ativos.
- **Trocar o supervisor do estagiário:** o supervisor só sai do estágio quando o orientador ou o coordenador coloca **outro no lugar**, pelo botão *Trocar supervisor* do estágio (ou ao editar o estágio). Nunca fica sem supervisor. Cada troca fica no histórico, e o novo supervisor, o anterior e o estagiário são avisados.
- **Concedente desativada:** some dos cadastros, mas só pode ser desativada sem estagiários ativos. Dá para desativar junto as contas dos supervisores que só atuam nela. Aprovar uma nova candidatura dela na captação, ou importá-la pela planilha, reativa a concedente.
- **Na importação (planilha ou CSV):** o supervisor fica vinculado à concedente da linha. Se a mesma pessoa já existir em outra concedente, a prévia avisa para você conferir.

### Atestados e faltas justificadas
O estagiário envia a **foto (ou PDF) do atestado** ou comprovante pelo botão *Enviar atestado* (na página do estágio, no aviso “Não vou poder ir” e na página de cada dia de falta). Ele informa o tipo (atestado médico, declaração de comparecimento, convocação oficial, outro), o primeiro e o último dia. Um atestado de 3 dias cobre os 3 de uma vez, pulando fins de semana e feriados.
- Os dias de estágio do período ficam como **ausência em análise**. Faltas já lançadas também podem ser justificadas assim, até 30 dias depois.
- **Quem analisa:** o orientador, a coordenação do curso e, se a opção estiver ligada em **Configurações** (*O supervisor da concedente também analisa os atestados*), o supervisor. Eles recebem um aviso, veem o documento e clicam em *Aceitar* ou *Recusar*. Para recusar, o motivo é obrigatório.
- **Aceito:** os dias viram **ausência justificada** e não contam no limite de faltas nem nos pontos de atenção.
- **Recusado:** os dias que já passaram viram **falta**, e os futuros voltam ao normal. O estagiário pode enviar outro documento.
- Se o próprio orientador registrar um documento entregue em papel, ele já sai aceito.

**Privacidade (LGPD):** atestado é dado de saúde. O documento só aparece para o estagiário e para quem pode decidir, não vai para a folha de frequência nem para os arquivos do estágio, e é baixado sem cache. As fotos são reduzidas e perdem os metadados (inclusive a localização do celular). O formulário lembra que o CID não é obrigatório e pode ser coberto. Se preferir que a concedente não veja atestados, desligue a opção do supervisor: ele passa a ver só que o dia foi justificado. A escola acompanha tudo em **Atestados** no menu, e os pendentes também aparecem no Painel e no resumo semanal.

### Revogar presença
Para imprevistos, na página do dia há o quadro **Revogar esta presença**, com motivo obrigatório. Ele serve quando o estagiário marcou e não ficou, teve de sair ou a presença foi confirmada por engano. Há três opções:
- **remover o registro:** o dia fica sem registro;
- **trocar por ausência justificada;**
- **trocar por falta.**

O supervisor e o orientador podem revogar mesmo depois de confirmada. O estagiário só desfaz a própria marcação enquanto o supervisor não confirmou. Fica tudo no histórico do dia (quem, quando, o que era e o motivo), e as outras pessoas são avisadas. Se ele só saiu mais cedo, basta ajustar a hora de saída em *Ajustar registro*.

### Pasta de documentos
Cada estágio tem uma **pasta** (aba *Arquivos*) com os documentos exigidos. Para cada um, a pasta mostra quem envia, o prazo e a situação: pendente, atrasado, aguardando conferência, conferido ou recusado. Os documentos exigidos ficam em **Pasta → Documentos exigidos**. Já vêm sugeridos, e você pode editar:
- TCE assinado (estagiário, até 15 dias após o início);
- plano de atividades (supervisor, 30 dias);
- relatório final (estagiário, 15 dias após o término);
- avaliação pelo supervisor (15 dias após o término);
- termo de realização (opcional).

Cada documento pode valer só para um curso e ter um **modelo para baixar**.
- O estagiário ou o supervisor envia o arquivo (foto, PDF ou Word), e o orientador **confere** (*Está certo*) ou **recusa** com o motivo. A pessoa é avisada e reenvia.
- O que a escola envia já entra como conferido. Documento que já está na escola em papel: *Já está na escola, em papel*, individualmente ou em lote no quadro (ex.: todos os TCEs da turma).
- O quadro **Pasta** no menu mostra um estagiário por linha e um documento por coluna, com filtros por turma e “só com pendências”, e a lista do que está para conferir.
- O estagiário e o supervisor veem um aviso do que precisam enviar (na página do estágio e no painel do supervisor).
- Documentos atrasados entram nos pontos de atenção do relatório, na planilha, no resumo semanal e num aviso na declaração de estágio.

### Histórico das marcações
Toda mudança no registro de um dia fica guardada: **quem fez, quando e o que mudou**, com os horários de antes e depois (ex.: “marcou a entrada pelo botão às 07:58” e depois “digitou os horários: Entrada 07:58 → 07:30”).
- Também ficam registrados ausências informadas e canceladas, ajustes do supervisor/orientador e validações.
- O que foi feito **depois do dia de estágio** ganha a etiqueta “depois do dia”.
- **Onde ver:** na página de cada dia (*Histórico deste dia*) e na aba *Registros e diário* do estágio. Lá cada registro mostra quando foi informado e quantas vezes mudou, e há o histórico completo.

### Feriados (municipais, nacionais e da escola)
Em **Feriados** há três abas. Todos esses dias saem da previsão de término, não contam como falta e aparecem escritos (com a linha em cinza) na folha de frequência.
- **Municipais:** valem só para os estagiários de concedentes daquele município, pelo campo *Município* da ficha da concedente (“General Sampaio”, “GENERAL SAMPAIO - CE” e sem acento contam como o mesmo).
  - A aba lista os municípios das concedentes, com quantos estagiários há em cada um, e avisa quais ainda não têm feriado municipal.
  - “Repete todo ano nesta data” serve para datas fixas (aniversário da cidade, padroeiro): não precisa cadastrar de novo a cada ano.
  - Estagiários e supervisores daquele município recebem aviso.
- **Nacionais e estaduais:** o sistema calcula os feriados nacionais e do Ceará do ano escolhido, inclusive os móveis (Paixão de Cristo, Carnaval, Corpus Christi). O orientador confere, marca os que valem e cadastra. Pontos facultativos vêm desmarcados. Valem para todos os estagiários.
- **Da escola:** eventos e recessos do orientador, como antes. Valem só para os estagiários dele (ou de um curso).
- **Recessos das concedentes** (*Feriados → Recessos das concedentes*, ou o quadro *Recessos* na ficha da concedente): períodos em que uma concedente não recebe estagiários, como férias coletivas, recesso de fim de ano ou reforma.
  - Valem só para os estagiários daquela concedente.
  - O supervisor também cadastra, no menu *Recessos*, mas só para as concedentes em que atua.
  - Estagiários, supervisores e orientadores da concedente são avisados.
  - O período aparece como um item só (ex.: 21/12 a 31/12) e é removido de uma vez.

Feriados municipais e nacionais são compartilhados: qualquer orientador pode cadastrar ou remover.

**Importar calendário** (botão na página de Feriados) carrega feriados municipais, nacionais e o calendário letivo de um arquivo:
- **ICS:** o formato exportado pelo Google Agenda, Outlook e muitas prefeituras. Eventos de dia inteiro viram dias sem estágio, eventos de vários dias viram um período e eventos anuais viram “todo ano”. Datas comemorativas que o Google marca como “observância” (Dia das Mães…) vêm desmarcadas.
- **CSV:** use o modelo (*Baixar modelo CSV*). Colunas `data` e `descricao` são obrigatórias; `ate`, `tipo` (municipal, nacional, estadual, concedente ou escola), `municipio`, `uf`, `anual`, `curso` e `concedente` (nome da unidade ou razão social, para recessos) são opcionais. Data só com dia/mês (`23/11`) repete todo ano. Serve para vários municípios de uma vez e para recessos e férias do calendário letivo.
- **Prévia:** nada é gravado antes de você conferir. Dá para desmarcar itens, e os que já existem aparecem como “já cadastrado”.
- **Versão nova do calendário:** “Substituir o que foi importado antes” troca a importação anterior do mesmo município e anos, sem apagar o que foi cadastrado à mão.
- **Origem:** cada dia guarda de onde veio (`manual`, `calendario` ou `importado`).

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

### Importação em massa (planilha modelo ou CSV)
O SICE não exporta planilhas, então o ponto de partida é a **planilha modelo** (Excel). Em **Contas → Importar planilha** (só administrador), clique em **Baixar planilha modelo**. Ela tem uma aba para cada cadastro:
- **Concedentes:** uma linha por unidade (nome, razão social, CNPJ, endereço, município, representante legal).
- **Supervisores:** uma linha por supervisor, escolhendo a concedente numa lista suspensa.
- **Estagiários:** uma linha por estagiário, escolhendo a concedente e o supervisor nas listas. Cursos, turmas e orientadores já cadastrados também aparecem em listas.

Passe o mouse no título de cada coluna para ver a explicação. Se a concedente tiver um supervisor só na aba, a coluna *Supervisor* do estagiário pode ficar vazia. Concedentes e supervisores sem estagiário também são cadastrados. CPFs digitados como número (sem o zero à esquerda) são corrigidos. Erros aparecem por aba e linha (ex.: “Supervisores, linha 4: escolha a concedente”). Funciona com Excel, LibreOffice ou Google Planilhas (baixe como .xlsx).

Também dá para enviar um CSV com **uma linha por estagiário**: dados do estagiário, a concedente (unidade) e o supervisor dele. Clique em **Modelo CSV** para ver todas as colunas.
- **Sem duplicar:** concedentes e supervisores que se repetem são cadastrados uma vez só. Órgãos com várias unidades no mesmo CNPJ viram uma concedente por nome de unidade.
- **Prévia:** primeiro aparece uma prévia com tudo o que será criado e os erros de cada linha, e nada é gravado até você confirmar.
- **Padrões:** dias e horários vazios no CSV usam os padrões escolhidos na tela.
- **Estágio já em andamento:** “Acompanhar no sistema a partir de” evita que os dias anteriores apareçam como sem registro. As horas já feitas vão na coluna `horas_anteriores`.
- **Reenvio:** reenviar o mesmo arquivo não duplica, porque estagiários com o mesmo CPF e estágio ativo não ganham outro estágio. Se a linha trouxer algo que faltava no cadastro (data de nascimento, telefone, e-mail, matrícula), isso é completado: a prévia mostra quem será completado.
- **Data de nascimento** (`estagiario_nascimento`, dd/mm/aaaa): é o que o estagiário usa no primeiro acesso, junto com o nome completo.
- **Dias já cumpridos e ainda não lançados no SICE** (`presencas_desde`, dd/mm/aaaa): os dias da escala dessa data até ontem, fora feriados e recessos cadastrados, entram como presença confirmada (com a observação “Lançado na importação”). O sistema passa a acompanhar o estágio a partir dessa data. A prévia mostra quantos dias serão lançados, o período e os dias de estágio usados. Use junto com `horas_anteriores` = horas cumpridas no relatório do SICE.
- **Os dias mudam a partir de** (na tela, opcional): para turmas que mudaram de dias no meio do período (ex.: segunda e terça até 14/11, segunda a sexta a partir de 15/11). Cada estágio ganha as duas escalas, e as presenças de `presencas_desde` seguem a escala de cada dia.
- **Carga horária do curso** (`curso_carga_horaria`): usada só quando o curso é criado pela importação (ex.: 250 para Administração e Finanças, 300 para Redes).

O arquivo gerado a partir dos TCEs fica em `importacao/`, pasta que não vai para o Git porque tem dados pessoais. A planilha preenchida também tem dados pessoais: guarde-a em local seguro.

### Relatório geral e exportação (PDF e planilha)
Em **Turmas e cursos**, o botão *Relatório* de cada turma abre o relatório daquela turma. Na lista de **Estagiários**, o botão *Exportar* gera o mesmo relatório para **o que estiver filtrado** (curso, turma, concedente, busca, ativos/encerrados/todos e ano), em PDF ou em planilha. O relatório é uma página A4 deitada com:
- **Resumo:** estagiários ativos, média da carga cumprida, quem já cumpriu, quem termina depois do fim do termo, faltas, dias sem registro e visitas realizadas.
- **Uma linha por estagiário:** concedente, supervisor, início, fim do termo, horas cumpridas (com barra), faltas, dias sem registro, presenças a validar, previsão de término, visitas e situação.
- **Pontos de atenção:** sem supervisor, previsão depois do termo, 3 ou mais faltas, 3 ou mais dias sem registro, presenças aguardando o supervisor, nenhuma visita.
- Espaço para assinatura do orientador e da coordenação.

Clique em *Salvar PDF / imprimir* e escolha **Salvar como PDF** (funciona também no celular).

A **planilha (.xlsx)**, também disponível pelo botão *Baixar planilha* do relatório, traz quatro abas: *Resumo*, *Estagiários* (uma linha por estágio, com horas, faltas, dias sem registro, visitas, previsão, situação e pontos de atenção), *Horas por mês* (horas validadas em cada mês) e *Visitas e conversas* (com o relato). Serve para prestar contas à escola, à CREDE ou à SEDUC sem redigitar. O CPF não vai para a planilha.

### Avaliações para o SICE
No SICE, a **autoavaliação** e a **avaliação do orientador** são **mensais** (mês de referência e ano). O estagiário responde as duas pelo sistema (menu *Avaliações*, um mês por linha). Dá para salvar um rascunho e continuar depois.

Ao concluir, a tela **Copiar para o SICE** mostra:
- os campos de cima como devem ser escolhidos lá: *Mês de Referência* (ex.: NOV), *Ano* e, na avaliação do orientador, o *Orientador*;
- cada resposta na ordem do SICE, os textos com o botão *Copiar* e os itens de lista como “Selecione: …”;
- o botão *Abrir o SICE*, se o endereço estiver configurado.

No fim, ele toca em *Já colei tudo no SICE*.
- **Perguntas:** já vêm iguais às telas do SICE. A autoavaliação tem 8 campos de texto obrigatórios, de até 1000 caracteres, com o contador “caracteres restantes”. A avaliação do orientador tem 12 itens de **SIM ou NÃO** e *Observações/Sugestões*. Os textos e a ordem podem ser ajustados em *Avaliações (SICE) → Perguntas*.
- **Liberar:** em **Configurações** há *Liberar as avaliações*, *Avaliações a partir de* (o primeiro mês cobrado; vazio = desde o início de cada estágio) e o endereço do SICE.
- **Lembretes:** o estagiário vê na tela inicial quantos meses faltam. A partir do dia 20, quem não concluiu as do mês recebe um aviso (sino, celular e e-mail), como o aviso que o próprio SICE mostra.
- **Acompanhar:** o quadro mostra, mês a mês, por estagiário, *não feita*, *rascunho*, *concluída* ou *no SICE*, e quantos meses anteriores ainda estão pendentes. Tem também um botão para lembrar quem ainda não terminou.
- **Mês a mês:** na aba *Registros* do estágio há a mesma tabela da *Frequência Detalhada* do SICE (dias, horas, CH cumprida / CH total e %), para conferir.
- **Privacidade:** a autoavaliação é lida pela escola, com o nome de quem respondeu. A **avaliação do orientador é anônima para ele**:
  - o orientador vê no quadro só se cada estagiário já fez, e não é avisado de quem concluiu;
  - as respostas chegam juntas, sem nomes, em **Avaliações sobre mim**: a contagem de SIM e NÃO por item e os comentários em ordem sorteada;
  - essa página só aparece com respostas de pelo menos 3 estagiários no período escolhido; com menos, daria para saber quem respondeu;
  - a coordenação e a administração podem ler individualmente, mas nunca o próprio orientador avaliado, mesmo que ele também seja administrador.

### Acompanhamento de visita
Na visita, o orientador preenche o **Acompanhamento de Visita** do SICE pelo sistema (até no celular). O formulário abre pela visita na Agenda (*Preencher*, um por estagiário) ou pela aba *Visitas* do estágio. Ele tem:
- a data;
- a **Avaliação Prática** (as atividades do curso), com *Observações* (obrigatória) e *Intervenções*;
- a **Avaliação Atitudinal** (os 23 critérios do SICE, com os mesmos textos), com as suas próprias *Observações* e *Intervenções*.

Cada um desses textos tem até 300 caracteres, com contador, como no SICE.

Os botões *Marcar todos* preenchem cada parte de uma vez (“Realizou Sem Auxílio” e “Sempre (100%)”), e aí é só ajustar as exceções. Em listas longas, a prática tem **busca** (ex.: “banco de dados”), o contador de atividades incluídas e o filtro *Só as incluídas*; o *Marcar todos* da prática vale só para as atividades que aparecem na busca. Depois, a tela **Lançar no SICE** mostra:
- o cabeçalho na ordem do formulário do SICE (ano, escola, curso, turma, aluno, concedente, setor, data da visita, orientador);
- na prática, **só as atividades marcadas**, para incluir no SICE com *Atividade Sugerida*;
- o atitudinal completo;
- os textos de cada parte com *Copiar*, e o botão *Já lancei no SICE*. O estagiário vê o acompanhamento na aba *Visitas*, como no SICE.
- **Atividades práticas:** mudam por curso. Recebem sozinhos a lista do SICE (inclusive cursos criados depois): **Desenvolvimento de Sistemas**, com as 162 atividades do *Atividade Sugerida*, e **Informática**, com 13. Para os demais (Administração, Finanças, Redes de Computadores, Comércio…), use **Colar várias atividades práticas** em *Avaliações (SICE) → Perguntas*: escolha o curso e cole a lista do SICE, uma por linha. Repetidas são ignoradas, e dá para substituir a lista atual.
- **Opções de resposta:** iguais às do SICE.
  - Prática: *Observou*, *Realizou Com Auxílio* ou *Realizou Sem Auxílio*. Não existe “não realizou”: a atividade que não entra na visita fica **Em branco** e não aparece na tela de lançar.
  - Atitudinal: *Sempre (100%)*, *Frequentemente (70-90%)*, *Algumas Vezes (40-60%)*, *Raramente (10-30%)* ou *Nunca (0%)*. Pode ficar **Em branco**, como a borracha “Limpar” do SICE.

### O que há de novo
Depois de cada atualização, cada pessoa vê um aviso só com o que mudou **para o tipo de conta dela**: o estagiário vê o que é de estagiário, o supervisor o que é de supervisor, e o administrador vê tudo, com a indicação de para quem vale cada item.
- No aviso: **Ver a cada atualização** (padrão) ou **Não mostrar novamente**. A escolha também fica em *Meus dados* e na página **Novidades** (menu da foto e rodapé), que guarda o histórico completo.
- Contas novas começam em dia, sem receber o histórico inteiro.
- **Para publicar uma atualização:** acrescente uma versão no topo de `VERSOES` em `core/novidades.py`, com a data (`AAAA.MM.DD`), um título e os itens. Cada item diz para quem vale: `"todos"`, `"estagiario"`, `"supervisor"`, `"orientador"` ou `"coordenador"`.

### Sugestões e erros
A página **Sugestões e erros** (menu da foto, rodapé e tela de login) aceita mensagens de qualquer pessoa, inclusive de quem não consegue entrar:
- tipo (erro, sugestão, dúvida, elogio, outro);
- nome;
- e-mail para resposta (opcional);
- mensagem;
- até 5 anexos (prints, fotos, PDF, documentos, planilhas, vídeos ou ZIP; 20 MB no total).

Tudo vai **por e-mail**, com os anexos e mais a conta, a página onde a pessoa estava e o navegador. Responder o e-mail responde a quem enviou. O destino é o campo *E-mail que recebe as sugestões e os erros* em **Configurações**; vazio, vale a variável `SUGESTOES_EMAIL` e, por último, o e-mail dos administradores.
- Também fica guardado em **Comunicação → Opiniões sobre o sistema** (e no /admin/), com os anexos para baixar e a marcação *resolvida*. Os administradores recebem um aviso no sino.
- Há uma proteção contra robôs (campo escondido) e um limite de 5 mensagens por hora por pessoa.

### Feedback do supervisor
Uma vez por mês, o supervisor conta à escola como está cada estagiário, pelo card **Feedback do mês** no painel dele. Leva uns 2 minutos por pessoa.
- **Notas de 1 a 5** (insuficiente, regular, bom, muito bom, excelente) em seis critérios: assiduidade e pontualidade, responsabilidade, iniciativa, relacionamento com a equipe, qualidade do trabalho e aprendizado. O que ele não conseguiu observar fica como “Não observei”.
- **Comentários:** pontos fortes, o que pode melhorar e um campo **só para a escola**, que o estagiário não vê. O supervisor também pode deixar o feedback inteiro oculto do estagiário.
- O feedback do mês pode ser ajustado até o fim do mês, e o do mês anterior até o dia 10.
- **Lembrete:** a partir do dia 20, quem ainda não respondeu recebe um aviso (sino, celular e e-mail). Dá para desligar em **Configurações**.
- **Onde aparece:** aba *Feedback* de cada estágio, para estagiário, supervisor e escola. O quadro **Acompanhamento → Feedback dos supervisores** mostra a média de cada estagiário nos últimos 4 meses e quem está pendente. Também entra nos **Indicadores** (média por turma e quantos já responderam no mês), na planilha exportada e nos pontos de atenção do relatório, quando a média fica abaixo de 3 (“bom”).

### Indicadores
Em **Acompanhamento → Indicadores**, um painel do andamento, filtrado por ano, curso e período (últimas 4, 8, 12 ou 26 semanas):
- **Números principais:** estagiários ativos, frequência (dias de estágio com presença), carga média cumprida, quem já cumpriu, quem recebeu visita e as pendências (presenças a validar, atestados, documentos).
- **Frequência semana a semana:** gráfico com o valor de cada semana ao passar o mouse (ou com as setas do teclado). Também dá para ver como tabela.
- **Situação:** quantos estão em andamento, já cumpriram a carga, terminam depois do termo ou foram encerrados.
- **Por turma:** carga média, frequência, quem recebeu visita e quanto da pasta está conferido, com atalho para a lista e o relatório da turma. Frequência abaixo de 75% ganha um aviso.
- **Por concedente:** frequência, faltas e presenças que o supervisor ainda não validou, com a menor frequência primeiro, para achar onde agir.

Frequência = dias de estágio com presença (confirmada ou aguardando o supervisor) ÷ dias de estágio previstos, sem contar feriados e recessos. Ausências avisadas e atestados aparecem separados.

### Resumo semanal
No **Painel**, o botão *Resumo da semana* mostra os pontos de atenção dos últimos 7 dias: quem ficou sem registro de presença, faltas, presenças há mais de 2 dias sem validação do supervisor, termos que vencem nos próximos 30 dias, previsões de término depois do termo, quem está perto de cumprir (90% ou mais) ou já cumpriu a carga, visitas dos próximos 7 dias e pedidos de agendamento sem resposta.

Com o e-mail configurado, esse resumo chega **toda segunda-feira** a cada orientador e coordenador (só dos estagiários que cada um acompanha). Não é preciso agendador: o envio sai no primeiro acesso ao sistema depois de segunda, 6h, uma única vez. Semanas sem nada a relatar não geram e-mail. Cada pessoa pode desligar em **Meus dados**, e o administrador pode desligar para todos em **Configurações**. Também dá para enviar pelo terminal:

```bash
python manage.py enviar_resumo_semanal --mostrar      # só mostra o texto
python manage.py enviar_resumo_semanal --forcar       # reenvia o desta semana
```

Para preferir um horário fixo, desligue o disparo automático com `RESUMO_AUTOMATICO=0` e agende `python manage.py enviar_resumo_semanal` em *Scheduled Tasks* do Coolify (ex.: `0 7 * * 1`).

### Declaração de estágio
Na página do estágio, o botão *Declaração* (para o orientador, o coordenador e o administrador) gera uma declaração A4 com o cabeçalho e o brasão da folha, pronta para imprimir e assinar:
- **Carga cumprida:** “Declaração de conclusão de estágio”, com período (do início ao último dia validado), concedente, CNPJ, supervisor, orientador e total de horas.
- **Ainda em andamento:** declaração de que o estudante realiza o estágio, com as horas cumpridas até a data.

Abaixo do texto vai um quadro com carga exigida, horas cumpridas, presenças, ausências justificadas e faltas. Antes de imprimir, dá para clicar no texto e ajustar a redação (a alteração não fica salva). A declaração é um documento da escola. Quando houver uma API da SEDUC, o ideal é que o certificado oficial venha do próprio SICE.

### Agenda no calendário do celular
Em **Agenda → No meu calendário**, cada pessoa gera um link secreto (.ics) para assinar no Google Agenda, no calendário do iPhone ou no Outlook. As visitas e conversas agendadas aparecem lá com local, estagiários e lembrete 1 hora antes. Remarcações e cancelamentos se atualizam sozinhos (o Google Agenda leva algumas horas). Vale para orientadores, supervisores e estagiários, cada um com as visitas que lhe dizem respeito. Quem tem o link vê a agenda sem senha: se ele vazar, *Gerar novo link* invalida o antigo.

### Check-in por QR code
Quando o supervisor está junto, ele toca em **QR code de presença** no painel dele e mostra a tela ao estagiário. O estagiário aponta a câmera do celular, o sistema abre e ele toca em *Marcar entrada*. A presença **já sai confirmada pelo supervisor**, sem precisar validar depois. O mesmo vale para a saída para o intervalo, a volta e a saída do dia.
- O código **muda a cada 20 segundos** e cada leitura serve para uma marcação só. Uma foto do QR mandada para quem está em casa não funciona.
- O QR só vale para os estagiários daquele supervisor.
- Se o estagiário não estiver logado no navegador da câmera (comum no iPhone), ele entra com usuário e senha e a marcação continua de onde parou.
- A tela do supervisor mostra quem marcou pelo QR naquele dia e mantém o celular aceso enquanto está aberta.
- No histórico do dia fica “marcou pelo QR code do supervisor”.

### Check-in com localização
Em **Configurações → Localização ao marcar presença**:
- **Não pedir a localização** (padrão).
- **Registrar e avisar:** o celular pede a localização ao marcar a entrada e a saída. A distância até a concedente fica no registro, e o supervisor é avisado quando a marcação foi longe (“marcou a 3,1 km da concedente”). A presença é aceita do mesmo jeito.
- **Exigir estar perto:** a entrada e a saída só são aceitas dentro da distância permitida. Sem permissão de localização, a marcação é recusada e o supervisor pode lançar o dia.

Para comparar, cadastre o **ponto de cada concedente** na ficha dela (*Localização para o check-in*): latitude e longitude, ou o botão “Estou na concedente: usar minha posição atual”, ou um link do Google Maps com coordenadas no campo *Link do mapa*. A *Distância aceita* padrão é 300 m. A imprecisão do GPS informada pelo celular (até 150 m) é descontada. Concedente sem ponto cadastrado: a localização é só registrada, nunca bloqueia.

**Onde ver:** no painel do supervisor (presenças a validar), na página do dia e na aba *Registros e diário*, com link para o mapa. A localização é lida só no momento da marcação, nunca em segundo plano. O celular só permite isso em endereço `https://`.

### Notificações no celular
Cada pessoa ativa em **Meus dados → Notificações no celular** (ou no lembrete que aparece na tela inicial). A partir daí, os mesmos avisos do sino chegam como notificação do celular, mesmo com o app fechado. Tocar na notificação abre a página certa.
- **Android:** funciona no Chrome, com ou sem o app instalado.
- **iPhone:** precisa do iOS 16.4 ou mais novo e do app instalado na tela de início (Safari → Compartilhar → *Adicionar à Tela de Início*). Depois, abra pelo ícone e ative.
- **Computador:** Chrome, Edge e Firefox também recebem.
- Vale por aparelho: quem usa celular e computador ativa nos dois. *Desativar neste aparelho* para de enviar, e *Enviar um teste* confere se está chegando.
- Não há custo nem cadastro em serviço externo: o próprio navegador entrega pelos servidores do Google, da Apple ou da Mozilla. As chaves de segurança (VAPID) são criadas sozinhas no primeiro uso, em `/data/vapid_privada.pem`, e ficam no backup. Se esse arquivo for apagado, cada pessoa precisa ativar de novo.
- Só funciona com o sistema em `https://` (no Coolify + Cloudflare isso já acontece).

### Avisos para a turma
Em **Avisos** no menu, o orientador manda um recado para os estagiários, os supervisores ou ambos, filtrando por turma, curso ou concedente (vazio = todos os seus estagiários ativos). O aviso chega no sino, no celular de quem ativou as notificações e por e-mail (com o texto completo). Quem recebe vê o histórico em *Notificações → Avisos da escola*, e o orientador vê os avisos enviados e quantas pessoas receberam cada um.

### Avisos por e-mail
Com o servidor de e-mail configurado (variáveis `EMAIL_*` abaixo), cada aviso do sino também vai para o e-mail de quem tem e-mail cadastrado. Cada pessoa pode desligar em **Meus dados** (“Receber os avisos também por e-mail”), e o administrador pode desligar para todos em **Configurações**. Lá também há o botão *Enviar e-mail de teste para mim*. O envio roda em segundo plano: se o servidor de e-mail falhar, o sistema continua funcionando e o erro vai para o log.

**WhatsApp automático** exige a API oficial do WhatsApp Business (Meta): número próprio, empresa verificada, mensagens-modelo aprovadas e cobrança por conversa. Ferramentas não oficiais que “automatizam o WhatsApp Web” violam os termos e podem banir o número, por isso não são usadas. Por enquanto há atalhos que abrem o WhatsApp com a conversa pronta (captação e telefone do supervisor na página do estágio).

### Encerramento do ano letivo
Em **Cadastros → Encerramento do ano** (orientador e administrador), escolha o ano das turmas. A página mostra, antes de qualquer ação:
- quem já cumpriu a carga e quem não cumpriu (com horas faltando e previsão);
- as pendências: presenças a validar, atestados e documentos a conferir;
- quem está com a pasta incompleta.

Há atalhos para as declarações e para a planilha do ano.

Ao encerrar, você escolhe:
- encerrar os estágios que cumpriram a carga (sempre) e, se quiser, também os que **não** cumpriram (por padrão eles continuam ativos para terminar no ano seguinte);
- desativar a conta dos estagiários encerrados (deixam de entrar; o histórico fica);
- desativar os supervisores que ficarem sem estagiário (desmarcado por padrão, porque costumam continuar no ano seguinte);
- arquivar as turmas que ficarem vazias;
- passar o ano de referência para o seguinte.

Os estagiários recebem um aviso de encerramento. Nada é apagado, e por **30 dias** dá para **desfazer**: o sistema reativa exatamente o que aquele encerramento desativou.

**Dados antigos (LGPD):** em **Configurações**, *Guardar dados pessoais por* define o prazo (padrão: 5 anos depois do ano do estágio). Passado o prazo, a mesma página oferece **anonimizar** os estágios encerrados daqueles anos (é preciso digitar ANONIMIZAR).
- **Sai:** nome, usuário, CPF, matrícula, e-mail e telefone viram “Estagiário anonimizado nº…”. São apagados foto, currículo, atestados, documentos da pasta, mensagens, diário, motivos e comentários, além dos IPs e das localizações.
- **Fica:** datas, horas, presenças e notas, para os indicadores e o histórico da escola.
- Não dá para desfazer. Fica registrado quando foi feita, por quem e quantas pessoas, sem dado pessoal.

### Captação de concedentes
Em **Configurações → Captação de concedentes**, abra a captação, escolha o ano letivo, os **cursos com vagas** (caixas de seleção) e, se quiser, um prazo. A página pública **/seja-concedente/** (link também na tela de login) recebe os cadastros:
- **quem está preenchendo:** o representante legal ou alguém autorizado por ele (declaração obrigatória);
- dados da ficha de concedente;
- **cursos e vagas:** a concedente marca o curso e informa as vagas dele (o campo só aparece com o curso marcado);
- atividades, turnos, horário e benefícios;
- contato de quem preencheu e supervisor indicado;
- **conta de acesso:** quem preenche cria a senha ali mesmo (e aceita os Termos), já entra conectado e recebe o link para confirmar o e-mail. Depois entra com o usuário ou o e-mail para ver o andamento em **Cadastro da concedente**. Enquanto a escola não analisa, corrige os dados e as vagas; depois de aprovada, as vagas não mudam mais (nem pela escola).
- Até a aprovação, essa conta só vê a própria candidatura: nada de estagiários, banco de talentos ou outras telas. Já tem conta (supervisor ou responsável)? Entra antes e manda pela conta.
- **A escola também cadastra:** em **Captação → Cadastrar pela concedente**, o orientador ou o coordenador preenche a pedido da concedente (mesmo com a página pública fechada). Fica marcado como preenchido pela escola e não cria conta.

Em **Captação**, o orientador ou o coordenador do curso vê o total de vagas por curso e analisa cada cadastro:
- **Aprovar:** cadastra a concedente (ou completa uma já existente com o mesmo CNPJ/nome), cria a conta do supervisor indicado (ou usa a de quem preencheu, se for a mesma pessoa) e faz de quem preencheu o responsável pela concedente. A pessoa recebe a decisão no sistema e por e-mail.
- **Recusar:** registra o motivo, que a pessoa vê na conta.
- Enquanto está pendente, *Alterar* ajusta os dados e as vagas.

Nos dois casos o sistema prepara uma mensagem para a concedente. Por enquanto o envio é manual: um botão abre o WhatsApp ou o e-mail com o texto pronto, e depois se marca o aviso como enviado. Os avisos ficam guardados para um envio automático no futuro.

**WhatsApp:** os botões do sistema usam links `wa.me` (o “clique para conversar” do próprio WhatsApp): abrem a conversa no celular ou no WhatsApp Web com a mensagem pronta, e a pessoa toca em enviar. Não precisa de API, conta especial nem tem custo. Enviar sozinho, sem ninguém tocar, exige a **API oficial do WhatsApp Business (Cloud API da Meta)**: um número de telefone só para isso, a empresa verificada no Gerenciador de Negócios, mensagens-modelo aprovadas pela Meta para iniciar conversas e cobrança por mensagem. Serviços não oficiais que “automatizam” o WhatsApp comum podem ter o número banido.

### Permissões
As permissões de cada papel ficam em uma tabela só, `PERMISSOES_POR_PAPEL` em `core/models.py`. Para tirar ou dar algo ao coordenador, basta editar o conjunto dele. O administrador pode tudo.

**Modo administrador** (para quem é administrador e também orientador): em **Meus dados → Modo administrador** ou no menu da foto (*Usar como orientador* / *Ligar o modo administrador*).
- **Desligado:** a conta funciona como a de um orientador comum: só os próprios estagiários em todas as telas (painel, listas, frequências, relatórios) e sem as telas de administração (Configurações, Sistema, Administração). No banco ela continua sendo de administrador, e salvar os próprios dados nesse modo não muda isso. Ao abrir uma tela de administração, a página de acesso negado oferece *Ligar o modo administrador e abrir*. Os avisos de erro continuam chegando.
- **Ligado** (padrão): vê os estagiários de todos os orientadores e as telas de administração.
- **Nos dois modos**, as ferramentas de visita são só do próprio orientador: *Agendar visita* lista só os seus estagiários (e a visita sai no seu nome), o roteiro e o agendamento rápido só montam rotas com os seus, e a agenda, o calendário do painel e o link para o celular mostram só as suas visitas. Uma visita de outro orientador ainda abre pelo link no modo administrador.

| Permissão | Orientador | Coordenador |
|---|---|---|
| Painel, estagiários, lançar/validar registros | ✔ | ✔ |
| Cadastrar estagiários | ✔ | ✔ (escolhe o orientador) |
| Contas, concedentes, cursos e turmas (inclui desativar/reativar) | ✔ | ✔ |
| Captação de concedentes | ✔ | ✔ |
| Frequências impressas | ✔ | ✔ |
| Relatório e exportação (PDF e planilha), resumo semanal, indicadores, declaração de estágio | ✔ | ✔ (cursos que coordena) |
| Analisar atestados (aceitar/recusar) | ✔ | ✔ (cursos que coordena) |
| Conferir documentos da pasta, marcar entregue em papel | ✔ | ✔ (cursos que coordena) |
| Definir os documentos exigidos na pasta | ✔ | — |
| Encerrar o ano letivo e anonimizar dados antigos | ✔ | — |
| Acompanhar as avaliações para o SICE / editar as perguntas | ✔ / ✔ | ✔ / — |
| Enviar avisos para a turma | ✔ | ✔ (cursos que coordena) |
| Ver o feedback dos supervisores (inclusive o comentário reservado) | ✔ | ✔ (cursos que coordena) |
| Agendar visitas | ✔ | — |
| Mudar dias em lote (cada um mantém seus horários) | ✔ | — |
| Mudar o ano de referência | ✔ | — |
| Feriados (municipais, nacionais e da escola) | ✔ | — |
| Arquivos gerais | ✔ | — |
| Emitir folhas em lote, enviar folhas e decidir se o estagiário emite | ✔ | — |
| Equipe e substituições das concedentes | ✔ | ✔ |
| Roteiro de visitas | ✔ | — |

Coordenadores são criados pelo administrador em **Contas → + Coordenador**.

Responsável pela concedente (conta de supervisor marcada pela escola): cadastra a equipe da própria concedente, dá e encerra permissões temporárias e confirma presenças dos estagiários dela. Substituto: confirma, contesta e lança dias só no período da permissão.

### Velocidade
- As listas (painel, estagiários, frequências, indicadores, resumo da semana, painel do supervisor) carregam registros, escalas, feriados e totais de horas **de uma vez para todos os estagiários**, em vez de um por um. Com 120 estagiários, o painel caiu de ~760 para ~20 consultas ao banco, e os indicadores de ~1.700 para ~20.
- A configuração geral é lida uma vez por página.
- Ao parar o dedo ou o mouse sobre um link, o navegador já começa a buscar a página (downloads, saídas e telas que registram algo ao abrir ficam de fora). Uma barra animada no topo mostra que a próxima página está carregando, e as mensagens de sucesso somem sozinhas.

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

Acesse http://localhost:8000. O comando `popular_demo` cria contas fictícias (a lista está no topo de `core/management/commands/popular_demo.py`), todas com a senha padrão e já ativadas (o primeiro acesso não vale para elas).

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
   - `SENHA_PADRAO`: a senha das contas antigas (não abre mais contas novas; veja *Contas*)
   - `ADMIN_NOME`: seu nome completo, que cria o primeiro orientador administrador
   - `PORTA`: a porta livre do servidor que o túnel vai usar (ex.: `8010`)
   - *(opcional, avisos por e-mail)* `EMAIL_HOST` (ex.: `smtp.gmail.com`), `EMAIL_PORT` (`587`), `EMAIL_HOST_USER` (o e-mail remetente), `EMAIL_HOST_PASSWORD` (no Gmail, uma “senha de app”, não a senha normal) e `SITE_URL` (ex.: `https://estagio.seudominio.com.br`, para os links dos e-mails; vazio = o de `CSRF_TRUSTED_ORIGINS`). O resumo semanal sai sozinho às segundas; `RESUMO_AUTOMATICO=0` desliga esse disparo, se preferir agendar o comando.
4. Garanta que o volume `/data` é persistente. No modo Compose isso já vem configurado.
5. Faça o deploy. No Cloudflare Tunnel, aponte o hostname para `http://localhost:<PORTA>` (ou o IP da VPS, se o cloudflared rodar em outra máquina).
6. No log do container aparecem o usuário gerado a partir de `ADMIN_NOME` e um **código de primeiro acesso**. Abra `/primeiro-acesso/`, escolha “Tenho um código” e crie a senha.

Para criar outros orientadores depois: entre como administrador → *Contas* → *+ Orientador*, ou pelo terminal do container:

```bash
python manage.py criar_orientador "Nome Completo"
```

### Segurança no servidor
- `SECRET_KEY` é obrigatória fora do modo de desenvolvimento: sem ela o sistema não sobe.
- **HTTPS obrigatório:** no Cloudflare, ligue *SSL/TLS → Edge Certificates → Always Use HTTPS*. Ou, no sistema, `FORCAR_HTTPS=1`, que redireciona `http://` para `https://` e envia HSTS (1 ano). Ligue só depois de confirmar que o site abre por `https://`. O `/saude/` do healthcheck continua liberado em http.
- **Porta do container:** com o Cloudflare Tunnel, ninguém precisa acessar a `PORTA` direto pela internet. Deixe-a fechada no firewall da VPS (ou publique como `127.0.0.1:${PORTA}:8000`), senão dá para pular o Cloudflare e falsificar o IP de origem que os limites de tentativas usam.
- Avisos de erro, registro de ações e verificação em duas etapas: ver *Privacidade, termos e segurança da conta*. Para o primeiro deploy com os termos, quem já usa o sistema vê a tela de aceite uma vez (`EXIGIR_ACEITE_TERMOS=0` desliga, só para emergência).
- Arquivos enviados pelos usuários nunca são públicos. Só PDF e fotos abrem no navegador; o resto baixa, e todos vão com CSP *sandbox*, sem rodar script.

### Backup
Tudo fica em `/data` (`db.sqlite3` e a pasta `anexos/`). Copiar esse volume já é um backup completo.

## Primeiros passos como orientador
1. **Turmas e cursos**: cadastre os cursos com a carga horária (ex.: Informática, 300h) e as turmas de cada ano (ex.: turma de 2024, estágio em 2026).
2. **Locais**: cadastre as concedentes (endereço, telefone, link do mapa).
3. **Contas → + Supervisores**: um por linha, vinculados ao local.
4. **Estagiários → Cadastrar estagiários**: cole os nomes (um por linha), escolha a turma, a concedente, supervisor, data de início e dias. Ao final aparece a lista de usuários para imprimir ou repassar.
5. **Feriados**: cadastre os feriados nacionais do ano (aba *Nacionais e estaduais*), os municipais de cada município das concedentes e os eventos da escola.

## Estrutura

```
core/models.py      Usuários, cursos, locais, estágios, escalas, registros, agenda, arquivos, mensagens
core/services.py    Regras: geração de usuário, status de cada dia, horas e previsão, notificações
core/views/         Telas por área (comum, estágio, orientador, supervisor, agenda, relatórios, app/PWA)
core/planilha.py    Planilha modelo (Excel) de importação: gerar e ler
core/acompanhamento.py  Situação de cada estágio (relatório, exportação) e resumo semanal por e-mail
core/exportacao.py  Planilha (.xlsx) com a situação dos estagiários
core/atestados.py   Atestados: envio, dias cobertos, aceite/recusa
core/pasta.py       Pasta do estágio: documentos exigidos, prazos e conferência
core/push.py        Notificações no celular (Web Push): chaves VAPID e envio
core/indicadores.py Indicadores por turma, por concedente e semana a semana
core/feedback.py    Feedback mensal do supervisor: meses abertos, pendências e lembrete
core/encerramento.py Encerramento do ano (com desfazer) e anonimização (LGPD)
core/qrcheckin.py   Check-in por QR code: código assinado que troca a cada 20 s
core/avaliacoes.py  Avaliações do estagiário e o texto para copiar no SICE
core/sice.py        Listas do SICE (atividades práticas por curso)
core/novidades.py   “O que há de novo”: versões e itens por tipo de usuário
core/sugestoes.py   Envio das sugestões e erros por e-mail, com anexos
templates/          HTML (visual inspirado no portal ce.gov.br)
static/             CSS e JS próprios, sem frameworks
```

## Ideias para as próximas versões
- Integração com o SICE por API oficial da SEDUC (dados dos estagiários, avaliações e certificado)
- WhatsApp automático pela API oficial do WhatsApp Business
