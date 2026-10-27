# EvalForge-Agent RAG-P1：仓库审查、技术方案与交付

日期：2026-10-27。基线 commit：1d0d916。实际仓库 `/home/terry/projects/agent-evaluation-harness`。
本阶段先完成源码审查和方案说明，再实施独立插件；未提交或推送 Git，未部署服务。

## 1. 仓库审查

| 组件 | 现有实现与约束 | 本阶段接入方式 |
| --- | --- | --- |
| Evaluator SDK | `packages/evaluator-sdk` 0.3.0 / API 1.0；async evaluate(context)；一次一指标 | 仅依赖公开 SDK，不修改协议 |
| Manifest / MetricResult | 显式版本、方向与 success/missing/not_applicable/unverified/error；非成功不可带分数 | 八个独立 Manifest；N/A 无假零分；错误结构化 |
| Registry | 新实例工厂、协议/版本检查、内置/第三方同名拒绝 | 直接复用，不覆盖任何已有名称 |
| Entry Points | 固定组 `evalforge.evaluators`；先发现、按允许清单加载；来源/版本固定 | pyproject 声明八个 `rag.*` 入口 |
| Catalog | 配置模型 extra=forbid、严格校验；固定配置 schema/Manifest/发行版 | 声明 RetrievalConfig / ContextConfig，不新增配置引擎 |
| Runner | `HarnessRunner` -> `EvaluatorExecution`；每 Case/指标新实例、独立超时/异常、取消传播 | 不创建第二 Runner；按原选择字段执行 |
| Trace Mapping | MappingSpec / map_agent_result 负责异构响应与 TraceEvent；没有统一 RAG 阶段契约 | metadata 或 trace 保留阶段事实；安全 JSON Pointer 读取，不扩展 Mapping DSL |
| Store | 实际指标在 `RunStore` / PostgreSQL `harness_runs.result_json.metrics`；SDK 信封在 details | 不新增 Metric 表；沿用保存、查询、Job Checkpoint |
| Comparison / Gate | Case ID 对齐、plan digest、版本/配置/statistical_scope 检查，证据不全失败关闭 | 输出可比口径与版本，直接复用 Baseline/Candidate 和 Gate |
| 现有 RAG 示例 | BusinessRAGEvaluator 已有 retrieval_recall_at_5 / retrieval_mrr_at_5 等 | 保留实现和 ID，新插件统一使用 rag.* |

## 2. 工程方案与通用性

完整链路：第三方项目观测 -> 原 Adapter/Trace Mapping -> SDK EvaluationContext -> 插件输入映射
-> Gold-ID 算法或显式 LLM Judge -> SDK MetricResult -> 原执行桥 -> RunStore -> 比较/Gate。

新增独立发行包 `evalforge-rag-evaluators` 0.1.0，源码位于 `packages/rag-evaluators`。
依赖公开 SDK、Pydantic、HTTPX；不依赖 app、FastAPI、LangChain、某个数据库或检索框架。
因此字段不同的项目可通过配置指针接入，而不必更改插件算法。不是任意结构自动猜测：
用户必须提供排序列表、稳定 ID、评测粒度和所需标注；复杂语义变换仍应由原 Adapter 完成。

八个入口：
`rag.recall_at_k`、`rag.precision_at_k`、`rag.hit_at_k`、`rag.mrr_at_k`、`rag.ndcg_at_k`、
`rag.context_relevance`、`rag.context_precision`、`rag.context_recall`。

原动态请求的 evaluators 中选择 ID 和 config，支持 stage=dense/bm25/fusion/rerank、
K=1..10000、level=document/chunk。每项配置一次选择一个阶段/K，不合并阶段、不回退到最终结果。
原 SDK 是一调用一结果、原 Runner 禁止重复 evaluator ID，因此多阶段/多 K 矩阵以独立运行实现；
不改变 SDK 来隐式展开多指标。比较应在相同配置内进行。

标准输入：Case.metadata.rag.gold = {level, ids 或 relevance}；
AgentResult.metadata.rag.stages.<stage> = {level, items:[{id,text}]}；
Context Recall 另需 Case.metadata.rag.reference_claims 字符串数组。
可配置 RFC 6901 pointer 读取不同项目字段，包括 trace 数组及含 / 或 ~ 的字段名。
Gold 与候选必须显式同粒度，不自动把 Chunk ID 当成 Document ID。

## 3. 指标与边界

| 指标 | 明确口径 |
| --- | --- |
| Recall@K | 唯一正相关命中数 / 全量正相关 Gold 数 |
| Precision@K | 唯一正相关命中数 / 请求 K，缺少的位置计未命中 |
| Hit@K | Top-K 是否有正相关 ID |
| MRR@K | 每 Case 首个相关位置的倒数，无相关为 0；数据集沿用均值聚合 |
| nDCG@K | graded gain=2^grade-1，log2(rank+1) 折扣；理想排序来自全量 Gold |
| Context Relevance | LLM 对实际 Top-K 上下文 query relevance 的布尔判断均值 |
| Context Precision | LLM relevance 标签的 AP，分母为 Top-K 中被判断相关的上下文数；全不相关为 0 |
| Context Recall | LLM 对显式参考原子声明是否被上下文整体支持的比例 |

检索列表按 ID 首次出现去重，然后 Top-K；不按 score 重排，同分保留输入顺序。
Gold ID 按集合去重；Gold 同时提供 ids 与 relevance 时集合必须一致。
分级标注接受有限 [0,20] 数值，>0 为二值相关；nDCG 使用 expm1 稳定计算，避免小正等级消失。
未标注检索 ID 按不相关处理，需要封闭标注集。显式空检索 + 非空 Gold 是确定性零分。
空/不存在的正 Gold、缺失阶段/粒度/必要字段返回 not_applicable；给出的结构错误或粒度冲突返回 error。
不把未知信息转换成空列表或 0。每个结果保留 evaluator_version、metric_version、stage、k、
level、完整规范化评测配置及 statistical_scope。

## 4. LLM Judge 与确定性评分隔离

前五项完全不调用 LLM，family=gold_ids_deterministic；后三项显式配置 judge，family=llm_judge。
无 Judge、文本、参考声明或上下文时返回 N/A；不使用关键词或 Gold ID 冒充语义判断。
Context Recall 不自动拆分参考答案，避免在评分中悄悄混入另一项模型任务。

提供异步 OpenAI-compatible JSON-mode HTTP transport。profile 只选择服务端环境配置，
不接受请求传入端点/密钥。model/revision 显式固定并留存，密钥和 URL 不进入指标或错误。
一次调用、不重试、不跟随重定向；输入/输出/响应体/超时均有限额；拒绝截断、不足标签、
非布尔标签和缺失模型标识。保存标签、提示词版本、provider-reported model、可用 token usage。
输出文本只作为数据发送；模型结果从未执行为代码。取消继续向原 Runner 传播。
不同 reported model 的 LLM 结果通过原 statistical_scope 保护拒绝直接比较。

## 5. 验证与交付

专项：111 passed，0 skipped；包含 101 项包级 Golden/边界/HTTP 协议测试与 10 项后端集成/E2E。
专项命令：

```sh
ADAPTER_REGISTRY_TEST_DSN='<private-test-dsn>' TEST_POSTGRES_DSN='<private-test-dsn>' \
backend/.venv/bin/python -m pytest -q --tb=short packages/rag-evaluators/tests backend/tests/test_rag_plugins_e2e.py
```

全量命令与结果：

```sh
ADAPTER_REGISTRY_TEST_DSN='<private-test-dsn>' TEST_POSTGRES_DSN='<private-test-dsn>' \
backend/.venv/bin/python -m pytest -q --tb=short backend/tests packages/evaluator-sdk/tests \
examples/evalforge-keyword-coverage/tests packages/rag-evaluators/tests
```

963 collected; 962 passed; 1 existing failure; 0 skipped

唯一失败：`backend/tests/test_v11_experiment.py::test_duplicate_case_is_rejected`，
期望 ExperimentRunConflictError，原 InMemoryExperimentStore 抛出 ValueError。
该问题在仓库前序阶段已有记录，本次重新实测仍存在；未修改、跳过或掩盖。
首轮临时库未应用既有 Job 迁移，额外 5 项失败；补齐原迁移后重跑，以最终结果为准。

测试库：新建 PostgreSQL 16 私有实例和 agent_harness_test，不连接现有开发/生产库。
新增 PG 用例各自使用隔离 schema；复用原 Job/Executor/Checkpoint/JSONB/Run API。
测试结束停止临时服务，保留临时数据和 schema 供检查。无数据迁移源文件修改。
LLM transport 使用 HTTPX MockTransport 验证完整请求/解析/异常/取消，没有调用线上模型。
检索 Agent 使用确定性 fixture，Registry/Loader/Runner/Store/Comparison 均是真实实现。

另在全新虚拟环境安装 SDK 与插件 wheel，确认无 app/FastAPI/LangChain，真实发现 8 个入口、
发现阶段不导入、加载注册后运行五个确定性指标、三项未配置 Judge 返回 N/A。
原后端 Python 3.12/Pydantic 2.13.5；独立环境 Pydantic 2.14.1/HTTPX 0.28.1。
AST、50 个新函数文档、依赖边界、wheel 源码一致性、独立 Decimal Golden 复核和 diff 空白检查通过。
未实际验证 Python 3.11 或最低依赖版本组合、线上 Judge 质量、压测、前端和生产部署。

## 6. 修改文件清单

新增独立包（12 个文件）：

- packages/rag-evaluators/pyproject.toml：发行包、依赖、八个 Entry Points。
- packages/rag-evaluators/.gitignore：构建和缓存排除。
- packages/rag-evaluators/README.md：安装、允许清单、输入/映射、公式、Judge、比较约束。
- packages/rag-evaluators/src/evalforge_rag_evaluators/__init__.py：公开插件工厂及配置导出。
- packages/rag-evaluators/src/evalforge_rag_evaluators/config.py：严格配置与字段映射契约。
- packages/rag-evaluators/src/evalforge_rag_evaluators/inputs.py：指针适配、粒度校验、去重、Gold。
- packages/rag-evaluators/src/evalforge_rag_evaluators/metrics.py：八个评测器及 SDK 状态/证据。
- packages/rag-evaluators/src/evalforge_rag_evaluators/judge.py：异步、有界、显式 LLM transport。
- packages/rag-evaluators/src/evalforge_rag_evaluators/py.typed：类型标记。
- packages/rag-evaluators/tests/golden.json：独立期望向量。
- packages/rag-evaluators/tests/test_metrics.py：公式、空输入、去重、K、分级标注、映射/粒度/并发。
- packages/rag-evaluators/tests/test_judge.py：LLM Golden、请求/响应、超时/预算/秘密保护/取消。

新增集成测试与文档：

- backend/tests/test_rag_plugins_e2e.py：真实安装/Entry Points/API/Runner/Mapping/Store/Comparison/Gate/PG Job。
- docs/plans/rag-p1.md：本审查、方案、测试与风险说明。

修改既有文档：

- README.md：新增 RAG-P1 文档入口，保留原历史测试记录。
- AI_CHANGELOG.md：追加请求、调用链、决策、验证和已知边界。

SDK、Registry、Loader、后端生产代码、Runner、Store、Comparison/Gate、数据库迁移均无改动。

## 7. 风险与工程取舍

1. LLM 判断有误差、提示词注入与不确定性，temperature=0 不保证复现；须用人工标注校准。
   本阶段的模拟传输测试证明接入协议和计算规则，不能证明真实模型质量。
2. 每项上下文指标每 Case 最多一次调用，同时选择三项产生三次调用；没有跨指标缓存。
   超限/超时保留 error，不截断输入。端点必须兼容 JSON-mode chat/completions，否则需网关适配。
3. ID 语义、文档/Chunk 声明、语料与参考版本由接入方负责，不能靠字段改名证明等价。
   文档聚合应在项目 Adapter 完成；指标只评估显式单位，closed-world Gold 应足够完整。
4. 原执行计划整体一致性检查较保守；不支持同一请求重复 ID 展开多个 K/阶段。
   依赖或 Judge 环境更新后需保持 deployment revision 真实，并重启相关 API/Worker。
5. 原插件运行在同一 Python 进程，允许清单不是沙箱；协作式超时不能强杀阻塞代码。
6. 全量仍有原重复 Case 异常类型失败；没有将项目声明为全绿。
