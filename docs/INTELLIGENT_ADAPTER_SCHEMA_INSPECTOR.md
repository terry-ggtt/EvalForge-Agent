# Stage 3：Schema Inspector

## 工业问题与位置

手工查看单个 Agent 响应容易把偶然出现的字段当成固定契约；
大量 Trace 事件又会令按 events[0]/events[1] 展开的结构重复膨胀。

本阶段提供：
多份异构 JSON 样本 → 有限扫描 → 结构/频率/差异/指纹 → 脱敏摘要接口。

Inspector 不执行 Mapping，不调用 LLM，不开发 API，也不推断业务字段含义。
不改变 Stage 1/2、AgentResult/TraceEvent、Runner 或 HTTP 协议。

## 使用方式

```python
from app.adapters.intelligent.inspection_contracts import (
    InspectionLimits, SummaryOptions,
)
from app.adapters.intelligent.inspector import SchemaInspector

inspector = SchemaInspector(InspectionLimits(
    max_input_bytes=1_048_576,
    max_depth=32,
    max_nodes=100_000,
    max_samples=32,
    max_path_bytes=4096,
))
result = inspector.inspect([
    {"answer": "sample A", "events": [{"kind": "model_end", "tokens": 12}]},
    {"result": {"message": "sample B"}, "telemetry": {"spans": []}},
])
assert result.success
external_summary = inspector.summarize(result)  # 无标量值、字段名编号化
named_summary = inspector.summarize(
    result, SummaryOptions(include_field_names=True),
)  # 显式开放结构字段名，仍然不包含标量值
```

输入必须为非空的内置 list，其中每项为已经解析的 JSON 值。
字符串样本视为 string，不隐式解析 JSON 文本；不消费任意迭代器。
只接受精确内置 dict/list/str/bool/int/有限 float/null，拒绝自定义对象、
非字符串键、循环引用和不可编码 Unicode。重复但非循环的 Python 引用合法。
不修改输入；输出不保存或引用原始标量值。

## 输出模型

SchemaInspectionResult：
- success：只有整个批次完整扫描后才为 true。
- schema_fingerprint / fingerprint_version：批次结构指纹和计算版本。
- sample_count：提交的样本数。
- input_bytes / visited_nodes：成功时为完整用量；失败时为停止前已计量前缀。
- fields：每条规范路径的类型、出现次数、样本频率、null/缺失统计。
- sample_fingerprints：按输入顺序排列的单样本 shape 指纹。
- sample_variants：相同结构合并，并保留 sample_indexes/occurrences。
- differences：跨样本未观测或类型集合不同的路径。
- errors：固定错误代码/消息及可选 sample_index/path；不嵌入原始值。

单样本 shape 指纹使用 structure 包装；批次指纹使用 sample_shapes 包装，
两者命名空间不同，不应直接混作一个标识。

InspectedField 的统计语义：
- occurrences：本路径实际扫描到多少个值，重复数组元素分别计数。
- sample_count：多少份不同样本观测到该路径。
- sample_frequency = sample_count / 总样本数，不按数组长度计算。
- types：观测到的精确 JSON 类型集合，排序输出，不强制统一类型。
- nullable / null_count：是否实际见过 null，以及出现次数。
- eligible_occurrences：根为样本数；对象键为真实对象父节点次数；
  [] 为父数组的元素总数。
- missing_occurrences = eligible_occurrences - occurrences。
- unobserved_sample_indexes：未观测此路径的样本，可能是祖先缺失、null、
  类型不同或空数组，不能一律断言该叶字段缺失。
- observations：每份样本的 occurrences/types/null_count。
- empty_array_count、min/max_array_length：仅在实际数组上统计。
- element_variants：不同元素结构的去重集合、频率及样本位置。

null-only 字段保持 types=["null"]，不推断 string/integer。
日期看起来像时间的字符串仍然是 string。
bool 不当成 integer；1 和 1.0 分别是 integer 和 number。

## 数组与路径

规范路径全部使用 JSON 双引号键和 []：
$["events"][]["usage"]["prompt_tokens"]。

这是结构发现用的路径，不是可执行 Mapping JSONPath。
Stage 1/2 不支持 [] 通配符的规则保持不变。

同构元素合并路径和元素 shape，保留 occurrence count。
异构元素共享 [] 统计路径，但 element_variants 保留不同对象字段组合。
嵌套数组保留多个 [] 层级，不扁平化。
空数组没有可观测元素 schema，因此不生成虚构的 [] 叶类型。

例如：
[{"x": 1}, {"x": 2}, {}]
- x 的 occurrences=2、eligible_occurrences=3、missing_occurrences=1；
- 三个元素不会创建三个带数字下标的字段路径。

## Schema Fingerprint 的精确依据

算法版本：schema-inspector/v1，SHA-256。

1. 标量替换成结构：{"type":"string"} / {"type":"integer"} 等，不保留值。
2. 对象替换成 {"type":"object","properties":{字段名:子结构}}。
3. 数组替换成 {"type":"array","items":[不同元素结构]}；
   items 根据规范 JSON 排序和去重，忽略元素顺序/重复次数。
4. 样本结构同样去重并按规范 JSON 排序。
5. 组装：
   {"fingerprint_version":"schema-inspector/v1","sample_shapes":[...]}
6. json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=True,
   allow_nan=False)，编码为 ASCII 后计算 SHA-256。

因此以下变化不改变批次指纹：
- 对象键插入顺序；
- 样本顺序或重复同结构样本；
- 数组顺序或重复同结构元素；
- 同类型的标量内容。

以下变化改变指纹：
- 字段名、JSON 类型、嵌套层级；
- 新观测的 null、字段组合或不同元素结构；
- 空数组从未知元素结构变成观测到非空元素结构。

不能只对扁平化 paths/types 求哈希：
[{"a":1,"b":2},{"a":"x","b":"y"}]
与
[{"a":1,"b":"y"},{"a":"x","b":2}]
虽然聚合字段类型相同，但元素结构组合不同，指纹必须不同。

次数、频率、数组长度、样本数、原始值不进入指纹。
指纹代表观测结构，不是业务语义、Agent 身份或 Mapping 正确性的证明。

## 真实检查的两个异构示例

完整样本：backend/tests/fixtures/agent_schema_samples.json。

A：
answer + events，事件使用 kind/at/model/usage 或 kind/tool/args。
B：
result.message + telemetry.spans，事件使用 event/name/tokens 或
event/name/arguments/latency_ms，顶层 error=null。

单独检查：
- A：13 条路径，两个数组元素结构；
  批次指纹 43f40fb973554e90df17a540f377dbd668a974232b921c3a7aaaa05f85d4f743。
- B：16 条路径，两个数组元素结构；
  批次指纹 43249ab14339d42e93f813a16ebe70475fd2af9dd50c4e49705bfac50a051fa6。

合并检查：
- 2 份样本、28 条路径、27 条跨样本差异；
- compact UTF-8 批次 508 字节，34 个 JSON 值节点；
- $["answer"]：sample_frequency=0.5，missing_occurrences=1；
- $["events"][]["kind"]：occurrences=2，sample_frequency=0.5；
- $["telemetry"]["spans"][]["tokens"]["output"]：types=["null"]，
  nullable=true，不伪造为 0；
- 批次指纹：
  94c6dda4f5f8d429dae7027e592580fd1b52f642cdf0b0fa7142f4c7de133ea6。

## 资源限制

默认限制：
- max_input_bytes：1,048,576，整个样本 list 的紧凑 UTF-8 JSON 字节数；
- max_depth：32，样本根深度为 0，不把外层样本 list 算作深度；
- max_nodes：100,000，整个批次 JSON 值节点，包含容器但不把对象键单独算值节点；
- max_samples：32；
- max_path_bytes：4096，规范路径为 ASCII 表示，防止长父键在大量子路径中放大。

字节数逐步计量，包含引号/转义/逗号/冒号/括号，避免先对整个输入做
大字符串序列化。超长字符串有编码前的长度下界检查；宽容器有剩余节点预检。
达到任何限制即失败关闭，不输出部分 fields/sample_variants/fingerprint。
限制参数严格验证；max_depth 硬上限 64，避免任意提高后触发 Python 递归问题。

这里测量的是已经解析后的规范紧凑 JSON，不是原 HTTP 文本的空白/压缩大小。
预算不是进程级内存或 CPU 沙箱，大规模吞吐仍需单独压测。

## 脱敏摘要边界

本地 inspection 结果保留真实字段名，以便工程师定位路径；即使不保留值，
动态对象键也可能是邮箱、用户 ID 或凭证，不能直接把本地结果发给外部模型。

summarize() 是单独的默认安全出口：
- 所有原始标量值从扫描阶段就不保存；
- 默认字段名/路径转为 field_000000 等中性编号，保留 parent_id；
- 不转发原始 shape、本地 error path/message、值样例；
- 只输出结构类型、计数、schema fingerprint 和错误代码；
- 默认 max_fields=64、max_bytes=16384；
- 超出摘要预算明确截断并返回 omitted_field_count/truncated；
- 若固定摘要信封也装不下，显式抛 ValueError，不返回超限数据。

include_field_names=True 是显式的信息开放选项，不保证字段名中没有秘密。
没有启发式“只清理 password 字段”的虚假安全承诺。
默认摘要缺少字段名与枚举值的语义信息，这是隐私与映射推断能力的权衡；
后续 AI 生成所需的信息披露策略应独立设计，本阶段没有自动发送任何数据。

## 验证

Inspector 单元测试：
backend/.venv/bin/python -m pytest -q backend/tests/test_schema_inspector.py

已覆盖多样本、null/缺失、空/异构/嵌套数组、路径合并和出现频率、
字段组合、指纹不变量和独立公式验证、各类预算边界、非法 JSON/循环、
不修改输入、序列化往返、摘要脱敏及截断。
