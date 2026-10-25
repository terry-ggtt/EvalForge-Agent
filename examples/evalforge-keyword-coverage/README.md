# evalforge-keyword-coverage

独立的第三方 Evaluator 包，唯一运行依赖为公开 evalforge-evaluator-sdk。
Entry Point、evaluator_id、metric_name 均为 keyword_coverage，方向 higher_is_better。

每个用例在 metadata.expected_keywords 提供字符串数组；去除前后空白、casefold 后去重。
按不区分大小写的子串匹配，score=命中唯一关键词数/唯一关键词数，
value=命中唯一关键词数，unit=keywords。不是 token 边界匹配或语义召回指标。
未提供关键词返回 missing，空集合返回 not_applicable，格式不合法返回结构化 error；
没有自动从 expected_output 猜测关键词。空 Agent 输出是明确的 0 覆盖，缺失输出则 missing。

插件不声明配置模型，因此只接受空 config，未知配置由宿主在执行前拒绝。
没有测试故障开关、网络调用、LLM 或宿主导入。

从仓库根安装：
```sh
python -m pip install ./packages/evaluator-sdk
python -m pip install ./examples/evalforge-keyword-coverage
```

服务端 allowlist：
```json
{"allowlist":[{"evaluator_id":"keyword_coverage","distribution":"evalforge-keyword-coverage","distribution_version":"0.1.0"}]}
```

将该 JSON 配置为 EVALFORGE_EVALUATOR_PLUGINS，并重启 API/Worker。
安装只产生可发现元数据，允许清单才授权加载。请求不允许安装或指定 Python 路径。
API 的 evaluators 传 [{"evaluator_id":"keyword_coverage"}]。
完整开发、E2E 与安全说明见仓库 docs/extending-evaluators.md。
