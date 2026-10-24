# 真实业务 Agent 接入与面试演示

## 当前链路与边界

Windows `D:\ai_agent\project agent` 保留自己的 Python 3.13、LangGraph、真实 CPU BGE Embedding/Reranker 和配置的 DeepSeek。WSL Harness 仍拥有 Job Queue、Worker、Case Checkpoint、Run/Experiment/Trace 持久化。

```text
前端 Agent Showcase
  → POST /evaluation-jobs（两组真实异步任务）
  → 原 PostgreSQL 队列 / 独立 Worker / Executor
  → BusinessHttpAdapter
  → Windows /evaluate（独立 Bearer Token）
  → 原 Agent build_graph / Nodes / Runner
  → 理解模型 → BM25 / Dense / RRF / Reranker / 证据门控 → 回答
  → 原 ToolExecutor（只读业务查询）
  → 真实事件 + 回答 + 引用
  → 参考标注指标 → 原 Experiment / Run Detail / Timeline
```

Bridge 使用 `data/runtime/harness-bridge` 的独立 SQLite、Qdrant 和合成业务库，不复用或修改原 Agent 正常业务数据库。每个评测案例建立新任务与 Checkpoint；不批准人工写入。API 与 Worker 必须加载同一份专用环境文件。

默认 `HARNESS_AGENT_KIND=demo` 仍保持原 DemoAgent。真实接入必须明确选择 `business_http`。Case 的 Agent Version 是版本标签，不会偷偷选择另一套实现。

## 启动：四个终端

本机已生成独立 Token、Bridge 索引与 Harness 的私有配置文件。下面命令用于重启；已有服务运行时不要重复启动。

### 1. Windows PowerShell：真实 Agent Bridge（8020）

```powershell
Set-Location 'D:\ai_agent\project agent'
.\.venv\Scripts\python.exe -X utf8 scripts\run_harness_bridge.py --port 8020
```

首次没有隔离索引时，显式增加 `--build-index`。本地模型文件需已准备；不会自动下载或修改模型凭据。

Bridge 启动脚本只在 Token 文件不存在时生成独立 Token：
`D:\ai_agent\project agent\data\runtime\harness-bridge\token.txt`。

### 2. Ubuntu / WSL：Harness API（8013）

```bash
cd /home/terry/projects/agent-evaluation-harness/backend
.venv/bin/python scripts/run_business_agent.py api --port 8013
```

### 3. Ubuntu / WSL：Harness Worker

```bash
cd /home/terry/projects/agent-evaluation-harness/backend
.venv/bin/python scripts/run_business_agent.py worker
```

### 4. Ubuntu / WSL：前端（5173）

```bash
cd /home/terry/projects/agent-evaluation-harness
nvm use 22
VITE_API_BASE_URL=http://127.0.0.1:8013 npm --prefix frontend run dev -- --host 0.0.0.0 --port 5173 --strictPort
```

打开 <http://localhost:5173/comparison>，侧栏名称为 **Agent Showcase**。保持浏览器来源为 `localhost:5173` 或 `127.0.0.1:5173`，不要使用 WSL Network IP 触发原后端的 CORS 拒绝。

## 私有配置与跨 Windows / WSL 地址

启动脚本加载已被 Git 忽略的 `backend/.env.business-agent`，其中保留原本的 `HARNESS_DATABASE_URL` 并加入：

```dotenv
HARNESS_AGENT_KIND=business_http
HARNESS_AGENT_BASE_URL=http://172.17.0.1:8020
HARNESS_AGENT_TOKEN_FILE="/mnt/d/ai_agent/project agent/data/runtime/harness-bridge/token.txt"
HARNESS_AGENT_TIMEOUT_SECONDS=110
```

无凭据模板位于 `backend/business-agent.env.example`。新环境先复制自己的后端数据库配置，再按模板添加字段；不要提交实际数据库密码或 Token。Token 不放在 Case、前端或 Trace 中。

`172.17.0.1` 是本次 WSL 到 Windows 的网关，重启或网络变更后可能改变。可以用以下命令确认，并更新配置后重启 API / Worker：

```bash
ip route show default
curl --connect-timeout 5 http://172.17.0.1:8020/health
```

不要把 WSL 中的 `127.0.0.1` 默认当成 Windows 的回环地址。Bridge 在 Windows 监听所有接口，实际跨系统地址应以连通性检查为准。

## 前端如何演示

1. 打开 Agent Showcase。页面通过真实 Job 关系自动找到最近一组成对结果；带 `baseline` / `candidate` 的 URL 可固定查看历史组。
2. 已有结果可以直接讲解，不会重新调用模型。点击“创建一组真实评测”才会新建两组 Job，执行真实 CPU 模型和配置的在线模型。
3. 从差旅变更案例进入“证据与指标”，对比原问题、目标来源 ID、检索与引用结果。
4. 进入“完整 Trace”，按 Tools / Models / Errors 筛选。每个卡片展示真实事件时间和阶段名称，展开查看完整参数、候选排名、结果、来源版本和安全模型用量。
5. 再讲无答案案例：基线可能已经安全拒答，但检索仍返回无关资料。当前联合判定还要求空检索、空引用；修正后通过固定的证据门控拒绝材料，并使用本地拒答策略，不虚报一次生成模型请求。
6. 最后展示故障案例：基线显式注入 `dense_unavailable`，留下 Dense 调用、失败返回、错误和 Case failed。Candidate 移除注入后重新真实执行。它不是自动自愈，也没有伪装成真实生产故障。
7. Job / Experiment / Run Detail / Timeline 均复用现有持久化资源；前端没有独立 RunStore。两组创建中断时可保留已接受的基线，只补建 Candidate。

最近结果发现仅扫描最近 100 条 Job，并严格跟随 Candidate 的 `baseline_job_id` 和相同语料指纹；不按名称猜测配对。更早的组仍可通过固定 URL 查看。

## 七个固定案例

| 案例 | Baseline | Candidate | 判定目标 |
|---|---|---|---|
| q077 出差日期变更 | BM25 | Hybrid + 重排 + 门控 | 目标条款 Recall/MRR、引用与答案关键词 |
| q070 订票前审批 | BM25 | Hybrid + 重排 + 门控 | 语义改写后的首位相关性 |
| q012 VPN / MFA | BM25 | Hybrid + 重排 + 门控 | 技术术语与引用精度 |
| multi-source | BM25 | Hybrid + 重排 + 门控 | 两份制度的证据与引用覆盖 |
| no-answer | Hybrid 无门控 | Hybrid + 重排 + 门控 | 空检索、空引用与明确拒答 |
| employee-tool | BM25 配置下的实际业务分支 | 同一只读分支 | employee.lookup 的真实调用 |
| injected-outage | Hybrid + 重排，显式 Dense 故障 | 移除故障后执行 | 结构化失败 Trace 与修正后的结果 |

这是一组精选诊断案例，不是单变量消融或未见测试集。标签来自原 Agent 合成制度的明确文本片段；Corpus SHA-256 不一致时 Adapter 拒绝评分，避免旧标签产生虚假通过。

## 指标与工程权衡

- `retrieval_recall_at_5`：前 5 条是否覆盖参考来源。
- `retrieval_mrr_at_5`：首个参考来源的倒数排名，揭示“召回了但排得靠后”。
- `citation_recall` / `citation_grounding`：参考来源覆盖与来源 ID 精度；不等同于逐句语义蕴含证明。
- `answer_keywords`：显式同义词组匹配；不是语义评委模型。
- `abstention`：当前演示的联合要求是空检索、空引用、明确拒答。模型安全拒答但仍有无关检索时不通过；这不意味着模型一定发生了幻觉。
- `tool_contract`：应调用的只读工具是否出现；实际参数校验和身份检查仍由原 ToolExecutor 执行。
- 不适用指标为 N/A，不混入综合分。运行成功与质量判定分开显示。

固定重排 logit ≥ 0 是明确展示的实验策略，未经独立数据校准，不是置信概率或通用无答案检测器。重排增加 CPU 延迟，改善相关性需要和成本/延迟一起看。每次真实运行仍可能受模型输出变化影响，不保证复现所有答案文本。

## 已验证与限制

验证结果和具体 Run ID 见交付报告及已保存的真实结果。此次完成真实 Windows CPU 模型 + 已配置 DeepSeek + WSL PostgreSQL/Worker + Chromium 前端闭环。

当前 Bridge 为本机单进程、串行只读评测入口；没有多实例排队/幂等调度或远程人审协议。HTTP 中断不会强制终止 Windows 中已经开始的只读推理；网络/进程崩溃时只能保存已收到的 Trace，不能编造缺失事件。正常完成与结构化失败的事件均完整返回。Case 级跨进程自动重试默认关闭，避免重复在线模型请求。

没有修改 Worker、Executor、JobStore 或数据库迁移；普通 Agent 服务、业务库及既有凭据保留。全量真实企业数据、生产 ACL、多实例容灾和高并发压测不在本次演示范围。
