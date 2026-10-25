# Evaluator Plugin Stage 4：接入现有 Runner 的动态评测执行

日期：2026-10-25。范围：SDK/Registry/Entry Points → 原 Runner → 原 RunRecord/Store/API；不新增 Runner，不修改 Comparison、Regression 或 Gate 算法，不开发前端。

## 1. 真实执行入口审查

| 真实位置 | 调用关系与本阶段处理 |
| --- | --- |
| backend/app/main.py::lifespan | build_harness_runner 创建 API 进程的同一 HarnessRunner；新增保存其 evaluator_catalog |
| backend/app/api/experiment_execution.py::run_experiment | POST /experiments/run → ExperimentRunner.run → HarnessRunner.run；透传可选选择 |
| backend/app/harness/experiment_runner.py::ExperimentRunner.run | 选择验证后创建任务内 Runner 绑定，随后复用原 Experiment 生命周期与 Run 关联 |
| backend/app/api/evaluation_jobs.py::create_evaluation_job | POST /evaluation-jobs 只验证/排队，绑定选择计划至已有 payload JSONB，不执行评分 |
| backend/app/worker.py::run_worker | 同一个 build_harness_runner 创建 Worker 进程目录和基础 Runner；Heartbeat/Lease 循环不改 |
| backend/app/jobs/executor.py::EvaluationJobExecutor.execute | 验证所有权 → Published Mapping 可选绑定 → 动态计划绑定 → 原 Checkpoint/Case 循环 |
| backend/app/harness/runner.py::HarnessRunner._run_case | 最终真正调用评测器的位置；无选择走旧循环，显式选择调用 EvaluatorExecution |
| backend/app/evaluator/runner.py::EvaluationRunner | 旧公开 shim 继承 HarnessRunner；增加可选目录装配，没有第二套循环 |
| backend/app/langgraph_test_runner.py / backend/app/v10_demo.py | 本地示例直接构造 HarnessRunner 并注入旧内置实例；继续复用同一 _run_case，默认不变；需要动态选择时显式注入目录 |
| backend/scripts/run_business_agent.py::main | 只是启动 API/Worker，不是另一评分入口 |
| backend/app/adapters/intelligent/published.py::EvidenceAwareEvaluator.evaluate | 旧指标证据装饰器；动态内置工厂也复用它，不重写算法 |
| backend/app/evaluator/sdk_compat.py | 两个方向的协议桥接调用被包装评测器；不是独立 Dataset/Job 引擎 |

api/gates.py 的 gate.evaluate 是回归闸门，不是 BaseEvaluator 插件执行入口；Mapping Runtime 的 _evaluate 也是不同概念。
全库搜索实际 HarnessRunner/EvaluationRunner 构造与 evaluate 调用后，未发现第二条正式 Dataset 评分循环。

## 2. 架构与最小接入点

```text
服务启动
  → build_evaluator_catalog
  → 原 SDK Registry 显式注册 13 个内置工厂
  → 原 Plugin Loader 发现并加载服务端允许的安装插件
  → EvaluatorCatalog：选择/配置/版本校验
          ↓
同步请求                         异步请求
POST /experiments/run            POST /evaluation-jobs
  → ExperimentRunner             → payload_json 固定 evaluator_plan
          ↓                      → 原 Worker / Executor / Checkpoint
          └───────────┬───────────┘
              同一个 HarnessRunner
                → _run_agent（HTTP/重试不变）
                → _run_case
                   ├─ 无选择：旧 evaluate(case, result) 循环
                   └─ 显式选择：EvaluatorExecution.evaluate
                       → Registry.create：每 Case/每指标新实例
                       → context_from_legacy：独立 EvaluationContext
                       → async evaluate + 单指标 timeout
                       → SDK validate_metric + metric_to_legacy
                       → 全部成功/失败指标保留
                → _persist_run → RunRecord.from_execution
                → 原 RunStore / result_json.metrics
                → 原 GET /runs/{run_id}
```

EvaluatorExecution 只是 Agent 完成后的评分边界，不处理 Dataset、Agent、重试、存储或 Job 状态。
HarnessRunner.with_evaluators 创建相同 HarnessRunner 类的任务内绑定，保留 transport、policy、retry、Store，不修改共享基础 Runner。
不是新建一套 Runner，也不绕过 Store。

## 3. 新契约与公共接口

backend/app/evaluator/contracts.py：

- EvaluatorSelection：evaluator_id、config（JSON 对象）、timeout_seconds（默认 30，有限数值且 0 < t <= 300）。
- EvaluatorChoices：非空列表，最多 16 项；Catalog 拒绝重复 ID。
- EvaluatorBinding：完整 Manifest、规范化选择、配置 Schema 摘要及安装来源包/版本。
- EvaluatorSelectionError：稳定、安全的错误码；API 转为现有 error envelope、HTTP 422。

backend/app/evaluator/catalog.py：

- build_evaluator_catalog：复用真实 Keyword/Tool/Latency/Token/Cost/BusinessRAG 类显式注册；第三方只在启动时按原服务端 allowlist 加载。
- EvaluatorCatalog.resolve：在 Agent 调用、Experiment 创建或 Job 排队前验证 ID、配置及可选已固定计划，返回 JSON 可序列化绑定。
- EvaluatorCatalog.list：返回可用声明/source/config_schema，隔离无效可选配置声明。
- fingerprint：排序键、有限 JSON 的 SHA-256；不依赖 JSON Key 顺序。
- summarize_plan：仅暴露计划 digest 和生产者声明/来源，不暴露配置值。

配置约定：
- 不声明 config_model 的插件只允许 {}。
- 声明 config_model 时必须为 Pydantic BaseModel 子类，extra=forbid；strict=True 验证配置，默认值被规范化进入固定计划。
- unknown key、字符串伪装数值、越界参数、无效超时、未知/重复 ID 均在执行前拒绝。
- 每次实际创建后再次核对 Manifest 和 config Schema 摘要，执行后再核对 Manifest，防止工厂或插件改变声明。

SDK 仍独立，不新增对后端的依赖。config_model 是 Harness 的可选插件约定，不强迫无配置的 Stage 1-3 插件改变接口。

## 4. API 最小扩展

新增 GET /evaluators，位于 backend/app/api/evaluators.py，使用现有 Router/tag/error envelope。
仅返回启动目录中的可用项，不按请求动态导入、不支持安装或代码路径。
启动目录缺失时返回 503，不在请求里扫描或装配插件。

已有两个创建接口追加可选 evaluators 字段：

```json
{
  "name": "dynamic-evaluation",
  "dataset_version": "dataset-v1",
  "agent_version": "agent-v1",
  "cases": [
    {"id": "case-1", "input_text": "answer", "expected_output": "answer"}
  ],
  "evaluators": [
    {"evaluator_id": "keyword_match", "config": {}, "timeout_seconds": 30},
    {"evaluator_id": "example.exact_match", "config": {}, "timeout_seconds": 10}
  ]
}
```

第二项需要管理员已安装示例包、设置 Stage 3 的 EVALFORGE_EVALUATOR_PLUGINS 允许规则并重启 API/Worker。
也可以只选第一项，不需要在线模型或第三方插件。

POST /evaluation-jobs 的响应增加 evaluator_ids，仅显示所选 ID，不回显 config。
GET /runs/{run_id} 的原 result.metrics 字段直接返回全部结果，不创建新指标查询体系。

不传 evaluators 或传 null：保持默认内置流程。
传 []：422，避免误以为“空选择”代表默认。
错误 ID/配置：创建副作用前拒绝。
来源包不可用/导入失败：启动 Loader 保留失败记录，此 ID 不可选择；不能回退默认插件。

## 5. 状态、异常与质量分

backend/app/evaluator/execution.py::EvaluatorExecution.evaluate：

1. 按请求顺序执行，各 Case 按原 HarnessRunner 的 Semaphore 并发；不额外扩大单 Case 的插件并行度。
2. 为每个 Case/指标 Registry.create 新实例，创建独立文本/Trace/配置/metadata 快照。
3. 使用 asyncio.wait_for 设置单指标超时；错误/超时形成结构化 SDK error 指标并继续后续指标。
4. SDK 主动返回 success/missing/not_applicable/unverified/error 均被保留并转换为原 MetricResult。
5. CancelledError 向上传播，Runner 取消并等待自己拥有的兄弟 Case 任务，不把取消伪装成评测失败。
6. 检测同名输出，所有冲突项明确失败，避免旧 Comparison 的同名 dict 后项覆盖。

错误占位指标使用保留命名空间 __evaluator_error__. + evaluator_id 的 SHA-256；原 ID 在 details 内 Manifest 可读。
这样长 ID 也不超出 SDK 指标名约束，并确保每个失败保留一个独立结果。插件禁止自行输出该保留命名空间。
错误包含稳定 code 和异常类型，不复制意外异常原文；插件显式返回的结构化 error 保持其契约内容。

| 动态结果 | Case 处理 |
| --- | --- |
| 全部有效，有质量 score | 保持现有非空 score 算术均值 |
| 合法 raw value，没有质量 score | Case.score=None，不把毫秒/Token 转成质量分 |
| 明确 not_applicable | 不贡献 score，不编造 0 |
| 任一 missing/unverified/error | 全部指标仍保留，Case.score=None、failure_kind=evaluation、error 为安全摘要 |
| Agent/Mapping 失败 | 不执行插件；动态质量为 None，保留正确 failure_kind |
| 未显式选择 | 旧内置循环、错误 fail-fast、总分 fallback 等行为保持原样 |

单指标失败不使其他指标丢失。Job 的 failed_cases 按原 result.error 规则计数，全部 Case 处理完仍按原状态机进入 completed。
因此 completed 表示任务已处理完，不代表每个评分都成功。没有改变 Job 的状态/进度模型。

## 6. 标识、秘密与 Trace 数据流

context_from_legacy 继续复用 Stage 1，输入是原 TestCase、AgentResult 和完整生命周期 Trace。
Runner 提供真实 run_id；从最后一次成功 attempt_end 提取 Agent attempt_id；找不到就保持 None。
ExperimentRunner/Executor 在创建或复用 Experiment 后提供 experiment_id；Job 执行另外提供真实 job_id。

evaluator config/plan 不进入 Agent-visible RunContext.metadata。Run 的安全计划摘要只在 _persist_run 阶段加入副本。
外部 Agent HTTP body 和原业务协议不变。
新增 evaluator_plan 为服务端保留的 Run metadata 键；用户 Case metadata 不能冒充该来源声明，原 Case 内容仍完整保存。

插件只收到 SDK 文本、JSON Trace/配置和事实标识，没有 DB 连接、Store、Runner 或服务密钥注入。
但同进程 Python 不是沙箱；插件仍需受信，不应在配置中放宿主服务凭据。

SDK 结果通过 metric_to_legacy，完整状态/Manifest 仍保存在 details._evalforge_evaluator_sdk。
Trace 继续使用原 TraceCollector 与 TraceEvent，插件收到的是复制的 JSON，不修改原 Replay 输入。

## 7. 固定计划、恢复、Published Mapping 与比较兼容

异步 API 将预验证 EvaluatorBinding 列表保存到已有 EvaluationJobPayload.evaluator_plan → payload_json。
没有新表/列/迁移，没有新的 Job Store。

Worker 使用自己的启动目录重新解析并与固定绑定逐项比较：
Manifest/API/实现版本、包版本、配置 Schema 摘要、规范化配置和 timeout 都必须一致。
无固定计划、目录缺失或版本/Schema 不同，在 Agent 执行前失败，不使用 latest 或回退默认。
恢复时校验已提交 Run 的 evaluator_plan.digest 与 Job 计划一致，再沿用原 Checkpoint 跳过逻辑。

Existing Lease、Heartbeat、attempt_count fencing、Checkpoint+Progress 原子提交均不改。
取消中的未完成 Case 不提交 Checkpoint，由原恢复机制接管。
Run 保存与 Checkpoint 是原有两个提交边界；本阶段不声称外部调用 exactly-once。

Published Mapping 的 bind_published_runner 会克隆 Runner，本阶段显式保留目录/执行边界/评测身份。
Executor 再按 Job 计划绑定，继续走原 save_with_mapping_artifacts。
真实 PostgreSQL 测试证明 Raw/Normalized 产物、插件指标和原 Replay 可以共同工作。

Comparison/Gate 算法文件不变，仅在其已经调用的 metric_semantics.ensure_metric_semantics 前置校验中：
- 拒绝默认/显式选择混用、不同计划摘要。
- 拒绝存在执行错误/不完整证据的动态 Run。
- 同计划的合法 raw-only Run 仍可沿用现有 value 比较，质量 delta 保持 None。
- 原 Published Mapping 的语义保护保持原样。

新 Manifest.direction 不自动反转旧 Regression/Gate 规则；score 始终高者好，原 value 规则仍由既有规则配置指定。

## 8. Dataset → Runner → Plugin → Metric Store 的实际追踪

异步真实 PostgreSQL 集成的函数/持久化顺序：

| 步骤 | 实际函数 | 持久化位置 |
| --- | --- | --- |
| 1 | create_evaluation_job → Catalog.resolve → PostgresEvaluationJobStore.create | harness_evaluation_jobs.payload_json 的 cases/evaluators/evaluator_plan |
| 2 | Worker claim_next / heartbeat_loop | 原 Job worker_id/attempt_count/lease/heartbeat 字段 |
| 3 | EvaluationJobExecutor.execute → bind_published_runner → HarnessRunner.with_evaluators | 只读固定 payload，运行期绑定不写第二套状态 |
| 4 | _get_or_create_experiment | 原 Experiment 表与 Job experiment_id |
| 5 | HarnessRunner.run → _run_case → _run_agent/_run_agent_with_retry | 原 TraceCollector/RunContext 内存状态 |
| 6 | EvaluatorExecution.evaluate → Registry.create → context_from_legacy → plugin.evaluate | SDK 上下文与每 Case 新实例；不写数据库 |
| 7 | validate_metric → metric_to_legacy | 原 name/value/unit/score/details DTO |
| 8 | HarnessRunner._persist_run → RunRecord.from_execution → RunStore.save | harness_runs.result_json.metrics；metadata_json 含安全计划摘要 |
| 9 | mapped 模式 save_with_mapping_artifacts | 原 Run 与 harness_mapping_artifacts 同一事务 |
| 10 | Executor.record_case_result | 原 harness_evaluation_job_cases + Job Progress 同事务 |
| 11 | ensure_run_linked / mark_completed | 原 Experiment membership 与 Job 终态 |
| 12 | GET /runs/{run_id} → RunReplayService.load → RunStore.get → RunDetailResponse | 读取同一 RunRecord，指标无旁路 |

同步 Experiment 使用同样的步骤 5～8，经 ExperimentRunner._attach_results 完成关联。
真实测试还在 SQL 中直接读取 result_json，确认成功 score 与失败 SDK status 同时存在。

## 9. 文件清单与推荐阅读顺序

新增：
1. backend/app/evaluator/contracts.py：选择、固定绑定、统一选择错误。
2. backend/app/evaluator/catalog.py：启动装配、配置校验、计划与安全摘要。
3. backend/app/evaluator/execution.py：单指标执行/错误隔离边界。
4. backend/app/api/evaluators.py：只读目录及标准错误处理。
5. backend/tests/test_dynamic_evaluators.py：执行/API/并发/取消/配置/语义保护。
6. backend/tests/test_dynamic_evaluators_postgres.py：真实 Job/Run/Checkpoint/Replay 集成。
7. docs/plans/evaluator-plugin-stage4.md：本报告。

修改：
- backend/app/harness/runner.py：可选动态边界、任务内绑定、取消清理、安全摘要持久化。
- backend/app/runtime_factory.py：API/Worker 共用启动目录。
- backend/app/main.py：保存目录、注册新路由和安全错误处理。
- backend/app/harness/experiment_runner.py：选择绑定与 evaluator-only Experiment 身份。
- backend/app/api/experiment_execution.py：可选字段透传。
- backend/app/api/evaluation_jobs.py：入队前验证与固定计划。
- backend/app/schemas/experiment_execution.py、schemas/evaluation_jobs.py：最小可选请求/响应字段。
- backend/app/jobs/models.py：已有 JSONB payload 新增可选选择/绑定。
- backend/app/jobs/executor.py：计划校验、身份、恢复摘要检查，状态/提交逻辑不变。
- backend/app/adapters/intelligent/published.py：Runner 克隆保留动态能力。
- backend/app/harness/metric_semantics.py：复用语义校验入口，不改比较算法。
- backend/app/evaluator/runner.py：旧公开 shim 复用目录与同一 Runner。
- requirements.txt：声明本地 SDK 包依赖，从仓库根安装。
- packages/evaluator-sdk/README.md、examples/evaluator-plugin/README.md：配置/调用和 Stage 4 边界。
- README.md：文档索引增加本报告链接。
- AI_CHANGELOG.md：追加本次记录。

建议阅读：contracts → catalog.resolve → execution.evaluate → HarnessRunner.with_evaluators/_run_case/_persist_run →
Job API/Executor → 新测试 → 原 Store/RunRecord。旧 Stage 0-3 文件与未提交工作保留，不重复归为本次新增。

重要代码审查锚点：

- [backend/app/harness/runner.py::with_evaluators:139](../../backend/app/harness/runner.py#L139)
- [backend/app/harness/runner.py::_run_case:280](../../backend/app/harness/runner.py#L280)
- [backend/app/harness/runner.py::_persist_run:849](../../backend/app/harness/runner.py#L849)
- [backend/app/evaluator/catalog.py::resolve:66](../../backend/app/evaluator/catalog.py#L66)
- [backend/app/evaluator/execution.py::evaluate:35](../../backend/app/evaluator/execution.py#L35)
- [backend/app/jobs/executor.py::execute:385](../../backend/app/jobs/executor.py#L385)
- [backend/app/api/evaluation_jobs.py::create_evaluation_job:51](../../backend/app/api/evaluation_jobs.py#L51)
- [backend/app/api/evaluators.py::list_evaluators:32](../../backend/app/api/evaluators.py#L32)

## 10. 真实测试、安装与风险

安装使用 Stage 3 已验证 SDK 0.3.0；requirements.txt 新增 ./packages/evaluator-sdk。
此 requirements 文件的历史 httpx2 等问题未顺带修复，也没有宣称全新环境完整后端安装已经通过。
从仓库根单独安装 SDK 的命令仍是 python -m pip install ./packages/evaluator-sdk。

新增单元/API 测试最终 41 项；真实 PostgreSQL 新增 5 项。
下列扩大单元/回归命令包含新测试，不重复累计：

```sh
backend/.venv/bin/python -m pytest -q --tb=short \
  backend/tests/test_dynamic_evaluators.py \
  backend/tests/test_evaluator_sdk_compat.py backend/tests/test_evaluator_plugin_config.py \
  backend/tests/test_run_context.py backend/tests/test_retry_policy.py \
  backend/tests/test_retry_decider.py backend/tests/test_v09_retry.py \
  backend/tests/test_v10_persistence.py backend/tests/test_replay.py \
  backend/tests/test_replay_timeline.py backend/tests/test_v11_comparison.py \
  backend/tests/test_v11_dataset_comparison.py backend/tests/test_v11_experiment_comparison.py \
  backend/tests/test_v11_experiment_runner.py backend/tests/test_v11_regression.py \
  backend/tests/test_v11_regression_gate.py backend/tests/test_v12_openapi.py \
  backend/tests/test_v12_error_contract.py backend/tests/test_v13_jobs_api.py \
  backend/tests/test_v13_jobs_contract.py backend/tests/test_v11_experiment.py
```

实际结果：142 passed，1 failed，3 warnings，2.10s。
唯一失败仍为 Stage 0 基线 test_v11_experiment.py::test_duplicate_case_is_rejected：
测试期望 ExperimentRunConflictError，InMemoryExperimentStore.attach_run 抛 ValueError。本阶段未修改或掩盖该失败。
warnings 是三个旧 TestCase 收集提示，不是新警告。

真实 PostgreSQL：

```sh
ADAPTER_REGISTRY_TEST_DSN='host=/tmp/evalforge-registry-stage6-cix7psid/socket port=6543 dbname=postgres user=terry' \
backend/.venv/bin/python -m pytest -q --tb=short \
  backend/tests/test_dynamic_evaluators_postgres.py \
  backend/tests/test_published_mapping_evaluation.py
```

最终结果：29 passed in 14.33s。
包含新 5 项与原 Published Mapping 24 项，独立 PostgreSQL 16 私有 socket，
每个测试新建 Schema，不删除已有数据，不连接开发/生产配置。完成后停止临时数据库。

SDK/Registry/Loader：

```sh
backend/.venv/bin/python -m pytest -q -c packages/evaluator-sdk/pyproject.toml packages/evaluator-sdk/tests
```

90 passed in 0.19s。无在线模型、无实际外部 Agent，Agent HTTP 使用 MockTransport。
包含真实安装元数据/EntryPoint.load 的启动到 Runner 测试，但不声称已跑生产插件或生产部署。

主要限制：
- asyncio.wait_for 是协作式超时，不是强制终止任意 CPU/阻塞/恶意 Python 的沙箱。
- 同一 Case 内顺序执行，Case 并发仍受原 ExecutionPolicy 控制；没有新增并行评分框架。
- Job 取消请求继续按既有 Case 边界处理；Worker 任务取消/Lease 丢失能传播到当前插件。
- 包版本/Manifest/Schema 快照不等于代码签名；仍需锁定安装环境并重启进程。插件外部模型/定价/资源若影响语义，作者必须反映在版本或声明配置中，框架不自动证明语义等价。
- 动态 Cost 内置工厂默认无定价条目，缺少定价时明确 unverified，不伪造费用；自定义服务端目录可提供可信 PricingCatalog。
- 旧 BusinessRAG 数值为空但未声明适用性时仍保守解释为 unverified；不会猜测为 not_applicable。
- 原 SDKToLegacyEvaluator 单独注入旧循环仍保留 Stage 1 异常语义；本阶段保证来自显式动态执行路径。
- 未做全项目全量、前端、负载或在线模型测试；未加入租户身份系统/插件沙箱/密钥管理。
- 没有修改 Comparison/Regression/Gate 算法，也不自动根据方向改变已有规则。

Stage 4 完成后停止，不进入后续阶段，不 commit/push。
