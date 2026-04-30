# Trading AI App

Uma plataforma que permite traders descrever estratégias em linguagem natural, validar com backtesting visual, acompanhar execução em tempo real, e exportar scripts prontos para produção.

## Stack
- **Frontend**: Next.js 14 (App Router) + TailwindCSS + Lightweight Charts
- **Backend**: FastAPI (Python) + WebSocket
- **Engine**: Python + TA-Lib + asyncio
- **Database**: PostgreSQL + Redis
- **LLM**: OpenAI GPT-4o
- **Broker**: MetaApi (MT4/MT5)

## Setup

```bash
# Instalar dependências do sistema (TA-Lib)
apt-get update && apt-get install -y libta-lib-dev

# Instalar dependências Python
pip install -r requirements.txt

# Configurar variáveis de ambiente
cp .env.example .env

# Executar backend
cd backend && uvicorn main:app --reload

# Executar engine (separado)
cd engine && python main.py
```

## Roadmap
Ver documento de planejamento: `docs/PLANO-PRODUTO.md`
