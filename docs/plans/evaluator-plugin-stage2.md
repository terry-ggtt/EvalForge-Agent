# Evaluator Plugin Stage 2：静态 Evaluator Registry

日期：2026-10-25。范围：注册、目录查询、实例创建和现有内置实现的显式兼容；不进入执行引擎阶段。

## 1. 从现有结构出发

Stage 1 已提供 SDK Manifest、Context、MetricResult 和 async evaluate(context)，以及 Harness 的 SDKToLegacyEvaluator。现有 runtime_factory.py 仍直接构造 KeywordMatchEvaluator 等旧评测器；business_evaluators() 仍返回旧接口实例。原 app/registry 管理的是 Intelligent Adapter 的数据库发布，不是 Evaluator 目录，不能直接挪用其持久化/权限/任务机制。

本阶段新增 SDK 内的纯内存 EvaluatorRegistry，独立于业务评测器、FastAPI、数据库和 Runner。静态装配代码显式提供 Manifest 与工厂。已有 runtime_factory、默认业务指标和正式 Worker 不接入、不变更。

## 2. 核心数据流与工程取舍

```text
可信装配代码
  → register_builtin(manifest, factory) / register(manifest, factory)
  → Manifest/API 版本验证 → 重复 ID 预检 → 构造预检实例
  → 检查 async evaluate(context) 签名及完整 Manifest
  → 加锁复查 ID、声明实例身份 → 原子写入目录
                  ↓
get(id) / list() → 独立元信息快照（不调用工厂）
                  ↓
create(id) → 锁内读取工厂 → 锁外构造新实例
           → 再次协议/Manifest 验证 → 锁内拒绝已存活实例复用
           → 返回给调用方
                  ↓
外部调用方负责 evaluate；Registry 不评分、不调度、不重试
```

为什么存工厂而不是实例：实例可能持有历史、缓存、计数器或任务配置，直接复用会造成并发任务污染。工厂每次构造新的实例，弱引用身份检查再拒绝单例复用。Registry 不会复制任意插件对象，因为客户端、锁、连接等可能无法安全 deepcopy。

为何预构造：只检查工厂名称或类注解无法确认实际返回对象符合 SDK。注册调用构造器一次检查真实对象，但绝不调用 evaluate；这要求工厂廉价、无 I/O、无任务状态，昂贵资源由未来生命周期方案处理。本阶段不实现初始化调度。

为何构造在锁外：第三方构造器可能阻塞，不能持有目录锁阻止元信息查询。提交前再次检查重复 ID，保证并发注册最多一个成功；失败不会留下半条目录记录。并发输家的预检构造可能已经发生，不能把它当作事务可回滚的外部动作。

## 3. 公共接口与职责

实现：packages/evaluator-sdk/src/evalforge_evaluator_sdk/registry.py。

| 类/类型/函数 | 职责 |
| --- | --- |
| EvaluatorFactory | 同步零参数 Callable，返回 SDK BaseEvaluator |
| RegisteredEvaluator | 可 JSON 序列化的 manifest/source 元信息快照，不暴露工厂或实例 |
| EvaluatorRegistry | 每个宿主独立持有的线程安全静态目录，无全局单例 |
| register_builtin(manifest, factory) | 标记内置来源并显式注册；不导入具体内置类 |
| register(manifest, factory) | 显式注册第三方来源 |
| get(evaluator_id) | 查询元信息；不存在或 ID 非法时抛统一错误 |
| list() | 按 evaluator_id 排序返回快照 tuple，不构造实例 |
| create(evaluator_id) | 每次调用工厂，检查完整声明和实例身份，返回 SDK 实例 |
| EvaluatorRegistryError | 统一注册/查询/创建异常，包含 code 和 evaluator_id |
| _checked_id / _checked_manifest | 校验 ID 和 SDK 声明，区分 API 不兼容 |
| _construct | 调用构造器并检查实际异步签名和声明，不执行评分 |
| _check_duplicate / _claim / _register | 锁内冲突检查、弱引用身份登记、原子目录发布 |

每个 ID 只允许一个实现版本。即使版本不同、工厂相同或来自同一插件，也视为重复；没有替换、注销或静默覆盖参数。第三方覆盖内置的错误码是 builtin_override_forbidden，其他重复为 duplicate_evaluator_id。

source 只是可信装配代码声明的来源，不是安全认证。外部不可信用户不能靠该字段获得执行权限；本阶段没有插件上传 API。

## 4. 协议和版本检查

注册声明必须是有效 EvaluatorManifest；即使使用 Pydantic model_construct/model_copy 绕过验证，Registry 仍会重新验证。

api_version 当前精确匹配 SDK_API_VERSION=1.0；不做宽松降级。实现 version 不等于 API 版本，不要求和 SDK 包分发版本相同。SDK 包本次新增公共能力后升级为 0.2.0，API 仍为 1.0。

实际实例必须具备可接受一个位置参数 context 的 async evaluate 方法；旧的 evaluate(case, result)、同步方法、对象缺少方法或工厂错误返回类而非实例都被拒绝。实例的完整 Manifest 必须等于注册快照。create 每次重复检查，防止工厂后续返回另一个声明/协议。

这些检查不执行评分，因此无法静态证明返回值在每次运行时都是合法 MetricResult；Stage 1 的 validate_metric 和执行兼容层继续负责结果边界，未来执行引擎负责统一运行策略。

统一错误码：
- invalid_evaluator_id / evaluator_not_found：查找参数与目录错误。
- invalid_manifest / incompatible_api_version：非法声明与 API 不兼容。
- invalid_factory / factory_failed：非法工厂与构造异常。
- invalid_protocol / manifest_mismatch：实例协议或完整声明错配。
- duplicate_evaluator_id / builtin_override_forbidden：禁止覆盖。
- shared_evaluator_instance / instance_not_weak_referenceable：实例复用或不支持弱引用。

错误默认字符串只输出稳定 code，不拼接插件异常原文。原异常保留为 cause，内部日志仍需按应用规范处理。

## 5. 现有内置评测器如何接入

backend/app/evaluator/sdk_compat.py 增加通用 LegacyToSDKEvaluator，与 Stage 1 的 SDKToLegacyEvaluator 方向相反。它不在 Registry 中，也不依赖某个具体业务实现。

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
first = registry.create("builtin.keyword_match")
second = registry.create("builtin.keyword_match")
assert first is not second
```

第三方实现 SDK 协议后直接 registry.register(manifest, factory)，无须依赖 backend。

LegacyToSDKEvaluator 的构造器验证旧 BaseEvaluator 和输出名；外部调用 evaluate(context) 时才复制上下文、重建旧 TestCase/AgentResult、调用一次旧评测器并用 metric_from_legacy / validate_metric 转换结果。评分算法完全复用原实现。

旧契约需要明确的 expected_output、agent_output、trace_events、expected_tool_calls；任一为 None，返回 missing，不把未知列表变成 []。任何事件缺少 timestamp 同样返回 missing，禁止触发旧 TraceEvent 的当前时间默认值。已知空列表合法。非旧 TraceEvent 的异构事件不在桥中自动映射。旧数值缺失依照 Stage 1 保守转换，不伪造 not_applicable 或 score。

真实 KeywordMatchEvaluator 的显式注册、创建、SDK 调用及 SDKToLegacyEvaluator 回接均已有测试；没有批量重写现有内置类，也没有改动默认工厂。

## 6. 并发隔离的保证与限制

- 目录状态由每个 Registry 独立管理，RLock 保护发布/查询/身份登记。
- 不缓存任务实例，只存工厂。工厂在每次 create 时调用。
- WeakValueDictionary 按对象 id 追踪仍存活的输出及注册预检对象，拒绝同一实例重复交付；对象释放后不保留其状态。
- 单例工厂若保留预检实例，第一次 create 就会被拒绝。
- 普通 Python 实例支持弱引用；使用 __slots__ 的插件需提供 __weakref__。不支持时明确失败，避免用永久强引用集合造成泄漏。
- 可证明的边界是同一个 Registry 内的对象身份。不证明不同实例内部没有共享列表、类属性、模块状态或客户端，也不协调不同 Registry。
- 工厂需拥有独立可变成员和任务配置；Registry 不是深层内存隔离或进程沙箱，不执行任意对象 deepcopy。
- 生命周期关闭/异步工厂/多版本解析/参数注入/动态发现留待另行授权，不属于本阶段。

## 7. 文件清单和阅读顺序

新增：
1. packages/evaluator-sdk/src/evalforge_evaluator_sdk/registry.py：静态目录及统一异常。
2. packages/evaluator-sdk/tests/test_registry.py：注册、查找、创建、协议与并发测试。
3. docs/plans/evaluator-plugin-stage2.md：本报告。

修改：
4. packages/evaluator-sdk/src/evalforge_evaluator_sdk/__init__.py：导出 Registry 公共接口。
5. packages/evaluator-sdk/pyproject.toml：包版本 0.2.0，无新增依赖或 Entry Points。
6. packages/evaluator-sdk/README.md：静态注册示例与隔离限制。
7. backend/app/evaluator/sdk_compat.py：追加 LegacyToSDKEvaluator，已有桥保持原行为。
8. backend/tests/test_evaluator_sdk_compat.py：追加 6 项真实内置注册和未知事实保护测试。
9. AI_CHANGELOG.md：追加本阶段记录。

原 Stage 0/1 文档及其他未提交工作保留。建议阅读 README 新章节 → registry.py → test_registry.py → LegacyToSDKEvaluator → 后端新增兼容测试。

## 8. 本次实际测试和打包结果

从仓库根目录，使用现有 Python 3.12.3 环境：

```sh
backend/.venv/bin/python -m pytest -q -c packages/evaluator-sdk/pyproject.toml packages/evaluator-sdk/tests
```

结果：64 passed in 0.10s（原 SDK 28 项 + Registry 36 项）。

```sh
backend/.venv/bin/python -m pytest -q --tb=short \
  backend/tests/test_evaluator_sdk_compat.py \
  backend/tests/test_v11_comparison.py \
  backend/tests/test_v11_dataset_comparison.py \
  backend/tests/test_v11_experiment_comparison.py \
  backend/tests/test_v11_regression.py \
  backend/tests/test_v11_regression_gate.py \
  backend/tests/test_v11_experiment_runner.py \
  backend/tests/test_v12_openapi.py \
  backend/tests/test_v13_jobs_contract.py
```

结果：59 passed，1 warning in 0.60s。39 项为兼容层（原 33 + 新 6）；其余 20 项为现有相关回归。warning 是原 TestCase 被 pytest 尝试收集，不是本次新错误。

复用 Stage 1 的独立环境（只有 SDK/Pydantic/构建和测试工具），重新构建并安装 SDK 0.2.0 wheel/sdist；后端环境同步安装此 wheel，不修改其他依赖。将 SDK 两个测试文件复制到仓库外运行：64 passed in 0.13s，是同一套测试的安装验证，不重复累计。确认从 site-packages 导入 Registry、py.typed 存在，app/FastAPI/psycopg 不可导入。

构建产物在 /tmp/evalforge-evaluator-registry-stage2-d1otjeo_/dist，未发布到包仓库。

未运行全量测试、数据库或在线服务。Stage 1 记录的旧 Experiment 重复 Case 异常类型问题未在本阶段复跑或修复，不据此宣称全项目全绿。原 Runner 对错误/N/A 的计分限制也未改变。Comparison/Regression/Gate 和业务评测器文件均未修改。

Stage 2 完成后停止，不实现 Entry Points，不进入执行引擎，不 commit/push。
