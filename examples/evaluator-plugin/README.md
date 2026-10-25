# 可安装的 Evaluator 插件示例

该包只演示 Entry Points 协议，不自动加入现有 Runner。

管理员在服务停机/镜像构建时，从仓库根目录安装 SDK 和插件：

```sh
python -m pip install ./packages/evaluator-sdk ./examples/evaluator-plugin
```

使用与服务进程相同的 Python 环境。服务端环境变量示例：

```sh
export EVALFORGE_EVALUATOR_PLUGINS='{"allowlist":[{"evaluator_id":"example.exact_match","distribution":"evalforge-example-evaluator","distribution_version":"0.1.0"}]}'
```

可信启动代码显式使用 app.config.get_evaluator_plugin_config() 创建 Loader；
Harness Stage 4 已在 API/Worker 启动时装配目录，并由现有 Runner 执行显式选择；
不指定插件时仍运行原默认指标。独立验证无需 backend：

```python
from evalforge_evaluator_sdk import (
    AllowedEvaluatorPlugin, EvaluatorPluginConfig,
    EvaluatorPluginLoader, EvaluatorRegistry,
)

registry = EvaluatorRegistry()
loader = EvaluatorPluginLoader(registry, config=EvaluatorPluginConfig(allowlist=(
    AllowedEvaluatorPlugin(
        evaluator_id="example.exact_match",
        distribution="evalforge-example-evaluator",
        distribution_version="0.1.0",
    ),
)))
report = loader.discover()  # 仅扫描安装元数据
loaded = loader.load("example.exact_match")  # EntryPoint.load()
registered = loader.register("example.exact_match")  # SDK 协议校验与注册
assert registered.status == "registered", registered.model_dump_json()
first = registry.create("example.exact_match")
second = registry.create("example.exact_match")
assert first is not second
```

安装记录进入 .dist-info/entry_points.txt：
evalforge.evaluators → example.exact_match → evalforge_example_evaluator:ExactMatchEvaluator。
实现 Manifest.version=1.0.0，与来源包版本 0.1.0 分开记录。

安装/升级/卸载插件及修改允许清单后，部署新环境并重启所有相关服务/Worker。
Loader 持有发现快照，Python 也缓存已导入模块；新建 Loader 不能保证热更新。
没有请求安装入口或任意导入路径入口。

第三方 Python 代码以服务进程权限运行，不是沙箱。工厂不接收数据库连接、服务密钥或宿主对象；
这不能阻止恶意代码自行读取进程环境，因此只能安装、允许经过审核的受信包。


启动 Harness 后，先 GET /evaluators 确认 example.exact_match 可用，
再向现有 /evaluation-jobs 或 /experiments/run 请求追加：

```json
{"evaluators": [{"evaluator_id": "example.exact_match", "config": {}, "timeout_seconds": 30}]}
```

保留原请求中的 name、dataset_version、agent_version 和 cases。
结果仍通过原 /runs/{run_id} 查询；示例插件不声明配置模型，因此仅接受空 config。
