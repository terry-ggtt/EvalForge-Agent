# Intelligent Adapter Stage 5：Mini Mapping Agent

## 工程位置与为什么需要生成服务

现有离线链路：

```text
Raw JSON 样本 → Schema Inspector → 人工配置 MappingSpec
  → Deterministic Runtime → Validator L1/L2/L3 → 候选规则审查
```

问题是异构字段多时，人工逐条配置成本高。仅让模型“写一个适配器”又会带来任意代码、猜测语义、
数据泄漏、无限修复和不可控费用。因此本阶段只用模型提出声明式规则，
执行、证据检查、Golden 比较、终止和费用预检均由本地代码掌握：

```text
SchemaInspectionResult + 目标 Schema + 字段披露白名单/必要标量样本/可选说明
  → 最小化上下文（Raw 与 Golden 留在本地）
  → Structured LLM Client → MappingProposal（MappingSpec + 证据声明）
  → 本地严格解析、受限操作、证据路径检查
  → 现有 Runtime + 三层 Validator（逐个本地样本）
  ├─ 全部通过 → candidate，仍然禁止自动发布
  ├─ 无 Golden → needs_manual_review
  └─ 可修复错误 → 结构化错误码 → 有限修复 → 超限则 needs_manual_review
```

这是开发期离线服务。没有接入 Evaluation Runner、Registry、数据库或 FastAPI。
正式评测不依赖 LLM，也没有新增 Agent 框架、Workflow 或依赖。

## 仓库检查与复用决策

- backend/app/langgraph_test_runner.py 的 main() 使用 ChatOpenAI、DEEPSEEK_MODEL、DEEPSEEK_API_KEY；
  它是组装业务 Agent 和 Runner 的实验入口，不是通用 LLM Client。
- backend/app/config.py 仅有 get_database_url()；没有统一的模型配置系统。
- 根 requirements.txt 已包含 langchain-openai、langchain-core、Pydantic。
- 本地检查版本：langchain-openai 1.6.7、langchain-core 1.6.6、Pydantic 2.13.5。
- 复用 ChatOpenAI 依赖，但不导入实验脚本，不复用其硬编码模型/地址，不读取业务 Agent 的模型凭据。
- MappingSpec、JsonPath、RuntimeModel、SchemaInspector、MappingValidator 和公开 AgentResult 契约保持不变。

## 新模块职责

| 文件 | 主要契约/函数 | 职责 |
| --- | --- | --- |
| backend/app/adapters/intelligent/generation_contracts.py | GenerationRequest、ValidationSample | 将模型可见请求与本地原始样本/Golden 分开 |
| 同上 | GenerationBudget | 最大修复次数、超时、Token 额度和显式价格上限 |
| 同上 | MappingProposal、MappingEvidence | 受限 DSL 和逐字段证据、不确定性 |
| 同上 | ModelReply、RepairFeedback、GenerationAttempt、GenerationResult | 用量、脱敏反馈、本地历史和终态 |
| backend/app/adapters/intelligent/generation_context.py | build_context() | 重算原始样本结构；按披露白名单导出 Schema/必要值 |
| 同上 | normalized_path()、evidence_feedback() | 统一 Inspector [] 证据路径；检查来源和证据覆盖 |
| backend/app/adapters/intelligent/llm_client.py | StructuredLLMClient | 可注入的单次异步调用协议 |
| 同上 | LLMConfiguration、LangChainMappingClient | 显式环境配置和现有 ChatOpenAI 的薄封装 |
| backend/app/adapters/intelligent/generation_service.py | MiniMappingAgent.generate() | 有界生成/修复状态机，管理本次会话的所有调用 |
| 同上 | _proposal()、_validation_feedback() | 严格解析、重复 JSON 键检查、无值错误反馈 |
| backend/tests/test_mini_mapping_agent.py | FakeLLMClient 等 | 不需要真实 Key 或网络的测试 |
| backend/tests/fixtures/mini_mapping_agent.json | 两次脚本化输出 | 独立 Golden、Raw 样本和失败/修复模型回复 |
| docs/INTELLIGENT_ADAPTER_MINI_MAPPING_AGENT.md | 本文 | 设计、使用方式、实测结果与限制 |
| AI_CHANGELOG.md | 追加记录 | 本阶段完成范围和验证证据 |

## 输入契约与披露控制

generate(request, samples) 接收两个隔离的输入：

1. GenerationRequest：
   - inspection：既有 SchemaInspectionResult；服务重算样本结构并核对指纹，不直接信任调用者修改过的 fields。
   - target_schema：默认 AgentResult.model_json_schema()；第一版只接受这个实际公共目标契约，不能让模型改写目标。
   - disclosed_paths：人工选择可向模型披露的 Inspector 规范路径。默认空列表，不发起模型调用。
   - disclosed_values：显式选中的少量原始标量，例如事件枚举 model/tool；其路径也必须获准披露。
   - field_hints：只针对已披露路径的可选说明和 optional 标记，始终视为不可信数据。
2. ValidationSample：
   - response：本地 Raw Response。
   - has_separate_trace/trace：区分未提供 Trace 与显式提供 null，沿用 Runtime 的根路径语义。
   - golden：独立本地 Golden；不会发送给模型。
   - partial_trace：传给既有 Validator，不降低其阻断规则。

最多 16 个本地样本；有独立 Trace 时，Inspector 扫描 Response/Trace 两个根，合计不超过既有 32 个根的默认限额。
原始数据先做 Inspector 限额检查再复制，防止跨 await 被调用方修改。每个会话使用独立状态。

披露采用 allowlist，而不是只靠密码字段黑名单。
未选中的字段名、字段值和整段事件不会进入模型请求。
必要值仅允许明确路径的标量，每个字符串最多 256 字符、最多 32 个选择项；对象和数组不能整包披露。
允许披露一个字段名，不等于允许披露其原始值；两份白名单分别控制。
白名单若主动包含敏感名称/值，服务会按授权发送，因此白名单本身需要人工审查。
这是数据最小化接口，不是通用 PII 检测器。

Schema 的 [] 是发现路径，只用于证据描述。
真正 MappingSpec 仍使用 Stage 1 的受限 JSONPath，不能用通配符执行。
Trace 字段操作是事件相对路径；证据路径会加上 events_path 和 [] 转为原始根相对的发现路径。

## Structured Output 与安全边界

LangChainMappingClient 每次构造 ChatOpenAI，设置：

- temperature=0、max_retries=0、cache=False。
- max_tokens 和 timeout 明确传入。
- with_structured_output(schema, method="function_calling", strict=False, include_raw=True)。
- 模型只获得一个“输出结构”工具，不存在执行工具的调度器。
- 关闭该调用的 LangSmith tracing，传入空 callbacks 列表。

选择工具式 Structured Output 是为了复用已有依赖；
DSL 的 discriminated union、可变 enum map 与默认值不兼容所有供应商严格 JSON Schema 子集，
所以没有声称供应商 strict=true。
服务端生成约束之后，仍以本地严格 MappingProposal/MappingSpec 校验为最终约束。
不支持该能力的模型会失败并在预算内终止；不会降级为自由 Python 文本或执行代码。

服务拥有固定 system 指令；Schema、字段名、说明、标量、历史提案和反馈只放在 human 消息的 JSON 数据区。
模型输出额外 code/python_code、未知操作、非法路径和代码围栏均不能作为合法提案通过。
没有 eval、exec、动态代码导入或模型输出代码执行。
JSON 文本输入检测重复键；SDK 已解析成 dict 的数据按严格契约再次验证。

提示隔离不保证模型绝不受 Prompt Injection 影响。
实际防线是：数据最小化 + 消息角色隔离 + 受限 DSL + 来源覆盖 + 本地 Runtime/Golden + 禁止自动发布。
模型可能生成“结构合法但业务含义错误”的规则，因此 Golden 与人工审查仍然必要。

## 证据与语义判断

每个响应字段及事件规则字段都必须有一条 MappingEvidence：

- event_source_type：null 表示 Response；事件字段填写该规则的原始 source_type。
- target：实际字段的目标路径。
- source_paths：操作实际引用的规范 Inspector 路径；必须全部观察到且获准披露。
- certainty：observed、inferred 或 unknown。
- explanation：模型的理由，限制长度，保存供人工审查。

服务检查证据和实际操作的路径集合、字段覆盖及唯一性；不能用解释文字替代缺失的来源。
inferred/unknown 使本次验证失败，最终可能 needs_manual_review。
“observed”只表示模型声称使用了已观察来源，不证明业务语义；LLM 的自信不等于独立证据。
整包 payload 提取可以复用原有字段，但仍必须经 Golden 检查关键内部字段。

仅当所有本地样本的 Validator.release_allowed 均为 true，且证据检查通过时：
status=candidate，semantic_verified=true。
这里的 true 仅表示这些本地 Golden 样本通过，不能推广为所有输入正确。
没有 Golden 时，一旦没有硬错误且证据合格，会直接返回 needs_manual_review/golden_required；
不会浪费剩余修复次数要求模型“猜出”缺失的人工期望。

无论结果如何，publication_allowed 永远是 Literal[False]。
本阶段没有人工批准入口，也不会把说明文本中的“已批准”当成授权。

## 状态、修复与终止

每次 generate() 的状态保存在 GenerationResult 和 GenerationAttempt 中，没有全局可变会话状态。

```text
输入/披露检查失败 ──────────────→ needs_manual_review（0 次 API）
              ↓
预留预算 → 单次模型调用 → 严格解析 → 证据检查 → 逐样本 Validator
   ↑         │                │                       │
   │         超时/API错误      格式错误               验证失败
   └─────────── 值无关结构化反馈 + 上次合法提案 ────────┘
              ↓
全部通过 / 无 Golden / 次数耗尽 / 预算不足 / 用量不可确认
              ↓
candidate 或 needs_manual_review
```

默认 max_repairs=3，即最多首次生成+3 次后续调用；可配置为 0～10。
API 错误和超时也占用次数，不另设隐藏重试环。
反馈只含 code、layer、sample_index、event_index，最多取 128 个 Validator 发现项；
完整本地报告仍保留，不向模型发送 actual/expected、Raw 路径、异常堆栈或凭据。
模型可以获得上一轮合法提案，但非法原始模型文本不会被原样回显。

终止原因包括：

| reason | 行为 |
| --- | --- |
| golden_validated_candidate | 所有本地样本与证据通过，仍禁止自动发布 |
| invalid_request_or_disclosure | 输入/目标/披露不合法，零调用 |
| golden_required | 已有候选但无独立 Golden，人工审查 |
| repair_limit_reached | 次数耗尽，保留最近可解析配置及历史 |
| prompt_token_limit | 单轮上下文过大，禁止调用 |
| token_budget_exhausted / cost_budget_exhausted | 无法预留下一轮额度 |
| usage_unavailable | 用量缺失或格式不可靠，禁止继续花费 |
| provider_limit_violation | 供应商报告用量超出预留/输出限制，立即停止 |

API 错误、超时、格式错误可以在额度内恢复；不使用无限重试或自动切换供应商。
asyncio.CancelledError 直接传播，不再启动修复。
超时依赖异步 Client 合作取消；实际 Client 同时设置传输超时。
服务不执行恶意或阻塞的任意第三方 Client，也不是进程隔离沙箱。

## Token 与费用控制

GenerationBudget 必须显式提供：
input_nano_usd_per_token、output_nano_usd_per_token，均为正整数价格上限。
1 USD = 1,000,000,000 nano-USD；例如每百万 Token 1 USD 对应每 Token 1000 nano-USD。
不提供免费调用或自动抓取价格的默认假设。

每次请求前：

```text
input_cap = UTF-8 bytes(system + data + 完整 Structured Output Schema) + 4096
token_reservation = input_cap + max_output_tokens
cost_reservation = input_cap × input_price + max_output_tokens × output_price
```

这比通常 tokenizer 计数保守，并计入工具 Schema 和消息框架余量。
累计预留超过单轮/总 Token/费用限制则拒绝派发。
成功、API 错误、超时都不退还预留，防止不确定计费时继续消耗额度。
API 回复必须带 input_tokens 和 output_tokens；缺失或超过本轮限制则停止。

预留是本会话预算，不是实际账单。部署者必须提供覆盖实际供应商口径的价格上限，
确认模型的 Token/推理 Token/附加收费规则与计数假设；异常供应商超限可能已经产生费用，服务只能停止后续调用。
跨进程、跨会话总费用和崩溃后额度恢复没有持久化，本阶段不宣称支持。
测试中的 Fake 计数用于状态机验证，不是实际模型消耗。

## 完整离线示例：Schema → 失败 → 修复 → Candidate

Fixture：backend/tests/fixtures/mini_mapping_agent.json。
原始响应包含 answer、events 和 private；private 中放置测试用秘密/注入文本。
Inspector 观察到 25 个路径，仅选择 22 个公开结构路径，披露两个 kind 标量 model/tool。
private 字段名、值、Raw 事件整体、answer 实际值和 Golden 不进入模型上下文。

指纹：

```text
4af4ef46112a6fb707551508e27f2affceabfee404780236009de277d689b42e
```

首次 Fake LLM 输出中的错误规则：

```json
{
  "target": "$.payload.usage.total_tokens",
  "operation": {
    "op": "enum_map",
    "path": "$.kind",
    "values": {"model": 20}
  },
  "value_type": "integer"
}
```

完整提案还包含响应字段、事件规则及每个字段的证据记录。
本地 Runtime 成功产生合法整数 20，但原始已知 input=12/output=4，独立 Golden 的 total=16。
因此第一轮 L1/L2 passed，L3 failed。模型收到的反馈示例：

```json
[
  {"code": "token_total_inconsistent", "layer": "L3", "sample_index": 0, "event_index": 0},
  {"code": "golden_value_mismatch", "layer": "L3", "sample_index": 0, "event_index": 0}
]
```

反馈中没有 Golden 的 16 或原始输入值。
第二次脚本化回复采用已观察到的规范 span 对象：

```json
{
  "target": "$.payload",
  "operation": {"op": "extract", "path": "$.span"},
  "value_type": "object",
  "on_null": "error"
}
```

对应证据为 source_paths=['$["events"][]["span"]']，certainty=observed。
它使用原始对象中真实存在的 Token/工具/父关系，不再用事件类别硬编码 Token。

实际运行结果：

```json
{
  "status": "candidate",
  "reason": "golden_validated_candidate",
  "semantic_verified": true,
  "publication_allowed": false,
  "reserved_tokens": 55651,
  "reserved_cost_nano_usd": 63843000,
  "attempts": [
    {"index": 0, "outcome": "validation_failed", "layers": ["passed", "passed", "failed"]},
    {"index": 1, "outcome": "candidate", "layers": ["passed", "passed", "passed"]}
  ]
}
```

此演示使用 Fake Client 的两次预设输出，Runtime 和 Validator 为真实本地实现；
不是在线模型实测，预留 0.063843 USD 是给定测试价格下的保守额度，未发生模型 API 费用。

## 使用与配置

注入接口示例：

```python
budget = GenerationBudget(
    input_nano_usd_per_token=1000,  # 示例；部署时提供实际价格上限
    output_nano_usd_per_token=2000,
    max_repairs=3,
)
service = MiniMappingAgent(client, budget)
result = await service.generate(request, local_validation_samples)
```

显式选择真实客户端时才读取：

```text
MAPPING_LLM_MODEL
MAPPING_LLM_API_KEY
MAPPING_LLM_BASE_URL（可选）
```

```python
client = LangChainMappingClient(LLMConfiguration.from_environment())
```

没有自动加载 .env、默认供应商、全局 Client 或服务启动即调用模型的行为。
凭据不进入 repr；不要将调用者自定义 Client 的异常、对象或完整报告作为公开日志。
输出报告保存 Raw 快照，必须按本地敏感数据对待。

## 验证结果

定向命令，从仓库根目录执行：

```bash
backend/.venv/bin/python -m pytest -q backend/tests/test_mini_mapping_agent.py
```

实际：55 passed in 1.48s。

回归命令：

```bash
backend/.venv/bin/python -m pytest -q \
  backend/tests/test_mini_mapping_agent.py \
  backend/tests/test_mapping_validator.py \
  backend/tests/test_schema_inspector.py \
  backend/tests/test_intelligent_mapping_runtime.py \
  backend/tests/test_intelligent_mapping_contracts.py \
  backend/tests/test_run_context.py \
  backend/tests/test_retry_policy.py \
  backend/tests/test_retry_decider.py \
  backend/tests/test_v09_retry.py \
  backend/tests/test_v10_persistence.py \
  backend/tests/test_replay.py \
  backend/tests/test_replay_timeline.py \
  backend/tests/test_business_agent_integration.py \
  backend/tests/test_v13_jobs_contract.py \
  backend/tests/test_v12_openapi.py
```

实际：476 passed, 3 warnings in 3.08s。三条均为既有 TestCase 收集提示。
另外，使用真实已安装 ChatOpenAI 成功构造 MappingProposal 的 Structured Output Runnable，
未调用 ainvoke，也未发起网络请求。客户端运行行为使用 MockModel 检查参数、消息角色、Structured Output 和用量传递。
未运行真实供应商、真实数据库、整个项目全量测试或负载测试；没有安装依赖、提交、推送或删除数据。

## 推荐审查顺序与剩余风险

按 generation_contracts.py → Fixture → generation_context.py → generation_service.py →
llm_client.py → tests 顺序阅读；重点关注披露边界、额度预留和终止规则。

- 模型质量、供应商 Structured Output 支持和真实计费未在线验证；不支持时安全失败。
- 提示注入无法仅靠提示词消除；业务 Golden 覆盖和人工审查不可省略。
- 证据说明是模型声明，机械来源检查不能证明所有业务含义。
- 不支持任意目标 Schema，仅针对原有 Harness 契约和显式 Trace Profile。
- 沿用 Stage 4 的一事件一 Span、规范 Token 输入+输出总和、未知规范时间拒绝等限制。
- 只有本次会话的内存状态与预算，没有持久化、恢复任务或全局费用池。
- 脱敏策略需要人工选择字段/标量，不能把含敏感值的白名单当作安全过滤器。

Stage 5 完成后停止，等待审查；未实现 Stage 6。
