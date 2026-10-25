# EvalForge Evaluator SDK

可独立安装的评测器协议包。仅依赖 Python 3.11+ 和 Pydantic 2；不导入 Harness、Runner、FastAPI、数据库或模型服务。

从仓库根目录安装：

```sh
python -m pip install ./packages/evaluator-sdk
```

## 实现一个评测器

```python
from evalforge_evaluator_sdk import (
    EvaluationContext, EvaluatorManifest, MetricResult,
)

class ExactMatchEvaluator:
    manifest = EvaluatorManifest(
        evaluator_id="example.exact_match",
        display_name="Exact match",
        version="0.1.0",
        description="Compare the explicit reference and answer.",
        direction="higher_is_better",
    )

    async def evaluate(self, context: EvaluationContext) -> MetricResult:
        if context.expected_output is None or context.agent_output is None:
            return MetricResult(
                metric_name="exact_match", status="missing",
                reason="Reference or agent output is unavailable.",
            )
        return MetricResult(
            metric_name="exact_match", status="success",
            score=float(context.agent_output == context.expected_output),
        )
```

采用结构化 Protocol，无须继承项目内部类。api_version 当前固定为 "1.0"；version 是评测器实现版本，不是自动加载地址。

## 数值与状态

- score：有限的 0～1 质量分，始终越高越好；不自动从 value 推导。
- value：原始有限数值，保留整数精度；unit 表示单位。direction 描述此原始值的好坏方向。
- 只有 score 的评测器必须声明 higher_is_better。lower_is_better 可返回原始 value，并另行提供明确计算的质量 score。
- success 必须有 score 或 value；0 是实际观测值。
- missing：必要证据缺失；not_applicable：明确不适用；unverified：证据不足以确认。三者必须给 reason。
- error 必须给 EvaluationError（code/message/retryable/details）。
- 所有非成功状态禁止携带 score/value；部分或未确认观测可以放 metadata。
- status 必须显式提供。字符串数值、bool、NaN、Infinity、未知字段/状态和非 JSON metadata 均被拒绝。

EvaluationContext 区分 None（未知）和空字符串/数组（已提供但为空）。trace_events 是 JSON 快照，保留已有 TraceEvent 的序列化结构和扩展字段，不创建第二套 TraceEvent 类，也不补时间戳。身份字段仅接受调用方已知的 run_id、attempt_id、job_id、experiment_id；均可为空。

模型构造时深拷贝，顶层冻结；嵌套 JSON 容器仍可修改。跨边界调用 validate_metric(manifest, result) 会重新验证并复制，不应将冻结解释为沙箱或深层不可变。

## Harness 兼容边界

旧 API 不变。Harness 侧 app.evaluator.sdk_compat 提供 context_from_legacy、metric_to_legacy、metric_from_legacy 和显式 SDKToLegacyEvaluator 适配器；本包不反向依赖这些模块。

SDK 状态、错误、Manifest 保存在旧 MetricResult.details 的 _evalforge_evaluator_sdk 命名空间。数据库和 API 仍使用原 name/value/unit/score/details。该命名空间是格式完整性检查，不是签名或授权证明。

普通 DTO 转换只保存语义。执行适配器对 missing/unverified/error 抛出结构化异常，不将其伪装成成功。旧 Runner 如何处理异常、全部不适用指标如何聚合、Comparison/Gate 如何解释方向，本阶段保持原样；不能据此宣称旧 Runner 已支持新的失败隔离。

## 测试

```sh
python -m pip install "./packages/evaluator-sdk[test]"
python -m pytest -c packages/evaluator-sdk/pyproject.toml packages/evaluator-sdk/tests
```

本包提供静态注册和受控 Entry Points 加载，不提供执行引擎或重试调度。详见下文。


## 静态 Evaluator Registry（0.2.0）

API 版本仍为 1.0；新增显式目录和工厂，不改变 Stage 1 的输入/结果语义。

```python
from evalforge_evaluator_sdk import EvaluatorRegistry

registry = EvaluatorRegistry()
# 复用上文 ExactMatchEvaluator；传入的是构造函数，不是实例。
registry.register_builtin(ExactMatchEvaluator.manifest, ExactMatchEvaluator)
# 第三方也显式注册：registry.register(plugin_manifest, plugin_factory)
declaration = registry.get("example.exact_match")
catalogue = registry.list()  # 按 evaluator_id 排序的元信息快照
first = registry.create("example.exact_match")
second = registry.create("example.exact_match")
assert first is not second
```

register_builtin / register 均拒绝任何重复 ID，没有 replace/override 参数。source 是可信装配代码的来源声明，不是权限认证。每个 ID 在一个 Registry 中仅有一个实现版本，版本共存/自动解析尚未实现。

注册时调用工厂一次进行协议预检，不调用 evaluate；因此工厂必须是廉价、无 I/O 的同步零参数构造器。get/list 不调用工厂。create 每次重新构造，核验完整 Manifest 和 async evaluate(context) 签名，然后返回实例，评分由外部调用方负责。构造函数本身是受信 Python 代码，Registry 不是沙箱。

注册、查询、创建统一抛 EvaluatorRegistryError，可读取 code 和 evaluator_id；包括重复/内置覆盖、未知 ID、无效工厂/协议、API 版本不兼容、声明错配及共享实例等错误。

Registry 不缓存可复用评测器实例；使用弱引用跟踪尚存活的返回对象和注册预检对象，拒绝单例工厂把同一对象交给多个任务。普通 Python 类默认支持弱引用；使用 __slots__ 时需提供 __weakref__（dataclass 可用 weakref_slot=True）。无法弱引用会明确拒绝，不使用无限增长的强引用缓存。

每个工厂负责创建独立的可变成员。Registry 无法证明不同实例内部是否共享列表、模块全局变量或客户端；工厂不应捕获任务可变状态，不能把此机制当成深层内存隔离。构造代码在锁外运行；目录插入和实例身份检查在锁内完成。

现有旧内置类的 evaluate(case, result) 不直接满足 SDK 协议。Harness 的通用 LegacyToSDKEvaluator 可显式适配，Registry 无须了解任何业务类：

```python
from app.evaluator.keyword import KeywordMatchEvaluator
from app.evaluator.sdk_compat import LegacyToSDKEvaluator
from evalforge_evaluator_sdk import EvaluatorManifest, EvaluatorRegistry

manifest = EvaluatorManifest(
    evaluator_id="builtin.keyword_match", display_name="Keyword match",
    version="1.0.0", description="Existing keyword evaluator.",
    direction="higher_is_better",
)
registry = EvaluatorRegistry()
registry.register_builtin(
    manifest, lambda: LegacyToSDKEvaluator(KeywordMatchEvaluator(), manifest=manifest),
)
```

LegacyToSDKEvaluator 只在外部实际调用 evaluate 时执行旧评分。旧契约无法表达未知的引用、输出、Trace 列表、工具期望或时间戳，因此缺少这些事实时返回 missing，不能用空值或当前时刻代替。它只接受已归一化、符合旧 TraceEvent 的事件，不负责异构 Trace 映射。默认 runtime_factory 没有接入 Registry，旧行为不变。


## Entry Points Plugin Loader（0.3.0）

入口组固定为 `evalforge.evaluators`。安装包的 Entry Point 名必须等于 Manifest.evaluator_id；
导出对象是带公共 `manifest` 的同步零参数 Evaluator 类/工厂。可安装示例见仓库
`examples/evaluator-plugin`。Registry 本身仍只管理静态注册，不自行扫描或导入模块。

```python
from evalforge_evaluator_sdk import (
    AllowedEvaluatorPlugin, EvaluatorPluginConfig, EvaluatorPluginLoader, EvaluatorRegistry,
)

registry = EvaluatorRegistry()
loader = EvaluatorPluginLoader(registry, config=EvaluatorPluginConfig(allowlist=(
    AllowedEvaluatorPlugin(
        evaluator_id="example.exact_match",
        distribution="evalforge-example-evaluator",
        distribution_version="0.1.0",
    ),
)))
discovery = loader.discover()
# 依次调用，亦可 load_selected(("example.exact_match",))；不加载其他 ID。
loaded = loader.load("example.exact_match")
registered = loader.register("example.exact_match")
if registered.status == "registered":
    evaluator = registry.create("example.exact_match")
```

三个阶段：
1. discover 用标准库 importlib.metadata.entry_points(group="evalforge.evaluators")，读取安装元数据，不导入插件。重复入口名全部拒绝；缺失来源包身份明确失败。
2. load(id) 只对服务器允许的 ID + 来源包 + 可选包版本调用 EntryPoint.load()，核对导出对象的 Manifest/API 和 ID；此时不注册、不构造评测器。
3. register(id) 复用 EvaluatorRegistry.register，检查构造出的 SDK 异步协议、Manifest、重复 ID 和实例新鲜性。随后 registry.create(id) 创建任务实例，评分仍由宿主另行调用。

默认允许清单为空。包名比较忽略大小写并归一化 - _ .；版本若配置则精确匹配。
同名入口即使来自一个未允许包，也会阻断该 ID 的全部入口，不能依赖扫描顺序选赢家。
已有 Registry 项无论内置/第三方均不可覆盖。导入失败不会清空或重置 Registry。

report() 返回可 JSON 序列化的来源包/包版本、Manifest 实现版本、状态、错误阶段/错误码/异常类型。
任意插件异常原文不复制到报告。缺失依赖、导入异常、协议错误分别记录；
失败在当前 Loader 中为终态，不无限重试。重复成功调用幂等。
load_selected 对合法 ID 的单插件失败继续处理其他选择；非法输入/调用顺序有独立 EvaluatorPluginLoaderError。

backend app.config.get_evaluator_plugin_config() 解析服务端环境变量
EVALFORGE_EVALUATOR_PLUGINS（JSON allowlist），不读取请求参数。
Harness Stage 4 在 API/Worker 启动时建立目录，显式选择才启用动态执行；SDK 本身不启动这些服务。
策略中不允许 import_path、安装命令、数据库或凭据字段。

Loader 是单启动线程顺序使用的进程内对象，不是热更新管理器。安装、更新、卸载插件或修改策略后，
应在构建/管理员部署流程完成安装，并重启所有使用插件的服务/Worker；
同一 Loader 保留发现快照，Python 缓存已导入模块，新建 Loader 也不能保证热更新。

不存在请求触发 pip install 或按用户字符串 import_module 的逻辑。插件只接收 SDK 上下文，
Loader/Registry 不向其注入 DB 连接或服务密钥。但 EntryPoint.load() 会运行第三方 Python，
其权限等于宿主进程，无法阻止其自行访问环境、网络或文件；允许清单不是沙箱，也不是签名校验。
只允许经审核的受信包，生产应锁定构建产物并使各 Worker 安装环境一致。


## Harness 动态执行（Stage 4）

Harness 现有 POST /experiments/run 与 POST /evaluation-jobs 支持可选 evaluators：
[{"evaluator_id": "example.exact_match", "config": {}, "timeout_seconds": 30}]。
GET /evaluators 返回当前服务目录中的声明及配置 JSON Schema。
不传该字段保留原内置评测流程；传 [] 会验证失败。每个任务最多选择 16 个不同 ID，
单指标超时范围为 0 < timeout_seconds <= 300 秒。

配置由 Harness 校验：无 config_model 的插件只接受空对象。
需要配置时，类上声明 Pydantic config_model，且其 model_config.extra 必须为 forbid；
Harness 使用 strict=True 验证，传入配置与默认值的 JSON 快照，不向构造器传宿主对象。

```python
from pydantic import BaseModel, ConfigDict, Field

class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")
    threshold: float = Field(default=0.8, ge=0, le=1)

# 在插件类中声明：config_model = Options
# evaluate 从 context.evaluator_config["threshold"] 读取已验证值。
```

动态执行每 Case/每指标创建新实例，异常/超时转为独立 error 指标，取消向上传播。
成功指标不因其他失败而丢失；missing/unverified/error 使 Case 质量分为 null、
failure_kind=evaluation，同时保留全部指标。纯 value 或明确 N/A 不被伪造成 0 分。
SDKToLegacyEvaluator 的旧异常桥仍保持 Stage 1 行为；新模式通过 Harness 的
EvaluatorExecution 处理状态，两者不能混为一谈。

任务计划在 Job Payload JSONB 固定，Worker 校验声明、来源包版本、配置 Schema 和配置，
恢复时校验 Checkpoint Run 的计划摘要；不一致即失败，不回退默认插件。
RunRecord.result.metrics 与原查询 API 保持原契约，扩展状态在 details 中。

完整数据流、文件清单、测试及限制见仓库 docs/plans/evaluator-plugin-stage4.md。


## Harness Regression Gate（Stage 5）

显式 SDK 指标按 metric_name 和稳定 Case ID 进入原 Comparison/Gate。
score 始终越高越好，value 使用 Manifest.direction。不同执行计划/版本/配置拒绝比较。
metadata.metric_version 可声明独立指标版本，缺省 Manifest.version；
metadata.statistical_scope 可声明固定口径（如匹配规则、统计总体），未提供保留 null。
不要把每 Case 的随机值、证据列表放进统计口径，否则口径不同会拒绝聚合。

MetricGateRule 可省略 operator，用非负 threshold 表示最大允许退化；
score_delta_mean/value_delta_mean 用原单位，relative_score_delta/relative_value_delta 用比例。
旧显式 gte/lte 及有符号阈值继续支持；SDK 方向冲突不可评估。
缺失观测、空交集、零相对基准不允许发布 PASS。
完整实现、阈值与统计语义见 docs/plans/evaluator-plugin-stage5.md。
