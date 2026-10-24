# EvalForge · Agent Evaluation Harness

### 让 Agent 的版本迭代，有可追溯的评测证据与可执行的发布标准。

EvalForge 是一个面向 AI Agent 的评测与回归测试平台。它将异构 Agent 的响应和执行轨迹，转换为统一的评测结果，再通过持久化任务、实验对比与质量门禁，回答三个工程问题：

> **新版本是否更好？变化发生在哪一步？这些结论能否追溯到原始执行证据？**

项目已实现从 **Agent 接入 → 异步评测 → Trace 与指标持久化 → Experiment 对比 → Regression Gate** 的后端链路，以及 **Adapter Studio：样本分析 → AI 规则生成 → 确定性预览 → 三层验证 → 人工审核发布** 的管理闭环。

当前定位为具有真实数据库、独立 Worker 和前端操作界面的工程实践项目，已验证本地 / WSL 部署及独立业务 Agent 接入。生产部署仍需补齐统一身份、依赖锁定、数据保留和容量验证。

[核心设计](#核心工程设计) · [系统架构](#系统架构) · [运行项目](#运行项目) · [演示路径](#建议的演示路径) · [测试证据](#测试与验证证据) · [源码导读](#源码导读)

---

## 先看项目已经解决了什么

| 工程问题 | 当前实现 | 可检查的证据 |
| --- | --- | --- |
| 不同 Agent 的回答、工具调用和 Trace 格式不一致 | 统一 Contracts + Adapter；可版本化的 Response / Trace Mapping | [AgentAdapter](backend/app/adapters/base.py)、[MappingSpec](backend/app/adapters/intelligent/contracts.py) |
| 长评测不能依赖 HTTP 请求进程存活 | PostgreSQL 持久化队列、独立 Worker、Lease / Heartbeat、Case Checkpoint | [JobStore](backend/app/jobs/postgres_store.py)、[Executor](backend/app/jobs/executor.py) |
| 改了 Prompt 或检索策略，却无法判断是否退化 | 按 Case 匹配实验，聚合指标变化，执行回归与门禁规则 | [ExperimentComparisonService](backend/app/harness/experiment_comparison_service.py)、[RegressionGate](backend/app/harness/regression_gate_service.py) |
| AI 生成的适配规则可能结构合法、语义错误 | 严格 DSL、确定性 Runtime、拓扑检查、独立 Golden、显式人工审核 | [Validator](backend/app/adapters/intelligent/validator.py)、[Registry](backend/app/registry/postgres_store.py) |
| 任务执行中规则被更新，影响历史结果解释 | Job 固定 adapter_id / version / digest，Worker 读取确切发布快照 | [Published Adapter](backend/app/adapters/intelligent/published.py)、[v015](backend/migrations/v015_pinned_mapping_evaluation.sql) |
| 看到了低分，却无法区分 Agent、适配层和评测器故障 | 故障分类、未知证据保留 null、Raw / Normalized 关联、可查看的 Trace Timeline | [Runner](backend/app/harness/runner.py)、[指标语义](backend/app/harness/metric_semantics.py)、[Studio](frontend/src/pages/AdapterStudioPage.tsx) |

**默认 Demo 流程无需模型 API Key。** 真实业务 Agent 和 AI Mapping Generation 是显式启用的独立路径，可能产生模型调用费用。

## 为什么需要这样一套系统

最初可以写一个脚本，循环调用 Agent，再检查最终答案。接入更多 Agent、增加工具调用和版本比较后，会依次遇到新的问题：

| 演进 | 暴露的问题 | EvalForge 的对应设计 |
| --- | --- | --- |
| 单次回答检查 → 多维评测 | 答案看似正确，但工具、参数、引用或成本可能有问题 | 拆分 Evaluator，将原始测量 value 与质量 score 分开 |
| 临时脚本 → 批量实验 | 进程中断后结果丢失，难以匹配前后版本 | Run / Experiment 持久化、稳定 Case 身份、实验对比 |
| HTTP 内执行 → 独立任务 | 请求超时、Worker 重启、并发领取和旧进程写回 | 数据库队列、Lease、Heartbeat、fencing 条件与 Checkpoint |
| 手工 Adapter → 智能规则生成 | 每种响应都写代码成本高，模型生成又存在不确定性 | AI 在配置阶段生成 DSL，评测时执行固定规则 |
| 可用规则 → 可发布规则 | JSON 合法无法证明业务语义正确 | 三层验证、独立 Golden、证据摘要绑定、人工审核与事务发布 |

这些设计共同服务于一个目标：**一次评测的输入、执行、标准化、评分与版本判断，都有明确的数据契约和证据关联。**

## 系统架构

系统分为管理与生成链路、评测执行链路。两者使用独立任务表与 Worker；正式 Case 评测不调用 Mapping Agent。

```mermaid
flowchart TB
    UI["React / TypeScript 前端"]
    API["FastAPI"]
    UI --> API

    subgraph Studio["管理与生成链路"]
        Samples["Profile / JSON 样本"]
        Inspector["Schema Inspector"]
        GQ["PostgreSQL 生成任务"]
        GW["独立 Mapping Worker"]
        AI["LLM 结构化生成 / 有界修复"]
        Validator["Runtime + 三层 Validator / Golden"]
        Review["人工审核 + 事务发布"]
        Versions["不可变 Published Mapping Version"]
        Samples --> Inspector --> GQ --> GW --> AI --> Validator --> Review --> Versions
    end

    subgraph Evaluation["评测执行链路"]
        JQ["PostgreSQL Evaluation Job"]
        EW["独立 Evaluation Worker"]
        Runner["Executor / HarnessRunner"]
        Adapter["Agent Adapter / 原 HTTP 调用"]
        Agent["本地 / LangGraph / 业务 HTTP Agent"]
        Mapping["可选：固定版本 Deterministic Mapping"]
        Metrics["统一 AgentResult / TraceEvent → Evaluators"]
        Evidence["Run / Trace / Raw 关联产物 / Checkpoint"]
        Comparison["Experiment → Comparison → Regression Gate"]
        JQ --> EW --> Runner --> Adapter --> Agent
        Agent --> Mapping --> Metrics --> Evidence --> Comparison
    end

    API --> Samples
    API --> JQ
    Versions -. "显式固定版本" .-> Mapping
    Evidence --> Replay["Replay Timeline / 证据查看"]
    Replay --> UI
    Comparison --> API
```

- **PostgreSQL 同时承担业务持久化与任务队列**，任务领取使用 `FOR UPDATE SKIP LOCKED`；当前执行链路没有 Redis、Celery 或外部消息队列。
- **Runner 编排生命周期，Adapter 隔离调用差异，Evaluator 计算指标**。外部框架变化不应扩散到每个评测器。
- **Replay 读取已保存的 Trace**，不重新调用 Agent，也不按当前 Mapping 重算历史结果。
- **Mapping Runtime 确定性只针对固定输入与规则**。真实 Agent 的模型输出、外部数据和网络仍可能变化。

## 核心工程设计

### 1. 用统一契约隔离 Agent 框架

实际的 Adapter 边界是：

```python
async def run(
    self,
    request: AgentRequest,
    context: RunContext,
) -> AgentResult:
    ...
```

| 契约 | 职责 |
| --- | --- |
| TestCase | 数据集身份、输入、期望输出、期望工具调用、案例元数据 |
| AgentRequest | 发送给 Adapter 的输入和元数据 |
| AgentResult | 统一 output_text、trace、metadata |
| TraceEvent | 统一事件类型、时间戳和 payload |
| RunContext | 单次执行的 run_id、TraceCollector、计时和隔离的元数据 |
| MetricResult | 指标名、原始测量值、单位、可选质量分和解释明细 |
| CaseResult | 完整案例档案：实际输出、指标、Trace、错误与故障类别 |

TestCase 的参考答案留在评测侧；Runner 不将 expected_output 作为 AgentRequest 的标准字段发送给 Agent。案例元数据仍需调用方合理管理，不能主动放入答案等泄漏信息。

当前存在 LocalAgentAdapter、LangGraphAdapter、TracingDemoAdapter 和 BusinessHttpAdapter。发布 Mapping 的正式集成针对 **BusinessHttpAdapter 的响应标准化边界**，保留原 HTTP 请求体、认证和调用逻辑；它不自动发现任意第三方协议。

源码：[Contracts](backend/app/harness/contracts.py) · [RunContext](backend/app/harness/context.py) · [Adapters](backend/app/adapters)

### 2. 将“完成任务”和“质量通过”分开

Evaluation Job 是持久化状态机：

```text
queued → running → completed / failed
   │         │
   │         ├─ 用户请求取消 → cancel_requested → cancelled / completed / failed
   │         └─ Lease 过期 → 有界恢复 queued，或达到上限后 failed
   └─ 执行前取消 → cancelled
```

**Job completed 表示案例处理完毕，可能包含 failed_cases；质量是否通过由指标和 Gate 决定。**

| 机制 | 解决的问题 | 实际保证范围 |
| --- | --- | --- |
| 原子领取 + SKIP LOCKED | 多 Worker 争抢同一任务 | 一个领取事务获得当前执行权 |
| 独立 Heartbeat | 长 Case 执行时租约过期 | 持续续租；续租失败后不能假设仍拥有任务 |
| worker_id + attempt_count + 有效 Lease 写入条件 | 旧 Worker 覆盖任务归属或进度 | 拒绝过期所有者更新 Job / Checkpoint |
| Case Checkpoint | 重启后重复执行已经完成的案例 | 恢复已提交案例的 Run 引用并跳过已完成 Case |
| Run 与 Raw 关联产物同事务保存 | 有规范结果却丢失原始证据 | 已提交 Run 与其私有产物一致落库 |

单个 Worker 进程一次执行一个 Job；可运行多个 Worker。Runner 另有 Case 并发与超时策略。**Job 执行尝试与 Agent 的 Case 内重试是两层不同机制。**

Run 与关联产物的事务、Case Checkpoint 与进度的事务是两个提交边界。Run 已保存但 Checkpoint 未提交时，可能留下未关联 Run；任务归属与恢复依据已提交的 Checkpoint。

Checkpoint 不等于外部调用 exactly-once：Agent 已执行但 Case 尚未提交时，恢复可能重新发起请求。同步阻塞调用或不合作的协程也不具备进程级强制超时保证。

源码：[Worker](backend/app/worker.py) · [Executor](backend/app/jobs/executor.py) · [JobStore](backend/app/jobs/postgres_store.py)

### 3. AI 只生成候选，运行时只解释受限 DSL

Intelligent Adapter System 的实际闭环：

```text
多个原始样本
  → Schema Inspector：路径 / 类型 / 出现频率 / nullable / 结构差异 / 指纹
  → 人工选择字段与必要标量披露
  → Mini Mapping Agent：结构化 MappingSpec + 来源证据与不确定性
  → 确定性 Runtime + Validator
  → 有界修复，默认首次生成后最多修复 3 次
  → Candidate / needs_manual_review
  → 独立人工审核与发布
  → Job 固定版本，逐 Case 执行确定性 Mapping
```

关键约束：

- DSL 支持 `extract`、`rename`、`enum_map`、`cast`、`coalesce`、`sum_if_present`，使用严格 Pydantic 契约，可序列化为 JSONB。
- JSONPath 限制为根、对象字段和非负数组索引，支持 JSON 引号键；不支持过滤表达式、切片或任意代码。
- 明确区分字段不存在、显式 null、类型不符和转换失败；不修改原始输入，不补造 Span、时间或 Token。
- Inspector 的数组归一化路径用于结构描述；它的 `[]` 不能直接当作 Runtime 的可执行通配符。
- 模型上下文使用显式披露白名单；Raw 与 Golden 不整体发给模型。样本和字段说明作为不可信数据处理。
- 超时、调用失败、格式错误和预算消耗均有终止条件；没有无限修复或自动发布。
- 不执行模型生成的 Python，不提供 eval / exec / 动态代码导入执行通道。

例如，供应商将答案写在 answer，并将 Span 信息嵌入事件的 span 对象。可以将它映射回已有 AgentResult / TraceEvent，无需再造一套规范结果模型：

```json
{
  "spec_version": "1.0",
  "name": "vendor-response-v1",
  "response": {
    "fields": [
      {
        "target": "$.output_text",
        "operation": { "op": "extract", "path": "$.answer" },
        "value_type": "string",
        "on_missing": "error",
        "on_null": "error"
      }
    ]
  },
  "trace": {
    "events_path": "$.events",
    "type_path": "$.kind",
    "on_unknown_event": "error",
    "rules": [
      {
        "source_type": "model",
        "event_type": "model_result",
        "fields": [
          {
            "target": "$.timestamp",
            "operation": { "op": "extract", "path": "$.finished" },
            "value_type": "datetime",
            "on_missing": "error",
            "on_null": "error"
          },
          {
            "target": "$.payload",
            "operation": { "op": "extract", "path": "$.span" },
            "value_type": "object",
            "on_missing": "error",
            "on_null": "error"
          }
        ]
      }
    ]
  }
}
```

Response 路径相对完整响应；type_path 和事件字段路径相对单个事件。上述规则要求真实的带时区 finished 时间以及 span 对象；缺失时返回错误，不用当前时间补齐。这份规则是否正确表达业务语义，还必须由独立 Golden 验证。

源码：[DSL](backend/app/adapters/intelligent/contracts.py) · [Runtime](backend/app/adapters/intelligent/runtime.py) · [Inspector](backend/app/adapters/intelligent/inspector.py) · [生成服务](backend/app/adapters/intelligent/generation_service.py)

### 4. 把“合法配置”和“可信规则”分成三层验证

| 层次 | 检查内容 | 不能据此推断的结论 |
| --- | --- | --- |
| L1：结构 | MappingSpec / 输出契约、类型、枚举、时间格式、重复 Span ID | 字段含义一定正确 |
| L2：拓扑 | 父 Span 引用、父子环、明显时间矛盾；允许合法并发 | Trace 已完整覆盖业务过程 |
| L3：语义 / Golden | 人工定义的期望输出、Span Type、Token Usage、Tool Call 等关键字段 | 对未见数据普遍正确 |

当前拓扑检查按配置路径将一个映射事件解释为一条 Span 记录；原始 start/end 分散在多个事件时，不会自动合并，也不会补造缺失关系或时间。

ValidationReport 分开输出 **error / warning / unverified** 和可执行的发布阻断原因。Partial Trace 的未知信息必须保留；没有独立 Golden 时，L3 不能宣称通过。Golden 来自人工期望，而非从当前预览反向复制。

发布时在一个 PostgreSQL 事务内锁定 Profile 和 Candidate，重新核对最新报告、样本/配置/规则摘要和人工审核记录，然后插入版本、递增版本计数并写审计。数据库唯一约束兜底并发；同一候选和审核的发布重试返回同一版本。

Published Version 及关键证据通过触发器禁止修改/删除/清空；应用代码不能覆盖已发布规则。数据库所有者能够修改 DDL，因此该保证以合理的部署权限为前提。

源码：[Validator](backend/app/adapters/intelligent/validator.py) · [Registry 发布事务](backend/app/registry/postgres_store.py) · [v014 约束](backend/migrations/v014_adapter_registry.sql)

### 5. 固定规则版本，保留完整证据关联

```text
Evaluation Job.payload_json
  └─ adapter_id + adapter_version + 服务端解析的 mapping_digest
        ↓ Worker 按执行尝试加载确切已发布快照
Business HTTP 原调用
        ↓
Raw Response → Deterministic Mapping → AgentResult / TraceEvent
        ↓
harness_runs：案例结果、标准化 Trace、公开关联 ID
harness_mapping_artifacts：Raw 文本/字节、MappingResult、NormalizedResult
        ↓
Case Checkpoint → Experiment → Replay / Comparison / Gate
```

Job 执行中发布新版本，不会改变当前绑定；Worker 恢复也使用同一绑定。RunContext 的 run_id 标识执行，Case ID 标识数据集案例，attempt_id 标识 Case 内尝试，三者分工明确。

原始事件通过 Runtime 的 raw_pointer 与标准化事件关联，保留映射过程。受保护的 Raw 查询要求 Registry editor 权限；公开 Run 元数据不携带整份原始响应。

源码：[PublishedBusinessHttpAdapter](backend/app/adapters/intelligent/published.py) · [v015 固定绑定与产物](backend/migrations/v015_pinned_mapping_evaluation.sql)

### 6. 故障隔离和指标语义一致，比一个总分更重要

启用已发布 Mapping 的链路区分：

| failure_kind | 含义 | 质量解释 |
| --- | --- | --- |
| agent_execution | Agent 调用或业务执行失败 | 执行故障，不能直接解释为回答质量差 |
| mapping | 原始响应无法可靠标准化 | 停止该案例评分，保留原始证据 |
| evaluation | 评测器计算失败 | 评测流水线故障，不能生成可信质量结论 |

这些流水线失败使用 `score=null`，不以零分混入 Agent 质量。该语义属于新的发布 Mapping 路径，未启用的历史流程保留兼容行为。

未知 Token / 成本保留 unverified / null；Token、工具指标读取最后成功 Attempt 的 Agent 证据，Latency 保留 Harness 生命周期范围。计量型指标没有质量 score 时，不参与质量分平均。

Comparison / Regression / Gate 复用 `harness-normalized/v1` 语义检查：拒绝将未知质量、流水线失败或混合的历史/新规范静默比较。固定规则版本提供可追溯性；可比性仍依赖相同案例、数据集约束和一致指标定义。

源码：[EvidenceAwareEvaluator](backend/app/adapters/intelligent/published.py) · [metric_semantics](backend/app/harness/metric_semantics.py)

## 指标与质量门禁

评测器可组合，Runner 的具体指标由配置选择，并非每次运行自动启用所有指标。

| 维度 | 当前实现 | 解释边界 |
| --- | --- | --- |
| 回答匹配 | KeywordMatchEvaluator | 关键词覆盖，不等同于语义正确性判定 |
| 工具调用 | ToolAccuracyEvaluator / ToolEfficiencyEvaluator / 参数匹配器 | 根据期望工具、参数和执行证据判断 |
| 时延 | LatencyEvaluator | 基于已有生命周期证据测量 |
| Token / 费用 | TokenUsageEvaluator / CostEvaluator / PricingCatalog | 依赖实际 usage 与已配置价格，价格目录不是实时账单 |
| 检索效果 | 业务 RAG 的 Recall@5 / MRR@5 | 依赖人工参考来源标注 |
| 引用 | citation_recall / citation_grounding | 来源 ID 覆盖与精度，不证明逐句语义蕴含 |
| 无答案行为 | abstention | 演示策略联合检查空检索、空引用与明确拒答 |

Regression Gate 支持案例回归率、平均质量分变化、缺失案例数量，以及指标级绝对/相对变化约束。例如：

```json
{
  "baseline_experiment_id": "<baseline-experiment-id>",
  "candidate_experiment_id": "<candidate-experiment-id>",
  "require_same_dataset_version": true,
  "policy": {
    "max_regression_rate": 0.05,
    "min_average_score_delta": -0.02,
    "max_missing_case_count": 0,
    "metric_rules": [
      {
        "name": "keyword-score-regression",
        "metric_name": "keyword_match",
        "target": "score_delta_mean",
        "operator": "gte",
        "threshold": -0.02
      }
    ]
  }
}
```

将该请求提交至 `POST /gates/evaluate`。结果给出 passed / failed 和逐规则 finding，保留可评估性、实际值、阈值及原因。Gate 已有后端接口；将其接入 CI 的退出码或 PR 阻断仍需集成工作。

## Adapter Studio

入口：`/adapter-studio`。页面沿用现有 React 组件风格、API Client 和 TanStack Query，不增加大型 UI 框架。

| 操作 | 页面提供的证据与保护 |
| --- | --- |
| 创建 Profile，上传/输入 JSON 样本 | 不可变样本批次，可携带人工独立 Golden |
| 查看 Inspector 字段 | 路径、类型、频率、nullable、缺失次数、跨样本差异与指纹 |
| 生成候选 | 显式披露、异步任务状态、错误、修复反馈和来源不确定性 |
| 查看规则 | Source Field → Target Field，操作与缺失/null 策略，完整 MappingSpec |
| 运行预览 | Raw 与 Normalized 对比，逐事件原始指针关联 |
| 运行验证 | L1/L2/L3、error/warning/unverified 和发布阻断原因 |
| 人工审核发布 | 最新有效报告、审核说明、精确证据绑定，发布前再次确认 |
| 查历史与使用 | 固定版本快照，实际 Job / Run / Attempt 产物计数，链接原 Replay |

Registry Bearer 仅保存在页面内存，不写 localStorage、sessionStorage 或 URL。页面使用独立缓存；离开或断开后清除本页状态。reader / editor / publisher 权限由服务端确定；前端按钮和确认框不替代鉴权。

生成只在 queued/running 轮询；错误或终态停止，允许手动恢复。POST 不自动重试。提交生成请求时发生网络错误，应先查看历史任务，确认是否已入队，再决定是否显式重试。

详细流程：[Adapter Studio](docs/INTELLIGENT_ADAPTER_STUDIO.md)。

## 建议的演示路径

### 路径 A：不使用在线模型，展示平台工程闭环

适合首次评审、现场网络受限或希望控制费用的场景。

| 顺序 | 打开哪里 | 展示什么 |
| --- | --- | --- |
| 1 | `/evaluation-jobs/new` | 创建真实持久化 Job，说明案例、数据集标签和版本标签 |
| 2 | `/evaluation-jobs/:jobId` | Worker 状态、处理进度、执行尝试、取消与 Experiment 关联 |
| 3 | Experiment / Run Detail | 从汇总进入原始案例输出、指标明细和失败原因 |
| 4 | `/runs/:runId/timeline` | 展示持久化 Trace；说明执行身份与事件来源 |
| 5 | `/adapter-studio` | 导入异构样本，查看 Schema、创建人工候选、预览和验证 |
| 6 | Gate API / Swagger | 比较两个已完成实验，查看规则级发布判定 |

默认 DemoAgent 返回固定格式响应；要展示丰富模型/工具事件，应使用已有 Tracing / LangGraph 适配器的测试，或路径 B 的真实业务 Agent。

Studio 可在不配置模型生成预算时使用人工候选。现成的离线样本、独立 Golden 和预先编写的修复规则见 [mini_mapping_agent.json](backend/tests/fixtures/mini_mapping_agent.json)：将 raw_response / golden 放入样本批次，将 repair_reply.mapping 作为人工规则。此方式验证管理与确定性链路，不代表真实 LLM 生成效果。

### 路径 B：展示独立业务 Agent 的真实评测

入口：`/comparison`，侧栏 **Agent Showcase**。它是专门的业务演示页；通用 Experiment Comparison 与 Gate 通过后端 API 使用，`/gate` 当前仍为占位页。

演示连接独立部署的业务 Agent，包含七个精选诊断案例：

- BM25 与 Hybrid + Reranker + 证据门控的检索/引用表现；
- 多来源问题、无答案拒答与只读业务工具调用；
- 显式注入 Dense 故障、结构化失败 Trace，以及移除故障后的真实执行。

语料指纹用于避免旧标签对新语料产生虚假评分。已有持久化结果可以直接查看；创建新评测组才会触发新的 Agent 调用。

**外部业务 Agent、Bridge、模型文件与其数据不包含在本仓库中。** 该演示是固定诊断集合，不是独立测试集上的质量提升证明，也不是单变量消融实验。部署与完整边界见 [业务 Agent 演示说明](docs/BUSINESS_AGENT_SHOWCASE.md)。

## 运行项目

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

在已应用 v014 / v015 后，按 [Registry 配置说明](docs/INTELLIGENT_ADAPTER_REGISTRY.md) 配置：

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

## 测试与验证证据

以下是 **截至 2026-10-24 的具体验证范围**，各组存在交叉，不能相加当作独立测试总数；不以此宣称全项目全绿或生产容量已验证。

| 范围 | 最近实际结果 | 环境与说明 |
| --- | --- | --- |
| DSL / Runtime / Inspector / Validator / Mini Mapping Agent | **443 passed，1.99s** | 本次 README 核对时重跑；离线，无真实 API Key |
| Registry + Stage 7 评测集成 + Stage 8 API | **70 passed，23.27s** | Stage 8 记录；真实隔离 PostgreSQL，Agent / LLM 使用替身 |
| 前端单元 / API 契约 | **14 passed** | Node 内置测试器 + Vite Loader |
| 前端真实浏览器交互 | **6 passed，24.52s** | Chrome + Fake Registry；覆盖完整审核发布、鉴权失败、网络恢复及旧页面导航 |
| 前端生产构建 / lint | **通过** | tsc -b + Vite build；JS gzip 113.99 kB |

### 无数据库、无在线模型的核心测试

在仓库根目录执行：

```bash
backend/.venv/bin/python -m pytest -q \
  backend/tests/test_intelligent_mapping_contracts.py \
  backend/tests/test_intelligent_mapping_runtime.py \
  backend/tests/test_schema_inspector.py \
  backend/tests/test_mapping_validator.py \
  backend/tests/test_mini_mapping_agent.py

npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run lint
```

### 数据库事务与恢复测试

在**专用隔离 PostgreSQL 测试实例**中配置 ADAPTER_REGISTRY_TEST_DSN，再执行：

```bash
backend/.venv/bin/python -m pytest -q \
  backend/tests/test_adapter_studio_api.py \
  backend/tests/test_adapter_registry.py \
  backend/tests/test_published_mapping_evaluation.py --tb=short
```

覆盖发布事务回滚、并发版本分配、不可变约束、角色鉴权、Lease / Heartbeat / Checkpoint、固定版本恢复、Mapping 故障隔离、Raw 关联、Replay 和指标语义。新测试为每项创建独立 schema 并保留数据；旧 PostgreSQL 测试另使用 TEST_POSTGRES_DSN，不应指向开发或生产数据。

### 浏览器交互测试

测试脚本复用环境中已有 Playwright 与 Chrome，不将其加入前端项目依赖。启动 Vite，设置 STUDIO_PLAYWRIGHT_MODULE、STUDIO_BROWSER_EXECUTABLE；必要时设置 STUDIO_BASE_URL。在 frontend 目录运行：

```bash
node --test --test-reporter=tap tests/browser/adapterStudio.browser.mjs
```

浏览器中的生成、验证响应是明确的 Fake Registry 数据，不能据此推断在线模型质量；真实服务和数据库行为由后端测试覆盖。详细命令与记录见 [Studio 验证说明](docs/INTELLIGENT_ADAPTER_STUDIO.md)。

**已知测试债务：** 较大范围回归曾确认 `test_v11_experiment.py::test_duplicate_case_is_rejected` 的异常类型预期与 InMemoryExperimentStore 实现不一致，在原 Git HEAD 也可复现。该问题尚未修复；完整历史记录见 [Stage 7 集成说明](docs/INTELLIGENT_ADAPTER_EVALUATION_INTEGRATION.md) 与 [变更记录](AI_CHANGELOG.md)。

## 主要 API

以下路径已从当前 FastAPI OpenAPI 核对，完整字段以运行中的 `/docs` 为准。

| 领域 | 入口 |
| --- | --- |
| 异步评测 | POST /evaluation-jobs；GET 列表、详情、/{id}/progress；POST /{id}/cancel |
| 实验 | POST /experiments/run；GET /experiments、/experiments/{id} |
| 执行证据 | GET /runs、/runs/{id}、/runs/{id}/timeline |
| 版本比较 | POST /comparisons/experiments |
| 质量门禁 | POST /gates/evaluate |
| Adapter Profile / 样本 | /adapter-registry/profiles；/profiles/{id}/samples；/samples/{id} |
| 规则生成 / 候选 | /profiles/{id}/generations；/generations/{id}；/profiles/{id}/candidates |
| 预览 / 验证 / 审核 / 发布 | POST /adapter-registry/candidates/{id}/preview、validate、review、publish |
| 固定版本 / 使用 | GET /adapter-registry/profiles/{id}/versions、/versions/{version}、/versions/{version}/usage |
| 私有原始产物 | GET /adapter-registry/runs/{run_id}/mapping-artifacts |

表中 Profile / 样本 / 生成候选的相对路径均在 /adapter-registry 下。Registry 接口和显式绑定 Mapping 的 Job 创建已有独立权限检查；旧评测 API 尚无全局统一认证，公开部署前需要补齐。

## 源码导读

```text
backend/
├── app/
│   ├── adapters/            # Local / LangGraph / Business HTTP 边界
│   │   └── intelligent/     # DSL、Runtime、Inspector、Validator、生成与固定版本集成
│   ├── agent/              # 本地与 LangGraph 演示 Agent
│   ├── api/                # FastAPI 路由与错误处理
│   ├── schemas/            # HTTP 请求/响应模型
│   ├── datasets/           # CSV / JSON / JSONL 与 TestCase 归一化
│   ├── evaluator/          # 质量、工具、时延、Token、费用与业务 RAG 指标
│   ├── harness/            # Contracts、Runner、Trace、Store、Experiment、Comparison、Gate
│   ├── jobs/               # 评测任务状态机、持久化领取与恢复执行器
│   ├── registry/           # 规则持久化、鉴权、审核发布、独立生成 Worker
│   ├── runtime_factory.py  # 服务端实际 Agent / Evaluator 选择
│   └── worker.py           # 独立 Evaluation Worker
├── migrations/             # 显式 SQL 迁移
├── scripts/                # 业务 Agent 模式启动脚本
└── tests/                  # 单元、契约、真实 PostgreSQL 与集成测试
frontend/
├── src/
│   ├── api/                # 复用请求 Client 与类型化接口
│   ├── components/         # 既有页面、Job 与 Adapter Studio 组件
│   ├── hooks/              # Query / 命令 / 轮询生命周期
│   ├── pages/              # Job、Experiment、Run、Timeline、Showcase、Studio
│   ├── types/              # 前端传输契约
│   └── utils/              # 表单、披露与显示纯函数
└── tests/                  # Node 契约测试与可选浏览器交互测试
docs/                       # 各模块设计、启动说明和验证边界
```

建议按“契约 → 编排 → 持久化恢复 → 规则治理 → 界面”的顺序阅读：

1. [contracts.py](backend/app/harness/contracts.py) 与 [context.py](backend/app/harness/context.py)：先理解数据和身份。
2. [runner.py](backend/app/harness/runner.py)：跟踪一个 Case 的生命周期、重试、错误与保存。
3. [executor.py](backend/app/jobs/executor.py) 与 [JobStore](backend/app/jobs/postgres_store.py)：看进程重启与旧 Worker 竞争时的行为。
4. [runtime.py](backend/app/adapters/intelligent/runtime.py) 与 [validator.py](backend/app/adapters/intelligent/validator.py)：看未知数据如何被约束和解释。
5. [Registry Store](backend/app/registry/postgres_store.py) 与 [v014](backend/migrations/v014_adapter_registry.sql)：看发布事务、并发和不可变性。
6. [published.py](backend/app/adapters/intelligent/published.py)：看 AI 生成如何与正式执行隔离。
7. [AdapterStudioPage.tsx](frontend/src/pages/AdapterStudioPage.tsx) 与 [ReviewWorkspace.tsx](frontend/src/components/adapters/ReviewWorkspace.tsx)：最后看端到端操作如何落到上述服务。

## 设计文档

| 主题 | 文档 |
| --- | --- |
| 真实业务 Agent 与诊断案例 | [Business Agent Showcase](docs/BUSINESS_AGENT_SHOWCASE.md) |
| Mapping 配置契约 | [Mapping DSL](docs/INTELLIGENT_ADAPTER_MAPPING_DSL.md) |
| 路径提取、类型与确定性执行 | [Mapping Runtime](docs/INTELLIGENT_ADAPTER_MAPPING_RUNTIME.md) |
| 多样本结构分析与 Fingerprint | [Schema Inspector](docs/INTELLIGENT_ADAPTER_SCHEMA_INSPECTOR.md) |
| 三层验证与独立期望 | [Validator / Golden Tests](docs/INTELLIGENT_ADAPTER_MAPPING_VALIDATOR.md) |
| 受限生成、证据与有界修复 | [Mini Mapping Agent](docs/INTELLIGENT_ADAPTER_MINI_MAPPING_AGENT.md) |
| 身份、队列、审核与发布事务 | [Adapter Registry](docs/INTELLIGENT_ADAPTER_REGISTRY.md) |
| 版本绑定、故障隔离与指标一致性 | [Evaluation Integration](docs/INTELLIGENT_ADAPTER_EVALUATION_INTEGRATION.md) |
| 前端操作闭环与交互测试 | [Adapter Studio](docs/INTELLIGENT_ADAPTER_STUDIO.md) |

## 当前边界与下一步

| 当前边界 | 下一步工程工作 |
| --- | --- |
| 后端依赖清单遗留、未锁定；迁移由 Store 初始化和 SQL 脚本共同管理 | 整理可复现依赖、统一迁移入口和干净环境安装验证 |
| 旧评测 API 无全局认证；Registry 为本地全局角色 | 统一身份、细粒度权限、多租户与部署边界 |
| Raw / Golden / 报告可能包含敏感数据，尚无自动保留与清理策略 | 数据分级、脱敏策略、存储/备份与生命周期管理 |
| 高并发吞吐和大规模历史使用查询未压测 | 容量基线、索引、查询计划与队列积压监控 |
| 现有质量指标以确定性规则和参考标注为主 | 扩充独立评测集；需要语义 Judge 时单独校准其可靠性与成本 |
| Gate 已提供 API，前端专页与 CI 阻断未完成 | 构建自动回归工作流并明确失败/未知证据策略 |
| Bridge 是独立项目的本地接入；Checkpoint 不保证外部副作用 exactly-once | 接入协议版本化，以及面向具体 Agent 的幂等与取消设计 |

**项目的核心工程价值，是把不确定的 Agent 行为放入有契约、有执行所有权、有证据、有版本边界的评测流程，让“看起来更好”变成可以检查和讨论的结论。**
