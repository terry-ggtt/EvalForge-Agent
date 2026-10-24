# Stage 6：Adapter Registry 与管理接口

本阶段复用现有 psycopg 异步连接池、手工 SQL 迁移和 FastAPI Router/Service 组织方式。
现有 API 没有统一身份系统；新增接口单独采用默认拒绝访问的 Bearer 鉴权。
Evaluation Job 绑定了案例和 Experiment，不能直接用来运行生成任务，因此复用其持久化设计，使用独立表和独立 Worker。

## 数据与流程

新增七张表：harness_adapter_profiles（配置）、samples（不可变本地样本/Golden）、
candidates（不可变规则内容及状态）、versions（已发布快照）、generations（队列/Lease/预算/检查点）、
validations（服务端生成报告）、audit（人工审核及操作审计）。

配置 → 上传 JSON 样本 → 手工候选或排队生成 → 服务端验证 → 授权人工审核 → 事务发布 → 精确版本查询。

候选状态：draft → validated → approved/rejected；approved → published。
内容修改必须创建新候选。生成成功也只产生 draft，不自动批准。
验证不接受客户端提供的报告，使用现有 MappingValidator 对存储样本重新计算。
审核必须提交 validation_id、完整 evidence_digest、明确决策和非空说明。
审核只接受最新有效报告；无 Golden 不能通过，不能用审核绕过验证。

## 发布事务与并发

PostgresAdapterRegistry.publish() 在一个事务中：
锁 Profile（FOR NO KEY UPDATE）→ 锁候选 → 核对审核/报告/样本/配置绑定 →
插入版本 → 增加计数器 → 候选 published → 写入审计。
任何一步失败，全部回滚。使用 NO KEY UPDATE 保持版本分配互斥，同时避免与外键 KEY SHARE 检查造成锁顺序冲突。
不同候选并发发布串行分配版本；同一候选/审核重试返回同一版本。
主键(profile_id,version)和唯一 candidate_id 作为数据库最终保护。

versions、samples、validations、audit 禁止 UPDATE、DELETE、TRUNCATE。
候选只允许状态转换，配置只允许版本计数器递增；生成终态也不可覆盖。
数据库管理员仍能通过 DDL 改变触发器，因此应用账号应无 DDL/所有者权限；这里不声称防御数据库管理员。

## 异步生成与恢复

POST generations 只保存已检查的请求和服务端预算，返回 202/Location，不调用模型。
独立入口：backend/.venv/bin/python -m app.registry.worker（从 backend 工作目录运行时使用 .venv/bin/python）。
Worker 使用独立队列、SKIP LOCKED、worker_id+attempt_count+未过期 Lease 写入条件和独立 Heartbeat。
模型调用前持久化完整额度预留，回复返回后保存检查点。
模型 Key 只在 Worker 环境，审核/发布凭据不会传给模型。

重启后：queued 可继续领取；过期且尚无付费调用的任务可有限重排；
已开始付费调用的过期任务转 needs_manual_review，保留费用/回复检查点，不盲目重复调用。
该方案保证不对未知付费结果自动重放，不承诺外部 API 的 exactly-once。
运行配置和最终结果保存在数据库；旧 Worker 不能提交结果。用户需要重新生成时显式创建新任务。

## 启用与权限

手工应用 backend/migrations/v014_adapter_registry.sql；没有自动修改开发/生产数据库。
HARNESS_ADAPTER_REGISTRY_ENABLED=1 才打开 Registry 连接池。
HARNESS_ADAPTER_PRINCIPALS 为服务端 JSON 列表，每项含 token_sha256、subject、role。
token_sha256 是高熵随机 Bearer Token 的 SHA-256；不要使用密码或将明文 Token 放进仓库。
身份/角色不能来自请求头 X-User/X-Role 或请求体。缺配置返回 503，缺失/错误凭据返回 401。

角色权限：
- reader：配置和已发布版本。
- editor：包含 reader，另可上传/读取本地敏感样本、创建候选、排队生成、验证和预览。
- publisher：包含 editor，另可显式审核、发布、读取审计。
这是 Registry 全局角色，未实现多租户、用户自助注册、SSO 或双人审批。

HARNESS_MAPPING_GENERATION_BUDGET 为 GenerationBudget JSON；价格和额度由服务端提供，不能由请求扩充。
Worker 另需 MAPPING_LLM_MODEL、MAPPING_LLM_API_KEY、可选 MAPPING_LLM_BASE_URL 及数据库环境变量。
不配置预算仍可手工候选、验证和发布；生成入口返回 503。
新增请求体在 JSON 解析前限制为 2 MiB，包括分块传输。
Raw/Golden/完整报告接口只允许 editor 以上角色；列表只返回必要元数据。

## 接口

前缀 /adapter-registry：
- POST/GET /profiles，GET /profiles/{profile_id}
- POST /profiles/{profile_id}/samples，GET /samples/{sample_id}
- POST/GET /profiles/{profile_id}/candidates，GET /candidates/{candidate_id}
- POST /candidates/{candidate_id}/validate，GET /validations/{validation_id}
- GET /candidates/{candidate_id}/validations
- POST /candidates/{candidate_id}/preview、/review、/publish
- GET /profiles/{profile_id}/versions，GET /profiles/{profile_id}/versions/{version}
- POST/GET /profiles/{profile_id}/generations，GET /generations/{generation_id}
- GET /profiles/{profile_id}/audit

版本和任务列表用于发现 ID/状态；单个详情读取完整快照。错误沿用已有 error.code/message/details 包装。

## 文件与阅读顺序

1. backend/migrations/v014_adapter_registry.sql：表、约束、索引和不可变触发器。
2. backend/app/registry/models.py、auth.py：命令、证据摘要、可信身份与权限。
3. backend/app/registry/postgres_store.py：短事务、审核发布、队列/隔离/恢复。
4. backend/app/registry/service.py：样本检查、服务端验证和生成入队。
5. backend/app/registry/worker.py：调用前预留、回复检查点、独立 Heartbeat/轮询。
6. backend/app/api/adapter_registry.py：管理接口和显式启用的 lifespan。
7. backend/app/main.py：只注册新 Router、错误处理和可选 Registry lifespan。
8. backend/tests/test_adapter_registry.py：真实 PostgreSQL 及 HTTP/Fake Client 测试。
9. AI_CHANGELOG.md：完成记录。

## 实测

ADAPTER_REGISTRY_TEST_DSN 指向独立临时 PostgreSQL，每个测试创建自己唯一的 schema；
不读取开发数据库配置，不删除已有数据。迁移在真实 PostgreSQL 重复应用验证。

定向测试：backend/.venv/bin/python -m pytest -q backend/tests/test_adapter_registry.py。
最终联合测试包含该文件与 Stage 1～5、RunContext、重试、持久化、Replay、业务接入和 Job/OpenAPI：
533 passed，3 条既有 TestCase 收集提示，16.77 秒。
其中新增 43 个 Registry 测试，覆盖事务回滚、并发发布、数据库不可变性、权限、审核摘要、
无 Golden、Worker 检查点/恢复/旧 Worker 隔离、HTTP 全流程和元数据发现。
一次回归因临时 PostgreSQL 未运行产生连接错误，重启同一隔离实例后通过；没有因此修改业务代码。
未调用真实模型、未部署生产迁移、未运行全项目全量测试；未提交或推送。

剩余边界：Raw 数据为受保护 JSONB/文本，仍需部署层 TLS/备份/保留策略；
权限为 Registry 范围的最小本地方案；全局费用配额与自动恢复未知付费结果未实现。
本阶段没有将 Mapping Runtime 接入 Evaluation Runner。
