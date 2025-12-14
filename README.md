# Forest Portal Helper - Documentação e Geração de Docs

Este projeto foi desenvolvido para automatizar a geração de documentação a partir de código-fonte, utilizando LLMs (Large Language Models), com integração ao Groq. A estrutura é modular e permite a customização de configurações, com foco na escalabilidade, eficiência e controle de requisições.

## Tabela de Conteúdos

1. [Visão Geral](#visão-geral)
2. [Estrutura do Projeto](#estrutura-do-projeto)
3. [Configuração](#configuração)
   1. [Configuração do `config.yaml`](#configuração-do-configyaml)
   2. [API Key e Taxas de Serviço](#api-key-e-taxas-de-serviço)
4. [Funcionamento do Router](#funcionamento-do-router)
5. [Gerenciamento de Rate Limiting](#gerenciamento-de-rate-limiting)
6. [Gerando Documentação](#gerando-documentação)
7. [Como Rodar o Projeto](#como-rodar-o-projeto)
8. [Considerações Finais](#considerações-finais)

## Visão Geral

O `Forest Portal Helper` é uma ferramenta para facilitar a documentação de código-fonte, utilizando LLMs, como o Groq. A ferramenta divide os arquivos de código em partes menores (chunks) e usa modelos de IA para gerar documentação explicativa sobre o código, organizando tudo em arquivos Markdown.

Além disso, o projeto oferece controle de requisições para a API Groq, garantindo que o processo de geração de documentação seja eficiente, respeitando os limites de taxa de requisições (rate limits) e otimizando o uso dos modelos de IA.

## Estrutura do Projeto

A estrutura do projeto foi organizada da seguinte forma:

```

forest-portal-helper/
│
├── src/
│   ├── forest_portal_helper/
│   │   ├── core/
│   │   │   ├── chunking.py
│   │   │   ├── config.py
│   │   │   ├── docgen.py
│   │   │   ├── fs_scanner.py
│   │   │   ├── imports_index.py
│   │   │   ├── manifest.py
│   │   │   ├── output_layout.py
│   │   │   └── prompting.py
│   │   ├── llm/
│   │   │   ├── groq_client.py
│   │   │   ├── rate_limiter.py
│   │   │   └── router.py
│   │   └── main.py
│   ├── requirements.txt
│   ├── setup.py
└── README.md

```

- **`core/`**: Contém a lógica principal de manipulação de arquivos, leitura de código-fonte e geração de documentação.
- **`llm/`**: Contém os módulos responsáveis pela comunicação com a API Groq e controle de requisições.
- **`main.py`**: O ponto de entrada principal do projeto.
- **`requirements.txt`**: As dependências do projeto.

## Configuração

### Configuração do `config.yaml`

O arquivo `config.yaml` contém todas as configurações do projeto, como parâmetros de taxa de serviço, temperatura dos modelos, número máximo de tokens, entre outros. Aqui está um exemplo de como o arquivo deve ser configurado:

```yaml
llm:
  provider: "groq"
  api_key_env: "GROQ_API_KEY"
  api_key_fallback: "${GROQ_API_KEY}"
  temperature: 0.2
  top_p: 1
  max_completion_tokens: 1200
  stream: false
  service_tier: "on_demand"  # Use on_demand para o plano gratuito
  reasoning_effort: "medium"
  throttle:
    enabled: true
    min_interval_seconds: 2.2  # Intervalo mínimo entre as requisições
    min_remaining_tokens: 800   # Número mínimo de tokens restantes

performance:
  max_concurrency: 1  # Limita a concorrência de requisições no plano gratuito

docgen:
  max_chars_per_request: 12000  # Tamanho máximo por requisição para não exceder o limite de tokens
  chunk_overlap_lines: 30
```

#### Explicação dos Parâmetros:

* **`provider`**: Define qual API de LLM será utilizada (no caso, Groq).
* **`api_key_env`**: A chave da API para autenticação com a Groq. Deve ser configurada como variável de ambiente.
* **`temperature`**: Controla a aleatoriedade das respostas do modelo (valor de 0 a 1).
* **`top_p`**: Define o top-p sampling para controlar a diversidade da resposta.
* **`max_completion_tokens`**: Número máximo de tokens que a IA pode gerar em uma resposta.
* **`service_tier`**: Define o nível de serviço. No plano gratuito, deve ser configurado para `on_demand`.
* **`throttle`**: Parâmetros de controle de taxa de requisições, incluindo intervalo mínimo entre requisições e número mínimo de tokens restantes.

### API Key e Taxas de Serviço

A chave da API do Groq (`GROQ_API_KEY`) deve ser configurada no arquivo de ambiente ou definida como variável de ambiente para garantir o acesso à API.

Para usuários no plano gratuito, **o `service_tier` deve ser configurado para "on_demand"**, caso contrário, você pode enfrentar erros de taxa de serviço (ex: `400`).

## Funcionamento do Router

O router é o componente responsável por gerenciar os modelos de LLM e as requisições. Ele tenta diferentes modelos com base nas preferências definidas em `config.yaml` e faz o tratamento adequado para erros, como limites de taxa (`429`), erro de capacidade (`498`), e outros erros estruturais (`4xx`).

O `ModelRouter` executa as seguintes etapas:

1. **Validação dos Modelos**: Verifica quais modelos estão disponíveis na API Groq.
2. **Geração da Documentação**: Para cada arquivo de código, o router gera a documentação utilizando os modelos disponíveis e processa os resultados.

## Gerenciamento de Rate Limiting

A ferramenta usa um mecanismo de **rate limiting** para garantir que o número de requisições feitas à API Groq respeite as limitações impostas pelo plano (especialmente o plano gratuito, que tem limites rigorosos).

* **Intervalo mínimo entre requisições**: Definido em `min_interval_seconds` no arquivo `config.yaml`.
* **Controle de tokens restantes**: O projeto usa os cabeçalhos de resposta da API Groq para verificar quantos tokens restam e ajusta o comportamento para não exceder o limite.

## Gerando Documentação

A geração de documentação é feita em etapas:

1. O código-fonte é dividido em **chunks** para facilitar o processamento.
2. Cada chunk é enviado para o modelo de LLM para gerar a documentação.
3. A documentação gerada é unificada em um único arquivo Markdown.

A documentação é organizada de forma que:

* **Importações** e **arquivos importados** são linkados nas seções apropriadas.
* O código é explicado linha por linha, e as conexões entre os arquivos de código são detalhadas.

## Como Rodar o Projeto

### Passo 1: Configuração do Ambiente

1. Crie um ambiente virtual com o comando:

   ```bash
   python -m venv venv
   ```
2. Ative o ambiente:

   * No Windows:

     ```bash
     .\venv\Scripts\Activate
     ```
   * No Linux/MacOS:

     ```bash
     source venv/bin/activate
     ```
3. Instale as dependências:

   ```bash
   pip install -r requirements.txt
   ```

### Passo 2: Defina a API Key

Configure a chave da API Groq como variável de ambiente:

```bash
setx GROQ_API_KEY "sua_chave_aqui"
```

### Passo 3: Execute o Projeto

Para gerar a documentação, execute o comando:

```bash
python -m forest_portal_helper.core.docgen generate_docs
```

O projeto irá processar os arquivos de código e gerar a documentação na pasta especificada.

## Considerações Finais

Este projeto oferece uma solução eficiente para a geração automatizada de documentação para projetos de código-fonte, utilizando poderosas ferramentas de IA, como o Groq. A modularidade e o controle de requisições garantem que o sistema seja escalável e eficiente, mesmo para grandes volumes de código.

Caso encontre algum erro ou deseje contribuir com melhorias, fique à vontade para abrir uma **issue** ou **pull request**.

---

**Este README foi gerado automaticamente pelo Forest Portal Helper.**
