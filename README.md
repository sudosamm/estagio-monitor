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

### App no celular
O sistema pode ser **instalado como app** (PWA): ícone na tela inicial, abre em tela cheia, sem barra do navegador.
- **Android (Chrome):** menu do usuário → *Instalar no celular*, ou o aviso “Instalar app” do próprio Chrome.
- **iPhone (Safari):** Compartilhar → *Adicionar à Tela de Início*.
- O app não guarda páginas com dados pessoais no aparelho: só o visual (CSS, ícones). Sem internet, aparece uma tela “Sem conexão”, e a presença só é marcada online, com o horário do servidor.

### Contas
- Usuário gerado como `primeiro.ultimo` sem acentos (ex.: *Maria da Silva Souza* → `maria.souza`). Se já existir, recebe um número (`maria.souza2`).
- Todas as contas nascem com a `SENHA_PADRAO` e a pessoa **é obrigada a criar a própria senha** no primeiro acesso.
- O orientador pode voltar a senha de alguém para a padrão (em *Contas → Editar*).
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
Em **Alterar dias**, escolha a data, os dias da semana e os estagiários (dá para filtrar por curso ou turma). O sistema guarda o histórico: os dias anteriores continuam valendo como antes, e a nova escala vale a partir da data escolhida. Estagiários e supervisores são avisados.

### Folha de frequência
Cada pessoa gera a folha do mês reproduzindo, medida a medida, a folha oficial da CEPAE/SEDUC: brasão, cabeçalho preenchido, fins de semana em cinza e feriados/eventos escritos na linha. O brasão padrão pode ser trocado em Configurações. A folha é só para impressão: não há botão de download.
- Toda abertura fica registrada, com o número de impressões (inclusive “Salvar como PDF”, que passa pela impressão do navegador).
- No rodapé sai um código. Em **Frequências**, o orientador e o supervisor buscam esse código para saber quem emitiu a folha e quando.
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
- **Reenvio:** reenviar o mesmo arquivo não duplica, porque estagiários com o mesmo CPF e estágio ativo são ignorados.

O arquivo gerado a partir dos TCEs fica em `importacao/`, pasta que não vai para o Git porque tem dados pessoais. A planilha preenchida também tem dados pessoais: guarde-a em local seguro.

### Relatório geral e exportação (PDF e planilha)
Em **Turmas e cursos**, o botão *Relatório* de cada turma abre o relatório daquela turma. Na lista de **Estagiários**, o botão *Exportar* gera o mesmo relatório para **o que estiver filtrado** (curso, turma, concedente, busca, ativos/encerrados/todos e ano), em PDF ou em planilha. O relatório é uma página A4 deitada com:
- **Resumo:** estagiários ativos, média da carga cumprida, quem já cumpriu, quem termina depois do fim do termo, faltas, dias sem registro e visitas realizadas.
- **Uma linha por estagiário:** concedente, supervisor, início, fim do termo, horas cumpridas (com barra), faltas, dias sem registro, presenças a validar, previsão de término, visitas e situação.
- **Pontos de atenção:** sem supervisor, previsão depois do termo, 3 ou mais faltas, 3 ou mais dias sem registro, presenças aguardando o supervisor, nenhuma visita.
- Espaço para assinatura do orientador e da coordenação.

Clique em *Salvar PDF / imprimir* e escolha **Salvar como PDF** (funciona também no celular).

A **planilha (.xlsx)**, também disponível pelo botão *Baixar planilha* do relatório, traz quatro abas: *Resumo*, *Estagiários* (uma linha por estágio, com horas, faltas, dias sem registro, visitas, previsão, situação e pontos de atenção), *Horas por mês* (horas validadas em cada mês) e *Visitas e conversas* (com o relato). Serve para prestar contas à escola, à CREDE ou à SEDUC sem redigitar. O CPF não vai para a planilha.

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

### Check-in com localização
Em **Configurações → Localização ao marcar presença**:
- **Não pedir a localização** (padrão).
- **Registrar e avisar:** o celular pede a localização ao marcar a entrada e a saída. A distância até a concedente fica no registro, e o supervisor é avisado quando a marcação foi longe (“marcou a 3,1 km da concedente”). A presença é aceita do mesmo jeito.
- **Exigir estar perto:** a entrada e a saída só são aceitas dentro da distância permitida. Sem permissão de localização, a marcação é recusada e o supervisor pode lançar o dia.

Para comparar, cadastre o **ponto de cada concedente** na ficha dela (*Localização para o check-in*): latitude e longitude, ou o botão “Estou na concedente: usar minha posição atual”, ou um link do Google Maps com coordenadas no campo *Link do mapa*. A *Distância aceita* padrão é 300 m. A imprecisão do GPS informada pelo celular (até 150 m) é descontada. Concedente sem ponto cadastrado: a localização é só registrada, nunca bloqueia.

**Onde ver:** no painel do supervisor (presenças a validar), na página do dia e na aba *Registros e diário*, com link para o mapa. A localização é lida só no momento da marcação, nunca em segundo plano. O celular só permite isso em endereço `https://`.

### Avisos por e-mail
Com o servidor de e-mail configurado (variáveis `EMAIL_*` abaixo), cada aviso do sino também vai para o e-mail de quem tem e-mail cadastrado. Cada pessoa pode desligar em **Meus dados** (“Receber os avisos também por e-mail”), e o administrador pode desligar para todos em **Configurações**. Lá também há o botão *Enviar e-mail de teste para mim*. O envio roda em segundo plano: se o servidor de e-mail falhar, o sistema continua funcionando e o erro vai para o log.

**WhatsApp automático** exige a API oficial do WhatsApp Business (Meta): número próprio, empresa verificada, mensagens-modelo aprovadas e cobrança por conversa. Ferramentas não oficiais que “automatizam o WhatsApp Web” violam os termos e podem banir o número, por isso não são usadas. Por enquanto há atalhos que abrem o WhatsApp com a conversa pronta (captação e telefone do supervisor na página do estágio).

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
| Contas, concedentes, cursos e turmas (inclui desativar/reativar) | ✔ | ✔ |
| Captação de concedentes | ✔ | ✔ |
| Frequências impressas | ✔ | ✔ |
| Relatório e exportação (PDF e planilha), resumo semanal, declaração de estágio | ✔ | ✔ (cursos que coordena) |
| Analisar atestados (aceitar/recusar) | ✔ | ✔ (cursos que coordena) |
| Agendar visitas | ✔ | — |
| Mudar dias em lote (cada um mantém seus horários) | ✔ | — |
| Mudar o ano de referência | ✔ | — |
| Feriados (municipais, nacionais e da escola) | ✔ | — |
| Arquivos gerais | ✔ | — |
| Emitir folhas em lote, enviar folhas e decidir se o estagiário emite | ✔ | — |

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
   - *(opcional, avisos por e-mail)* `EMAIL_HOST` (ex.: `smtp.gmail.com`), `EMAIL_PORT` (`587`), `EMAIL_HOST_USER` (o e-mail remetente), `EMAIL_HOST_PASSWORD` (no Gmail, uma “senha de app”, não a senha normal) e `SITE_URL` (ex.: `https://estagio.seudominio.com.br`, para os links dos e-mails; vazio = o de `CSRF_TRUSTED_ORIGINS`). O resumo semanal sai sozinho às segundas; `RESUMO_AUTOMATICO=0` desliga esse disparo, se preferir agendar o comando.
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
templates/          HTML (visual inspirado no portal ce.gov.br)
static/             CSS e JS próprios, sem frameworks
```

## Ideias para as próximas versões
- Pasta de documentos por estagiário (TCE, plano de atividades, relatório final), com o que está faltando
- Notificações no celular pelo app (Web Push), inclusive avisos do orientador para a turma
- Painel de indicadores por curso e turma, e área de feedback do supervisor
- Check-in por QR code mostrado pelo supervisor (confirma a chegada na hora)
- Encerramento do ano letivo: fechar turmas, arquivar estágios e anonimizar dados após o prazo (LGPD)
- Integração com o SICE por API oficial da SEDUC (dados dos estagiários, avaliações e certificado)
- Avaliação do estagiário pelo supervisor (formulário periódico)
- Autoavaliação do estagiário e avaliação do orientador, com texto pronto para copiar no SICE
- WhatsApp automático pela API oficial do WhatsApp Business
