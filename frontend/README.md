# EvalForge Frontend V0.3

React 19 / TypeScript / Vite / React Router / TanStack Query v5 / Tailwind CSS v4。

前端负责创建和查看评测任务，独立 Worker 负责执行。完整启动步骤见 [项目 README](../README.md#quick-start)。

## 启动前端

在 Ubuntu / WSL 的仓库根目录执行，使用 Node 22.13+（已验证 22.23.3）：

```bash
cd /home/terry/projects/agent-evaluation-harness
nvm use 22
VITE_API_BASE_URL=http://127.0.0.1:8013 npm --prefix frontend run dev -- --host 0.0.0.0 --port 5173 --strictPort
```

首次安装依赖可在切换到 Node 22 后执行 `npm --prefix frontend ci`。API 默认地址为 `http://127.0.0.1:8000`；以上命令显式指向本地 EvalForge API 的 `8013` 端口。修改环境变量后需要重启 Vite。

打开 <http://localhost:5173/evaluation-jobs> 或 <http://127.0.0.1:5173/evaluation-jobs>。

**不要使用 WSL Network IP 或 `0.0.0.0` 作为本机浏览器地址。** 当前后端只允许来源 `http://localhost:5173` 和 `http://127.0.0.1:5173`；使用 `http://172.17.3.158:5173` 等地址会触发 `OPTIONS 400 / Disallowed CORS origin`，导致页面无法加载数据。

`--host 0.0.0.0` 表示监听所有网络接口；`--strictPort` 防止 Vite 自动改用未经 CORS 允许的端口。若确需通过其他 IP / 域名访问，请按项目 README 中的 CORS 排查说明配置后端。

## 启动 API 与 Worker

两个独立终端，均使用现有数据库配置和 Python 环境：

```bash
# 终端一：API
cd /home/terry/projects/agent-evaluation-harness/backend
.venv/bin/python -m uvicorn app.main:app --env-file .env --host 0.0.0.0 --port 8013
```

```bash
# 终端二：Worker
cd /home/terry/projects/agent-evaluation-harness/backend
.venv/bin/python -m app.worker
```

PostgreSQL、现有持久化表与 Job 迁移需要已就绪。`backend/.env` 中的 `HARNESS_DATABASE_URL` 必须有效。Worker 自动读取该文件，与 API 使用同一个数据库；未启动 Worker 时异步任务不会被执行。

## 页面与交互

Routes: `/evaluation-jobs`, `/evaluation-jobs/new`, `/evaluation-jobs/:jobId`, and `/experiments/:experimentId`. Existing synchronous `/experiments/run`, `/runs`, `/runs/:runId`, and `/runs/:runId/timeline` remain available.

Create Job accepts the actual backend case fields: ID, nonempty string input, string expected output (including empty), expected tool calls (JSON array or null), and object metadata. Each tool call uses `tool_name` and object `arguments`. Version fields are experiment labels, not selectable agent implementations.

Detail polls every two seconds while active; the visible list page polls every five seconds when it contains active jobs. Terminal-only/empty pages use manual refresh. Changing filters/pages uses a separate cache identity and never retains another page as placeholder data. Leaving a page removes its polling subscription. Cancellation returns the server's state; `cancel_requested` remains active until the worker acknowledges it. Worker attempts are separate from case retries, and failures count toward processed progress.

Experiment details fetch the selected experiment directly and link its real `run_ids` to existing Run Detail/Timeline views. The existing Runs API cannot filter by experiment; no unsupported query parameter is sent. The existing backend represents cancelled experiments as `failed`; the job still shows its distinct `cancelled` state.

Checks from the repository root:

```sh
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run lint
npm --prefix frontend test
```

Tests use Node's built-in test runner and the existing Vite loader; no additional runtime or test dependency was added.

## 真实 Agent Showcase

`/comparison` 已接入真实成对评测演示，侧栏名为 Agent Showcase。自动恢复最近一组明确关联的 Job；历史组可使用带 baseline/candidate 参数的 URL。Run Detail 增加来源与指标细节，Timeline 支持事件筛选与完整参数展开。

完整启动与验证边界见 [Agent 接入说明](../docs/BUSINESS_AGENT_SHOWCASE.md)。


## Adapter Studio（Stage 8）

侧栏进入 `/adapter-studio`，完成 Profile、JSON 样本、显式字段披露、异步生成、Trace 预览、验证、人工审核发布和历史版本/使用查询。复用现有 UI/API/状态管理，无新增依赖。Registry Bearer 只保存在本页内存，不写浏览器存储；离开需重新连接。

需先启用原 Registry 并运行独立 Registry Worker；使用数据需已有 v015 迁移。Agent HTTP 配置继续由原服务端管理。没有独立 Golden 的候选无法发布。完整流程、文件职责、部署前提和真实测试结果见 [Adapter Studio 说明](../docs/INTELLIGENT_ADAPTER_STUDIO.md)。
