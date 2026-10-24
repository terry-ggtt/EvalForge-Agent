# Intelligent Adapter Stage 8：Adapter Studio

本阶段新增独立页面 `/adapter-studio`，只完成样本接入、生成、预览、验证、人工审核发布和版本发现。没有改写评测 Runner、Mapping Runtime、生成 Worker 或业务 Agent HTTP 协议，没有新增依赖、数据表或迁移。

## 系统位置与工程取舍

工业问题是：生成了一份合法 JSON，并不能说明它正确理解了 Agent 的业务语义；直接在界面点“保存规则”又容易把未验证候选用于正式评测。因此沿用已有分层：

```text
Adapter Studio（当前阶段）
  ├─ Profile + 不可变样本批次 → Schema Inspector（服务端）
  ├─ 显式字段/必要标量披露 → Registry 持久化生成任务
  │                           → 独立 Registry Worker → Stage 5 有界生成/修复
  ├─ Candidate → 确定性 Runtime 预览 → Validator / 独立 Golden
  └─ 最新有效 Validation → 明确人工 Review → 另一次明确 Publish
                               ↓
                       不可变 Published Version
                               ↓
              原 Stage 7 固定版本 Evaluation Job / Replay
```

前端没有另建模型调用服务、任务执行器或发布规则。复用 React 19、React Router 8、TanStack Query 5、Tailwind 4、原 apiRequest / ApiClientError / JobError 和 TraceEvent 类型。新页面采用既有白色卡片、slate 色系、原生表单和可展开 JSON；不引入画布、图编辑器或新 UI 框架。

状态分为三类：选中项/表单/确认保存在组件内；服务器快照保存在本页面专属 QueryClient；候选、任务、报告和发布记录仍以 PostgreSQL 为准。QueryClient 不与公开 Run/Job 页面共用，凭据不进入缓存 key、URL 或浏览器持久存储。断开、导航离开和刷新后需要重新输入凭据。POST 不自动重试，避免隐式重复生成或审核。

reader 可以读取配置和发布版本；editor 能操作样本/候选/生成/验证/预览和读取使用引用；publisher 能审核和发布。没有新建登录系统或客户端角色授权，服务端仍执行真实鉴权。低权限用户操作不允许的区域会看到 403，而不会获得模拟成功。

## 使用闭环

1. 在侧栏进入 Adapter Studio，输入已有 Registry Bearer。配置 API 地址继续使用 VITE_API_BASE_URL。Registry、v014 和需要查看使用数据时的 v015 迁移须由部署者事先准备，详见同目录 Registry/Stage 7 文档。
2. 创建 Profile，填写名称和 Agent 数据格式说明。该说明不是 Agent 连接设置；HTTP 地址/认证仍由原服务端配置管理。
3. 输入或上传 `{ "samples": [...] }` JSON。每项必须显式包含 response；独立 Trace 使用 trace 与 has_separate_trace:true；partial_trace 标记不完整数据。客户端限制约 1.9 MB / 16 个样本，服务端继续执行原来的结构和资源限制。
4. golden 可选，但没有独立 Golden 无法发布。必须由人工独立定义 output_text、spans/checks、not_applicable 等实际 Stage 4 字段。界面提供格式示例，不会把预览复制为期望结果。实际异构样本及独立 Golden 可参考 backend/tests/fixtures/mini_mapping_agent.json。
5. 上传得到 sample_id 与服务端 Inspector。表格显示路径、类型、频率、nullable、缺失次数，另可展开跨样本差异。重新连接后可以分页发现旧批次，不需要记住其 ID。
6. 手工勾选可向模型披露的字段名，默认全不选。不提供“一键披露全部”。必要枚举值通过 disclosed_values 定位符单独选择，例如 `[{"sample_index":0,"source":"response","path":"$.events[0].kind"}]`；先查看本地原始样本，再明确勾选同意披露。可提供 field_hints JSON。样本和 Golden 不作为生成请求整体转发给模型；Stage 5 服务端继续检查/裁剪实际模型上下文。字段白名单和标量授权不是自动 PII 检测。
7. 点击生成只排入原 Registry 队列。必须运行独立 app.registry.worker，并配置原模型/预算环境。只在 queued/running 轮询，完成、失败、needs_manual_review 或读取错误后停止。错误后可手动刷新；重新进入可从历史选择原任务。生成提交网络失败可能已成功入队，应先刷新历史，确认后再决定是否显式创建新任务，避免重复付费。
8. 展示调用次数、预留 Token / nano-USD 上限（不是实际账单）、尝试结果、结构化修复反馈、来源证据及 observed/inferred/unknown 声明。推断/未知条目标记需人工核对；模型声明不是业务正确性证明。进程中断的调用检查点可展开查看，恢复仍由原 Worker 管理。
9. 打开候选，查看 Source → Target 表和完整 MappingSpec。事件字段明确相对事件根；events_path/type_path 单列展示。复杂 enum_map 等参数可查看完整 JSON。无法自动完成时可粘贴人工修正后的 MappingSpec，创建新候选，不覆盖旧规则。
10. “运行预览”调用确定性服务，分别展示同一个不可变样本的 Raw Response/Trace/Golden 和 Normalized Result/Trace。逐事件关联直接展示 Runtime 的 raw_pointer/raw_event/normalized_event，不按成功事件列表下标猜测关联。
11. “运行服务端验证”保存实际报告。历史可分页读取，显示 L1/L2/L3、error/warning/unverified、Golden 已覆盖字段和阻断原因。Unverified 不能通过勾选解除；需补充独立证据或修正规则重新验证。
12. 仅候选 validated、当前报告为最新且 eligible、填写审核说明并确认已核对证据时才开放审核。请求绑定 validation_id + evidence_digest。服务端继续检查权限和是否过期。审核通过后再次确认，另点发布，发送实际 audit/review_id；没有自动发布动作。拒绝由服务端记录并终结候选。
13. 已 approved 候选重新进入后，可恢复最近 50 条审计中的对应批准记录；更早记录可显式填写已有审核 ID，服务端会再次核验，不能靠填写任意 ID 越权。
14. 历史版本按固定整数查询，展示发布人、指纹、摘要、完整快照及真实 Job / Run / Attempt 数和分页引用。Job 包含未执行及失败任务，Run 仅统计已保存产物，不能用绑定数推断质量。Run 链接进入原 Replay Timeline。

## 关键数据链与持久化

| 界面入口 / 函数 | API / 服务函数 | 状态或持久化位置 |
| --- | --- | --- |
| StudioProfiles.submit | POST /profiles → PostgresAdapterRegistry.create_profile | harness_adapter_profiles + 原 audit |
| SampleImport.submit / sampleUpload | POST /profiles/{id}/samples → AdapterRegistryService.upload → inspect_samples → add_samples | harness_adapter_samples 的 samples_json / inspection_json / 指纹 |
| GenerationForm.start / generationRequest | POST /profiles/{id}/generations → enqueue → 原 Worker | harness_adapter_generations 的状态、lease、budget、checkpoints、result；候选进入原 candidates |
| GenerationPanel / useRegistryQuery | GET /generations/{id} | 只读任务快照；前端定时器不执行生成 |
| CandidateReview / MappingTable | GET /candidates/{id} | harness_adapter_candidates.mapping_json |
| 运行预览 | POST /candidates/{id}/preview → validate_samples / 原 Validator 与 Runtime | 不修改候选，不持久化新的验证报告 |
| 运行验证 | POST /candidates/{id}/validate → AdapterRegistryService.validate / record_validation | harness_adapter_validations + candidate 状态 |
| submitReview | POST /candidates/{id}/review → store.review | harness_adapter_audit 的人工身份、说明和精确报告关联 |
| 发布按钮 | POST /candidates/{id}/publish → store.publish | 既有事务、锁和不可变 harness_adapter_versions |
| VersionPanel | GET /profiles/{id}/versions/{v} 与 /usage | 只读原 versions、evaluation_jobs、mapping_artifacts；链接原 Run/Job 页面 |

前端不重算规范 Trace，也不重跑发布规则以显示历史版本。正式 Job 使用 Stage 7 固定版本语义，没有添加 latest 解析。

## 两个最小后端补充

原 API 能按 sample_id 读取，但不能发现孤立上传批次；原版本查询也不包含实际使用引用。因此仅追加：

- GET /adapter-registry/profiles/{id}/samples：editor、limit 1..200、offset>=0，元数据分页，不批量返回 Raw / Inspector。
- GET /adapter-registry/profiles/{id}/versions/{v}/usage：editor，精确已发布版本，返回 job_count/run_count/artifact_count 和分页 jobs/runs 元数据。两个列表使用同一 limit/offset、各自独立排序；计数和列表来自一条 SQL 的一致快照。没有 v015 返回 503，版本不存在返回 404，不伪造零。

使用查询不返回完整 Job payload、Raw 或私有 MappingResult。没有新增数据库表、迁移、运行时更新、发布流程或鉴权模型。

## 本阶段文件与职责（实际路径）

仓库根路径为 /home/terry/projects/agent-evaluation-harness，Windows 对应 \\wsl.localhost\Ubuntu\home\terry\projects\agent-evaluation-harness。以下路径均相对此根：

| 变更 | 文件 | 关键职责 |
| --- | --- | --- |
| 新增 | frontend/src/pages/AdapterStudioPage.tsx | AdapterStudioPage 管理内存凭据；StudioSession 私有缓存；StudioProfiles/ProfileWorkspace 组织配置和独立选中范围 |
| 新增 | frontend/src/api/adapterStudio.ts | registryRequest 复用 apiRequest，仅 Registry 请求携带 Bearer；registryId 编码路由 ID |
| 新增 | frontend/src/hooks/useAdapterStudio.ts | useRegistryQuery 管理取消/有界状态轮询；useRegistryCommand 单次命令、成功刷新本页面快照 |
| 新增 | frontend/src/types/adapterStudio.ts | Registry 前端传输类型，复用已有 TraceEvent |
| 新增 | frontend/src/utils/adapterStudio.ts | 有界 JSON / 样本形状、显式披露请求、源目标表行、轮询与审核资格纯函数 |
| 新增 | frontend/src/components/adapters/StudioComponents.tsx | 复用 JobError；卡片、折叠 JSON、加载状态、元数据分页、MappingTable、ValidationView |
| 新增 | frontend/src/components/adapters/SampleWorkspace.tsx | SampleImport 本地文件读取与上传；GenerationForm 披露/排队/人工候选 |
| 新增 | frontend/src/components/adapters/ReviewWorkspace.tsx | GenerationPanel 修复历史；CandidateReview 预览/验证/审核/发布；VersionPanel 快照与真实使用引用 |
| 修改 | frontend/src/App.tsx | 仅追加 /adapter-studio 路由和导入 |
| 修改 | frontend/src/components/layout/AppShell.tsx | 仅追加导航项 |
| 新增 | frontend/tests/adapterStudio.test.mjs | JSON / 披露 / 源目标 / 状态资格测试 |
| 新增 | frontend/tests/adapterStudioApi.test.mjs | 复用 Client、方法/授权隔离/取消/编码/错误测试；关闭测试用 Vite websocket |
| 新增 | frontend/tests/browser/adapterStudio.browser.mjs | 可选真实 Chromium + Fake Registry 六项交互测试 |
| 修改 | backend/app/api/adapter_registry.py | 两个只读发现/使用路由及原鉴权复用 |
| 修改 | backend/app/registry/postgres_store.py | list_records 增加样本元数据；version_usage 只读一致快照查询 |
| 新增 | backend/tests/test_adapter_studio_api.py | 三项真实 PostgreSQL/API 用例 |
| 修改 | frontend/README.md | 页面入口、运行前提和详细文档索引 |
| 新增 | docs/INTELLIGENT_ADAPTER_STUDIO.md | 本文 |
| 修改 | AI_CHANGELOG.md | 追加本阶段验证后记录 |

其他已有未提交文件不是本阶段修改。尤其没有改 RunDetailPage、RunTimelinePage、旧 Job 创建页或原 Client 的行为。

## 真实验证结果

2026-10-24，在现有环境内执行，无新增依赖：

```sh
# frontend 目录；使用 WSL 已有 Node 22.23.3
npm run build
npm run lint
npm test
```

- build 包含 tsc -b，通过；Vite 8.3.3，168 modules，JS 388.92 kB / gzip 113.99 kB，CSS 16.53 kB / gzip 4.07 kB。
- lint 通过。
- 原 8 项 + 新 6 项前端测试，共 14 passed，最终 445.614066 ms；新测试禁用 Vite websocket 后不再争用测试端口。

```sh
# 仓库根；ADAPTER_REGISTRY_TEST_DSN 明确指向专用隔离测试实例
backend/.venv/bin/python -m pytest -q \
  backend/tests/test_adapter_studio_api.py \
  backend/tests/test_adapter_registry.py \
  backend/tests/test_published_mapping_evaluation.py --tb=short
```

70 passed in 23.27s。三项新增测试覆盖样本发现与分页/敏感数据隔离/鉴权、缺迁移不能伪造使用统计、精确版本实际 Job→Run→产物计数与分页。另 67 项复验原 Registry 和固定版本评测集成。使用既有临时私有 PG16 socket /tmp/evalforge-registry-stage6-cix7psid/socket:6543，每个用例创建新的独立 schema；未删除数据、未操作开发/生产数据库。HTTP Agent 使用 MockTransport，生成使用 Fake Client。

```sh
# frontend 目录；使用环境中已有的 Playwright 和 Chrome，无需新增项目依赖
# 设置 STUDIO_PLAYWRIGHT_MODULE 为现有 playwright/index.mjs 的本地绝对文件路径
# 设置 STUDIO_BROWSER_EXECUTABLE 为现有 Chrome 可执行文件
# Vite 需已监听 http://127.0.0.1:5173，可用 STUDIO_BASE_URL 覆盖
node --test --test-reporter=tap tests/browser/adapterStudio.browser.mjs
```

实际为 Windows Chrome 无头模式，Vite 在 WSL，6 passed / 0 failed，最终 24.5224882s：

1. 真实文件上传 → 显式披露 → 生成状态轮询与修复 → 预览原始事件关联 → 实际界面验证操作 → 人工审核 → 二次确认发布 → 使用计数及 Replay 链接 → 清除凭据。
2. 没有 Golden，Unverified 阻断审核/发布。
3. 服务端 403 保持可见，无法发布。
4. 401 不自动重试，可清除凭据。
5. 网络读取失败暂停轮询；恢复网络后手动刷新，最终 needs_manual_review 停止，未重复排入付费任务。
6. 原 Evaluation Jobs 页面仍能通过侧栏访问；返回 Studio 需重新连接。

浏览器 API 是显式 Fake Registry，修复结果为脚本数据，不能视为真实在线模型质量验证；真实 SQL/服务鉴权和原发布事务由上述 70 项 PostgreSQL 测试覆盖。初轮 Fake 缺少 Profile 详情路由、StrictMode 初始请求重挂载影响故障注入，测试已修正并最终全绿，没有把测试替身失败误报为产品功能失败。

本次未跑全项目全量、在线 LLM/业务 Agent、生产部署或压力测试。Stage 7 已记录的旧 Experiment 异常类型基线失败不在本次改动范围。

## 边界与阅读顺序

- 本阶段是可用的表单/JSON 审核台，枚举标量和复杂 DSL / Golden 仍需要懂数据契约的审核者。没有自动 PII 判定、可视化 DSL 编辑器或业务协议配置器。
- 凭据内存隔离不替代部署级权限体系。没有新建 SSO/多租户。错误恢复不自动重复付费任务，需先查历史再明确重试。
- 使用查询当前依赖 JSONB 绑定筛选，未加新索引；大规模历史 Job 时应先测量再决定索引或汇总策略。503 明确说明迁移缺失，不能当零使用量。
- 无自动采集在线 Agent 样本、全局费用池、前端批量发布或语义强制通过入口。
- 推荐先读本文的系统链路，再按 AdapterStudioPage.tsx → useAdapterStudio.ts / api/adapterStudio.ts → SampleWorkspace.tsx → ReviewWorkspace.tsx → StudioComponents.tsx → 浏览器测试 → 后端两个只读函数 / API 测试阅读。
- Stage 8 完成后停止，不开始其他阶段。
