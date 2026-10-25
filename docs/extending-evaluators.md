# 开发第三方 Evaluator：从独立包到回归门禁

## 先看完整工程链路

业务 Agent 产生回答和 Trace → 原 HarnessRunner 调用选中的 Evaluator →
SDK MetricResult → 兼容层转换为原 MetricResult → 原 RunRecord / PostgreSQL JSONB →
Experiment Baseline / Candidate 按 Case ID 与 metric_name 对齐 →
原 RegressionDetector → 原 RegressionGate → 原比较与 Gate API。

插件要解决的是“不同团队能独立发布指标，宿主仍统一处理任务、存储与发布门禁”。
把一个评分函数手动 import 到 Runner 虽然简单，但会把插件发布与宿主改代码绑定起来。
这里用独立 Python distribution + Entry Points 声明 + 服务端 allowlist：
安装负责可发现，加载负责执行 Python 导入，注册负责 SDK 协议检查，Runner 负责评分。
Registry 本身不评分，也不接受 API 传入任意导入路径。

## 1. SDK 与目录边界

公开 SDK 位于 packages/evaluator-sdk，安装包名 evalforge-evaluator-sdk，
Python 导入名 evalforge_evaluator_sdk，当前包版本 0.3.0、api_version 1.0。
SDK 不依赖 FastAPI、数据库或 Runner；插件仅依赖公开 SDK 和 Python 标准库。
SDK 自己通过依赖声明携带 Pydantic，插件无需引入宿主依赖。

可直接安装的完整示例：

```text
examples/evalforge-keyword-coverage/
  pyproject.toml
  README.md
  src/evalforge_keyword_coverage/__init__.py
  tests/test_keyword_coverage_unit.py
```

示例是独立 distribution，不是 backend 子模块。它的 pyproject.toml：

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "evalforge-keyword-coverage"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["evalforge-evaluator-sdk>=0.3,<0.4"]

[project.entry-points."evalforge.evaluators"]
keyword_coverage = "evalforge_keyword_coverage:KeywordCoverageEvaluator"

[tool.setuptools.packages.find]
where = ["src"]
```

Entry Point 名必须等于 Manifest.evaluator_id。模块路径由管理员安装的包声明，
请求只传 evaluator_id，不会传模块路径。宿主没有手动 import 示例包，也没有为它修改 Registry。

## 2. 实现协议与指标契约

实现类公开 manifest 和 async evaluate(context: EvaluationContext) -> MetricResult。
采用结构化协议，不需要继承宿主评测器或获得 Runner/Store 引用。

Manifest：
- evaluator_id：稳定选择键，示例 keyword_coverage。
- display_name / description：目录展示信息。
- version：评分实现/语义版本，示例 1.0.0；与 distribution 的 0.1.0 不是同一字段。
- api_version：公开 SDK 协议版本，默认 1.0。
- direction：原始 value 越高越好或越低越好。

EvaluationContext 是 JSON 快照，提供 case_id、input_text、expected_output、
agent_output、trace_events、case_metadata、agent_metadata、evaluator_config，
以及已知 run_id / attempt_id / experiment_id / job_id。没有数据库连接、HTTP 服务实例或服务密钥。
不要推断未知运行标识、Token 或 Trace 时间。

MetricResult：
- metric_name：持久化/比较键；同一个 evaluator_id 必须稳定地产出同一种 metric_name。
- score：可选 [0,1] 的归一化质量，始终越高越好。
- value：可选有限整数/浮点原始计量，使用 Manifest.direction；unit 明确原单位。
- status：success / missing / not_applicable / unverified / error。
- metadata：可 JSON 序列化的解释证据，不包含任意对象。
- reason / error：非成功状态必须按 SDK 契约提供说明或结构化 EvaluationError。
- success 至少有 score 或 value；其他状态不带数值，不能用 0 冒充缺失。
- lower_is_better 的 score-only 输出无原始值不合法；同时提供 value 与归一化 score 才能明确区分方向。

metadata.metric_version 可声明指标语义版本，缺省 Manifest.version。
metadata.statistical_scope 可声明固定的匹配/统计规则；不要放入每个 Case 的不同测量值，
否则框架会视为口径不一致而拒绝聚合。真实证据放入 metadata 的其他键。
外部模型、Prompt、资源、定价或数据版本影响语义时，应体现在版本或配置中。

## 3. Keyword coverage 的具体评分规则

输入从 Case.metadata.expected_keywords 读取，必须是非空白字符串数组。
每个词 strip + casefold 后去重；Agent 输出 casefold 后做子串匹配。
排序后的匹配列表保证解释证据稳定。

```text
expected_keywords = ["VPN", "MFA"]
Agent output = "VPN 已启用"
matched_count = 1
expected_keyword_count = 2
score = 1 / 2 = 0.5
value = 1
unit = "keywords"
direction = higher_is_better
```

重复词 ["VPN", "vpn", " VPN "] 只计一个。多次出现不重复加分。
完整代码：examples/evalforge-keyword-coverage/src/evalforge_keyword_coverage/__init__.py。

| 输入情况 | 输出 |
|---|---|
| 没有 expected_keywords 或为 null | missing，不从 expected_output 猜关键词 |
| 显式 [] | not_applicable，不能宣称 100% |
| 非数组、含非字符串或空白词 | error / invalid_expected_keywords |
| Agent 输出未知 null | missing |
| Agent 输出明确为空字符串 | success，score=0、value=0 |
| 有完整证据 | success，按覆盖率计算 |

这是廉价、可解释的基础指标，适合核对必需术语、条款或要点。
它不是语义正确性评估：cat 会匹配 concatenate；否定句也可能含关键词。
工业评测通常将其与事实性、工具行为、引用验证等指标并用，不能只靠关键词决定答案可靠性。
当前示例固定匹配规则，不支持 evaluator_config；非空配置由宿主执行前拒绝。
没有故障注入配置、网络请求或动态执行代码。

## 4. 安装、允许加载与进程生命周期

从仓库根使用同一个 Python 环境：

```sh
python -m pip install ./packages/evaluator-sdk
python -m pip install ./examples/evalforge-keyword-coverage

python -c 'from importlib.metadata import entry_points; print(list(entry_points(group="evalforge.evaluators")))'

export EVALFORGE_EVALUATOR_PLUGINS='{"allowlist":[{"evaluator_id":"keyword_coverage","distribution":"evalforge-keyword-coverage","distribution_version":"0.1.0"}]}'
```

然后启动/重启 API 与所有执行该插件的 Worker。插件安装、更新、卸载或 allowlist 变化后都要重启相关进程。
Loader 使用进程启动时的发现快照，Python 有模块缓存；再次扫描不等于可靠热更新。
生产应锁定 wheel、SDK 与包版本，让所有 Worker 环境一致；示例未上传 PyPI。

三步真实调用链：
1. build_harness_runner → build_evaluator_catalog → importlib.metadata.entry_points(group="evalforge.evaluators")。
2. allowlist 核对 evaluator_id、来源包、可选包版本 → EntryPoint.load() 加载导出类。
3. EvaluatorPluginLoader.register → 原 EvaluatorRegistry.register，校验异步协议、Manifest/API、重复 ID 与实例新鲜性。

安装本身不授予执行权限；未允许的插件不会导入。导入失败/缺失依赖记录错误，健康插件继续可用。
同名 Entry Points 全部拒绝；已注册 ID 也不允许覆盖内置或其他第三方评测器。
GET /evaluators 列出当前进程已注册目录及配置 Schema；不代表整个环境中所有已安装包都被授权。

## 5. 通过现有 API 选择指标

POST /experiments/run 示例（Agent 仍由现有服务端配置选择）：

```json
{
  "name": "keyword-baseline",
  "dataset_version": "keywords-v1",
  "agent_version": "agent-v1",
  "evaluators": [{"evaluator_id":"keyword_coverage"}],
  "cases": [
    {
      "id":"case-1",
      "input_text":"如何开启 VPN 和 MFA？",
      "expected_output":"开启 VPN 和 MFA",
      "metadata":{"expected_keywords":["VPN","MFA"]}
    }
  ]
}
```

响应返回 experiment_id 和 run_ids；GET /runs/{run_id} 读取原 result.metrics。
POST /evaluation-jobs 使用同一 evaluators 字段，Job payload 固定计划，Worker 复核。
不传 evaluators 保持原内置评测器行为，不会因安装插件就默认选它。

每 Case/每 Evaluator 创建新实例；Case 并发沿用原 ExecutionPolicy。
单个评分异常或超时变成独立 error 指标，其他成功指标保留。
missing/unverified/error 会使 Case 总分未知并标记 evaluation failure，
避免把评分基础设施错误当成 Agent 回答差。取消向上传播，不虚构完成结果。

## 6. 持久化、比较与 Gate

metric_to_legacy 将 SDK 结果/Manifest 保存在原 MetricResult.details SDK 信封，
原 RunRecord 保存结果，PostgresRunStore 存入 harness_runs.result_json。
Run metadata 中 evaluator_plan 摘要保存来源包/版本；完整任务计划在已有 Job payload JSONB。
不增加平行指标表。

Baseline / Candidate 必须使用稳定 Case ID 和相同指标计划/配置/版本。
Dataset version 应指向不可变用例，不能保持同一 ID/version 却偷偷修改关键词集合。
Comparison 按 metric_name 匹配，检查指标版本、配置摘要、统计口径与单位，
不同版本/配置返回 HTTP 409 metric_semantics_unavailable，不会给 PASS。
未声明的外部资源版本不能由框架自动证明等价。

POST /comparisons/experiments 使用两组 experiment_id。
POST /gates/evaluate 同时读取它们并执行原 Gate：

```json
{
  "baseline_experiment_id": "baseline-id",
  "candidate_experiment_id": "candidate-id",
  "policy": {
    "metric_rules": [
      {
        "name":"coverage-drop",
        "metric_name":"keyword_coverage",
        "target":"score_delta_mean",
        "threshold":0.2
      }
    ]
  }
}
```

省略 operator：非负 threshold 为最大允许退化，SDK 自动推导方向。
此处 score 从 1.0 降到 0.5，delta=-0.5，允许 -0.2，判 failed。
旧显式 operator="gte", threshold=-0.2 仍支持。value_delta_mean 使用原单位，
relative_score_delta / relative_value_delta 使用比例（0.1=10%），Baseline 为零时不可评估。

原 Gate 同时检查逐 Case 回归率与均值规则；少量提升不能掩盖其他 Case 的退化。
缺失 Case 默认不允许；部分数值、空对齐、缺失指定指标或零相对基准均不能误判 PASS。
聚合是按 Case 的配对算术均值，score=平均每 Case 覆盖比例，不是全 Dataset 的关键词微平均。
完整字段语义与兼容策略见 docs/plans/evaluator-plugin-stage5.md。

## 7. 运行测试与真实 E2E 边界

先安装 SDK 和示例包，避免源码路径偶然让未安装包也能被发现。
插件独立测试无需后端：
```sh
python -m pytest examples/evalforge-keyword-coverage/tests -q
```

后端端到端测试：
```sh
ADAPTER_REGISTRY_TEST_DSN='host=TEST_SOCKET port=TEST_PORT dbname=postgres user=TEST_USER' python -m pytest backend/tests/test_keyword_coverage_e2e.py -q
```

该变量必须指向私有、专用测试 PostgreSQL。
测试复用项目现有 fresh-schema fixture，保留旧数据和新建 Schema，不读取生产 DSN。
E2E 使用真实 FastAPI ASGI 请求、服务层、Runner、SDK 插件、Entry Points 与 PostgreSQL JSONB；
只有业务 Agent 传输被替换为确定性文本响应，不调用外部 Agent/模型。
这不是线上部署、浏览器或负载验收。

测试覆盖：
- 真正安装的 distribution 元数据，真实 entry_points 与 EntryPoint.load；没有 Mock Registry 或伪造安装元数据。
- 临时独立虚拟环境安装 SDK → 验证插件未安装不可发现 → 安装插件 → 从 Entry Point 加载并评分。
  该环境不存在 app 或 fastapi，证明示例不靠宿主导入。
- API 选择插件 → Dataset/多 Case 并发 → 原 Run API / PostgreSQL → Baseline / Candidate → 原 Gate failed。
- 不支持的配置、旧内置评测器兼容。
- 独立 test-only wheel 安装后导入异常/缺依赖、执行异常/超时、重复入口和重复注册。
  故障实现只在 backend/tests/fixtures 下，不在生产示例包中。

完整回归命令：
```sh
ADAPTER_REGISTRY_TEST_DSN='专用 Registry 测试连接' TEST_POSTGRES_DSN='专用 agent_harness_test 数据库连接' python -m pytest -q --tb=short backend/tests packages/evaluator-sdk/tests examples/evalforge-keyword-coverage/tests
```

旧 Worker/Store 测试要求 database 名称 agent_harness_test 且队列空闲。
不要填开发/生产数据库。部分旧测试只清理自己创建的行；新 E2E 使用隔离 Schema。
Stage 6 实际执行数量、失败/跳过与复现命令见 docs/plans/evaluator-plugin-stage6.md。

## 8. 安全、成本与生产限制

- EntryPoint.load 执行真实第三方 Python，权限等于宿主；插件不是沙箱，allowlist 不是签名校验。
- 管理员审核/构建/锁定受信 wheel；请求不能 pip install、提交导入路径或覆盖已有 ID。
- SDK 不传数据库和服务密钥，但同进程 Python 仍可能自行读环境/网络/文件。
  不信任的代码应移到独立进程/容器与权限隔离，本阶段不声称提供这种沙箱。
- timeout 是 asyncio 协作式超时；CPU 阻塞或恶意代码不能靠 wait_for 强制终止。
- 示例无 LLM、无调用费用。需要远程模型的评测器应自行声明版本、费用/并发策略与缺失状态；
  API Key 由服务器受控提供，不放入 Case、配置公开响应或 Metric metadata。
- 大集合关键词匹配耗时与关键词数及文本长度相关；生产须按应用限制输入大小。
  当前示例展示可复现工程链路，不宣称语义正确性或大规模文本搜索性能。

面试表达可以这样组织：
“我们把评分算法做成只依赖 SDK 的独立包，通过 Entry Points 声明能力，服务端允许清单控制加载；
Runner 仍统一处理实例、超时、错误和持久化。指标通过原数据流进入配对比较与 Gate。
版本、配置和样本口径不一致时拒绝比较，因为能算出一个差值不代表它具备发布决策依据。”
