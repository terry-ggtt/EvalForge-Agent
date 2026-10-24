# Stage 2：Deterministic Mapping Runtime

## 系统位置与边界

Raw Response / Raw Trace + MappingSpec
→ map_agent_result（纯函数）
→ MappingResult
→ 现有 AgentResult / TraceEvent（仅完整无错误时）。

本阶段没有接入 Evaluation Runner、HTTP Adapter、LLM、Registry、数据库或 API。
不调用时钟、随机数或环境变量；不执行 eval/exec、不动态导入配置代码。

## API 与最小示例

```python
from app.adapters.intelligent.runtime import map_agent_result

spec = {
    "name": "example",
    "response": {"fields": [{
        "target": "$.output_text",
        "operation": {"op": "extract", "path": "$.answer"},
        "value_type": "string",
        "on_null": "error",
    }]},
    "trace": {
        "events_path": "$.events",
        "type_path": "$.kind",
        "rules": [{
            "source_type": "llm.finished",
            "event_type": "model_result",
            "fields": [
                {
                    "target": "$.timestamp",
                    "operation": {"op": "extract", "path": "$.at"},
                    "value_type": "datetime",
                },
                {
                    "target": "$.payload.model",
                    "operation": {"op": "rename", "path": "$.engine"},
                    "value_type": "string",
                    "on_missing": "null",
                },
            ],
        }],
    },
}
raw = {
    "answer": "已找到说明",
    "events": [{
        "kind": "llm.finished",
        "at": "2026-10-20T12:00:00+08:00",
        "engine": "vendor-model",
    }],
}
report = map_agent_result(raw, spec)
assert report.success
assert report.result.trace[0].type == "model_result"
```

raw_response 必须是已经解析的 JSON 值；JSON 文本不会被隐式解析。
spec 可为 Stage 1 MappingSpec 或普通配置字典。即使传入模型也重新验证，
防止配置对象构造后被修改而绕过检查。

默认从 raw_response 按 trace.events_path 读取事件。
如果提供 raw_trace，则 events_path 相对该独立根：
传入事件列表时，配置 events_path="$"。
省略 raw_trace 与明确 raw_trace=None 不同；不猜测根位置、不自动扁平化数组。

## 路径解析及限制

复用 Stage 1 _path_tokens，不另写表达式引擎。
$.groups[1][0].text → ("groups", 1, 0, "text")。
只做精确 dict 键或 list 非负下标访问；不使用 getattr。

支持点字段、JSON 双引号字段和固定非负数组下标，路径长度上限 1024。
禁止通配符、递归下降、过滤器、切片、负数下标和函数调用。
不存在的键/越界下标为 MISSING；
中间节点为 null 是 null_parent；容器种类错误是 type_error。
后两种错误不能被 optional/coalesce 当作缺失掩盖。
目标继续限制为对象路径，数组可作为完整值复制；目标路径最多 100 层字段，超限返回 mapping_limit。

输入只允许精确的内置 JSON 类型、字符串键和有限数值。
拒绝 tuple、datetime、任意 Python 对象、循环引用和超过 100 层的嵌套。
输入验证时复制树，每次目标赋值再次复制值，所有修改只发生在本次调用拥有的对象上。
JSON 边界/配置错误会提前返回；字段与事件阶段才收集独立错误。

## 执行顺序

1. 验证并复制配置；重新构造 MappingSpec。
2. 验证并复制 Raw Response，以及显式提供的 Raw Trace。
3. 按 response.fields 顺序执行每条规则。
4. 按源数组顺序处理 Trace，每个事件精确匹配一条类型规则。
5. 每条字段依次进行：路径读取 → 单个声明式操作 → missing/null 策略
   → value_type 精确断言 → 复制写入新目标。
6. 构造时间明确、完整合法的现有 TraceEvent。
7. 无任何错误时构造现有 AgentResult；否则 result=None。

每个 FieldMapping 只有一个 operation，不是隐式操作流水线。
每条规则都读取原始快照，不读取先前写出的目标。
例如先把原始 "12" cast 后写入 metadata，不会令后面的
sum_if_present 自动把原始 "12" 当作数字。求和直接拒绝数值字符串。

## 操作语义与类型保护

- extract / rename：保留 JSON 类型；rename 不删除源字段。
- enum_map：源值必须为字符串；精确匹配，不将 1/true/null 字符串化。
  缺失和 null 先保持原状态；未命中的字符串按 on_unmapped 处理。
- cast/string：接受字符串、整数、有限浮点和布尔值；布尔值明确输出
  "true"/"false"；容器不随意 stringify。
- cast/integer：接受 int、无小数部分的有限 float，以及符合
  -?(0|[1-9][0-9]*) 的字符串；拒绝 bool、空白、+号、前导零和小数截断。
- cast/number：接受 int/float，或 JSON 数字语法的字符串；
  int 不先转 float，避免额外精度丢失；溢出/Infinity 报错。
- cast/boolean：仅 bool 或精确字符串 "true"/"false"；不采用 truthiness。
- coalesce：按配置短路，选首个存在且非 null 的值；保留 0、false、""。
- sum_if_present：按路径顺序加有限数值，不接受 bool/字符串；
  缺失/null 不贡献；全无贡献得到 MISSING；部分贡献发出 partial_sum。
  字段记录及警告保留 contributing_paths、missing_paths、null_paths。
- value_type：除显式 cast 外不转换类型；unknown 只跳过类型断言，
  仍受 JSON 输入验证约束。integer 不接受 bool，number 不接受 bool。

missing 与 null 策略分别执行：on_missing=null 生成的 null 不会再被
on_null=error 二次处理。真正的源 null 或 enum 输出 null 才应用 on_null。
错误转换固定报错，不被 omit/null 策略吞掉。

## 时间兼容：不补造 TraceEvent

现有 TraceEvent.timestamp 不能为 null，默认是当前时间。
Runtime 始终明确传入源时间，绝不调用该默认值。

时间要求带秒、最多 6 位小数、明确 Z 或 ±HH:MM 的 ISO-8601 字符串；
验证日历日期及 offset 范围；保留源 offset，不猜测单位或时区。
缺失时间、显式 null 或未配置时间映射，报告 unknown_timestamp 并保留 Raw；
不生成该标准事件，也不使用 model_construct 绕过契约。

因此 Stage 1 原始夹具中：
- 模型事件成功，模型名 vendor-model，input_tokens=12，total_tokens=16；
- 无时间的工具事件失败，Raw 仍在；
- vendor.debug 作为未知事件保留 Raw；
- 整体 success=False/result=None，成功事件可在 events 中检查。
这是现有公共契约的真实兼容边界，本阶段没有修改它。

## 失败策略及结果结构

单字段失败不会阻止其他独立字段/事件的诊断；
该事件任一字段失败则不生成该 TraceEvent。
任何 error 都阻止完整 AgentResult，避免半成品被当作正式评测输入。
显式允许的 omit/null、枚举 null、未知事件 preserve_raw 等为 warning。

MappingResult：
- success / result：完整转换状态和现有 AgentResult，错误时为 False/None。
- errors / warnings：MappingIssue，包含稳定 code、message、source_root、
  source_paths、target、event_index 和 JSON details。
- fields：FieldMappingRecord，记录目标、候选源、实际贡献源与赋值状态。
- events：EventMappingRecord，含原始事件的独立快照、原始数组 index、
  source_root、RFC 6901 raw_pointer、状态和可选现有 TraceEvent。
- trace_status：not_configured/missing/null/mapped/partial/failed。
  mapped 仅表示源事件覆盖，不证明所有工具/usage 字段均已观测完整。

事件关联示例：source_root=response、raw_pointer=/telemetry/events/1、
event_index=1。JSON Pointer 对 / 和 ~ 转义。
字段路径在事件记录中以该事件为根；通过 event_index 连接原始位置。
不按时间排序、不去重相同事件、不生成调用 ID。
原生 call_id 由显式 Mapping 写入；配置与原生 metadata 不被诊断信息覆盖。

preserve_raw 只在返回对象保留内存快照，不代表已经写入数据库。
错误消息不包含原始字段值；原始快照本身可能包含业务敏感信息，调用方应按需展示。
独立调用之间没有共享可变状态；相同输入和配置在同一版本下得到相同输出。

## 已覆盖的测试与使用边界

测试包括六种操作、类型严格性、缺失/null/错误分类、嵌套数组、
空/缺失/null 事件数组、未知事件和枚举、缺失 Token/部分求和、
时间缺失/非法 offset、独立 Raw Trace、原始关联、结果序列化、
重复事件、输入与配置不变、输出不反向修改输入、修改过的配置重新验证、
循环/非 JSON 输入以及重复运行确定性。

本模块未安装为 Harness Adapter；调用方不能绕过 MappingResult.errors，
也不能把 partial_sum、unknown_event_type、missing_trace 等警告解释成证据完整。
吞吐、总输入字节数及大事件量限制未做生产压测；已设置 JSON 输入深度和目标字段层数限制。
后续接入需要另外明确证据质量门槛；本阶段到此停止。
