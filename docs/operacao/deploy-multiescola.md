# Deploy da fundação multiescola (fase B da Etapa 1)

Vem **depois** da troca para o PostgreSQL ([migracao-postgresql.md](migracao-postgresql.md)), num deploy próprio.
Para quem usa, nada muda: a escola atual continua com as mesmas telas, textos e folha.

## O que o deploy faz

O `migrate` automático do `entrypoint.sh` aplica:

| Migration | O que faz | Reversão |
|---|---|---|
| `core.0046_segredo_2fa_cifrado` | cifra o segredo da verificação em duas etapas (chave fora do banco) | decifra (precisa da mesma chave) |
| `escolas.0001_initial` | cria `RedeEnsino`, `Escola`, `VinculoEscola` | apaga as tabelas |
| `core.0047_escola_nas_entidades` | coluna `escola` (opcional) em 22 entidades; tira a unicidade global de `Curso.nome` e `ModeloEmail.tipo` | remove as colunas |
| `core.0048_associar_escola_atual` | cria a rede SEDUC/CE e a escola atual a partir da `Configuracao`, associa todas as linhas a ela, cria os vínculos (papel de cada conta; `ADMIN` para os administradores) e **compara as contagens de todas as tabelas** antes e depois | limpa a coluna, apaga vínculos, escola e rede; compara de novo |
| `core.0049_escola_obrigatoria` | `escola` obrigatória; unicidades `(escola, nome)` em cursos e `(escola, tipo)` nos modelos de e-mail | volta a opcional |
| `core.0050_arquivos_por_escola` | caminhos novos de arquivos (só no código; nada no banco) | — |

Se as contagens diferirem, a migration 0048 falha e a transação desfaz tudo: o deploy não sobe e o banco fica como
estava.

## Antes

1. Ensaio na homologação com `popular_demo` (feito pelo agente num SQLite: ida, volta e ida sem diferença em
   nenhuma tabela). Repita na homologação com PostgreSQL.
2. Ensaio com a cópia real: restaure o último backup do PostgreSQL de produção num recurso temporário e rode lá
   `DATABASE_URL=postgres://...temporario... python manage.py migrate` com a imagem nova. Confira a saída e o
   `python manage.py relatorio_cpf` (só ids). Apague o recurso.
3. Decida a `CHAVE_DADOS`: sem ela, a cifragem do 2FA usa uma chave derivada do `SECRET_KEY`. Recomendado: gere uma
   própria (`python manage.py chave_dados --nova`), guarde fora do servidor e coloque nas variáveis **antes** do deploy.
4. Backup na hora (banco e volume) e anote a última migration (`0045_responsaveis_legais`).

## Depois

- `/saude/`; contas de teste de cada perfil; painel; Configurações (o nome da escola é o mesmo); folha de frequência
  com o brasão de sempre; "Avaliações (SICE)" no menu; um anexo antigo abrindo; um anexo novo indo para
  `escolas/<id>/…`.
- Scheduled Task nova: `python manage.py tarefas_periodicas` a cada 10 minutos (`*/10 * * * *`).
- `python manage.py relatorio_cpf`: lista de CPFs repetidos para a limpeza antes da regra de CPF único (só ids).

## Reversão

Com a imagem **nova** (é ela que tem as funções de volta):

```bash
python manage.py migrate core 0045
```

```bash
python manage.py migrate escolas zero
```

Depois, deploy da versão anterior (fase A). A reversão só funciona enquanto houver **uma escola** no banco (a 0048
recusa juntar escolas diferentes).

## Cadastrar uma segunda escola (só depois do piloto ou para testes na homologação)

No `/admin/` (administrador da plataforma): *Escolas → Adicionar* (a configuração da escola é criada junto) e
*Vínculos* para as pessoas. Telas de implantação ficam para a Etapa 7.
