# Evaluator Plugin Stage 1：独立 SDK 与兼容层

日期：2026-10-25。只实现 SDK 和显式兼容层，不进入执行引擎阶段。

## 1. 工程问题与边界

当前链路为 AgentAdapter → HarnessRunner → 旧 BaseEvaluator.evaluate(case, result) → 旧 MetricResult → Run JSONB / API → Comparison / Regression / Gate。

原 BaseEvaluator 和 MetricResult 均位于 backend/app，外部评测器如果直接依赖它们，就需要安装整个后端代码。原 MetricResult 也没有统一的缺失、错误和未验证状态。仅增加 Python 抽象方法无法解决跨包依赖与结果语义问题。

因此增加独立协议包，把文本、Trace 的 JSON 快照和配置作为输入，把显式状态的结果作为输出。Harness 一侧负责转接现有契约。独立包不反向导入 Harness，不自行调用 Agent，不创建任务，不连接数据库。

Stage 0 提议先实现目录和配置契约；本次用户明确将 Stage 1 定义为独立 SDK，因而以本次范围为准，不提前创建 Registry/Engine/Entry Points，也不改写原 Stage 0 审计结论。

## 2. 实际数据流

```text
外部评测器
  imports evalforge_evaluator_sdk
  manifest + async evaluate(EvaluationContext) → SDK MetricResult
                 ↑                                    ↓
Harness 显式 SDKToLegacyEvaluator
  context_from_legacy(case, agent_result, config)  validate_metric
                                                  metric_to_legacy
                                                       ↓
                              旧 name/value/unit/score/details DTO
                                                       ↓
                  原 HarnessRunner / Run Store / API（实现不变）
```

适配器没有自动注册。旧内置评测器继续直接执行 evaluate(case, result)，不会导入本 SDK。只有调用方主动构造 SDKToLegacyEvaluator 才使用新协议。

兼容层可直接显式测试，但正式工厂、同步入口、Worker 尚未选择它。外部插件身份/版本不代表已冻结 Job 配置；本阶段没有解决任务版本绑定。

## 3. 公共契约和职责

### EvaluatorManifest

位于 packages/evaluator-sdk/src/evalforge_evaluator_sdk/models.py。

| 字段 | 含义 |
| --- | --- |
| evaluator_id | 稳定评测器身份；与单个 metric_name 分离 |
| display_name | 展示名称 |
| version | 非空实现版本字符串，不执行包查找或动态加载 |
| api_version | 当前只接受 1.0，缺省为 1.0 |
| description | 非空说明 |
| direction | 原始 value 的方向：higher_is_better / lower_is_better |

版本字符串暂不强制 SemVer，避免添加解析依赖。没有版本解析或兼容降级。未知 API 版本明确验证失败。

### EvaluationContext

同一文件。input_text 必填，其余未知事实允许为空：

- case_id、run_id、attempt_id、job_id、experiment_id：已知身份，不自动生成。
- expected_output、agent_output：None 是未知，空字符串是实际空文本。
- trace_events：None 是未提供，[] 是已提供但无事件；使用 JSON 对象列表。
- evaluator_config：仅供评测器消费的 JSON 配置。
- expected_tool_calls：保留已有用例的工具期望。
- case_metadata、agent_metadata：显式快照，保留现有标签和 Agent 证据。

不创建 SDK TraceEvent 或 AgentResult 平行领域模型。Trace 的正式定义仍是 backend/app/harness/contracts.py 中的 TraceEvent；跨包只传已有序列化表示，因而不会补造 timestamp 或绑定后端类型。

构造时深拷贝，防止评测器修改调用方输入。顶层 frozen，嵌套列表/字典仍可修改；每次转接构造新上下文，并重新验证输出。它提供数据隔离，不是进程隔离或安全沙箱。

### BaseEvaluator

位于 packages/evaluator-sdk/src/evalforge_evaluator_sdk/base.py。

结构化 Protocol 要求 manifest 和 async evaluate(context) -> MetricResult；实现类无须继承。每次调用返回一个指标，不设计多指标依赖图。

runtime_checkable 只做属性存在性检查，不证明实现异步、纯净或安全。兼容层还检查实际返回模型、指标名和调用前后的 Manifest。同步实现返回不可 await 对象时被转为明确的边界异常。

### MetricResult / EvaluationError / validate_metric

同 models.py。所有字段禁止额外键，数值不接受 bool、字符串、NaN 或 Infinity。metadata/error.details 仅接受 JSON 值。

| 字段 | 语义 |
| --- | --- |
| metric_name | 指标输出名，继续匹配旧 name；不强制等于 evaluator_id |
| score | 0～1 归一化质量分，始终越高越好，可为空 |
| value | 原始有限数字，保留整数类型和精度，可为空 |
| unit | 原始测量单位，可为空 |
| status | 必填显式状态，见下表 |
| metadata | JSON 证据与说明 |
| reason | missing / not_applicable / unverified 的必填说明 |
| error | error 状态的必填 EvaluationError |

例如 latency 的 value=1200、unit=ms、direction=lower_is_better 只表示测量结果。SDK 不将其自动转成 score=1/1200。若评测器另有明确质量曲线，可同时给 score=0.8；方向依然描述原始延迟。

只有 score 的评测器必须声明 higher_is_better，避免出现“score 越低越好”的冲突；validate_metric 在输出边界检查这一组合约束。

| status | 必须有的内容 | 数值 |
| --- | --- | --- |
| success | score 或 value 至少一个 | 允许真实 0 |
| missing | reason，说明缺什么 | 均为 None |
| not_applicable | reason，说明为何不适用 | 均为 None |
| unverified | reason，说明证据不足 | 均为 None |
| error | EvaluationError(code, message, retryable, details) | 均为 None |

不成功时若要保留部分观测，应放 metadata，不混进可供聚合的数值。retryable 只是声明，不触发重试。未知状态和矛盾组合直接拒绝。

## 4. 兼容层

文件：backend/app/evaluator/sdk_compat.py。这个文件允许依赖旧契约，SDK 包不允许反向依赖它。

| 类/函数 | 职责 |
| --- | --- |
| context_from_legacy | 序列化旧 TestCase / AgentResult，复制 Trace、工具期望和配置；仅传已知运行身份，拒绝冲突的 run_id |
| metric_to_legacy | 验证 SDK 结果与方向，转换为原 MetricResult，保留所有状态和 Manifest |
| metric_from_legacy | 验证带 SDK 扩展的旧 DTO 并精确恢复；普通旧结果采用保守解释 |
| SDKToLegacyEvaluator | 实现旧 BaseEvaluator 接口，单次调用 SDK；检查 Manifest、返回类型和输出名 |
| SDKCompatibilityError | 稳定错误 code；默认异常文本不直接展示插件错误正文 |
| SDKResultUnavailable | missing/unverified/error 的边界异常，metric 属性保留完整结构化结果 |
| _Envelope / _legacy_details | 私有版本化存储格式和旧 details 兼容标记 |

原 MetricResult 的 name/value/unit/score/details 不变。SDK Manifest 和完整结果保存在 details._evalforge_evaluator_sdk，format_version=1.0；也将原 metadata 复制到外层 details，便于现有读者读取。非成功结果增加旧读者使用的 status/reason/quality_score_unverified 标记；原始 SDK metadata 始终完整保留在扩展内部。

该扩展可以按现有 JSONB 链路序列化，无须迁移。SDK metadata 不能使用保留命名空间。逆向转换检查扩展与外层 DTO 一致性，拒绝错配、额外外层修改、未知版本或调用方覆写状态。这只是结构一致性检查，不提供签名或鉴权。

对于没有扩展的历史结果：
- 有数值且无冲突状态时可转换为 success。
- 没有数值且未说明适用性时转为 unverified，不能凭空认定 not_applicable。
- 已有 quality_score_unverified 会保留为未验证。
- error 必须提供结构化错误，不能猜测。
- 越界 score 或数值与状态矛盾时拒绝，不能悄悄裁剪或丢弃数值。

转换不会修改原 DTO，也不重命名指标、不转换单位、不反转原始值。

## 5. 兼容性结论与明确限制

| 范围 | 本阶段行为 |
| --- | --- |
| 旧 BaseEvaluator / 内置实现 | 文件和接口保持原样，不强制所有旧类立即声明 Manifest |
| 旧 AgentResult / TraceEvent / RunContext | 保持原样 |
| 旧 MetricResult / API | 字段保持原样，SDK 信息只在 details 扩展 |
| Comparison / Regression / Gate | 算法与文件不变；不自动采用新 direction |
| Runner / 工厂 / Worker | 不接入、不修改 |
| Entry Points / Registry | 未实现 |
| 新协议依赖 | 仅 Pydantic；pytest 是可选测试依赖 |

DTO 转换本身只保存数据，不保证旧 Runner 理解新状态。执行适配器对 missing/unverified/error 抛异常，避免将其作为成功指标返回，但旧非 Mapping Runner 对评测异常仍得到 score=0、failure_kind=None、metrics=[]；全部 not_applicable 仍可能聚合为 0。这是本次真实兼容测试明确覆盖的旧行为，不能宣称已经修复“评测失败被计为回答质量差”。

此外，旧 Runner 丢弃异常前已产生的指标，因此异常上的完整 SDK 结果还不会自动持久化。后续 Engine 阶段应统一处理状态与失败隔离，不能依赖普通 DTO 扩展自动完成。

旧 Comparison/Gate 仍按已有规则消费数值。Manifest.direction 当前仅存储和校验，不是更改历史规则的指令；请求级指标选择与方法版本一致性仍需后续阶段完成。

完整上下文可能包含敏感原文/配置，SDK 不负责脱敏或向外发送；可信实现应按原应用权限接入。没有实现插件沙箱，也不提供请求动态执行代码能力。

## 6. 安装与实际验证

从仓库根目录：

```sh
python -m pip install ./packages/evaluator-sdk
backend/.venv/bin/python -m pip install --no-deps ./packages/evaluator-sdk
backend/.venv/bin/python -m pytest -q -c packages/evaluator-sdk/pyproject.toml packages/evaluator-sdk/tests
backend/.venv/bin/python -m pytest -q backend/tests/test_evaluator_sdk_compat.py
```

第二条 --no-deps 仅适用于当前后端已经有兼容 Pydantic 的环境；一般安装应允许解析依赖。生产包不依赖 pytest。未修改后端历史 requirements.txt 的无关问题；使用兼容层时需要显式安装本地 SDK。

本次 Python 3.12.3、后端 Pydantic 2.13.5：
- SDK 协议测试：28 passed in 0.04s。
- 兼容层最终测试：33 passed in 0.09s，覆盖五状态 JSON 往返、整数精度、方向、输入复制、异常/取消/错名/变化声明、原 API 和旧 Runner。
- 独立临时环境安装构建工具与 Pydantic 2.14.1，构建 wheel 和 sdist，安装 wheel 成功；在仓库外复制并运行测试：28 passed in 0.08s。这是同一套 SDK 测试的安装验证，不累计为新的测试数。
- 通过 importlib 断言安装来源为 site-packages、py.typed 存在、app / fastapi / psycopg 不可导入、没有加载 app 模块。包生产依赖只有 pydantic>=2.7,<3；没有 Entry Points。

构建命令（在临时干净环境的 Python 下执行）：

```sh
python -m pip wheel --no-build-isolation --no-deps --wheel-dir /tmp/evalforge-sdk-stage1-70yia37o/dist packages/evaluator-sdk
# 在 packages/evaluator-sdk 目录执行：
python -c "from setuptools.build_meta import build_sdist; build_sdist('/tmp/evalforge-sdk-stage1-70yia37o/dist')"
```

产物保留在仓库外 /tmp/evalforge-sdk-stage1-70yia37o/dist；没有上传包仓库。

复跑 Stage 0 相同 18 个测试模块的命令：

```sh
backend/.venv/bin/python -m pytest -q --tb=short \
  backend/tests/test_run_context.py \
  backend/tests/test_retry_policy.py \
  backend/tests/test_retry_decider.py \
  backend/tests/test_v09_retry.py \
  backend/tests/test_v10_persistence.py \
  backend/tests/test_replay.py \
  backend/tests/test_replay_timeline.py \
  backend/tests/test_v11_comparison.py \
  backend/tests/test_v11_dataset_comparison.py \
  backend/tests/test_v11_experiment_comparison.py \
  backend/tests/test_v11_experiment_runner.py \
  backend/tests/test_v11_regression.py \
  backend/tests/test_v11_regression_gate.py \
  backend/tests/test_v12_openapi.py \
  backend/tests/test_v12_error_contract.py \
  backend/tests/test_v13_jobs_api.py \
  backend/tests/test_v13_jobs_contract.py \
  backend/tests/test_v11_experiment.py
```

结果：56 passed，1 failed，3 warnings，1.89s。既有失败 test_v11_experiment.py::test_duplicate_case_is_rejected，与 Stage 0 一致：测试期望 ExperimentRunConflictError，InMemoryExperimentStore.attach_run 实际抛 ValueError。三条 warnings 仍是旧 TestCase 收集提示。本阶段没有修复或掩盖这一基线失败。

未运行真实数据库、在线 LLM、前端或全量项目测试；API 验证是原 MetricResultResponse 的模型序列化验证，不是新增 HTTP 接口。依赖范围下限 Pydantic 2.7 / Python 3.11 尚未逐版本验证。

## 7. 文件清单与阅读顺序

本次新增：
1. packages/evaluator-sdk/README.md：安装、示例和语义。
2. packages/evaluator-sdk/src/evalforge_evaluator_sdk/models.py：严格契约与跨模型验证。
3. packages/evaluator-sdk/src/evalforge_evaluator_sdk/base.py：异步协议。
4. packages/evaluator-sdk/src/evalforge_evaluator_sdk/__init__.py：公共导出。
5. packages/evaluator-sdk/src/evalforge_evaluator_sdk/py.typed：PEP 561 类型标记。
6. packages/evaluator-sdk/pyproject.toml：独立打包与测试配置。
7. packages/evaluator-sdk/.gitignore：本地构建 egg-info 忽略规则。
8. packages/evaluator-sdk/tests/test_sdk.py：公共契约测试。
9. backend/app/evaluator/sdk_compat.py：旧 Harness 边界。
10. backend/tests/test_evaluator_sdk_compat.py：兼容性与现有 Runner 行为测试。
11. docs/plans/evaluator-plugin-stage1.md：本报告。

本次修改：AI_CHANGELOG.md 追加执行记录。

建议按上表 1 → 2 → 3 → 9 → 8/10 → 6 阅读，再对照旧 backend/app/evaluator/base.py、backend/app/harness/contracts.py。已有 docs/plans/evaluator-plugin-stage0.md 保留不变；它在本次开始前已是未跟踪文件，不归为本次新增产物。

Stage 1 到此为止，不开始 Stage 2，不执行 commit/push。
