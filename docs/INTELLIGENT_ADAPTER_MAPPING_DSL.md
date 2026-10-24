# Intelligent Adapter Mapping DSL v1（Stage 1）

## 所在位置与范围

Raw Agent Response / Trace → MappingSpec 配置 → 后续确定性 Runtime
→ 现有 AgentResult / TraceEvent → 现有 Evaluation Harness。

本阶段只实现配置模型、配置验证和 JSON 序列化。没有执行原始字段读取、
转换、Agent 调用、AI 生成、Registry、数据库或 API。
现有业务 HTTP 协议、AgentResult、TraceEvent、Runner 和 Replay 均未修改。

现有 datasets.mapping.FieldMapping 服务于测试集导入；新 DSL 使用独立命名空间：
app.adapters.intelligent.contracts，不替换 Dataset 模型。

## 模型与字段

| 模型 | 字段与职责 |
|---|---|
| MappingSpec | spec_version 固定为 "1.0"；name 为非空描述名；response 必需；trace 可为 null |
| ResponseMapping | fields：映射至现有 AgentResult.output_text 或 metadata |
| FieldMapping | target、operation、value_type、on_missing、on_null |
| TransformOperation | 由 op 区分的六种 Pydantic 操作模型联合 |
| TraceMapping | events_path、type_path、rules、on_unknown_event、on_missing、on_null |
| TraceEventMapping | source_type 精确匹配原始字符串事件类型；event_type 指向现有 TraceEventType；fields 描述 timestamp/payload |

name 不是 Registry 主键或发布版本；spec_version 是 DSL 语法版本。
Response 必须且只能有一个 output_text 映射，类型为 string，
on_missing=error、on_null=error，禁止凭空默认答案。
metadata/payload 整体赋值必须为 object，且不能写入 null；可选择缺失时报错或省略。
同一作用域内拒绝重复目标和父子目标同时赋值，避免写入顺序影响语义。

Trace 的 type 由规则 event_type 决定，不通过 fields 重写。
event_type 复用 TraceEventType，但禁止 agent_start、agent_end、
attempt_start、attempt_end、retry，这些事件归 Harness Runner 所有。
未知原始事件类型不能填充为一个猜测的标准类型。

## JSON 路径子集

支持：$、$.answer.text、$.events[0]、$["key.with.dots"]、$["中文"]。
方括号字符串采用 JSON 双引号及转义规则。最大长度 1024。
源路径可有非负数组下标；目标只允许对象字段路径，数组可作为完整字段值提取。

不支持：通配符、递归下降、过滤器、切片、负下标、单引号键或函数调用。
路径验证只检查语法和配置冲突，不解析样本、不访问属性或执行 Python。
$.a 与 $["a"] 视为同一个路径，不能以不同写法重复计数或覆盖。

Response 中的源路径、Trace 的 events_path 相对完整原始响应。
Trace 的 type_path 和规则内操作源路径相对单个原始事件。

## 六种操作

| op | 参数 | 后续执行时应遵守的语义 |
|---|---|---|
| extract | path | 原样提取；区分不存在和显式 null |
| rename | path | 与 extract 相同，目的字段在 FieldMapping.target 指定；不修改原始数据 |
| enum_map | path、非空 values、on_unmapped=error/null | 对字符串源值精确查表；输出只允许有限 JSON 标量或 null |
| cast | path、to=string/integer/number/boolean | 显式标量转换；转换失败报错，不补默认值 |
| coalesce | 至少两个不同 paths | 选择第一个存在且非 null 的值；false、0、空字符串均是有效值 |
| sum_if_present | 至少一个不重复的 paths | 对存在且非 null 的数值求和；拒绝布尔值及非数值 |

rename 在 v1 中明确作为 extract 的同义操作，保留配置可读性。
enum_map 的输入缺失/null 分别保持缺失/null，不变成字符串 "null" 参与查表。
on_unmapped 仅处理存在但未命中的字符串，非字符串源值为类型错误。
cast 不允许把容器随意转成字符串、不允许整数转换截断小数；
布尔转换只允许布尔值或精确的 "true"/"false" 字符串，不采用 Python truthiness。
数值转换的其他边界必须在 Runtime 阶段明确并补测试。

coalesce 全部不存在/null、sum_if_present 没有有效贡献项时，结果为 MISSING，
之后应用 on_missing，不能自动返回 0 或空字符串。
sum_if_present 的部分求和并不代表完整 token 用量，后续 Runtime 必须保留贡献项和覆盖诊断。
存在但格式错误的输入不能伪装成缺失值跳过。

没有时间转换操作。datetime 声明期望带明确 UTC offset 的 ISO-8601 时间；
epoch 单位识别、时区猜测均不属于第一版。

## 缺失、null、unknown

value_type 支持 string/integer/number/boolean/object/array/datetime/unknown。
它表示操作输出的预期类型；unknown 表示类型不作断言，不是写入字符串 "unknown"，
更不是推断原始数据中没有的信息。

| 情况 | 策略 | 语义 |
|---|---|---|
| 字段不存在 | on_missing=error（默认） | 映射失败 |
| 字段不存在 | on_missing=omit | 不写入目标，保留缺失诊断 |
| 字段不存在 | on_missing=null | 写入 JSON null |
| 显式 null | on_null=error | 映射失败 |
| 显式 null | on_null=preserve（默认） | 保留 JSON null |
| 显式 null | on_null=omit | 不写入目标 |

转换错误固定报错，不通过上述策略吞掉。
配置没有 default、expression、code、module 或任意 Python 扩展钩子。

Trace 数组缺失/null 分别支持 error/omit；omit 不意味着“观测到空 Trace”。
trace=null 表示没有配置 Trace 映射，也不证明 Agent 没有事件。
原始事件类型未知、缺失、null 或非字符串时，on_unknown_event 支持：
preserve_raw（默认，保留原始证据且不制造标准事件）或 error。
这些是对未来 Runtime 的要求，本阶段没有实现原始证据存储。

## 与现有时间契约的边界

Trace 规则省略 timestamp 表示原始时间未知；
显式配置 timestamp 时可以选择 on_missing=null。
现有 TraceEvent.timestamp 仍不可为 null，且默认填当前时间。
因此配置通过不代表已经能直接转换成当前 TraceEvent；
在完成 Stage 0 提出的契约/Timeline 兼容设计之前，不得用当前时间补齐源事件时间。
本阶段没有为绕过该冲突而修改现有契约。

## 具体异构示例

完整原始响应和 MappingSpec：
backend/tests/fixtures/intelligent_mapping_v1.json。

该示例包含：
- answer.text / fallback_answer → coalesce → output_text；
- llm.finished → model_result；
- at 原样映射时间，engine 重命名，prompt 显式转整数；
- prompt + completion 通过 sum_if_present 声明总数；
- finish 使用 enum_map 转换为 completed/truncated；
- tool.started → tool_call，映射 name/params/id；
- 工具事件没有源时间，规则不制造时间；
- vendor.debug 不存在匹配规则，要求保留 Raw，不创建猜测事件。

单元测试仅验证该配置和 JSON 往返，不生成或断言 Runtime 的转换结果。

## 序列化与验证

MappingSpec.model_validate(data) / MappingSpec.model_validate_json(text)
用于验证。model_dump(mode="json") / model_dump_json() 用于保存。
model_json_schema() 可生成带 discriminator 的 JSON Schema。

模型统一采用 strict=True、extra="forbid"、allow_inf_nan=False。
错误参数类型、未知操作、未知配置字段、NaN/Infinity、非法路径等
抛出 Pydantic ValidationError。不引入额外依赖。

从仓库根目录（WSL）执行：

    backend/.venv/bin/python -m pytest -q backend/tests/test_intelligent_mapping_contracts.py
