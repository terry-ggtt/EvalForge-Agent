# 本地运行 EvalForge

[返回项目首页](../README.md) · [第三方 Evaluator 开发](extending-evaluators.md)


以下命令在 **Ubuntu / WSL** 执行。浏览器使用本机 localhost。完整默认演示需要 PostgreSQL、API、Evaluation Worker 和前端；AI Mapping Generation 另需独立 Mapping Worker。

### 1. 准备运行环境

已验证环境：Python **3.12.3**、PostgreSQL **16**、Node **22.23.3**。前端使用 React 19、TypeScript 6、Vite 8、Tailwind 4；后端使用 FastAPI、Pydantic v2、psycopg 异步连接池。LangGraph / LangChain 用于框架适配和模型生成客户端。

从仓库根目录首次安装：

```bash
python3.12 -m venv backend/.venv

backend/.venv/bin/python -m pip install \
  fastapi uvicorn 'pydantic>=2,<3' 'psycopg[binary,pool]>=3.2' \
  python-dotenv httpx sqlalchemy aiosqlite \
  langgraph langchain-core langchain-openai \
  pytest pytest-asyncio

# 安装宿主使用的公开 Evaluator SDK
backend/.venv/bin/python -m pip install ./packages/evaluator-sdk

# 使用已安装的 Node 22；如本机通过 nvm 管理，可先执行 nvm use 22
npm --prefix frontend ci
```

已有可用虚拟环境时无需重建。当前根 requirements.txt 保留历史 httpx2 项，且没有完整列出 dotenv / 异步测试依赖，因此这里显式列出当前运行与测试所需包。后端尚未提供可复现依赖锁文件；上述是环境准备命令，不是已验证的全新环境一键安装承诺。

### 2. 配置独立开发数据库

准备一个可连接的 PostgreSQL 开发库，在本地 `backend/.env` 中填写：

```dotenv
HARNESS_DATABASE_URL="postgresql://USER:PASSWORD@127.0.0.1:5432/evalforge_dev"
HARNESS_AGENT_KIND=demo
```

用实际账号替换 USER / PASSWORD。已有 .env 应保留并检查，不要覆盖。该文件已被 Git 忽略，不提交真实凭据。

**首次初始化仅对选定的开发库执行。** 当前 Run / Experiment 的基础表由已有 Store.initialize 管理；Evaluation Job 及后续扩展使用显式 SQL 迁移。先创建基础表，再按顺序应用迁移：

```bash
cd backend
.venv/bin/python - <<'PY'
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from psycopg import AsyncConnection

from app.config import get_database_url
from app.harness.postgres_run_store import PostgresRunStore
from app.harness.postgres_experiment_store import PostgresExperimentStore


async def initialize():
    """Create base tables and apply job migrations to the configured development DB."""
    load_dotenv(".env")
    dsn = get_database_url()
    async with PostgresRunStore(dsn) as runs, PostgresExperimentStore(dsn) as experiments:
        await runs.initialize()
        await experiments.initialize()

    async with await AsyncConnection.connect(dsn, autocommit=True) as conn:
        for name in ("v0131_evaluation_jobs.sql", "v0136_recovery.sql"):
            await conn.execute((Path("migrations") / name).read_text())


asyncio.run(initialize())
PY
cd ..
```

可选 Intelligent Adapter 的迁移顺序为 `v014_adapter_registry.sql` → `v015_pinned_mapping_evaluation.sql`，在上述基础表和 Job 迁移之后应用。应用不会自动执行这些可选迁移。

### 3. 启动 API、评测 Worker 与前端

三个终端分别执行：

```bash
# 终端一：API
cd backend
.venv/bin/python -m uvicorn app.main:app \
  --env-file .env --host 0.0.0.0 --port 8013
```

```bash
# 终端二：Evaluation Worker
cd backend
.venv/bin/python -m app.worker
```

```bash
# 终端三：前端，从仓库根目录执行
VITE_API_BASE_URL=http://127.0.0.1:8013 \
  npm --prefix frontend run dev -- --host 0.0.0.0 --port 5173 --strictPort
```

访问：

- 前端：[http://localhost:5173/evaluation-jobs](http://localhost:5173/evaluation-jobs)
- API 文档：[http://127.0.0.1:8013/docs](http://127.0.0.1:8013/docs)
- 健康检查：[http://127.0.0.1:8013/health](http://127.0.0.1:8013/health)

API 与 Worker 必须使用同一个数据库和一致的 Agent 配置。当前 CORS 允许 localhost:5173 与 127.0.0.1:5173；浏览器使用 WSL Network IP 或 Vite 自动切换端口会被拒绝。前端默认 API 地址为 8000，此处显式使用 8013，避免本机端口冲突。

### 4. 创建第一个真实持久化 Job

```bash
curl -sS http://127.0.0.1:8013/evaluation-jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "first-demo-evaluation",
    "dataset_version": "demo-dataset-v1",
    "agent_version": "demo-v1",
    "cases": [
      {
        "id": "rag-001",
        "input_text": "Explain RAG.",
        "expected_output": "Demo Agent response: Explain RAG.",
        "expected_tool_calls": [],
        "metadata": {}
      }
    ]
  }'
```

接口返回 job_id。Worker 处理后，可从任务进入 Experiment、Run 和 Timeline。

agent_version、model_name、prompt_version 是实验记录标签，**不会仅凭标签自动部署模型或切换 Agent**。当前运行实现由服务端 HARNESS_AGENT_KIND 决定。CSV / JSON / JSONL 的加载和字段归一化已有库接口，当前没有完整 Dataset 管理 CRUD 页面/API。

### 5. 可选：启用 Adapter Studio 与 AI 生成

在已应用 v014 / v015 后，按 [Registry 配置说明](INTELLIGENT_ADAPTER_REGISTRY.md) 配置：

| 配置 | 用途 |
| --- | --- |
| HARNESS_ADAPTER_REGISTRY_ENABLED=1 | 启用 API / Evaluation Worker 的 Registry 读取能力 |
| HARNESS_ADAPTER_PRINCIPALS | 服务端 token_sha256、subject、role 绑定 |
| HARNESS_MAPPING_GENERATION_BUDGET | 服务端 Token / 费用 / 次数 / 超时预算；不配置仍可使用人工规则流程 |
| MAPPING_LLM_MODEL / MAPPING_LLM_API_KEY | 独立 Mapping Worker 的模型配置 |
| MAPPING_LLM_BASE_URL | 可选模型供应商地址 |

重启 API / Evaluation Worker，使可选配置生效。Mapping Worker 与 Evaluation Worker 是不同入口；前者从进程环境读取配置，启动前需显式导入：

```bash
# 单独终端；仅在已配置模型和预算时启动
cd backend
set -a
source .env
set +a
.venv/bin/python -m app.registry.worker
```

在 Studio 输入服务端配置的 Bearer，完成样本与规则流程。正式评测绑定 Mapping 时，创建 Job 还需显式提供 adapter_id、正整数 adapter_version，并使用 editor 以上 Registry 凭据；当前该响应集成要求 Business HTTP 模式。不要使用 latest，也不要将模型生成接口放入逐 Case 运行路径。


## 可选：安装关键词覆盖率插件

```bash
backend/.venv/bin/python -m pip install ./examples/evalforge-keyword-coverage
export EVALFORGE_EVALUATOR_PLUGINS='{"allowlist":[{"evaluator_id":"keyword_coverage","distribution":"evalforge-keyword-coverage","distribution_version":"0.1.0"}]}'
```

将该环境变量配置到 API 与 Worker，再重启相关进程。
通过 GET /evaluators 确认已注册；创建任务时显式选择 evaluators，并在 Case.metadata.expected_keywords 提供预期关键词。
完整示例与验证流程见[开发指南](extending-evaluators.md)。
