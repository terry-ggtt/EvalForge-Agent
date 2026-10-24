# Stage 7：Intelligent Adapter 与评测系统集成

## 工程位置与接入决策

工业链路有两条，必须隔离：

```text
开发/治理：
样本 → Inspector → Mapping Agent → Validator/Golden → 人工审核 → Published Mapping Version

正式评测：
Job 固定 ID/版本/摘要 → Worker 读取该 Published Version → 原 Business HTTP 请求
→ 原始响应 → Deterministic Mapping Runtime → 原 AgentResult/TraceEvent
→ 原评测器 → Run + 私有 Raw/Normalized 产物 → Case Checkpoint → Experiment
→ Replay / Comparison / Regression / Gate
```

模型可以帮助提出规则，但不能在每个 Case 中重新解释响应。
正式执行只使用已发布的确定规则；中途发布 v2 不会改变已绑定 v1 的 Job。

当前实际仓库没有 RemoteAgentAdapter，唯一外部 HTTP 接入是
backend/app/adapters/business_http.py 的 BusinessHttpAdapter。
最小接入点是其 HTTP 响应进入 BridgeResponse 校验之前。
本阶段将原响应处理原样移入 normalize_response()，显式绑定时使用子类覆盖该边界；
URL、Bearer 认证、请求 JSON、profile/fault 白名单、超时和传输异常处理保持原逻辑。
没有新增一个假定存在的远程协议，也没有将所有 AgentAdapter 都强行包装。

## 绑定契约与启用方式

创建 Evaluation Job 时可以增加：

```json
{
  "adapter_id": "adapter-实际已发布配置ID",
  "adapter_version": 1
}
```

adapter_id 对应 Adapter Profile 的 profile_id，不是 Candidate ID、Generation ID 或 MappingSpec.name。
它们必须成对出现，版本必须是严格正整数；不接受 latest、字符串版本、bool 或只提供一个字段。
PostgresEvaluationJobStore.create() 查询指定已发布版本，服务端补充 adapter_mapping_digest，
并将三项固定到原有 harness_evaluation_jobs.payload_json。客户端摘要不是可信来源。

新 SQL 触发器对已绑定 Job 冻结完整 payload_json，包括 Case 和 metadata；
状态、Lease、计数器仍按原 Job Store 更新。对未绑定 Job 不施加这个冻结规则。
绑定写入时还在数据库检查 Published Version 与摘要，不存在或不一致则拒绝。
Published Version 自身沿用 Stage 6 的数据库不可变保护，因此解析摘要与插入 Job 之间不会被改写成另一套规则。

API 创建已绑定 Job 需要 Registry editor 或 publisher 身份，并显式启用 Registry；
未绑定 Job 的既有创建协议和行为保持兼容。
原 Job 查询/管理端点仍沿用既有项目权限，本阶段没有引入全局用户系统。

部署需先按原机制初始化 Run/Experiment/Job 表，再手工应用：
- backend/migrations/v014_adapter_registry.sql（若 Stage 6 尚未应用）；
- backend/migrations/v015_pinned_mapping_evaluation.sql。

执行环境沿用 runtime_factory.py 实际读取的 HARNESS_AGENT_KIND=business_http，
并设置 HARNESS_ADAPTER_REGISTRY_ENABLED=1 与原业务桥接配置。
正式评测 Worker 启动仍为 python -m app.worker，不需要 Mapping LLM Key。
没有自动在开发或生产数据库执行迁移；没有变更现有 Agent HTTP 协议。

本地 Demo 或其他没有响应边界的 Adapter 不会被猜测转换。
若显式绑定与 Worker 的实际 Adapter 不兼容，会在发起 HTTP 前以配置错误停止，不回退默认 Agent 或最新版本。

## 完整数据流：函数、对象和持久化

| 步骤 | 实际函数 | 数据/持久化位置 |
| --- | --- | --- |
| 1 创建请求 | api/evaluation_jobs.py:create_evaluation_job()；CreateEvaluationJobRequest.to_domain() | 严格 adapter_id/version；仅绑定模式额外鉴权 |
| 2 解析并固化 | jobs/postgres_store.py:PostgresEvaluationJobStore.create() | 从 harness_adapter_versions 精确读取摘要，写 harness_evaluation_jobs.payload_json |
| 3 领取/续租 | PostgresEvaluationJobStore.claim_next()/heartbeat()/recover_expired()；worker.run_claimed_job() | 原 Evaluation Job worker_id/attempt_count/Lease 和恢复机制 |
| 4 加载本 Job 的规则 | EvaluationJobExecutor.execute() → bind_published_runner() → PostgresAdapterRegistry.version() | 每次 Worker 执行尝试加载一次指定版本，验证摘要和 Stage 7 迁移 |
| 5 构造隔离 Runner | bind_published_runner() | 新 PublishedBusinessHttpAdapter 与 Evaluator 装饰器；不修改共享 Runner，规则保存在该 Job 实例 |
| 6 创建/复用 Experiment | EvaluationJobExecutor._get_or_create_experiment() | harness_experiments.metadata_json 保存 evaluation_job_id 与固定绑定；已有 run_ids 继续使用 |
| 7 发起 Case | HarnessRunner.run() → _run_case() → _run_agent() → _run_agent_with_retry() → BusinessHttpAdapter.run() | RunContext 为每 Case 生成真实 run_id；原 HTTP 请求与 Agent 执行不变 |
| 8 响应标准化 | PublishedBusinessHttpAdapter.normalize_response() → map_agent_result() | 检查原 bridge 状态/run/corpus/error 信封，保存私有原始响应，再用固定 MappingSpec 转换 |
| 9 合并 Trace | normalize_response() → TraceCollector.extend_agent_events() | 标准化事件在 attempt_end 之前进入原 collector；增加真实 Harness 关联信息，不伪造 Span 字段 |
| 10 评测 | HarnessRunner._run_case() → EvidenceAwareEvaluator.evaluate() → 原 evaluator.evaluate() | 相同指标算法/名称/单位；Agent 指标读取最后成功 Attempt，Latency 保留完整生命周期 |
| 11 原子保存 | HarnessRunner._persist_run() → PostgresRunStore.save_with_mapping_artifacts() | 同一事务写 harness_runs 与 harness_mapping_artifacts；公开 Run 元数据仅保存关联 ID |
| 12 Case Checkpoint | EvaluationJobExecutor.execute() → record_case_result() → ensure_run_linked() | 原 harness_evaluation_job_cases 的 run_id/outcome 和进度计数；原 harness_experiment_runs 关联表 |
| 13 结束/恢复 | mark_completed()；_sync_experiment_terminal()；恢复时 _load_checkpoints() | 原 Job/Experiment 状态机制。恢复检查每个已提交 Run 的绑定，跳过已提交 Case |
| 14 Replay | RunReplayService.events()/timeline() → build_run_timeline() | 只读取原 harness_runs.result_json.trace，不重新运行 Mapping，不读取最新规则 |
| 15 比较/发布门禁 | ComparisonService.compare_records()；DatasetComparisonService.compare() → ExperimentComparisonService/RegressionDetector/RegressionGate | 复用已持久化的 canonical metrics；统一语义检查后再计算质量差异 |

Run/Experiment 关联保存在 harness_experiment_runs(experiment_id,run_id,case_id,position)，
Schema 定义仍是 backend/app/harness/postgres_experiment_schema.py；没有增加第二套 Experiment 或 Trace Store。

每个 Case 的 Raw/Normalized 产物包含：
- 真实 run_id（表列）、attempt_id、evaluation job_id、adapter_id、adapter_version、mapping_digest。
- raw_response_text 与 raw_response_base64。base64 保存真实响应体字节，避免解码替换导致丢失。
- http_status 与 agent_failed / mapping_failed / mapped 状态。
- 现有 MappingResult 的完整序列化：错误、警告、raw_event、raw_pointer 和规范事件。
- 现有 AgentResult 的标准化快照。失败时保持 null，不猜测未知结果。
- 标准化事件的技术关联 metadata：mapping_artifact_id、normalized_event_index、harness_run_id 等。

Raw Trace 本来就在 Raw Response 的事件数组中：
MappingResult.events[i].raw_pointer/raw_event → normalized_event，
再通过 mapping_artifact_id + normalized_event_index 对应原 Run Trace 中的事件。
一条有效规则产生的规范事件顺序不被重新排序，来源 timestamp 保留原值。
Harness 的 attempt_id、run_id 是真实执行标识；它们不等于猜测或补造供应商 span_id/parent_span_id。

## 原子持久化与访问控制

harness_mapping_artifacts 是本阶段唯一新增表：
- run_id → harness_runs；
- job_id → harness_evaluation_jobs；
- adapter_id/version → 不可变 Published Version；
- 唯一(run_id,attempt_id)，支持同一 Run 的多个真实 Agent Attempt；
- 触发器禁止 UPDATE、DELETE、TRUNCATE。

PostgresRunStore.save() 仅增加可选 connection，复用原有 INSERT/UPSERT SQL。
save_with_mapping_artifacts() 使用同一连接事务，避免 Run 已成功但 Raw/Normalized 对应物缺失。
失败会一起回滚；Case Checkpoint 仍在 Run 成功保存之后提交。
InMemoryRunStore 提供相同语义的锁内复制方法，供本地测试复用。

公开 Run 元数据没有整段 Raw Response 或 MappingResult。
私有读取入口：
GET /adapter-registry/runs/{run_id}/mapping-artifacts，
要求 editor/publisher；reader、匿名用户均不能读取。
规范化 Trace 仍沿用原 Run/Replay 接口权限，因此发布审核必须检查映射投影字段是否适合公开。
没有自动敏感信息识别器；不能把“已标准化”当作“已脱敏”。

## 错误隔离和未知证据

| 类别 | 判定 | 结果 |
| --- | --- | --- |
| agent_execution | HTTP/连接/超时、错误 Run/Corpus 信封、Agent 明确 error | 失败 Run；若收到响应则保留 Raw，未产生的标准化结果保持 null |
| mapping | MappingFailure：提取/转换失败、非完整 Trace 覆盖、部分求和等 | 不运行评测器；即使自定义 RetryDecider 总是返回 true，也不重复调用 Agent |
| evaluation | 标准化已成功后 evaluator 或评测阶段异常 | 保留标准化证据，质量评分不可用 |

显式绑定模式的流水线失败返回：
failure_kind 为上述类别，score=null，metrics=[]。
不把配置/映射/评测异常填成质量 0 分。
CaseResult、Run API 的 score 因此允许 null；数据库 score 列本来就允许 null，无需破坏性迁移。
未绑定路径仍使用原来的异常 score=0，failure_kind 默认 null。
若某个报告包含不可评分的 Case，其 average_score 为 null，不将其偷偷当成零参与均值。
只有 Token/费用等计量指标而没有评分型指标时，新路径总体质量同样为 null，仍保留真实计量值。

Job 的 completed 表示 Case 处理和计数已结束，失败数仍由 failed_cases 表达，沿用既有含义；
这不是“全部质量通过”。映射失败的已提交 Case 不会在发布新规则后自动重算；需要新建 Job。

新路径沿用原评测器，EvidenceAwareEvaluator 只处理执行范围和证据充分性：
- Token/费用/工具等 Agent 指标限定到最后成功 Attempt；Latency 等生命周期指标保留原 Trace 范围。
- Token 计数必须是已知、非负、真实整数，且总和一致；未知不进入原 int()/默认零转换。
- 费用还需要已知 model 和已配置价格；不足则 value=null、status=unverified。
- 工具名称/参数未知时，工具质量指标和综合质量分为 unknown，而不是失败匹配。
- 缺失事件时间仍由 Runtime 拒绝，绝不使用当前时间填充原事件。
- 不在逐 Case 路径调用 Mapping Agent、LLM、Golden 修复或自动发布。

## Comparison、Regression、Gate 的一致性

metric_semantics.py 定义唯一规范标识 harness-normalized/v1。
成功绑定运行均带此标识；不同 Mapping 版本只改变 Raw 到 canonical 的配置，不改变指标算法。

ensure_metric_semantics() 在单 Run 与 Dataset 比较入口共同执行：
- 任何绑定流水线失败或质量不可确认，拒绝质量比较；
- 新路径与 legacy 的指标定义不能静默混用；
- 缺失或不兼容的定义标识同样拒绝；
- legacy-only 保持原比较行为。

原因是旧路径历史上将部分缺失 Token 解释为 0，而新路径必须保留 unknown；
把两种定义直接比较会产生假变化。
需要对照旧响应格式时，可以发布恒等/等价 Mapping 并重跑基线，使双方进入同一规范模式。
已经没有原始充分证据的历史结果不会被自动解释成“语义一致”。

ExperimentComparison → DatasetComparison → Regression/Gate 使用同一入口。
有流水线故障时 API 返回 metric_semantics_unavailable（409），不会把故障计为回答质量退化，
也不会产生“质量门禁已通过”的结论。直接对人为伪造 Comparison DTO 调用纯检测函数不属于该服务链路保证。

## 为什么版本不会漂移

1. 创建 Job 必须有明确数字版本，服务器补充摘要。
2. SQL 触发器阻止对已绑定完整 payload 的原地修改。
3. Published Version 内容不可变。
4. Worker 每个执行尝试只按 Job 的 ID/version 读取一次，并核对摘要。
5. 每个 Job 使用自己的 Runner/Adapter 实例，不修改长期共享对象。
6. 每个 Raw 产物和 Run 都记录固定绑定。
7. 恢复时加载同一 payload，并核验已提交 Run 的绑定；提交过的 Case 被跳过。
8. 没有 latest 查询，没有自动升级，没有生成服务热路径。

Case 执行/Run 保存与 Case Checkpoint 之间仍存在原系统的崩溃窗口：
未提交 Checkpoint 的外部请求可能被重执行，不承诺外部 Agent exactly-once。
新 Run/Artifact 使用独立 ID，保留真实多次执行，不覆盖旧响应。
已提交 Checkpoint 的 Case 不重复执行，且不能换版本解释。

## 新增及修改文件

新增：
- backend/app/adapters/intelligent/published.py：发布版本装饰 Adapter、证据感知评测器、绑定 Runner、可选 Registry 连接。
- backend/app/harness/metric_semantics.py：共享指标定义与不可比较判定。
- backend/migrations/v015_pinned_mapping_evaluation.sql：唯一新产物表及固定 payload/不可变证据触发器。
- backend/tests/test_published_mapping_evaluation.py：24 个 Stage 7 真实 PostgreSQL/HTTP/恢复测试。
- docs/INTELLIGENT_ADAPTER_EVALUATION_INTEGRATION.md：本文。

修改：
- backend/app/adapters/business_http.py：只提取可覆盖的响应处理边界。
- backend/app/adapters/errors.py：MappingFailure。
- backend/app/harness/context.py：私有的每 Case 产物缓冲。
- backend/app/harness/contracts.py：可空质量分、明确失败类别、可空平均分。
- backend/app/harness/runner.py：固定执行元数据、映射失败隔离、原子产物保存分支。
- backend/app/harness/postgres_run_store.py：复用原 SQL 的可选事务连接和原子保存。
- backend/app/harness/memory_run_store.py：锁内保存及复制测试产物；保留原换行风格。
- backend/app/harness/comparison_service.py、dataset_comparison_service.py：统一语义检查。
- backend/app/jobs/models.py：成对、严格的绑定契约。
- backend/app/jobs/postgres_store.py：查询指定已发布摘要后创建 Job。
- backend/app/jobs/executor.py：每 Job 绑定隔离 Runner、保存 Experiment 绑定、恢复核验。
- backend/app/schemas/evaluation_jobs.py：请求/响应绑定字段。
- backend/app/schemas/runs.py：可空 score 与失败类别。
- backend/app/api/evaluation_jobs.py：仅显式绑定创建追加鉴权。
- backend/app/api/errors.py：409 指标语义不可用。
- backend/app/worker.py：显式启用时注入可选 Registry Store。
- backend/app/registry/postgres_store.py：迁移检查和私有产物查询。
- backend/app/api/adapter_registry.py：保护 Raw 产物读取。
- AI_CHANGELOG.md：本阶段追加记录。

未修改 runtime_factory.py 的评测器组合或 HTTP 接入配置逻辑，也未修改任何前端文件。
工作区这些文件中已有的早期阶段变更未回滚或提交。

## 测试命令和实际结果

ADAPTER_REGISTRY_TEST_DSN 显式指向独立临时 PostgreSQL，测试只创建唯一 schema。
没有读取开发数据库配置或对既有数据执行删除。

定向命令：

```bash
backend/.venv/bin/python -m pytest -q --tb=short \
  backend/tests/test_published_mapping_evaluation.py \
  backend/tests/test_v11_comparison.py \
  backend/tests/test_v11_dataset_comparison.py \
  backend/tests/test_v11_experiment_comparison.py \
  backend/tests/test_v11_regression.py \
  backend/tests/test_v11_regression_gate.py \
  backend/tests/test_v12_error_contract.py
```

扩展过程中实测：37 passed in 13.35s（当时新增集成文件 23 项）。
随后补充“仅计量指标不伪造质量零分”用例；最终该文件 24 项全部在下面的扩大回归通过。

扩大回归命令：

```bash
backend/.venv/bin/python -m pytest -q --tb=short \
  backend/tests/test_adapter_registry.py \
  backend/tests/test_business_agent_integration.py \
  backend/tests/test_intelligent_mapping_contracts.py \
  backend/tests/test_intelligent_mapping_runtime.py \
  backend/tests/test_mapping_validator.py \
  backend/tests/test_mini_mapping_agent.py \
  backend/tests/test_published_mapping_evaluation.py \
  backend/tests/test_replay.py \
  backend/tests/test_replay_timeline.py \
  backend/tests/test_retry_decider.py \
  backend/tests/test_retry_policy.py \
  backend/tests/test_run_context.py \
  backend/tests/test_run_query.py \
  backend/tests/test_run_store.py \
  backend/tests/test_schema_inspector.py \
  backend/tests/test_v09_retry.py \
  backend/tests/test_v10_persistence.py \
  backend/tests/test_v11_comparison.py \
  backend/tests/test_v11_dataset_comparison.py \
  backend/tests/test_v11_experiment.py \
  backend/tests/test_v11_experiment_comparison.py \
  backend/tests/test_v11_experiment_runner.py \
  backend/tests/test_v11_regression.py \
  backend/tests/test_v11_regression_gate.py \
  backend/tests/test_v12_error_contract.py \
  backend/tests/test_v12_openapi.py \
  backend/tests/test_v13_jobs_api.py \
  backend/tests/test_v13_jobs_contract.py
```

最终：577 passed, 1 failed, 5 warnings in 31.70s。
失败是 test_v11_experiment.py::test_duplicate_case_is_rejected：
测试期待 ExperimentRunConflictError，原 InMemoryExperimentStore.attach_run() 抛 ValueError。
相关 Store/Service/测试文件未修改；另在独立临时目录只导出 Git HEAD 的应用代码和该测试，
同样复现 1 failed in 0.08s。未擅自修复这个既有问题。
5 条 warning 是既有 TestCase 模型收集提示。

测试实际覆盖原 HTTP 未绑定流程、绑定完整链、三类错误、Raw 隐私与事务回滚、
发布新版本不影响执行、Case 重试多产物、Checkpoint/Lease 恢复版本一致、
不确定 Token/工具证据、标准化 Replay、Comparison/Regression/Gate 和迁移重入。
首轮曾发现事件追加发生在 attempt_end 之后导致 final-attempt 范围为空，
已修正为 normalize_response 内先追加。另增加 Lifecycle Latency 测试，确保它保留
agent_end 的真实计时，不套用 Agent 指标的事件范围；集成测试锁定这两个边界。

未运行七个依赖项目专用 TEST_POSTGRES_DSN/数据库名及旧测试环境的数据库测试模块：
test_postgres_experiment_store.py、test_postgres_run_store.py、
test_v11_postgres_experiment_service.py、test_v13_atomic_claim.py、
test_v13_cancel_store.py、test_v13_recovery.py、test_v13_worker_e2e.py。
新增 Registry/Stage 7 测试在真实隔离 PostgreSQL 上运行，不是用 Mock Store 代替事务和并发。
因此不宣称全项目测试全部通过。没有调用真实模型或业务 Agent，也没有前端测试、生产迁移、commit/push。

## 审查顺序与剩余边界

推荐先读 published.py 和数据流表，再读 Job 的契约/创建/Executor；
随后检查 v015 SQL 和原子保存，最后读 metric_semantics.py 与集成测试。

- 首版只接入实际存在的 Business HTTP 信封，不能宣称已支持任意外部 Agent 协议。
- 规则应输出既有评测器读取的规范字段；自定义 Profile 的证据别名不会隐式改变评测器字段定义。
- 新 score=null、失败类别和版本字段是新增 API 契约；前端没有新增配置界面，按阶段要求未做修改。
- 旧模式与新模式不自动混比；充分基线证据需要以同一规范重跑。
- Raw 产物增加存储量，没有自动清理或保留策略，HTTP 响应体积策略沿用原 Adapter。
- 标准化不等于脱敏，公开 Trace 投影字段需要人工审核。
- 未提交 Checkpoint 的外部请求可能在恢复后再次执行；版本一致不等于外部副作用 exactly-once。
- 已有重复 Case 异常类型测试失败保留，基线验证证据如上。
- 配置启用及迁移需要用户审查后部署，本次未改开发/生产数据库。

Stage 7 完成后停止，等待审查；没有前端实现，没有进入 Stage 8。

静态检查：新增代码 AST/函数说明/禁止动态执行检查通过；作用域空白检查显式允许原有 CRLF，未为格式统一重写两个既有 Store 文件。
