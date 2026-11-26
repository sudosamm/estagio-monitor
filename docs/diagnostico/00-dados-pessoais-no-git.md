# 00 — Dados pessoais versionados no Git (achado da Etapa 0)

> **Prioridade máxima.** Este achado vem antes de qualquer etapa da atualização.
> A verificação leu **só os nomes dos arquivos e os metadados dos commits** (as "árvores" do Git). Nenhum conteúdo de
> arquivo com dados pessoais foi aberto, copiado ou usado. Os nomes dos arquivos dentro de `TCEs/` também não foram
> listados aqui, porque podem conter nomes de estudantes.

## Como foi verificado

O `git` não está disponível no ambiente do agente. Foi usado um leitor próprio, em Python, dos objetos do repositório
(`.git/objects`, soltos e empacotados). Ele percorre todos os commits a partir da `main`, abre a árvore da raiz de cada
um e procura entradas com os nomes sensíveis. O conteúdo dos arquivos (blobs) não é descompactado.

Estado do repositório no momento da verificação:

- branch local única: `main`, no commit `be1c6059e5` (25/11/2026);
- `origin/main` aponta para **o mesmo commit**. Portanto, tudo abaixo já está no remoto `origin` (GitHub);
- não existe a branch `desenvolvimento` (nem local nem remota);
- 38 commits na `main`.

## O que está no histórico

| Caminho | Primeiro commit | Commits que o contêm | Está no último commit (`be1c6059e5`)? |
|---|---|---|---|
| `data/db.sqlite3` | `519c0a7d37` (11/11/2026) | 34 de 38 (saiu em 4 e voltou) | **sim** |
| `file.csv` | `03bb2937e6` (12/11/2026) | 29 | **sim** |
| `sicereport.pdf` | `674541d7be` (16/11/2026) | 15 | **sim** |
| `TCEs/` (91 arquivos) | `2702a67187` (17/11/2026) | 10 | **sim** |
| `importacao/` | nunca | 0 | não |
| `Relatorio-estagio/` | nunca | 0 | não |
| `.env` | nunca | 0 | não |
| `data/vapid_privada.pem` | nunca | 0 | não |
| `data/anexos/` | nunca | 0 | não |

O `.gitignore` já listava `data/`, `TCEs/` e `/*.pdf`, mas o `.gitignore` **não tira do Git** um arquivo que já foi
versionado. Por isso esses arquivos continuam sendo enviados a cada commit e push.

## Por que é grave

- `TCEs/`, `file.csv` e `sicereport.pdf` contêm, segundo as regras do projeto, dados pessoais de estudantes (muitos
  menores de idade).
- `data/db.sqlite3` é um banco completo do sistema. Não foi aberto, então **não se sabe se é uma cópia da produção ou
  um banco de desenvolvimento**. Se for da produção, ele traz, entre outros:
  - CPF, data de nascimento, telefone e e-mail de estudantes, responsáveis, supervisores e equipe;
  - `totp_segredo` (o segredo da verificação em duas etapas fica **em texto claro** no banco). Os códigos de
    recuperação e os de primeiro acesso ficam como HMAC com o `SECRET_KEY`, que nunca foi versionado;
  - sessões ativas (`django_session`) e tokens da agenda iCal (`token_agenda`, em texto claro);
  - metadados de atestados (dados de saúde) e o histórico de presenças;
  - hashes de senha (PBKDF2; não reversíveis, mas sujeitos a ataque de dicionário).
- **Imagem Docker:** o `Dockerfile` faz `COPY . .`. O `.dockerignore` excluía `data`, mas **não** excluía `TCEs/`,
  `file.csv` e `sicereport.pdf`. Toda imagem construída pelo Coolify desde 16–17/11 tem esses arquivos em `/app`. Isso
  vale também para o clone do repositório que o Coolify mantém no servidor.

## O que já foi feito nesta etapa

- `.gitignore`: entraram `file.csv` e `/*.csv` (com um aviso de que ignorar não desversiona).
- `.dockerignore`: entraram `TCEs`, `importacao`, `Relatorio-estagio`, `/*.pdf`, `/*.csv` e `file.csv`. O próximo
  build já não leva esses arquivos para a imagem.

## O que falta (depende de você — nada disso foi executado)

Em ordem de urgência:

1. **Conferir a visibilidade do repositório** no GitHub (o README pede repositório privado) e quem tem acesso a ele,
   incluindo forks e clones (Coolify, outros computadores).
2. **Parar de versionar** os arquivos, sem apagá-los do disco. Como isso precisa chegar à produção, o caminho das
   regras do projeto é uma branch de correção a partir da `main`, que depois volta também para `desenvolvimento`:

   ```bash
   git switch -c correcao-dados-pessoais main
   git rm -r --cached data TCEs file.csv sicereport.pdf
   git add .gitignore .dockerignore
   git commit -m "Para de versionar dados pessoais (banco, TCEs, CSV e PDF da raiz) e os exclui da imagem Docker"
   ```

   O `--cached` tira só do índice do Git; os arquivos continuam na pasta. O merge na `main` e o push ficam para você
   decidir (regra: nada na `main` sem pedido explícito).
3. **Apagar do histórico.** O passo 2 não remove o que já está nos 38 commits nem no GitHub. Para isso é preciso
   reescrever o histórico (por exemplo, com `git filter-repo --invert-paths --path data --path TCEs --path file.csv
   --path sicereport.pdf`), fazer *force push*, pedir ao suporte do GitHub a limpeza de caches e referências de
   *pull requests*, e clonar de novo em todo lugar que tenha cópia (inclusive no Coolify). É irreversível e muda todos
   os hashes de commit: **decisão sua** (ver "Decisões pendentes").
4. **Se o `db.sqlite3` versionado veio da produção:**
   - trocar o `SECRET_KEY` (invalida sessões, links de "esqueci a senha", confirmação de e-mail, QR, links "Confirmar
     todas" e os códigos de primeiro acesso ainda não usados);
   - pedir nova configuração da verificação em duas etapas a quem a ativou (o segredo vazou) e gerar novos códigos de
     recuperação;
   - gerar novos tokens da agenda iCal;
   - avaliar a troca de senha das contas da gestão.
5. **Coolify:** apagar imagens antigas que contêm os TCEs e fazer um novo build depois do passo 2.
6. **LGPD:** avaliar, com o controlador (escola/SEDUC) e o encarregado de dados, se o caso é um incidente de segurança
   que precisa ser comunicado à ANPD e aos titulares (art. 48 da LGPD). Não é uma decisão técnica.

## Como evitar que volte a acontecer

- Manter os dados reais **fora da pasta do projeto** (por exemplo, em `~/Documentos/estagio-dados-reais/`). É a
  medida mais segura: o que não está na pasta não entra em commit, imagem ou ferramenta.
- Um *hook* de `pre-commit` que recuse arquivos `.sqlite3`, `.pem`, `.csv` e `.pdf` fora de `docs/` e `static/`.
  Fica como sugestão; não foi criado porque a Etapa 0 só pode criar arquivos em `docs/`.
