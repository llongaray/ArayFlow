# Aray Social Publisher — P1 (Google Sheets + Drive)

Pacote de validação e download: **não agenda nem publica no Instagram e não altera a planilha**.

## 1. Preparação Windows

Coloque estes arquivos na pasta `L:\Sistemas\GitHub_llongaray\Auto_post\` (mantendo `config/`). Preserve seu `.env` existente e acrescente as variáveis de `.env.example` que faltarem.

Execute:

```powershell
py -m pip install -r requirements.txt
py -m pip install tzdata
```

## 2. Ativar APIs Google e criar OAuth Desktop

1. Acesse https://console.cloud.google.com e selecione/crie um projeto do Google Cloud na conta **aray.solucoes@gmail.com**.
2. Em **APIs e serviços > Biblioteca**, habilite **Google Sheets API** e **Google Drive API**.
3. Em **Google Auth Platform**, configure a tela de consentimento. Se o aplicativo estiver em modo *Testing*, adicione `aray.solucoes@gmail.com` como usuário de teste.
4. Crie o **OAuth Client ID** para **Desktop app** (Aplicativo para computador).
5. Baixe o JSON e salve como `config/google_credentials.json`. Nunca publique o JSON ou o token no GitHub.
6. Na primeira execução, escolha **aray.solucoes@gmail.com** na janela OAuth.

## 3. Testar

```powershell
py main.py --check
py main.py --date 2026-10-14 --dry-run
py main.py --date 2026-10-14 --download
py main.py --date tomorrow --dry-run
```

- `--check`: autenticação e leitura da planilha.
- `--dry-run`: verifica pasta, nomes, quantidade, legenda e ordem, sem baixar arquivos.
- `--download`: salva as imagens em `downloads/AAAA-MM-DD/ARAY-...`.
- Nenhuma dessas opções cria contêiner, agenda ou publica mídia na Meta.

**Planilha:** https://docs.google.com/spreadsheets/d/1dA5GFM2qS6RXzpgEiBXLHO4uYkwp4l46B17dCZCcZKM/edit

## Observações

- A coluna **Tipo** deve indicar `Imagem única` ou `Carrossel`.
- **Qtd. imagens** deve corresponder à quantidade de slides oficiais. Arquivos contendo `alternativa`, `alternative` ou `backup` são ignorados.
- A coluna **Pasta das imagens** deve conter a URL da pasta Google Drive de cada publicação.
- Utilize o Google OAuth Desktop. O MCP do ChatGPT não é uma credencial OAuth reutilizável automaticamente pelo Python local.
- Em caso de erro de OAuth, nunca exponha credenciais ou tokens ao pedir ajuda.


---

## ArayFlow v0.2.0 — validacao e publicacao controlada

Esta versao adiciona `image_validator.py`, `instagram_publisher.py`, `publication_store.py` e `publish_post.py`.

**IMPORTANTE:** O fluxo completo de publicacao de carrossel ainda nao passou por um teste real. A Meta exige URLs HTTPS publicas diretamente acessiveis para buscar as imagens. O download do Google Drive e local e **nao** fornece essa hospedagem por si so. Nao existe agendamento automatico nesta versao.

### Atualizar localmente

No terminal PowerShell do projeto, com `.venv` ativo:

```powershell
git pull origin main
python -m pip install -r requirements.txt
```

Se ainda nao tiver baixado as imagens:

```powershell
python main.py --date 2026-10-14 --download
```

### Etapa A — validacao offline, sem publicar

```powershell
python publish_post.py --post ARAY-20261014-001
```

O comando verifica a planilha, a quantidade de arquivos locais, integridade, tamanho, resolucao, proporcao e legenda. Nao cria conteineres nem publica.

### Etapa B — preparar conteineres na Meta (opcional)

Antes, revisar o conteudo editorial e mudar o Status da linha para `Aprovado`.

Criar, **somente no seu computador**, um JSON como `data/post-001-urls.json`:

```json
{
  "ARAY-20261014-001_slide-01.png": "https://seu-dominio.exemplo/post-001-slide-01.png",
  "ARAY-20261014-001_slide-02.png": "https://seu-dominio.exemplo/post-001-slide-02.png",
  "ARAY-20261014-001_slide-03.png": "https://seu-dominio.exemplo/post-001-slide-03.png"
}
```

Os enderecos acima sao **apenas exemplos**. As URLs reais precisam servir os arquivos PNG/JPG por HTTPS sem autenticacao nem pagina intermediaria.

```powershell
python publish_post.py --post ARAY-20261014-001 --manifest .\data\post-001-urls.json --prepare
```

Confirmacao interativa: `PREPARAR ARAY`. Isso cria conteineres na Meta, mas **nao publica**. IDs ficam em `data/arayflow.sqlite3`, arquivo ignorado pelo Git.

### Etapa C — publicacao real e imediata (opcional)

```powershell
python publish_post.py --post ARAY-20261014-001 --publish
```

Confirmacao interativa: `PUBLICAR ARAY`. O comando publica imediatamente, nao agenda. Evita segundo envio automatico se houver publicacao confirmada ou resultado incerto.

### Limitacoes importantes

- A planilha Google e consultada com OAuth de **somente leitura**; esta versao nao muda o status no Sheets.
- A conta precisa continuar configurada no `.env` (`TOKEN` e `CONTA_INSTA_ID`).
- Mantenha `.env`, `config/google_credentials.json`, `config/google_token.json`, `data/`, `downloads/` e manifestos locais fora dos commits.
- Registros antigos publicados fora do ArayFlow nao estao no SQLite: revise o perfil antes de publicar.
- O limite de formato aqui e uma verificacao preliminar; a validacao definitiva e feita pela Meta.
- Nao execute comandos de publicacao ate revisar o conteudo, as fontes e as imagens.

### Estado de desenvolvimento

- P0: teste isolado de publicacao de uma imagem — validado anteriormente.
- P1: Google Sheets e Drive — validados para leitura e download.
- P2: validacao offline e modulos de carrossel/idempotencia — implementados, **aguardando teste local e teste real supervisionado**.
