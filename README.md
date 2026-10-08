# EvalForge

> Agent Evaluation & Regression Testing Platform

EvalForge 是一个面向 AI Agent 的自动化评测与回归测试平台，用于解决传统单元测试难以评估 Agent 非确定性输出的问题。

平台通过统一的 Agent Adapter、Dataset、Metric、Experiment、Comparison 与 Regression 模型，对不同 Agent、Prompt、Model 版本进行批量测试、指标计算和版本对比，并通过 Regression Gate 判断新版本是否出现质量退化。

---

## Why EvalForge?

传统软件可以通过明确的输入与输出进行测试：

```text
Input
  ↓
Function
  ↓
Expected Output
```

但 Agent 的执行过程通常包含：

```text
User Input
    ↓
LLM
    ↓
Tool Calling
    ↓
External Data
    ↓
LLM
    ↓
Final Answer
```

因此，仅判断：

```python
actual == expected
```

通常无法准确衡量 Agent 的真实质量。

Agent 评测需要同时关注：

- 最终回答质量
- Tool 选择是否正确
- Tool Arguments 是否正确
- 执行过程是否稳定
- Latency
- Token / Cost
- Citation
- 不同版本之间是否出现 Regression

EvalForge 的目标就是提供一套统一的 Agent Evaluation Harness。

---

# Core Workflow

整体评测流程：

```text
Dataset
   ↓
Normalizer
   ↓
TestCase
   ↓
Agent Adapter
   ↓
Evaluation Runner
   ↓
Run Result
   ↓
Metrics
   ↓
Experiment
   ↓
Comparison
   ↓
Regression Detection
   ↓
Gate Decision
```

版本对比流程：

```text
Baseline Experiment
        +
Candidate Experiment
        ↓
Case Comparison
        ↓
Metric Comparison
        ↓
Experiment Comparison
        ↓
Regression Report
        ↓
PASS / FAIL
```

---

# Features

## 1. Unified Agent Adapter

EvalForge 不依赖具体 Agent 框架。

所有 Agent 只需要实现统一接口：

```python
from abc import ABC, abstractmethod


class BaseAgent(ABC):

    @abstractmethod
    async def run(
        self,
        input_text: str,
    ) -> dict:
        ...
```

因此可以接入：

```text
Local Agent
Remote Agent
Research Agent
RAG Agent
LangChain Agent
LangGraph Agent
Custom Agent
```

Harness 不关心 Agent 内部实现，只负责：

```text
Input
  ↓
Agent
  ↓
Result
  ↓
Evaluation
```

---

## 2. Dataset Normalization

不同测试数据集通常具有不同字段：

```json
{
  "question": "...",
  "answer": "..."
}
```

或者：

```json
{
  "query": "...",
  "expected": "..."
}
```

EvalForge 通过 `FieldMapping` 与 `CaseNormalizer` 将不同数据格式统一转换为标准 `TestCase`。

```text
Raw Dataset
    ↓
Field Mapping
    ↓
Normalizer
    ↓
TestCase
```

标准结构示例：

```json
{
  "id": "case_001",
  "input_text": "What is RAG?",
  "expected_output": "...",
  "expected_tool_calls": [],
  "metadata": {}
}
```

这样 Evaluator 不需要感知原始 Dataset 的具体格式。

---

# 3. Evaluation Runner

Evaluation Runner 是 Harness 的核心执行器。

主要负责：

```text
TestCase
   ↓
Agent.run()
   ↓
Trace Collection
   ↓
Metric Calculation
   ↓
RunResult
```

支持：

- Async Agent Execution
- Batch Evaluation
- Error Handling
- Trace Collection
- Metric Evaluation
- Run Result Storage

---

# 4. Metrics

EvalForge 支持针对不同维度进行评测。

例如：

```text
Answer Quality
Tool Accuracy
Tool Arguments
Latency
Token Usage
Citation Accuracy
Citation Coverage
```

Metric 与 Runner 解耦，可以独立扩展新的指标。

概念结构：

```python
Metric
  │
  ├── AnswerMetric
  ├── ToolMetric
  ├── LatencyMetric
  └── CustomMetric
```

后续可扩展：

```text
LLM-as-a-Judge
Correctness
Relevance
Completeness
Faithfulness
Recall@K
MRR
Cost
```

---

# 5. Experiment

单次 Run 无法代表一个 Agent 版本的整体能力。

因此 EvalForge 引入 Experiment：

```text
Experiment
│
├── Agent Version
├── Dataset
├── Test Cases
├── Runs
├── Metrics
└── Metadata
```

例如：

```text
experiment_agent_v1

dataset:
customer-support-v1

agent:
agent-v1

cases:
100

answer_quality:
0.82

tool_accuracy:
0.91

latency:
1.42s
```

Experiment 将大量 Case Run 聚合成一个完整的测试结果。

---

# 6. Experiment Comparison

EvalForge 支持 Baseline / Candidate 实验对比。

例如：

```text
Baseline
agent-v1

Candidate
agent-v2
```

系统会自动匹配相同 Case：

```text
case_001
baseline: 0.80
candidate: 0.88

delta:
+0.08
```

随后进行整体指标聚合：

```text
                    Baseline   Candidate   Delta

Answer Quality        0.81       0.86      +0.05

Tool Accuracy         0.92       0.89      -0.03

Latency               1.20       1.48      +0.28
```

从而回答一个核心问题：

> 新版本 Agent 是否真的优于旧版本？

---

# 7. Regression Detection

仅展示 Delta 并不能自动判断版本是否可以发布。

因此 EvalForge 引入 Regression Rule。

例如：

```text
Answer Quality

允许下降：
2%
```

如果：

```text
baseline = 0.85
candidate = 0.78
```

则：

```text
delta = -0.07
```

触发 Regression：

```text
REGRESSION DETECTED
```

---

# 8. Quality Gate

通过 `MetricGateRule` 可以为不同指标配置独立阈值：

```text
answer_quality >= -0.02

tool_accuracy >= -0.03

latency <= +20%
```

最终生成 Gate Result：

```text
PASS
```

或者：

```text
FAIL
```

例如：

```text
Agent V2 Evaluation

Answer Quality
+4.2%    PASS

Tool Accuracy
-7.1%    FAIL

Latency
+8.4%    PASS

----------------

Final Gate

FAIL
```

这使 EvalForge 可以进一步接入 CI/CD。

---

# 9. Trace & Observability

Agent 的最终 Answer 只是执行结果的一部分。

为了定位 Agent 为什么失败，需要记录完整执行过程。

EvalForge 使用 Trace Event 描述运行轨迹：

```text
agent.start

llm.start
llm.end

tool.start
tool.end

retry

error

agent.end
```

例如：

```text
0 ms       agent.start

120 ms     llm.start

840 ms     llm.end

860 ms     tool.search.start

1320 ms    tool.search.end

1340 ms    llm.start

2150 ms    llm.end

2180 ms    agent.end
```

可以进一步统计：

```text
LLM Latency
Tool Latency
Tool Calls
Retry Count
Errors
Token Usage
```

---

# Architecture

```text
                     ┌───────────────┐
                     │   Frontend    │
                     │ React + TS    │
                     └───────┬───────┘
                             │
                             ▼
                     ┌───────────────┐
                     │    FastAPI    │
                     │  API Server   │
                     └───────┬───────┘
                             │
               ┌─────────────┼─────────────┐
               │             │             │
               ▼             ▼             ▼

          PostgreSQL       Redis       Job Queue
               │             │             │
               │             └──────┬──────┘
               │                    │
               │                    ▼
               │            Evaluation Worker
               │                    │
               │                    ▼
               │               Agent Adapter
               │                    │
               │                    ▼
               │                  Agent
               │
               ▼

        Dataset / Experiment
        Run / Metric
        Comparison
        Regression
        Trace
```

---

# Project Structure

```text
agent-evaluation-harness/
│
├── backend/
│   └── app/
│       │
│       ├── main.py
│       │
│       ├── database.py
│       │
│       ├── models.py
│       │
│       ├── api/
│       │   ├── datasets.py
│       │   ├── evaluation.py
│       │   ├── experiments.py
│       │   └── comparisons.py
│       │
│       ├── agent/
│       │   ├── base.py
│       │   └── demo_agent.py
│       │
│       ├── datasets/
│       │   ├── base.py
│       │   └── mapping.py
│       │
│       ├── evaluator/
│       │   ├── runner.py
│       │   └── metrics.py
│       │
│       ├── harness/
│       │   ├── contracts.py
│       │   ├── comparison.py
│       │   ├── regression.py
│       │   └── trace.py
│       │
│       └── storage/
│           └── run_store.py
│
├── frontend/
│
├── tests/
│
├── requirements.txt
│
└── README.md
```

> 实际目录以当前代码版本为准。

---

# Quick Start

## 1. Clone

```bash
git clone <repository-url>

cd agent-evaluation-harness/backend
```

---

## 2. Create Virtual Environment

Windows：

```bash
python -m venv .venv
```

激活：

```powershell
.venv\Scripts\Activate.ps1
```

Linux / WSL：

```bash
python3 -m venv .venv

source .venv/bin/activate
```

---

## 3. Install Dependencies

```bash
python -m pip install -r requirements.txt
```

---

## 4. Run Tests

```bash
python -m pytest -q
```

---

## 5. Start FastAPI

```bash
uvicorn app.main:app --reload
```

默认访问：

```text
http://127.0.0.1:8000
```

FastAPI Swagger：

```text
http://127.0.0.1:8000/docs
```

---

# Example

假设存在一个 Demo Agent：

```python
class DemoAgent(BaseAgent):

    async def run(
        self,
        input_text: str,
    ) -> dict:

        return {
            "answer":
                f"Demo Agent response: {input_text}"
        }
```

输入 TestCase：

```json
{
  "id": "case_001",
  "input_text": "Explain RAG",
  "expected_output": "RAG combines retrieval with generation."
}
```

Runner：

```text
TestCase
   ↓
DemoAgent
   ↓
RunResult
   ↓
Metric
```

生成类似：

```json
{
  "run_id": "run_001",
  "status": "completed",
  "metrics": {
    "answer_quality": 0.85,
    "latency": 0.21
  }
}
```

多个 Run 最终组成：

```text
Experiment
```

并可以进一步：

```text
Experiment A
     VS
Experiment B
```

执行 Regression Analysis。

---

# API Design

主要 API 规划：

```text
POST   /datasets
GET    /datasets

POST   /evaluations

POST   /experiments
GET    /experiments
GET    /experiments/{id}

POST   /comparisons
GET    /comparisons/{id}

POST   /evaluation-jobs
GET    /evaluation-jobs/{id}
POST   /evaluation-jobs/{id}/cancel
```

具体接口以当前版本 OpenAPI 文档为准。

---

# Roadmap

## V0.1 - V0.10

基础 Harness：

```text
Agent Adapter
TestCase
Dataset Normalization
Runner
Metrics
Trace
RunStore
```

## V0.11

Experiment：

```text
Experiment
Experiment Run
Metric Aggregation
```

## V0.12

Regression：

```text
Case Comparison
Metric Comparison
Experiment Comparison
Regression Detection
Metric Gate
```

## V0.13

Async Evaluation Job：

```text
Job State Machine
Concurrency
Progress
Cancellation
```

## V0.14

Persistent Runtime：

```text
PostgreSQL
Redis
Worker
Failure Recovery
```

## V0.15

Observability：

```text
Trace Timeline
LLM Trace
Tool Trace
Latency
Token Usage
Error Tracking
```

## V0.16

Dataset Management：

```text
Dataset Version
Benchmark
Tags
Filtering
```

## V0.17

Advanced Evaluation：

```text
LLM-as-a-Judge
Correctness
Relevance
Completeness
Faithfulness
Citation Evaluation
```

## V0.18

Experiment Management：

```text
Agent Version
Prompt Version
Model Config
Experiment Tracking
```

## V0.19

CI/CD：

```text
GitHub Actions
Regression Dataset
Quality Gate
PR Blocking
```

## V1.0

目标形成完整的：

```text
Agent Evaluation Platform

Dataset
   ↓
Evaluation
   ↓
Experiment
   ↓
Comparison
   ↓
Regression
   ↓
Gate
   ↓
Observability
   ↓
CI/CD
```

---

# Design Principles

EvalForge 主要遵循以下设计原则：

### Framework Agnostic

Harness 不依赖具体 Agent Framework。

```text
LangGraph
LangChain
Custom Agent
Remote Agent
```

都可以通过 Adapter 接入。

### Evaluation First

平台重点不是运行 Agent，而是：

```text
Measure
Compare
Detect
Decide
```

### Reproducible Experiments

每次实验应尽可能记录：

```text
Agent Version
Dataset Version
Prompt
Model
Config
Metrics
Trace
```

便于结果复现和版本比较。

### Extensible

Agent、Dataset、Metric、Storage 与 Runner 尽量通过抽象接口解耦。

新增能力不应修改 Harness 核心执行流程。

---

# Vision

传统软件已经拥有成熟的：

```text
Unit Test
Integration Test
Regression Test
CI/CD
```

但 Agent 系统具有：

```text
Non-deterministic Output
Tool Calling
LLM Dependency
External Environment
Semantic Quality
```

因此需要新的测试基础设施。

EvalForge 希望将传统软件工程中的：

```text
Test
Benchmark
Regression
Quality Gate
Observability
```

扩展到 Agent 系统中，让 Agent 的每一次版本迭代都可以：

```text
被运行
被测量
被比较
被追踪
被验证
```
0.1版本项目框架思考：
我要做的是一个 Agent Evaluation Harness。

既然目标是评估 Agent，那么首先一定要有评估器，也就是 Evaluator。Evaluator 负责从不同维度对 Agent 的执行结果进行评分，比如答案质量、工具调用准确率、延迟、成本、轨迹质量等。

但是马上会遇到第二个问题：不同 Agent 的实现方式和底层框架并不一样。

有的 Agent 可能基于 LangGraph，有的可能基于 Pi，有的可能只是自己写的 Python Agent，甚至还有可能是一个远程 HTTP Agent。它们的输入格式、输出格式、状态结构、Tool Calling 格式都可能完全不同。

如果 Harness 直接依赖这些具体 Agent 的实现，那么每接入一种新框架，就需要修改 Harness 本身，这样 Harness 就失去了通用性。

所以我们需要增加一层 Adapter，也就是适配器。

Adapter 的作用并不是要求外部 Agent 遵循 Harness 的协议，而是反过来，由 Adapter 去适配不同 Agent 的原生接口。

也就是说：

```text
Harness 的统一格式
        ↓
      Adapter
        ↓
不同 Agent 自己的原生格式
```

这样 Harness 本身就不需要关心底层到底是 LangGraph、Pi、HTTP Agent 还是普通 Python Agent。

但这时候又产生一个新的问题：

Harness、Adapter、Evaluator 之间到底如何交换信息？

如果它们之间全部直接传 `dict`，那么很快就会出现：

```text
输入字段叫什么？
输出字段叫什么？
trace 放在哪里？
metadata 放在哪里？
Evaluator 返回什么结构？
```

如果没有统一约定，系统内部很快就会变得混乱。

所以我们需要设计一层统一协议，也就是 `contracts`。

`contracts` 的作用就是定义 Harness 内部不同模块之间统一的数据结构。

首先是 `TraceEvent`。

一开始容易把 Trace 理解成“Harness 要做什么”，但更准确地说，Trace 并不是用来控制 Harness 执行的，而是用来记录：

> Agent 和 Harness 执行过程中发生了什么。

比如一次 Agent 执行过程中可能发生：

```text
agent_start
↓
model_call
↓
model_result
↓
tool_call
↓
tool_result
↓
model_call
↓
agent_end
```

所以 Trace 更像是 Agent 执行过程中的“黑匣子”。

为了限制 Trace 中允许出现哪些事件，我们定义 `TraceEventType`。

例如：

```text
agent_start
agent_end
model_call
model_result
tool_call
tool_result
error
```

它的作用不是决定 Harness 应该执行什么，而是定义：

> Harness 能识别和记录哪些标准事件类型。

每一个 TraceEvent 除了事件类型之外，还需要记录事件发生时的一些附属信息。

例如 `tool_call` 可能需要记录：

```text
tool_name
arguments
```

而 `model_call` 可能需要记录：

```text
model
messages
tokens
```

不同事件携带的信息是不一样的，所以不能把所有字段全部写死。

因此 TraceEvent 中增加一个：

```python
payload: dict
```

用于保存不同事件对应的动态数据。

这样就形成了统一结构：

```text
TraceEvent
├── type
├── timestamp
└── payload
```

接下来要思考的是：

Harness 如何向 Adapter 发起一次 Agent 执行？

所以我们定义 `AgentRequest`。

最基本的信息肯定是用户输入，因此需要：

```text
input_text
```

但是一次 Agent 执行通常不只有文本输入。

还可能有：

```text
thread_id
conversation_id
user_id
task_id
timeout
tags
```

而不同 Agent 使用的附属字段又可能不一样，所以这里同样不适合全部写死。

因此增加：

```python
metadata: dict
```

于是 AgentRequest 可以理解为：

> Harness 向 Adapter 发起一次标准 Agent 执行请求时使用的数据结构。

注意，这并不意味着外部 Agent 必须接受 AgentRequest。

真正的关系应该是：

```text
AgentRequest
    ↓
Adapter
    ↓
转换成 Agent 自己需要的格式
```

比如 LangGraphAdapter 可能把：

```text
input_text
```

转换成：

```text
messages
state
config
```

PiAdapter 又可能转换成另外一种格式。

所以 Adapter 本质上承担的是“协议转换”的职责。

当 Adapter 调用外部 Agent 后，会得到一个 `raw_result`。

但不同 Agent 的返回结果同样可能完全不同。

有的可能返回：

```python
{
    "answer": "..."
}
```

有的可能返回：

```python
{
    "messages": [...]
}
```

还有的甚至直接返回一个字符串。

所以 Adapter 需要把这些不同的原始结果统一标准化。

于是我们定义 `AgentResult`。

首先肯定需要最终输出，因此有：

```text
output_text
```

其次，我们希望能够记录完整 Agent 执行轨迹，所以需要：

```text
trace
```

另外不同 Agent 可能还会返回：

```text
model
token_usage
finish_reason
session_id
```

等额外信息，所以再提供：

```text
metadata
```

因此：

```text
AgentResult
├── output_text
├── trace
└── metadata
```

它表示：

> 一次 Agent Execution 被 Adapter 标准化之后的统一结果。

整体关系就是：

```text
外部 Agent
    ↓
raw_result
    ↓
Adapter normalize
    ↓
AgentResult
```

到这里，Agent 的执行结果已经进入 Harness 的统一世界。

下一步就需要进行评估。

但是 Evaluator 要拿什么进行比较？

除了 AgentResult 之外，还需要知道：

```text
这个 Agent 原本接受的题目是什么？
我们期望它达到什么结果？
```

因此我们需要统一定义测试用例，也就是 `TestCase`。

这里并不是说用户不能自己定义测试数据，而是：

> 不管原始 Dataset 来源是什么，在进入 Harness Core 之前，都应该统一转换成 TestCase。

比如某个 Dataset 可能使用：

```text
question
reference
```

另一个 Dataset 可能使用：

```text
prompt
gold_answer
```

进入 Harness 后都应该转换成：

```text
TestCase
```

TestCase 至少包含：

```text
id
input_text
expected_output
metadata
```

其中：

`id` 用来唯一标识这道测试用例。

`input_text` 表示需要发送给 Agent 的输入。

`expected_output` 表示参考答案或者期望结果，用于后续评估。

`metadata` 用于保存分类、难度、标签、来源等额外信息。

这里还有一个非常重要的设计：

`expected_output` 只属于评估阶段，不能发送给 Agent。

所以：

```text
TestCase
    ↓
HarnessRunner
    ↓
只取 input_text
    ↓
AgentRequest
```

而：

```text
expected_output
```

会保留下来，在 Agent 执行完成之后交给 Evaluator。

这样可以避免 Agent 在执行时看到标准答案，造成 Evaluation Contamination。

当 Evaluator 拿到：

```text
TestCase
+
AgentResult
```

之后，就可以开始进行评估。

但是 Agent Evaluation 肯定不只有一个指标。

以后可能会有：

```text
Answer Quality
Tool Accuracy
Tool Efficiency
Latency
Cost
Trajectory Quality
```

因此需要统一表示一个指标的评估结果。

于是定义 `MetricResult`。

里面至少需要：

```text
name
score
details
```

其中：

`name` 表示是什么指标。

比如：

```text
keyword_match
answer_quality
tool_efficiency
```

`score` 表示具体得分。

而 `details` 用来解释：

> 为什么得到这个分数。

例如：

```text
score = 0.67
```

还不够，我们可能还希望知道：

```text
matched = ["检索", "生成"]
missing = ["增强"]
```

所以 `details` 才是解释单个指标评分原因的地方。

但是一道 TestCase 通常会经过多个 Evaluator。

因此最终不能只返回一个 MetricResult。

比如一道题可能得到：

```text
Answer Quality = 0.9
Tool Accuracy = 1.0
Latency = 0.7
Cost = 0.8
```

除此之外，我们还需要知道：

```text
这道题是什么？
Agent 实际回答了什么？
完整 Trace 是什么？
执行有没有失败？
最终综合得分是多少？
```

所以我们需要更高一层的数据结构：

```text
CaseResult
```

CaseResult 可以理解成：

> 一道 TestCase 完整执行后的评测档案。

它内部可以包含：

```text
case_id
input_text
expected_output
actual_output
metrics
score
trace
error
```

这里要注意：

`MetricResult.details` 负责解释某一个指标为什么得到某个分数。

而 `CaseResult` 负责聚合一整道测试用例的全部执行和评估信息。

最后，一个 Benchmark 通常不会只有一个 TestCase，而是有几十、几百甚至几千个 Case。

所以我们还需要最外层的：

```text
EvaluationReport
```

它负责聚合多个 CaseResult。

结构大致是：

```text
EvaluationReport
│
├── CaseResult #1
│   ├── MetricResult
│   ├── MetricResult
│   └── TraceEvent[]
│
├── CaseResult #2
│   ├── MetricResult
│   ├── MetricResult
│   └── TraceEvent[]
│
└── CaseResult #3
```

所以从数据结构角度看，我们最终形成了这样一套协议：

```text
AgentRequest
↓
描述一次 Agent 执行请求

AgentResult
↓
描述一次 Agent 标准化执行结果

TraceEvent
↓
描述 Agent 执行过程中发生的事件

TestCase
↓
描述一道标准测试用例

MetricResult
↓
描述一个评估指标的结果

CaseResult
↓
描述一道 TestCase 完整执行后的结果

EvaluationReport
↓
描述一整个 Benchmark 的评估报告
```

但是有了这些协议之后，还需要一个核心模块把所有东西组织起来。

这个模块就是：

```text
HarnessRunner
```

Runner 本身不应该知道：

```text
LangGraph 怎么调用
Pi 怎么调用
Keyword 怎么计算
LLM Judge 怎么实现
```

Runner 只负责整个 Evaluation 生命周期的编排。

也就是：

```text
拿到 TestCase
↓
构造 AgentRequest
↓
交给 AgentAdapter
↓
Adapter 调用具体 Agent
↓
得到并标准化为 AgentResult
↓
交给多个 Evaluator
↓
得到多个 MetricResult
↓
组合成 CaseResult
↓
所有 Case 执行完成
↓
组合成 EvaluationReport
```

因此整个 Harness 最终形成以下架构：

```text
                   Dataset
                      │
                      ▼
                  TestCase
                      │
                      ▼
                HarnessRunner
                      │
                AgentRequest
                      │
                      ▼
                 AgentAdapter
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
      LangGraph       Pi        HTTP
          │           │           │
          └───────────┼───────────┘
                      │
                 raw_result
                      │
                   normalize
                      │
                      ▼
                  AgentResult
                    │      │
                    │      └──────────────┐
                    ▼                     │
                Evaluators                │
                    │                     │
              MetricResult[]              │
                    │                     │
                    └──────────┬──────────┘
                               ▼
                           CaseResult
                               │
                      多个 CaseResult
                               │
                               ▼
                      EvaluationReport
```

其中 Trace 是横穿 Agent 整个执行过程的一条记录链。

例如：

```text
agent_start
↓
model_call
↓
model_result
↓
tool_call
↓
tool_result
↓
model_call
↓
model_result
↓
agent_end
```

最终这些事件会进入 AgentResult 的 `trace` 中。

这样 Harness 以后就不仅能够评价：

```text
最终答案好不好
```

还可以进一步评价：

```text
Agent 调用了哪些工具
工具调用是否正确
调用了多少次
有没有重复调用
模型调用了几轮
执行路径是否合理
是否发生异常
整个 trajectory 是否高效
```

所以目前这个项目真正的核心思想可以总结为：

> Harness Core 不应该依赖任何具体 Agent Framework，而应该通过 Adapter 层隔离不同 Agent 的实现差异，通过 Contracts 定义 Harness 内部统一的数据协议，再由 HarnessRunner 负责执行生命周期编排，由 Evaluator 负责不同维度的评估，最终统一生成 CaseResult 和 EvaluationReport。

目前 v0.1 实现的本质就是：

```text
Framework-Agnostic Agent Evaluation Core
```

而下一阶段继续实现 TraceCollector，就是为了把当前只记录 `agent_start / agent_end / error` 的基础 Trace，升级成能够真正描述 Agent Runtime 行为的完整执行轨迹。

## V0.8 — RunContext and trace lifecycle

HarnessRunner owns one RunContext for each case execution. RunContext creates a
fresh UUID run_id, a private TraceCollector, a monotonic start time, and an
isolated metadata snapshot. case_id remains the dataset identity; it may repeat
across executions. AgentRequest remains a data contract and does not contain
RunContext.

All adapters implement `run(request, context)`. LocalAgentAdapter,
LangGraphAdapter, and TracingDemoAdapter write native execution events into
`context.trace`; they do not own `agent_start` or `agent_end`. The runner records
start, closes successful agent execution, refreshes AgentResult.trace, and only
then invokes evaluators. Failed and timed-out executions retain their partial
trace and finish with an error rather than a successful agent_end. Evaluator
failures preserve the already-completed agent trace and are isolated per case.

LangGraph callbacks share the same collector. LangChain callback UUIDs identify
individual model/tool invocations; they differ from the harness execution UUID.
Graph config metadata contains `harness_run_id`. An explicitly supplied
`thread_id` remains the conversation/checkpoint identity and is never derived
from the harness run_id. CaseResult keeps its existing contract; the execution
identity is available in lifecycle trace metadata.

Run the complete offline regression suite from the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests include a real compiled LangGraph with fake model responses and a real
ToolNode, so no model API key or paid network call is required. The standalone
`backend/app/langgraph_test_runner.py` remains a separate external-model demo.

Timeouts use asyncio.wait_for and cooperative coroutine cancellation. Blocking
synchronous agents and agents that suppress cancellation do not have a hard
process-level deadline. Adapters can preserve events already written to the
shared collector; native events buffered inside an agent and never returned are
not visible to the harness.
