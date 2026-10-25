# Evaluator Plugin Stage 6：独立第三方包与真实 E2E

## 交付结论与范围

新增 evalforge-keyword-coverage 0.1.0 独立安装包，指标/选择 ID 为 keyword_coverage，
Manifest 语义版本 1.0.0、SDK API 1.0、方向 higher_is_better。
唯一运行依赖为公开 evalforge-evaluator-sdk>=0.3,<0.4。

没有为示例修改 SDK Registry、Loader、Runner、Comparison 或 Gate，也没有在 backend/app 手动导入插件。
Stage 5 的 Gate 适配已先完成，见 evaluator-plugin-stage5.md；本阶段直接验证其实际第三方包接入。
不新增数据库表、API、安装 API、生产故障开关或依赖框架。

## 包、类和职责

| 文件 | 职责 |
|---|---|
| examples/evalforge-keyword-coverage/pyproject.toml | 独立 distribution、SDK 依赖、真实 evalforge.evaluators 入口 |
| examples/evalforge-keyword-coverage/src/evalforge_keyword_coverage/__init__.py | KeywordCoverageEvaluator，确定性的显式关键词覆盖率 |
| examples/evalforge-keyword-coverage/tests/test_keyword_coverage_unit.py | 17 项独立 SDK 单元测试，无后端依赖 |
| examples/evalforge-keyword-coverage/README.md、.gitignore | 包安装与规则说明，排除构建产物 |
| backend/tests/test_keyword_coverage_e2e.py | 10 项真实安装、目录、HTTP/PG/Gate 与故障隔离测试 |
| backend/tests/fixtures/evaluator-fault-plugin/pyproject.toml、.gitignore、src/evalforge_test_faults.py、src/evalforge_test_import.py、src/evalforge_test_dependency.py | 独立 test-only 安装包：评分异常、超时、导入异常、缺依赖 |
| backend/tests/fixtures/evaluator-duplicate-plugin/pyproject.toml、.gitignore、src/evalforge_test_duplicate.py | 独立 test-only 同名 Entry Point，用于拒绝覆盖测试 |
| docs/extending-evaluators.md | 第三方开发、安装、注册、配置、评分方向、测试与安全指南 |
| docs/plans/evaluator-plugin-stage6.md | 本报告 |
| README.md、AI_CHANGELOG.md | 文档索引和已验证变更记录 |

KeywordCoverageEvaluator.evaluate(context)（示例源码第 16 行）：
输入 SDK EvaluationContext，仅从 case_metadata.expected_keywords 取人工定义关键词；
strip + casefold 去重，再对输出 casefold 做子串匹配，返回 SDK MetricResult。
score=命中数/唯一预期词数，value=命中数，unit=keywords。
没有预期词返回 missing；空数组 not_applicable；非法数组 structured error；
未知输出 missing；明确空字符串是有证据的零覆盖。上下文不被修改。
metadata 提供匹配证据及固定统计口径，不把每个 Case 的关键词集合当成不同指标定义。

该规则便于解释与复现；substring 会有词内命中、否定句命中，不能代替事实性或语义正确性判断。
插件没有配置模型，因此只接受空 config；示例不通过故障模式或延迟参数模拟异常。
测试故障独立放在 fixtures，而非污染真实插件职责。

测试主要函数：
- install：调用真实 pip 安装本地包，安装失败显示诊断，不伪造 dist-info。
- installed_faults / installed_duplicate：将真实 test-only distribution 安装到独立目录，
  仅在相应测试加入 sys.path；不替换 importlib.metadata 或 Registry。
- application：组装已有 FastAPI 服务/Runner/Store，目录由原 build_harness_runner 建立。
- test_clean_sdk_environment_absence_then_real_install:119：
  新建虚拟环境安装 SDK，证明插件未安装不可发现；安装插件后通过真实 Entry Point 评分。
  该环境 app / fastapi 均不存在，证明运行依赖独立。
- test_api_postgres_baseline_candidate_and_real_gate:145：完整 PostgreSQL/API 比较与门禁。
- test_installed_plugin_config_error_and_legacy_compatibility:193：配置提前拒绝、旧内置及 8 Case 并发。
- test_installed_import_failure_isolated:214：真实导入异常/缺依赖不影响健康插件。
- test_installed_duplicate_entrypoint_rejected:226：同名入口全部拒绝，无扫描顺序赢家。
- test_installed_exception_or_timeout_preserves_other_metric:241：真实安装异常/超时插件，
  保留 keyword_coverage 成功指标，Case 质量未知而非伪造 0。
- test_repeated_real_loader_registration_cannot_override:262：
  第二个真实 Loader 导入同一入口并尝试注册，得到 duplicate_evaluator_id，原项不变。

## 安装与端到端调用链

实际在 backend/.venv 中构建 wheel 并安装 SDK 0.3.0 与插件 0.1.0。
SDK-only 临时环境还分别执行“先安装 SDK → 未安装探测 → 再安装插件”，没有利用仓库源码路径绕过安装。
源码与已安装 site-packages 内插件文件逐字节一致；包只声明 SDK 依赖。

1. 服务端允许列表指定 keyword_coverage / evalforge-keyword-coverage / 0.1.0。
2. backend/app/runtime_factory.py::build_harness_runner:32
   → app/evaluator/catalog.py::build_evaluator_catalog:110。
3. SDK plugin_loader.py::discover:126
   → 标准库 entry_points(group="evalforge.evaluators") 读取真实安装元数据。
4. plugin_loader.py::load:215
   → allowlist 来源核对 → 实际 EntryPoint.load() → Manifest/API 检查。
5. plugin_loader.py::register:249
   → 原 EvaluatorRegistry.register → 注册完成；没有手动 Registry.register 示例工厂。
6. POST /experiments/run
   → backend/app/api/experiment_execution.py::run_experiment:40
   → 原 ExperimentRunner.run → Catalog.resolve 固定插件/配置计划。
7. HarnessRunner._run_case:280 → 原 Agent Adapter
   → EvaluatorExecution.evaluate → Registry.create → context_from_legacy
   → KeywordCoverageEvaluator.evaluate → SDK validate_metric。
8. sdk_compat.py::metric_to_legacy:111 → 原 CaseResult/RunRecord
   → HarnessRunner._persist_run:849 → PostgresRunStore.save:118
   → harness_runs.result_json.metrics；来源包/版本在 Run metadata 的 evaluator_plan。
   Experiment 仍关联原 run_ids，未绕过 Store。
9. GET /runs/{run_id} 返回已持久化 keyword_coverage；
   PostgreSQL 测试还直接 SELECT result_json 验证 .5，而非只检查响应内存。
10. POST /comparisons/experiments
    → 原 ExperimentComparisonService / DatasetComparisonService
    → 稳定 Case ID + metric_name 配对 → 原 RegressionDetector / AggregateMetricComparison。
11. POST /gates/evaluate
    → 同一比较服务与原 RegressionGate，返回 comparison 和 gate。
    Gate 结果没有另造历史表或新查询 API。

测试 Dataset 3 个稳定 Case，Candidate 将用例顺序反转：
Baseline Agent 输出 VPN MFA，coverage=1.0；Candidate 输出 VPN，coverage=.5。
阈值 score_delta_mean 最大允许下降 .2，结果如下：

| 字段 | 实测值 |
|---|---|
| metric_name | keyword_coverage |
| score_count / matched_case_count | 3 / 3 |
| score_delta_mean | -0.5 |
| regression_rate | 1.0 |
| Gate 有符号阈值 | -0.2 |
| Gate status / passed | failed / false |
| 来源包 / 包版本 | evalforge-keyword-coverage / 0.1.0 |

E2E 使用真实 FastAPI ASGI HTTP、服务、安装发现、SDK、Runner、PG、Comparison 与 Gate。
业务 Agent 传输是确定性 TextAdapter；没有外部模型调用，不宣称线上部署或负载测试完成。

## 实际测试命令与结果

安装：
```sh
backend/.venv/bin/python -m pip install --disable-pip-version-check ./packages/evaluator-sdk ./examples/evalforge-keyword-coverage
```

成功构建/安装 evalforge-evaluator-sdk 0.3.0、evalforge-keyword-coverage 0.1.0。
这是开发/测试环境中的真实安装，没有修改生产环境或发布 PyPI。

首次专项测试：
```sh
ADAPTER_REGISTRY_TEST_DSN='host=/tmp/evalforge-registry-stage6-cix7psid/socket port=6543 dbname=postgres user=terry' backend/.venv/bin/python -m pytest -q --tb=short backend/tests/test_keyword_coverage_e2e.py examples/evalforge-keyword-coverage/tests
```
26 passed in 65.42s。随后增加真实第二 Loader 重复注册测试，单项 1 passed in .39s。
本阶段最终新增 27 项（插件 17 + 安装/API/PG 10），均在完整回归中通过，不重复累计。

最终完整命令：
```sh
ADAPTER_REGISTRY_TEST_DSN='host=/tmp/evalforge-registry-stage6-cix7psid/socket port=6543 dbname=postgres user=terry' TEST_POSTGRES_DSN='host=/tmp/evalforge-registry-stage6-cix7psid/socket port=6543 dbname=agent_harness_test user=terry' backend/.venv/bin/python -m pytest -q --tb=short backend/tests packages/evaluator-sdk/tests examples/evalforge-keyword-coverage/tests --junitxml=/tmp/evalforge-plugin-stage6-final.xml
```

实测：852 项，851 passed、1 failed、0 skipped、7 warnings，85.33s。
JUnit testcase 数、failure 数和 skipped 数已解析核对。
全部后端、SDK/Registry/Loader 和新独立插件测试均包含在此命令范围；不代表前端或线上验收。

唯一失败：
backend/tests/test_v11_experiment.py::test_duplicate_case_is_rejected:340，
预期 ExperimentRunConflictError，实际 InMemoryExperimentStore.attach_run:172 抛 ValueError。
这是 Stage 0/4/5 已记录失败，未修改测试、跳过或越界修复。
warnings：6 个旧 TestCase 类收集提示，1 个旧 test_v13_cancel_store.py::test_dsn 返回字符串的提示。
没有新增插件测试失败，也没有因为数据库未配置而跳过数据库验证。

数据库：复用本会话私有 PostgreSQL socket；
为旧 Store/Worker 测试新建此前不存在的 agent_harness_test 数据库并初始化原迁移。
Registry/新 E2E 继续每测试 fresh Schema。未连接开发/生产数据库，旧测试只清理本次创建的行，
未删除任何原有业务数据；保留数据库和测试 Schema供检查，完成后停止私有 PG 服务。

静态检查：新增函数 docstring、插件只导入公开 SDK、backend/app 没有示例插件手动导入、
pyproject 依赖/入口、安装源码一致、文档围栏与 git diff --check 均通过。

## 边界与建议阅读顺序

1. docs/extending-evaluators.md：全链路、规则和接入方式。
2. examples/evalforge-keyword-coverage/pyproject.toml：如何成为真正独立安装包。
3. 同目录 src/evalforge_keyword_coverage/__init__.py：输入、评分、未知/错误状态。
4. 同目录 tests/test_keyword_coverage_unit.py：评分契约。
5. backend/tests/test_keyword_coverage_e2e.py：真实安装与原系统闭环。
6. docs/plans/evaluator-plugin-stage5.md：比较字段语义与门禁适配。

已安装并不代表已授权；启动时仍需服务端 allowlist。安装/更新插件后应重启 API/Worker。
插件是受信任的同进程 Python，不是沙箱；协作式超时不能隔离恶意阻塞代码。
关键词指标只测术语覆盖，不能保证事实性。外部资源/数据变更必须通过版本/配置治理。
全量回归仍有上述已知失败，不声称全绿。本阶段不继续新增功能，不 commit/push。
