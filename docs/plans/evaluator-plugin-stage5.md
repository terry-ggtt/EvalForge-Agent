# Evaluator Plugin Stage 5：Regression Gate 集成

本阶段复用 ExperimentComparisonService、DatasetComparisonService、RegressionDetector 和 RegressionGate。
未增加第二套比较器、Gate、Runner 或数据库表。Stage 6 示例包另行实施。

## 架构与原有字段语义

原始数据流：Evaluator → SDK MetricResult → metric_to_legacy → RunRecord.result.metrics
→ RunStore 的 result_json JSONB → Experiment.run_ids → Case ID 对齐 → metric.name 匹配
→ RegressionReport → AggregateMetricComparison → RegressionGate → POST /gates/evaluate。

已有能力：稳定 Case ID 交集/差集、重复 Case 拒绝、指标名匹配、同单位原始值比较、绝对差、
relative_value_delta、MetricGateRule 显式 gte/lte、缺失指定指标失败关闭。
需要补充：插件来源和方向、版本/配置/口径一致性、部分缺失的覆盖率、默认仅比较总分导致 raw-only 指标被漏掉的问题。

关键代码位置：
- backend/app/harness/experiment_comparison_service.py::ExperimentComparisonService.compare:50
- backend/app/harness/dataset_comparison_service.py::DatasetComparisonService.compare:68
- backend/app/harness/dataset_comparison_service.py::_aggregate_metrics:433
- backend/app/harness/regression_detector.py::_evaluate_rule:114
- backend/app/harness/regression_gate_service.py::_check_regression_rate:142
- backend/app/harness/regression_gate_service.py::_check_metric_rule:347
- backend/app/api/gates.py::evaluate_experiment_gate:49

AggregateMetricComparison.score_count/value_count 是有效成对观测数，不是原组样本量。
matched_case_count 新增为 SDK 指标的完整对齐 Case 分母。均值只用有效配对，缺失不会补零。
所有 delta 都是 Candidate - Baseline，不因 direction 改变符号。
RegressionReport.has_regression=False 只表示没有已确认退化；evaluable=False 不表示证据充分。
Gate 仍对回归率、缺失 Case 和所有指定指标规则取 AND，任何不可评估项均阻断发布。

## 语义与兼容适配

新增 backend/app/evaluator/comparison_contracts.py::PluginMetricSemantics，仅承载比较来源，
不替代 SDK 或持久化 MetricResult。包括 Manifest、指标版本、计划摘要、来源包/版本、
可选 statistical_scope 和固定 paired-case-mean/v1 聚合口径。

新增 backend/app/evaluator/comparison.py：
- plan_producers：验证持久化执行计划；metric_semantics：验证 SDK 信封与生产者一致。
- validate_plugin_records：检查成功状态、稳定 Case ID、重复指标和输出名称一致性。
- pair_semantics：为原 MetricComparison 附加语义证据。
- normalize_gate_rule：将方向及可选非负容忍度转为已有 gte/lte、有符号阈值。
- plugin_regression：将插件规则转成已有 RegressionRule，调用原 RegressionDetector.detect。
- paired_delta/paired_statistics：使用 Decimal 中间值实现原减法/配对算术均值，避免浮点边界误判；
  超出表示范围或下溢不会被静默当成零差值。

SDK score 始终越高越好，value 使用 Manifest.direction。
score-only 且 lower_is_better 仍由原 SDK 拒绝；没有修改 SDK 协议。
没有显式 Gate 指标规则时，SDK 各个实际输出数值通道采用零退化容忍度；
有规则时，现有 API 将其传入逐 Case 检测，避免原总分下降 0.03 的默认规则与指定容忍度冲突。
显式策略只选择对应通道；未声明的未知通道不会伪造。
旧无 SDK 记录继续使用原 detector/rules 和显式 operator。

版本/配置比较沿用 Stage 4 完整计划摘要：Manifest/API、包版本、配置 Schema、配置值、超时及选择顺序均参与。
另检查 SDK metadata.metric_version（缺省 Manifest.version）及 metadata.statistical_scope。
不同版本/配置/统计口径、缺失 SDK 信封、无效状态/非有限数值 → 原 MetricSemanticsError / HTTP 409。
这里采用保守的整组计划一致策略：即使只比较一个指标，其他配置变化也拒绝比较。
statistical_scope 未提供时保留 null，框架不能证明外部模型/资源语义一致；作者必须通过版本/配置表达变化。

## 阈值和 API

新增兼容写法，operator 省略时 threshold 必须非负，表示最大允许退化：
- score_delta_mean/value_delta_mean：原单位的绝对变化，不是百分比。
- relative_score_delta/relative_value_delta：均值差除以 Baseline 均值绝对值；0.1 表示 10%，不是 0.1 秒。
- Baseline 为零或缺失时相对变化不可评估，不引入 epsilon。
- 原显式 gte/lte、有符号 threshold 保持；与 SDK 声明方向冲突则不可评估。
- 逐 Case 相对容忍度转成原单位交给 RegressionDetector；
  Gate 相对规则仍用“均值的相对变化”，不是“相对变化的均值”。
- 个别 Case 退化可以使回归率超限，即使均值符合阈值；这是原 Gate 的 AND 语义。

POST /gates/evaluate 请求片段：
```json
{
  "baseline_experiment_id": "baseline-id",
  "candidate_experiment_id": "candidate-id",
  "policy": {
    "metric_rules": [
      {"name":"quality-budget","metric_name":"measurement","target":"score_delta_mean","threshold":0.05}
    ]
  }
}
```

同一个接口读取已存 Experiment 并返回 comparison 与 gate；未假设存在 Gate 历史查询表/GET。
POST /comparisons/experiments 保留原入口并返回可选语义证据。
直接在 Python 调用 comparison service 后再 Gate.evaluate 的调用者，应将同一 policy.metric_rules 传入 compare；
Gate 不会对已生成的 RegressionReport 隐式重新计算。

验收结果（真实 API/原 Store；A/B 另有 PostgreSQL 测试）：

| 场景 | 结果 |
|---|---|
| A .84 → .78，允许绝对下降 .05 | failed，delta=-.06 |
| B 1.2s → 1.5s，允许增加 .2s | failed，delta=.3 |
| C Baseline 缺失指定指标，包括部分/两侧均缺失 | failed，不可评估 |
| D Manifest/metric version、配置、统计口径不同 | HTTP 409，不产生 PASS |
| .84 → .80，允许 .05 | passed，不被旧总分规则误阻断 |
| .9 → .85，允许 .05；1.2 → 1.4，允许 .2 | 边界 passed |
| 空交集、单位不同、相对零基准、部分观测 | failed / 不可评估 |

样本数不同仍显示 missing_in_baseline/candidate；原 max_missing_case_count 默认 0。
用户显式允许缺 Case 时，比较范围仍明确为交集；不会声称全量样本等价。
SDK 总分只在完整成对总分证据上比较，否则整体为 null，防止比较两个不同子集。

## 文件与推荐审查顺序

1. backend/tests/test_plugin_regression_gate.py：47 项 Runner/Store/API/边界验收。
2. backend/app/evaluator/comparison_contracts.py、comparison.py：新增证据与规则适配。
3. backend/app/harness/metric_semantics.py：接入共有前置检查。
4. backend/app/harness/comparison.py、comparison_service.py：原单 Case 指标流扩展。
5. backend/app/harness/dataset_comparison.py、dataset_comparison_service.py：
   来源证据、覆盖数、原聚合及逐 Case detector 适配。
6. backend/app/harness/experiment_comparison_service.py：可选传递策略。
7. backend/app/harness/regression.py、regression_detector.py：有限阈值、使用 SDK 规范 delta；
   direction/threshold 判定算法保持。
8. backend/app/harness/regression_gate.py、regression_gate_service.py：
   可选方向推导、relative_score_delta、缺失覆盖与空交集失败关闭。
9. backend/app/schemas/comparisons.py、gates.py、backend/app/api/gates.py：原 API 可选扩展。
10. backend/tests/test_plugin_regression_gate_postgres.py：5 项真实 JSONB/API 比较。
11. README.md、packages/evaluator-sdk/README.md、AI_CHANGELOG.md：文档与记录。

## 验证与限制

最终相关后端扩大回归：200 passed、1 failed、5 warnings，4.77s。
覆盖 25 个模块：Stage 4 文档扩大回归的 21 个模块，加 test_plugin_regression_gate、
test_run_store、test_run_query、test_business_agent_integration。
唯一失败为既有 test_v11_experiment.py::test_duplicate_case_is_rejected：
预期 ExperimentRunConflictError，实际 InMemoryExperimentStore 抛 ValueError；未修改或跳过。
五个 warning 为既有 TestCase 收集提示。新 47 项均包含于通过项。

```sh
ADAPTER_REGISTRY_TEST_DSN='host=/tmp/evalforge-registry-stage6-cix7psid/socket port=6543 dbname=postgres user=terry' backend/.venv/bin/python -m pytest -q --tb=short  backend/tests/test_plugin_regression_gate_postgres.py  backend/tests/test_dynamic_evaluators_postgres.py backend/tests/test_published_mapping_evaluation.py
# 34 passed in 18.65s

backend/.venv/bin/python -m pytest -q -c packages/evaluator-sdk/pyproject.toml packages/evaluator-sdk/tests
# 90 passed in 0.10s
```

不新增置信区间、显著性检验或分位数算法；这是配对算术均值和规则 Gate，不声称统计显著性。
旧 API 可选字段有默认值，无数据库迁移。没有运行前端/负载/在线模型/生产插件。
插件的外部资源版本诚实性仍属于插件作者及部署治理责任。
