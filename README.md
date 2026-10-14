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
