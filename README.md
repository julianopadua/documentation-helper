# forest-portal-helper

Gera documentação profunda (Markdown) para cada arquivo em `forest-portal/src`,
replicando a estrutura e criando um `.md` por arquivo.

Layout padrão:
- `src/components/Header.tsx` -> `generated/src/components/Header/Header.md`

## Setup (Windows)

1) Defina a chave:
- PowerShell: `setx GROQ_API_KEY "SUA_CHAVE"`

2) Instale em modo dev:
- `python -m pip install -e .`

3) Gere docs:
- `fphelper build`

Comandos:
- `fphelper build --force`
- `fphelper models`
