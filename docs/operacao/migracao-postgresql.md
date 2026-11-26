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
