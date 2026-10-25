# Evaluator Plugin Stage 3：Entry Points Plugin Loader

日期：2026-10-25。只实现已安装插件的发现、受控加载和注册；不修改 Runner、Comparison 或 Gate。

## 1. 工业问题与实际接入位置

Stage 2 Registry 已能显式接收 Manifest 和零参数工厂，但宿主仍需为每个第三方类编写 import。
安装包的 Entry Points 元数据提供一个固定发现目录，使宿主无需将某个业务模块路径写进实现。
这会引入真实 Python 导入，因此发现和执行信任边界必须分开。

本阶段结构：

```text
管理员/镜像构建安装受信 Python 包
  → .dist-info/METADATA + entry_points.txt
  → importlib.metadata.entry_points(group="evalforge.evaluators")
  → 服务端 ID/来源包/可选包版本允许清单
  → 对选定 evaluator_id 调用 EntryPoint.load()
  → 导出对象 Manifest / SDK API / Entry Point ID 校验
  → EvaluatorRegistry.register(manifest, factory)
  → 原 Registry 异步协议、完整声明、重复 ID、实例身份检查
  → Registry.create(evaluator_id) 返回独立实例
  → 实际评分由宿主另行调用
```

Loader 位于独立 SDK，不反向依赖后端。原 Registry 不承担导入或扫描职责。
后端只新增服务端配置读取函数，不接入 FastAPI lifespan、默认工厂、Runner 或 Worker。
因此本阶段不宣称正式 Evaluation Job 已能选择第三方插件。

## 2. 插件导出约定

固定入口组 evalforge.evaluators，Entry Point 名必须等于 Manifest.evaluator_id。
导出对象是同步零参数 SDK Evaluator 类/工厂，且具有可直接读取的 manifest。
通常导出一个带类属性 manifest 的 Evaluator 类最简单。

为何将 ID 写进入口名：发现阶段只能安全读安装元数据，不能导入全部插件后再决定加载哪一个。
加载后再次核对 Manifest ID，可以拒绝元数据名称与实际声明的重定向。

实际示例位于 examples/evaluator-plugin/pyproject.toml：

```toml
[project]
name = "evalforge-example-evaluator"
version = "0.1.0"

[project.entry-points."evalforge.evaluators"]
"example.exact_match" = "evalforge_example_evaluator:ExactMatchEvaluator"
```

示例 ExactMatchEvaluator 的 Manifest.version 为 1.0.0，api_version 为 1.0。
来源包版本 0.1.0 和评测器实现版本 1.0.0 是不同事实，分别记录，不互相推导。

SDK 分发版升级为 0.3.0，SDK API 继续为 1.0。协议不兼容明确拒绝，不宽松降级。

## 3. 发现、加载、注册的函数职责

核心实现：packages/evaluator-sdk/src/evalforge_evaluator_sdk/plugin_loader.py。

| 类/函数 | 输入、输出及职责 |
| --- | --- |
| AllowedEvaluatorPlugin | evaluator_id / distribution / 可选 distribution_version，绑定服务端允许来源 |
| EvaluatorPluginConfig | allowlist，默认空，拒绝额外字段和重复 ID |
| EvaluatorPluginRecord | 插件名、ID、来源包、包版本、Manifest、状态及错误 |
| PluginError | discovery/load/registration 阶段、稳定错误码、异常类型；不复制任意异常原文 |
| PluginDiscoveryReport | 全部插件记录和可选扫描级错误，可 JSON 往返 |
| EvaluatorPluginLoaderError | 非法选择或阶段顺序的统一控制错误，不是评分错误 |
| EvaluatorPluginLoader.__init__ | 接收 Registry 和服务端策略快照，不向工厂注入宿主服务 |
| discover | 使用 metadata.entry_points(group=ENTRY_POINT_GROUP)，只读安装元数据，构建固定快照 |
| load(evaluator_id) | 仅加载已发现且被允许的 ID，调用对应 EntryPoint.load；尚不注册或构造实例 |
| register(evaluator_id) | 仅注册已加载对象，复用 Registry.register 全部检查，不隐式导入 |
| load_selected(tuple_of_ids) | 顺序 load/register 选定 ID，单插件错误不阻塞其他合法选择 |
| report | 返回独立结构化记录快照，不扫描、不导入 |
| _select / _fail / _package_key | ID 唯一选择、失败记录、发行包名称规范化 |

阶段状态：discovered → loaded → registered；策略不允许为 blocked，发现/加载/注册失败为 failed。
失败在当前 Loader 中为终态，无隐式重试；重复成功 load/register 幂等。
get/list 元信息读取和实际实例创建仍属于 Stage 2 Registry。

load 不做实际评分协议的完整实例预检；register 调用现有 Registry，后者构造一次预检实例并检查 async evaluate(context)。
这样既满足三个阶段分离，也避免复制已有协议判断。

## 4. 服务端允许清单和安全边界

backend/app/config.py 新增 get_evaluator_plugin_config()：

```sh
export EVALFORGE_EVALUATOR_PLUGINS='{"allowlist":[{"evaluator_id":"example.exact_match","distribution":"evalforge-example-evaluator","distribution_version":"0.1.0"}]}'
```

默认 {} 对应空允许清单。未知字段、非法 JSON、非法包名、重复规则 fail closed；错误文本不输出环境变量内容。
配置只从服务端环境读取，未创建任何请求参数或 API。

可信启动代码可以这样装配，但本阶段没有自动接入现有启动流程：

```python
from app.config import get_evaluator_plugin_config
from evalforge_evaluator_sdk import EvaluatorPluginLoader, EvaluatorRegistry

registry = EvaluatorRegistry()
loader = EvaluatorPluginLoader(registry, config=get_evaluator_plugin_config())
discovery = loader.discover()
outcomes = loader.load_selected(("example.exact_match",))
if outcomes[0].status == "registered":
    evaluator = registry.create("example.exact_match")
```

允许清单在 EntryPoint.load 之前判断。来源包名按 Python 发行包命名规则归一化大小写及 - _ .；
版本若指定，则精确比较已安装包版本。没允许、来源不符或版本不符，都不导入插件。

没有任意字符串 import_module 路由，没有 pip install 调用、shell 命令或安装 API。
用户给一个 module:Class 字符串，只能按已发现的 ID 查找，不能当作导入路径执行。
只有安装元数据中选定的 Entry Point 能进入 load。

Loader 和 Registry 不把数据库连接、宿主对象或服务密钥传给构造器；构造器零参数。
但第三方 Python 以宿主进程权限运行，可以自行访问进程环境、网络或文件；允许清单不是沙箱、不是签名验证。
恶意代码也可能挂起进程或调用 os._exit，不能由异常捕获提供隔离。
因此仅允许经过审核的包，部署时锁定包来源和构建产物；任务上下文/配置中的敏感数据仍需宿主按应用规范管理。

## 5. 重复与错误隔离策略

两层拒绝策略：

1. 两个安装入口同名：无论来源、版本、是否在允许清单内，该 ID 的所有入口全部失败，且不导入任意一个。
   不选择“扫描到的第一个”。一个未允许的同名包也能阻断该 ID，这是避免来源歧义的保守取舍，应清理部署环境。
2. 不同入口的声明 ID 必须等于自己的入口名；已注册 Registry ID 绝不覆盖，
   builtin_override_forbidden / duplicate_evaluator_id 直接沿用 Stage 2 错误。

错误记录保留来源包和包版本，即使导入失败；尚无法读取的 Manifest 为 None。
ModuleNotFoundError 记 missing_dependency；其他导入异常记 import_failed；
协议/API/Manifest/重复错误标记各自阶段和稳定 code。
显式捕获插件导入/构造的 SystemExit，避免普通 sys.exit 终止启动；KeyboardInterrupt 不被吞掉。
一个插件失败不清空 Registry，也不回滚其他已注册插件；批量选定加载继续处理后续合法 ID。

扫描级 metadata 异常进入 PluginDiscoveryReport.error，既有 Registry 仍可查询和创建。
单条缺失/非法包元数据成为失败记录，未知事实保持 None。

报告保留异常类型而不保存任意异常原文，防止原文携带环境路径或服务信息。
这是结构化诊断，不是持久化审计系统；当前报告仅保存在进程内，没有新增数据库/日志服务。

## 6. 安装与重启的关系

管理员/构建流程从仓库根目录安装：

```sh
python -m pip install ./packages/evaluator-sdk ./examples/evaluator-plugin
```

这是部署动作，不是 HTTP 请求动作。应使用与服务相同的 Python 环境。
API 与 Worker 若运行在不同镜像/虚拟环境，必须安装相同审核版本。

安装、更新、卸载插件以及修改允许清单后，应构建新环境并重启所有使用插件的相关进程。
原因：Loader 保留一次发现快照，Python 也缓存已导入模块。
新建 Loader 或重复扫描不等于清除 sys.modules，不能宣称可靠热更新。
本阶段不尝试 reload、运行时卸载、包安装、进程管理或滚动发布。

Loader 按单启动线程顺序使用，不提供并发导入管理器。
注册后按 ID 创建任务实例继续复用 Registry 的并发隔离机制。

## 7. 实际安装后的完整调用链

独立测试环境安装 SDK wheel 和示例插件 wheel 后，真实输出：

```json
{
  "plugin_name": "example.exact_match",
  "evaluator_id": "example.exact_match",
  "distribution": "evalforge-example-evaluator",
  "distribution_version": "0.1.0",
  "manifest": {
    "evaluator_id": "example.exact_match",
    "display_name": "Example exact match",
    "version": "1.0.0",
    "api_version": "1.0",
    "description": "Compare explicit reference and answer text.",
    "direction": "higher_is_better"
  },
  "status": "registered",
  "error": null
}
```

实际函数链：

1. 示例 pyproject 声明入口，构建生成 evalforge_example_evaluator-0.1.0.dist-info/entry_points.txt。
2. EvaluatorPluginLoader.discover → importlib.metadata.entry_points(group="evalforge.evaluators")。
3. 元数据中 name=example.exact_match、value=evalforge_example_evaluator:ExactMatchEvaluator；检查包/版本允许规则。
4. load("example.exact_match") → 该 EntryPoint.load() 导入示例类；此前 sys.modules 中没有示例模块。
5. 核对 SDK Manifest、api_version 和 evaluator_id，状态 loaded，Registry 仍为空。
6. register("example.exact_match") → EvaluatorRegistry.register → _register → _construct 预检 async evaluate，原子提交。
7. Registry.create("example.exact_match") 两次得到不同实例；没有在 Loader 中调用 evaluate。

测试没有向示例注入 DB/密钥，独立环境不存在 app/FastAPI/psycopg 依赖。
示例只在独立验证环境安装，后端仅安装 SDK 新版，没有把示例加入正式默认指标。

## 8. 文件清单及推荐阅读顺序

新增：
- packages/evaluator-sdk/src/evalforge_evaluator_sdk/plugin_loader.py：加载器、允许清单、结构化记录。
- packages/evaluator-sdk/tests/test_plugin_loader.py：元数据/允许规则/失败隔离/真实 EntryPoint 测试。
- backend/tests/test_evaluator_plugin_config.py：服务端 JSON 策略解析测试。
- examples/evaluator-plugin/pyproject.toml：固定组入口声明。
- examples/evaluator-plugin/src/evalforge_example_evaluator/__init__.py：可安装示例 SDK 实现。
- examples/evaluator-plugin/README.md：安装、完整调用链及信任边界。
- examples/evaluator-plugin/.gitignore：忽略构建 egg-info。
- docs/plans/evaluator-plugin-stage3.md：本报告。

修改：
- packages/evaluator-sdk/src/evalforge_evaluator_sdk/__init__.py：导出 Loader 相关公共契约。
- packages/evaluator-sdk/pyproject.toml：SDK 包版本 0.3.0，无新增依赖。
- packages/evaluator-sdk/README.md：Loader 使用方式、状态/安全/重启说明。
- backend/app/config.py：新增服务端策略读取，原 get_database_url 逻辑不变。
- AI_CHANGELOG.md：追加本阶段执行记录。

建议阅读：示例 pyproject → 示例类 → plugin_loader.py 的 discover/load/register → 配置读取 →
test_plugin_loader.py → 本文安全边界。Stage 1/2 工作保留，原 Registry/业务评测器/Runner/Comparison/Gate 不修改。

## 9. 实际测试与限制

从仓库根目录：

```sh
backend/.venv/bin/python -m pytest -q -c packages/evaluator-sdk/pyproject.toml packages/evaluator-sdk/tests
```

结果：90 passed in 0.13s（原 SDK/Registry 64 + 新 Loader 26）。
首轮修正了新增 JSON tuple 字段往返和 Python 3.12 EntryPoints 按名称索引的测试用法，最终通过。
安装验证还发现公共 __all__ 缺少新增导出，已补齐并重建 wheel。

```sh
backend/.venv/bin/python -m pytest -q --tb=short \
  backend/tests/test_evaluator_plugin_config.py \
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

结果：65 passed，1 warning in 0.61s（服务端配置新 6 + 兼容原 39 + 相关回归原 20）。
warning 仍是原 TestCase 收集提示。

构建 SDK 0.3.0 和示例插件 0.1.0 的 wheel，在已有独立 SDK 验证环境安装。
从仓库外运行复制的三套 SDK 测试：90 passed in 0.14s；这是同套测试的安装验证，不重复累计。
随后实际 importlib 发现已安装示例包，断言发现前后示例模块未被导入、加载后 Registry 仍空、
注册成功、实例不同，以及 SDK 来自 site-packages、py.typed 存在。
修正导出后重新构建与安装，最终冒烟通过。

构建命令使用独立环境已有 setuptools：

```sh
python -m pip wheel --no-build-isolation --no-deps --wheel-dir /tmp/evalforge-entrypoints-stage3-4p5p9wx8/dist ./packages/evaluator-sdk
python -m pip wheel --no-build-isolation --no-deps --wheel-dir /tmp/evalforge-entrypoints-stage3-4p5p9wx8/dist ./examples/evaluator-plugin
```

产物保留在上述临时目录，没有发布到 PyPI，没有请求安装机制。
未运行全项目全量、真实数据库、在线模型或生产部署；原 Experiment 异常类型基线失败未越界修复，
原 Runner 的失败/N/A 计分语义和任务方法版本冻结也没有改变。

Stage 3 到此停止，不进入执行引擎或 Runner 集成，不 commit/push。
