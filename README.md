# Documentation Helper
Geração automatizada de documentação técnica (Markdown) a partir de código-fonte, com LLM routing, controle de rate limiting e execução interativa via terminal.

## Tabela de conteúdos
- [Visão geral](#1-visão-geral)
- [Principais funcionalidades](#2-principais-funcionalidades)
- [Estrutura do projeto](#3-estrutura-do-projeto)
- [Como funciona a geração de documentação](#4-como-funciona-a-geração-de-documentação)
  - [Espelhamento de estrutura](#41-espelhamento-de-estrutura)
  - [Chunking e merge](#42-chunking-e-merge)
  - [Cache e modo continuar](#43-cache-e-modo-continuar)
- [Logs e rastreabilidade](#5-logs-e-rastreabilidade)
  - [Log textual](#51-log-textual)
  - [Log estruturado (JSONL)](#52-log-estruturado-jsonl)
  - [Onde os logs são salvos](#53-onde-os-logs-são-salvos)
- [Configuração](#6-configuração)
  - [config.yaml](#61-configyaml)
  - [Parâmetros de LLM e routing](#62-parâmetros-de-llm-e-routing)
  - [Controle de rate limit e concorrência](#63-controle-de-rate-limit-e-concorrência)
- [Como obter uma API key da Groq](#7-como-obter-uma-api-key-da-groq)
- [Como rodar no seu PC](#8-como-rodar-no-seu-pc)
  - [Pré-requisitos](#81-pré-requisitos)
  - [Instalação](#82-instalação)
  - [Configuração da variável GROQ_API_KEY](#83-configuração-da-variável-groq_api_key)
  - [Execução](#84-execução)
- [Solução de problemas](#9-solução-de-problemas)
  - [Erro 429 Too Many Requests](#91-erro-429-too-many-requests)
  - [Erro 400 relacionado a service_tier](#92-erro-400-relacionado-a-service_tier)
  - [Onde verificar o que está sendo gerado](#93-onde-verificar-o-que-está-sendo-gerado)


## 1. Visão geral
O Documentation Helper é uma ferramenta para gerar documentação técnica em Markdown a partir do código-fonte de um projeto. O processo percorre arquivos selecionados (por extensões), divide o conteúdo em partes menores (chunks), envia cada chunk para um modelo via API (Groq), consolida o resultado e salva a documentação espelhando a estrutura do projeto de origem.

O objetivo é produzir documentação explicativa, formal e detalhada, incluindo trechos relevantes do código, conexões entre arquivos, imports e relações no grafo de dependências, com foco em consistência e rastreabilidade do que foi gerado e quando foi gerado.

## 2. Principais funcionalidades
- Execução interativa (wizard) para escolher:
  - Pasta fonte (scan_root) a documentar
  - Pasta destino (output_root) para salvar documentação
  - Extensões de arquivos a incluir (por exemplo: .py, .ts, .tsx)
  - Modo de execução:
    - Continuar (reaproveita cache e documentação já existente)
    - Do zero (reinicia a documentação e o cache)
- Espelhamento de estrutura do projeto documentado:
  - Para cada arquivo de origem, gera um arquivo Markdown correspondente na árvore de saída
- LLM routing com fallback:
  - Prioriza modelos definidos no config.yaml e cai para alternativas em caso de falhas estruturais ou indisponibilidade
- Rate limiting robusto:
  - Respeita respostas 429 e usa headers de rate limit para aguardar janelas de liberação 
- Logs estruturados por execução:
  - Identifica exatamente qual arquivo e chunk estão sendo processados, em que momento, com duração e modelo utilizado

## 3. Estrutura do projeto

```
forest-portal-helper/
├── src/
│  └── forest_portal_helper/
│     ├── core/
│     │  ├── docgen.py
│     │  ├── logging_utils.py
│     │  ├── interactive.py
│     │  └── ...
│     └── llm/
│        ├── groq_client.py
│        ├── rate_limiter.py
│        ├── router.py
│        └── ...
├── logs/ (é gerado localmente após rodar)
├── pyproject.toml
├── config.py
├── .gitignore
└── README.md

```

## 4. Como funciona a geração de documentação

### 4.1 Espelhamento de estrutura
O helper percorre o projeto de origem e salva, no output_root, a documentação em Markdown seguindo a mesma árvore de diretórios. Isso facilita navegação e revisão, pois a documentação fica alinhada aos caminhos reais do projeto.

### 4.2 Chunking e merge
Arquivos grandes são divididos em chunks para:
- evitar estourar limites de tokens por requisição
- reduzir o risco de 429 por excesso de tokens/minuto
- melhorar confiabilidade em execuções longas

Ao final, se houver múltiplos chunks, o helper executa uma etapa de merge para unificar as documentações parciais em um único Markdown coerente, removendo duplicações e preservando a ordem lógica.

### 4.3 Cache e modo continuar
O helper mantém um manifest (cache) com hash do conteúdo do arquivo. No modo continuar, arquivos inalterados podem ser pulados automaticamente, reduzindo custos e tempo. No modo do zero, a saída e o estado são reiniciados.

## 5. Logs e rastreabilidade
A rastreabilidade foi fortalecida para permitir auditoria completa do processo.

### 5.1 Log textual
Um arquivo .log por execução registra mensagens do processo, erros e avisos.

### 5.2 Log estruturado (JSONL)
Um arquivo events_<run_id>.jsonl por execução registra eventos em formato JSON por linha, por exemplo:
- run_start, scan_done, models_ready
- file_seen, file_start, file_skipped_cache, file_end
- chunk_start, chunk_end
- merge_start, merge_end
- run_end

Esse formato é adequado para:
- grepar eventos por arquivo
- carregar em pandas
- construir dashboards de observabilidade

### 5.3 Onde os logs são salvos
- No modo wizard, logs e estado podem ser armazenados dentro do output_root em uma pasta interna:
  - output_root/.fphelper/logs
  - output_root/.fphelper/state
- No modo build padrão, logs seguem os paths configurados no config.yaml.

## 6. Configuração

### 6.1 config.yaml
O config.yaml concentra parâmetros de:
- LLM routing e limites
- chunking
- concorrência
- paths padrão

Exemplo de seção de LLM e rate limiting:

```yaml
llm:
  provider: "groq"
  api_key_env: "GROQ_API_KEY"
  api_key_fallback: "${GROQ_API_KEY}"

  temperature: 0.2
  top_p: 1
  max_completion_tokens: 1200
  stream: false

  # No plano gratuito, recomenda-se on_demand ou omitir
  service_tier: "on_demand"
  reasoning_effort: "medium"

  throttle:
    enabled: true
    min_interval_seconds: 2.2
    min_remaining_tokens: 800

  routing:
    validate_with_models_endpoint: true
    preferred_models:
      - "openai/gpt-oss-120b"
      - "groq/compound"
      - "llama-3.3-70b-versatile"
      - "qwen/qwen3-32b"
      - "openai/gpt-oss-20b"
      - "llama-3.1-8b-instant"

performance:
  max_concurrency: 1

docgen:
  max_chars_per_request: 12000
  chunk_overlap_lines: 30
```

Observação sobre service_tier:

* A Groq oferece diferentes tiers (on_demand, flex, performance, auto). A disponibilidade depende do plano e permissões da org. ([GroqCloud][1])
* Em contas free, é comum que auto não esteja disponível. Nesses casos, use on_demand (ou omita o parâmetro e deixe o default). ([GroqCloud][1])

### 6.2 Parâmetros de LLM e routing

O router tenta os modelos na ordem definida e troca automaticamente em caso de falhas. Em workloads grandes, a lista deve incluir modelos mais leves no fim para garantir que o processo conclua mesmo sob limitações.

### 6.3 Controle de rate limit e concorrência

A Groq retorna 429 Too Many Requests quando limites são excedidos e recomenda respeitar o header retry-after e demais headers de rate limit. ([GroqCloud][2])

Recomendações para plano gratuito:

* max_concurrency = 1
* min_interval_seconds >= 2.0
* reduzir max_completion_tokens
* reduzir max_chars_per_request quando houver muitos arquivos grandes

## 7. Como obter uma API key da Groq

A forma recomendada é criar uma conta na Groq Cloud e configurar a variável de ambiente GROQ_API_KEY. O Quickstart oficial descreve a configuração via variável de ambiente. ([GroqCloud][3])

Links úteis (copie e cole no navegador):

```text
Groq Quickstart (oficial): https://console.groq.com/docs/quickstart
Groq API Keys (console):   https://console.groq.com/keys
Video no YouTube:          https://www.youtube.com/watch?v=MZaXGlTcWrA
```

O vídeo acima mostra o passo a passo para obter a API key e validar que a chave funciona. ([YouTube][4])

Boas práticas:

* Nunca commitar a chave no repositório
* Preferir variável de ambiente ou arquivo .env (quando aplicável) ([GroqCloud][5])

## 8. Como rodar no seu PC

### 8.1 Pré-requisitos

* Python 3.10+ recomendado
* Acesso à internet para chamadas à Groq API
* Uma GROQ_API_KEY válida

### 8.2 Instalação

Na raiz do projeto:

```bash
python -m venv venv
```

Ative a venv:

* Windows (PowerShell):

```powershell
.\venv\Scripts\Activate.ps1
```

* Linux/Mac:

```bash
source venv/bin/activate
```

Instale o projeto:

```bash
python -m pip install -e .
```

Verifique se o CLI está acessível:
```bash
python -m forest_portal_helper.cli --help
```

### 8.3 Configuração da variável GROQ_API_KEY

Windows (PowerShell), para a sessão atual:

```powershell
$env:GROQ_API_KEY="sua_chave_aqui"
```

Windows (persistente para novos terminais):

```powershell
setx GROQ_API_KEY "sua_chave_aqui"
```

Linux/Mac:

```bash
export GROQ_API_KEY="sua_chave_aqui"
```

### 8.4 Execução

O projeto possui três formas principais de execução:

1. Wizard interativo (recomendado)

* Pergunta scan_root, output_root, extensões e modo (continuar ou do zero)
* Ao final, permite rodar novamente sem encerrar o processo

Comando:

```bash
python -m forest_portal_helper.cli wizard
```

2. Build não interativo (usa defaults do config.yaml)

```bash
python -m forest_portal_helper.cli build
```

3. Documentar um único arquivo por caminho relativo

```bash
python -m forest_portal_helper.cli file "components/Header.tsx"
```

## 9. Solução de problemas

### 9.1 Erro 429 Too Many Requests

Causa:

* rate limit excedido (requests/minuto ou tokens/minuto)

Ação:

* reduzir max_concurrency para 1
* aumentar min_interval_seconds
* reduzir max_completion_tokens
* reduzir max_chars_per_request
* manter a lista de modelos com fallback para modelos mais leves

A Groq indica o uso de retry-after e headers de rate limit quando ocorre 429. ([GroqCloud][2])

### 9.2 Erro 400 relacionado a service_tier

Causa:

* service_tier não disponível no plano da org

Ação:

* usar on_demand ou omitir service_tier

Os tiers aceitos e a semântica do parâmetro estão documentados pela Groq. ([GroqCloud][1])

### 9.3 Onde verificar o que está sendo gerado

Consulte:

* logs/run_<run_id>.log para logs textuais
* logs/events_<run_id>.jsonl para rastreio estruturado por arquivo e chunk

[1]: https://console.groq.com/docs/service-tiers "Service Tiers - GroqDocs"
[2]: https://console.groq.com/docs/rate-limits "Rate Limits - GroqDocs"
[3]: https://console.groq.com/docs/quickstart "Quickstart - GroqDocs"
[4]: https://www.youtube.com/watch?v=MZaXGlTcWrA& "How to Get a Groq API Key (Tutorial)"
[5]: https://console.groq.com/docs/libraries "Groq Client Libraries - GroqDocs"
