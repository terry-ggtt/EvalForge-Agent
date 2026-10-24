# Intelligent Adapter Stage 4：Mapping Validator 与 Golden Tests

## 为什么需要这一层

当前离线链路为：

```text
Raw Response / Raw Trace
  → SchemaInspector：限定输入规模、确认 JSON 结构、计算结构指纹
  → MappingSpec：描述已审核的声明式映射
  → Deterministic Runtime：生成原有 AgentResult / TraceEvent，保留来源快照
  → MappingValidator
      L1：配置、输出契约和已观察字段类型
      L2：Span 父子图与时间证据
      L3：独立 Golden 期望与关键语义覆盖
  → ValidationReport：本地发布资格判定
```

Schema 相同不代表语义相同。Runtime 能执行映射，也不能证明把某个数字映射为 total_tokens 就是正确的。
因此先验证“能否执行、结构是否合法”，再验证“关系是否合理”，最后用独立期望验证“是否映射了正确含义”。

本阶段没有接入 Evaluation Runner、Registry、数据库、HTTP API 或模型调用。
release_allowed 只是当前样本和 Golden 的本地判定，不执行发布，不代表人工批准，也不证明未覆盖样本正确。

## 现有 Trace 契约与 Profile 决策

仓库的 backend/app/harness/contracts.py 中，TraceEvent 只有 type、timestamp、payload；
没有独立 Span 契约，也没有原生 span_id、parent_span_id。
因此不修改 AgentResult / TraceEvent，而用 TraceValidationProfile 明确描述 payload 内的证据位置。

默认路径均相对于映射后的 TraceEvent：

| Profile 字段 | 默认路径 | 已知值要求 |
| --- | --- | --- |
| span_id | $.payload.span_id | 非空字符串，同一 Trace 内不能重复 |
| parent_span_id | $.payload.parent_span_id | 非空字符串或 null |
| span_type | $.payload.span_type | agent / model / tool / unknown |
| start_time | $.payload.start_time | 带时区的 ISO-8601 字符串 |
| end_time | $.payload.end_time | 带时区的 ISO-8601 字符串 |
| duration_ms | $.payload.duration_ms | 非负有限数字，不接受 bool |
| usage | $.payload.usage | 对象；input_tokens/output_tokens/total_tokens 已知时必须是非负整数 |
| tool_name | $.payload.tool_name | 非空字符串 |
| arguments | $.payload.arguments | JSON 对象 |
| call_id | $.payload.call_id | 非空字符串 |

所有路径可以显式配置为不同的 payload 对象字段，但禁止重复、相互覆盖、指向 payload 外部或带数组索引。
usage 内部三个 Token 键保持规范名称；arguments 第一版只接受对象。
time_tolerance_ms 默认为 1，允许显式设置为 0～60000 的整数。

该 Profile 明确采用“一条事件是一条 Span 记录”。不会把 model_call/model_result 或 tool_call/tool_result 自动合并；
同一 Span 若以多条生命周期事件重复出现，不能直接套用这个 Profile，否则会报告重复 ID。
这类输入未来需要经明确设计的归并方案处理，本阶段没有实现归并。

不会猜测 call_id、run_id 是 span_id，也不会构造 ID、当前时间、零 Token 或缺失父节点。
payload 中未配置的供应商字段保留，但不宣称已验证其语义。

## 数据模型与入口

文件：

- backend/app/adapters/intelligent/validation_contracts.py：严格、可 JSON 序列化的配置与报告模型。
- backend/app/adapters/intelligent/validator.py：本地确定性校验流程。
- backend/tests/fixtures/mapping_validation_golden.json：独立常量期望、输入样本及故意错误的 MappingSpec。
- backend/tests/test_mapping_validator.py：离线回归测试。

核心契约：

- TraceValidationProfile：声明 Span 证据位置与时间容差。
- GoldenCheck：事件相对路径及人工期望值；只允许现有 type、timestamp、payload 范围。
- GoldenSpanExpectation：用 span_id 定位期望事件，避免并发数组顺序造成错误匹配。
- GoldenExpectation：期望 output_text、完整 Span ID 集合、逐字段检查、显式不适用语义类别。
- ValidationFinding：layer、code、message、event_index、span_id、path；严重级别由报告中的 errors/warnings/unverified 列表区分。
- ReleasePolicy：唯一可接受项为具体 warning code 白名单。
- ValidationReport：三层状态、发现项、映射结果、配置摘要、结构指纹、已验证字段计数与发布阻断原因。

调用示例（从仓库根目录，Python 导入路径应包含 backend）：

```python
import json
from pathlib import Path

from app.adapters.intelligent.validator import MappingValidator

fixture = json.loads(
    Path("backend/tests/fixtures/mapping_validation_golden.json").read_text()
)
report = MappingValidator().validate(
    fixture["spec"],
    fixture["samples"]["correct"],
    golden=fixture["golden"],
)
print(report.model_dump_json(indent=2))
assert report.release_allowed
```

validate(spec, raw_response, *, raw_trace=..., golden=None, partial_trace=False, policy=None) 支持独立 Raw Trace 根，
沿用 Runtime 的路径解释规则。省略 raw_trace 与显式传 null 不同。

Profile 和 Policy 是开发者配置，非法配置直接抛出 Pydantic ValidationError；
样本、MappingSpec 和 Golden 的校验问题进入结构化报告。
重复调用结果一致，配置和输入不会被修改，输出报告拥有独立快照。

## L1：结构和已观察值验证

1. 重新验证 MappingSpec，包括已被外部修改过的模型实例。
2. 先用 SchemaInspector 检查原始 JSON，沿用 Stage 3 默认大小、深度、节点数、路径和样本数限制。
3. 调用现有 Runtime，保留其错误、警告和完整来源记录。
4. 对完整输出重新执行 AgentResult 的严格 Pydantic 验证。
5. 对 Profile 声明的已观察字段执行显式类型、枚举、时间格式和重复 ID 检查。

False、0、"0"、0.0 不会被隐式当成同一种值。Token 不接受浮点数、字符串、bool 或负数。
未知字段不会补造，missing/null/unknown 证据也不会被强行变成合法数值。

Runtime 失败时 result=None，仍检查成功转换的事件预览，但不会将其宣称为完整映射结果。

## L2：拓扑和时间

- 所有 ID 建索引后再检查父引用，允许父 Span 在事件列表后面出现。
- 完整可观察 Trace 的不存在父引用为 error。
- 明确 Partial Trace，或者存在未知身份/未映射事件而无法证明完整时，外部父引用为 warning + unverified。
- parent_span_id=null 明确表示根；字段不存在表示未知父关系。这是显式 Profile 约定。
- 迭代遍历父指针检测自环和多节点环，不使用递归，也不依赖事件顺序。
- 自身 end_time < start_time 为确定错误。
- 兄弟 Span 重叠、事件乱序、并发执行均不报错。
- 子 Span 超出父区间、事件时间超出自身区间、duration 与区间明显不符为 warning + unverified：
  异步工作或跨时钟可能导致这些情况，因此不据此直接判定拓扑非法。
- 缺少起止时间为 unverified；声明 partial_trace=True 时增加缺失证据 warning。
- 不比较全局单调时间，不要求子 Span 串行。

Partial Trace 允许信息不足，不豁免已观察到的重复 ID、环、非法类型和反向时间。
现有 TraceEvent 的 timestamp 不能为 null，所以缺少规范事件时间仍会产生 Runtime/L1 error。
本阶段不会改公共契约或伪造时间来绕过这个限制。

## L3：Golden 语义与覆盖

Golden 文件中的 expected 是独立写入的常量，没有使用 Runtime 结果生成或回填。
这些常量仍需项目审查者确认业务含义；代码无法自动证明某个期望确实经过人工批准。

比较内容：

1. 完整 output_text，采用精确字符串比较。
2. 完整 Span ID 集合，避免只检查某条正确事件就忽略丢失或多出的事件。
3. 每条 Span 的 type 与 span_type。
4. 模型事件或包含 usage 的 Span：input_tokens、output_tokens、total_tokens 全部覆盖。
5. 工具事件或包含工具证据的 Span：tool_name、arguments、call_id 全部覆盖。
6. 已知三项 Token 同时存在时，检查 total=input+output。

JSON 比较递归且类型严格；对象键顺序无关，数组顺序仍有语义。
因此 arguments 中整数 42 与浮点数 42.0 不会被视为相等。
该版本 Token 总数采用规范输入输出总和约定；若供应商统计口径不同，映射设计必须先明确口径，不能直接套用。

遇到以下情形保留 unverified：

- 无 Golden 或 Golden 不合法。
- 关键字段未被期望检查覆盖。
- 字段 missing/null、span_type=unknown。
- Runtime 使用部分数据求和，即使数字碰巧匹配 Golden。
- Partial Trace 或 Runtime 没有观察到完整 Trace。
- 某语义类别没有出现，同时 Golden 没有显式声明 not_applicable。

parent_span_id=null 是已知根节点的特例，可被 Golden 精确验证。
其他 null 即使与期望 null 相同，也只能说明未知值被保留，不能证明语义正确。

not_applicable 支持 span_type、token_usage、tool_call；
与已观察领域矛盾的“不适用”声明会报错。
观测到空事件数组可以通过，但必须有明确空 Span 集合、正确输出和三个显式 N/A；
未配置 Trace 或缺失 Trace 不等于确认空 Trace。

三层独立报告：有环的 Trace 可能 L3 字段比较通过，但 L2 仍失败，最终依然阻断。

## 可执行发布阻断规则

任何以下条件成立即 release_allowed=False：

| 阻断码 | 条件 |
| --- | --- |
| errors_present | 存在任意 error |
| unverified_present | 存在任意 unverified |
| golden_required | 没有有效 Golden 名称，或未验证任何期望字段 |
| layers_not_passed | L1/L2/L3 任一不为 passed |
| warnings_not_accepted | 有 warning 不在具体 code 白名单中 |

默认不接受任何 warning。ReleasePolicy 只能接受指定 warning code，不会删除报告项。
error、unverified、无 Golden 或未通过的层无法通过白名单绕过。
允许 warning 的常见例子是一个明确可选、与关键语义无关的 metadata 字段被省略。
时钟不确定同时带 unverified，因此不能只接受其 warning 就发布。

这不是 Registry 的发布接口，也没有运行时自动启用映射的功能。
后续阶段如果使用该报告，应重新执行校验，不能信任外部提供的可修改报告中的布尔值。

mapping_digest 是当前完整 MappingSpec 的规范排序 JSON 的 SHA-256，用于本地配置关联；
schema_fingerprint 复用 Inspector，是原始输入样本结构指纹。
两者都不证明 Golden、Profile、Policy 或原始值的完整身份，也不是签名或全局发布版本号。

## 实际四个样例结果

正确样本：一个模型 Span（12 输入 Token、4 输出 Token、16 总 Token），两个并发工具子 Span。
tool-a 与 tool-b 的时间区间重叠，依然验证通过。

| 样例 | L1 | L2 | L3 | release_allowed | 关键发现 |
| --- | --- | --- | --- | --- | --- |
| correct | passed | passed | passed | true | 17 项期望证据通过，无发现项 |
| missing_fields | passed | unverified | unverified | false | 缺少 output_tokens、工具 arguments、父关系；partial_topology、golden_value_unavailable、golden_coverage_missing |
| bad_topology | passed | failed | passed | false | 两工具父指针互相引用，span_cycle |
| semantic_wrong | passed | passed | failed | false | 错误 Mapping 把 total_tokens 映为 20，golden_value_mismatch、token_total_inconsistent |

missing_fields 使用 partial_trace=True，已验证 15 项；
bad_topology 已验证 17 项字段，但拓扑独立失败；
semantic_wrong 已验证 16 项，另有 runtime_null_value warning，不能掩盖 Token 错误。

## 测试与边界

新增定向命令：

```bash
backend/.venv/bin/python -m pytest -q backend/tests/test_mapping_validator.py
```

实际结果：76 passed in 0.67s。

连同 Stage 1～3、RunContext、重试、持久化、Replay、业务接入、Job/OpenAPI 的回归命令：

```bash
backend/.venv/bin/python -m pytest -q \
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

实际结果：421 passed, 3 warnings in 1.61s。
三条 warning 为既有 TestCase 模型被 pytest 尝试收集的提示。
测试覆盖类型与时区、完整/Partial 父引用、重复 ID、自环/多节点环、1100 节点父链、
并发/乱序、严格 Golden 比较、不完整语义、N/A、发布规则、输入隔离、确定性、JSON 序列化往返和超限输入。
这不是整个项目的全量测试，也未运行真实数据库或在线 Agent。

## 审查顺序及未解决边界

建议按 Profile/Golden/Report 模型 → 四个 Fixture → validate 主流程 → L1 → L2 → L3 → 发布规则 → 测试的顺序阅读。

- Golden 仅证明覆盖样本，不能证明所有未来 Agent 响应；增加业务样本需要独立人工期望。
- 固定 Profile 为一事件一 Span；当前公共事件流不具备自动 Span 归并语义。
- 严格模型 Token 和工具检查可能使实际缺少证据的 Trace 长期处于 unverified；这是保留未知信息的预期行为。
- 报告包含 Runtime 原始快照，字段路径和 span_id 也可能敏感；不能直接作为对外模型输入或公开日志。
  finding 消息不回显实际/期望值，但不等于整个报告已经脱敏。
- Raw 与 Golden 复用 Inspector 资源限制；配置属于受信本地配置，不是任意上传配置的隔离沙箱。
- mapping_digest/schema_fingerprint 未覆盖整个验证证据包，未来发布流程仍需单独设计完整版本身份和审核机制。

本阶段结束，等待代码审查；未进入 Stage 5。
