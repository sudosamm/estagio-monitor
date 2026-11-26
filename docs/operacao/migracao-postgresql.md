# Troca do SQLite para o PostgreSQL 18: procedimento

> **Você executa; o agente escreveu.** Nenhum banco real foi aberto pelo agente. Este documento substitui o plano da
> Etapa 0 ([04](../diagnostico/04-migracao-postgresql.md)) nos comandos: veja as correções no
> [ADR 0004](../decisoes/0004-copia-sqlite-postgresql.md).

## Resumo

- O código da **fase A** da Etapa 1 (branch `etapa-1a-postgres`) já sabe usar o PostgreSQL, mas só passa a usá-lo
  quando `DATABASE_URL` existir. Fazer o deploy dela **não muda nada** para quem usa.
- A troca é um passo de operação: copiar os dados, conferir e colocar `DATABASE_URL`. A reversão é tirar a variável.
- A migração multiescola é um deploy **posterior** e separado ([deploy-multiescola.md](deploy-multiescola.md)).

## 0. Pré-requisitos

- Backup do volume funcionando e testado ([backup.md](backup.md)).
- Deploy da fase A em homologação e em produção, sem `DATABASE_URL` (tudo igual a antes).
- Contas de teste por perfil em produção, marcadas como teste e sem dados pessoais (decisão da Etapa 0), para a
  conferência do passo 10.

## 1. Recurso PostgreSQL no Coolify (homologação primeiro, depois produção)

1. Coolify → *New Resource* → *Database* → **PostgreSQL**, imagem `postgres:18` (a mesma em todos os ambientes).
2. Nome do banco `estagio`, usuário `estagio`, senha gerada pelo Coolify.
3. **Initial Database Arguments** (`POSTGRES_INITDB_ARGS`):
   `--encoding=UTF8 --locale-provider=icu --icu-locale=pt-BR` (ordem alfabética do português; "Álvaro" junto de
   "Alvaro"). Isso só vale na criação do banco: confira antes de subir.
4. **Não** marque *Make it publicly available*. A aplicação usa a **URL interna** (*Postgres URL (internal)*), na
   mesma rede do Coolify. Se a aplicação e o banco estiverem em projetos ou redes diferentes, ative *Connect to
   Predefined Network* nos dois, ou coloque-os no mesmo projeto e ambiente.
5. **Backups** do recurso: agende diário (`0 2 * * *`), destino S3 = o R2 (*Settings → S3 Storages*, com um token
   próprio para os backups do banco), retenção 7 locais e 7/4/6 no S3 se a versão do Coolify permitir; senão, 30
   dias. Faça um *Backup now* e confira que o arquivo aparece no R2.

## 2. Ensaio na homologação (dados fictícios)

Com o `popular_demo` na homologação (SQLite), siga os passos 3 a 10 abaixo, **inclusive a reversão R1 e a R2**, e
cronometre. Corrija o que falhar antes de seguir.

## 3. Ensaio com a cópia real (no servidor de produção)

Decisão da Etapa 0: recurso PostgreSQL **temporário** no próprio servidor, sem porta pública, apagado ao final.

1. Crie um recurso PostgreSQL 18 temporário como no passo 1 (sem backups agendados), por exemplo `estagio-ensaio`.
2. No terminal do container da aplicação (produção, ainda no SQLite), faça uma cópia consistente:

   ```bash
   mkdir -p /data/migracao && python -c "import sqlite3; a=sqlite3.connect('file:/data/db.sqlite3?mode=ro', uri=True); b=sqlite3.connect('/data/migracao/ensaio.sqlite3'); a.backup(b); b.close(); a.close()"
   ```

3. Verifique (só lê; não mostra dados pessoais):

   ```bash
   python manage.py verificar_para_postgres --banco /data/migracao/ensaio.sqlite3
   ```

   Se apontar problema (texto maior que o campo, caractere NUL, IP inválido…), corrija na produção pela tela do
   sistema ou com uma migration de dados registrada, e repita.
4. Exporte da cópia (sem tocar no banco em uso):

   ```bash
   DATABASE_URL=sqlite:////data/migracao/ensaio.sqlite3 python manage.py dumpdata --all --natural-foreign --exclude contenttypes --exclude auth.permission --format jsonlp -o /data/migracao/ensaio.jsonlp.gz
   ```

5. Crie o esquema e importe no banco temporário (URL interna do `estagio-ensaio`):

   ```bash
   DATABASE_URL=postgres://...ensaio... python manage.py migrate
   ```

   ```bash
   DATABASE_URL=postgres://...ensaio... python manage.py loaddata /data/migracao/ensaio.jsonlp.gz
   ```

6. Compare:

   ```bash
   DATABASE_URL=postgres://...ensaio... python manage.py comparar_bancos --origem sqlite:////data/migracao/ensaio.sqlite3
   ```

   Tem que terminar com "Os dois bancos são iguais."
7. Anote o tempo de cada passo. Apague `ensaio.sqlite3` e `ensaio.jsonlp.gz` e o recurso `estagio-ensaio`.

Critério para seguir: os dois ensaios sem erro, `comparar_bancos` igual, a suíte verde no PostgreSQL (abaixo) e o
tempo da janela conhecido.

**Suíte no PostgreSQL** (na sua máquina, com o `docker-compose.dev.yml`, ou num container da homologação com um
usuário que possa criar bancos):

```bash
DATABASE_URL=postgres://estagio:estagio-dev@127.0.0.1:5432/estagio .venv/bin/python manage.py test
```

## 4 a 9. Produção (janela avisada, fora do horário de estágio)

4. **Congelar:** nenhum outro deploy na véspera.
5. **Parar a aplicação** no Coolify.
6. **Backup:** `python manage.py backup_dados` num container temporário da mesma imagem (ou o da própria aplicação
   logo antes de parar) e a cópia local:

   ```bash
   mkdir -p /data/migracao && python -c "import sqlite3; a=sqlite3.connect('file:/data/db.sqlite3?mode=ro', uri=True); b=sqlite3.connect('/data/migracao/db-antes-postgres.sqlite3'); a.backup(b); b.close(); a.close()"
   ```

7. **Verificar, exportar e importar** (container temporário da mesma imagem, URL interna do recurso de produção):

   ```bash
   python manage.py verificar_para_postgres --banco /data/migracao/db-antes-postgres.sqlite3
   ```

   ```bash
   DATABASE_URL=sqlite:////data/migracao/db-antes-postgres.sqlite3 python manage.py dumpdata --all --natural-foreign --exclude contenttypes --exclude auth.permission --format jsonlp -o /data/migracao/dados.jsonlp.gz
   ```

   ```bash
   DATABASE_URL=postgres://... python manage.py migrate
   ```

   ```bash
   DATABASE_URL=postgres://... python manage.py loaddata /data/migracao/dados.jsonlp.gz
   ```

8. **Comparar:**

   ```bash
   DATABASE_URL=postgres://... python manage.py comparar_bancos --origem sqlite:////data/migracao/db-antes-postgres.sqlite3
   ```

   Diferença = **pare e vá para R1**.
9. **Trocar:** coloque `DATABASE_URL` (URL interna) nas variáveis da aplicação e faça o deploy. O `db.sqlite3`
   **fica onde está**, intocado. As sessões foram copiadas: ninguém precisa entrar de novo.

## 10. Conferir e liberar

- `/saude/`; entrada com cada conta de teste (estagiário, supervisor, orientador, coordenador, responsável); painel;
  ficha de um estágio; folha de frequência; abrir um anexo; push de teste; uma ação aparecendo no Registro de ações.
- Acompanhe **Erros do sistema** nas primeiras horas.
- Faça um *Backup now* no recurso do banco e confira no R2.
- Apague `/data/migracao/dados.jsonlp.gz` (tem todos os dados pessoais). Guarde `db-antes-postgres.sqlite3` até o
  ponto sem volta.

## Reversão

- **R1 — antes de liberar (passos 7 a 10):** tire `DATABASE_URL` e faça o deploy. A aplicação volta ao SQLite, que não
  foi alterado desde o passo 5.
- **R2 — depois de liberar, com dados novos no PostgreSQL:** pare a aplicação e faça o caminho inverso:

  ```bash
  DATABASE_URL=postgres://... python manage.py dumpdata --all --natural-foreign --exclude contenttypes --exclude auth.permission --format jsonlp -o /data/migracao/volta.jsonlp.gz
  ```

  ```bash
  DATABASE_URL=sqlite:////data/migracao/db-volta.sqlite3 python manage.py migrate
  ```

  ```bash
  DATABASE_URL=sqlite:////data/migracao/db-volta.sqlite3 python manage.py loaddata /data/migracao/volta.jsonlp.gz
  ```

  ```bash
  DATABASE_URL=sqlite:////data/migracao/db-volta.sqlite3 python manage.py comparar_bancos --origem postgres://...
  ```

  Com "iguais", troque `db.sqlite3` por `db-volta.sqlite3` (guarde o antigo), tire `DATABASE_URL` e faça o deploy.
- **Ponto sem volta:** depois de duas semanas sem incidente, arquive o `db-antes-postgres.sqlite3` fora do servidor
  (cifrado, como os backups) e apague-o de `/data`. A partir daí a reversão é pelo backup do PostgreSQL.

## Backup diário e teste de restauração do banco

- Diário: o agendado do recurso (passo 1.5). O volume continua com o `backup_dados` diário (anexos e chave VAPID).
- Mensal: restaure o último backup do PostgreSQL num recurso temporário, rode
  `DATABASE_URL=postgres://...temporario... python manage.py comparar_bancos --origem postgres://...producao...`
  (as contagens devem ser iguais ou só um pouco menores, pelo que entrou depois do backup) e
  `DATABASE_URL=postgres://...temporario... python manage.py check --database default`. Registre data e resultado e
  apague o recurso temporário.

## Diferenças entre o SQLite e o PostgreSQL (verificação de 26/11/2026)

A suíte passava no SQLite e tinha 5 falhas no PostgreSQL 18 (nas duas branches da Etapa 1). As duas causas foram
corrigidas, e o código foi varrido atrás de outras diferenças que mudariam o que o usuário vê. Os testes estão em
`core/test_diferencas_bancos.py` e rodam nos dois bancos.

### Causas das 5 falhas

1. **"the connection is closed" (4 testes do resumo semanal).** Com `EMAIL_ASSINCRONO=False`, o envio rodava na
   própria thread de quem chamou, e o `finally` chamava `connections.close_all()`, fechando a conexão do teste (ou da
   requisição). O SQLite em memória ignora o `close`; o PostgreSQL fecha de verdade. **Correção:** só a thread criada
   por `iniciar_thread` (`core/threads.py`) fecha as conexões, ela mesma, num `try/finally` em volta da função. Nenhum
   ponto de chamada fecha mais nada (e-mail em `services.py`, push, sugestões, resumo semanal). As conexões do Django
   são por thread, então isso vale também com o Gunicorn em `gthread`. De quebra: o `tarefas_periodicas` (Scheduled
   Tasks) espera as threads de envio terminarem antes de sair; antes, como são threads daemon, os e-mails podiam
   morrer com o processo depois de a semana já ter sido "reservada".
2. **Feriado municipal (1 teste).** Confirmado: o teste procurava `texto__contains="General Sampaio"`, e a notificação
   trazia o município como foi digitado ("GENERAL SAMPAIO - CE"). O `contains` vira `LIKE`, que no SQLite ignora
   maiúsculas e minúsculas (só de A a Z) e no PostgreSQL não. **Correção:** a notificação mostra o município
   formatado (`nome_municipio`: "General Sampaio"), e o teste continua com `contains`.

### Varredura

| Diferença | SQLite | PostgreSQL | Onde aparece no código | Resultado |
|---|---|---|---|---|
| `__contains`, `__startswith`, `__endswith` (LIKE) | ignora maiúsculas de A a Z | diferencia | limite de tentativas (`username__contains=":"`, prefixos `1o:`, `senha:`…), busca por IP no Registro de ações | Os prefixos e os usuários das tentativas são gravados sempre em minúsculas: igual nos dois. **Corrigido:** a busca por IP passou a `istartswith` (IPv6 tem letras). |
| `__iexact`, `__icontains` | ignora maiúsculas só de A a Z ("É" ≠ "é") | ignora todas (`UPPER`), com acentos | login por e-mail, "Esqueci minha senha", primeiro acesso, aviso de senha errada, importação (orientador, estagiário pelo nome, concedente), sugestões da captação, turmas, filtros das listas (estagiários, contas, concedentes, banco de talentos, registro de ações) | O PostgreSQL acha o mesmo ou mais, nunca menos. Acentos continuam diferenciando nos dois ("joao" não acha "João" no filtro das listas, como hoje). Única mudança: nomes que só diferem por maiúscula acentuada passam a ser iguais (ex.: na importação, "JOSÉ" e "José" viram homônimos). O `verificar_para_postgres` avisa se houver casos. |
| Igualdade (`=`) | diferencia maiúsculas | diferencia (ICU pt-BR determinística) | login pelo usuário (exato), CPF (formatado), e-mail exato | Igual nos dois. |
| Busca global (Ctrl+K) | — | — | `views/roteiro.py`: compara em Python, sem acentos e sem maiúsculas (`chave_texto`) | Não depende do banco. |
| Municípios, cursos, concedentes e supervisores por nome | — | — | `chave_municipio`, `_chave` da importação: comparação em Python | Não depende do banco. O `iexact` antes do Python só restringe a lista, e há o caminho completo quando ele não acha. |
| Ordem alfabética | bytes (maiúsculas antes, acentos no fim) | ICU pt-BR ("Álvaro" junto de "Alvaro") | todas as listas por nome | Melhora, sem correção. Onde a importação pega "o primeiro" de nomes repetidos, a escolha pode mudar: o `verificar_para_postgres` avisa. |
| Vazios (NULL) na ordem | primeiro na crescente, por último na decrescente | o contrário | histórico da agenda, última visita da ficha, atestados decididos, responsáveis (ativos primeiro), exportação das visitas, solicitações do painel | **Corrigido:** ordem explícita (`nulls_first`/`nulls_last`), igual à de sempre. A ordem padrão de `Agendamento` (`-data_hora`) ficou como está (mudar pediria migration); as telas onde há visita sem data já usam ordem explícita. |
| Caractere NUL (`\x00`) | aceita | recusa (erro 500) | qualquer busca, o login, parâmetros de URL | **Corrigido:** `CaractereNuloMiddleware` responde 400 antes de consultar o banco. Os dados antigos com NUL já são apontados pelo `verificar_para_postgres`. |
| Tamanho do texto | não confere | recusa acima do `max_length` | cabeçalhos guardados (navegador, endereço de origem) | O código já corta no limite; os dados antigos são conferidos pelo `verificar_para_postgres`. |
| Datas e fuso | texto em UTC | `timestamptz` | `__date`, `__year`, `__month`, `TruncMonth` | O Django converte igual nos dois (suíte verde). Os microssegundos são preservados na cópia (`jsonlp`). |
| Booleanos | 0/1 | `true`/`false` | só pelo ORM; o único SQL escrito à mão (migration 0046) não usa booleanos | Igual nos dois. Valores fora de 0/1 no SQLite são apontados pelo `verificar_para_postgres`. |
| Erro dentro de transação | segue | a transação inteira fica abortada | `sessoes._adotar` (`except IntegrityError`) | Usa `get_or_create`, que já abre um savepoint: igual nos dois. |

### O que o `verificar_para_postgres` passou a avisar

Além dos **problemas** (que impedem a cópia), o comando lista **avisos**, que não a impedem. São só ids, sem
conteúdo:

- usuários que só diferem por maiúsculas e minúsculas (o login exige a grafia exata; o aviso de senha errada e o
  primeiro acesso procuram sem diferenciar e podem achar a outra conta);
- o mesmo e-mail, ignorando maiúsculas, em mais de uma conta ativa (o login pelo e-mail não vale para elas);
- estagiários cujos nomes só diferem por maiúscula acentuada (no PostgreSQL, a importação passa a vê-los como
  homônimos);
- concedentes com o mesmo nome (sem acentos e maiúsculas) e o mesmo CNPJ/CPF, e cursos com o mesmo nome: a
  importação usa o primeiro em ordem alfabética, e essa ordem muda.

Com avisos, confira os casos pela tela do sistema (contas, concedentes, cursos) antes do passo 7, e corrija o que
for duplicata de verdade. Se não for, a cópia pode seguir.
