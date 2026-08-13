# PRODUCT-02 Expanded Benchmark

- Executed: 2026-08-13 19:49:53
- Provider / model: DeepSeek Official / 
- Model mode: real
- Fake fallback: 0

## SIMPLE

- Gate: PASS (10/10)
- Calls avg / median / P95: 2.7 / 3.0 / 3.0
- Average tokens / rework / latency: 3662.8 / 0 / 6.89s

| Case | Result | Complexity | Shape | Calls | Tokens | Rework | Latency |
|---|---|---|---|---:|---:|---:|---:|
| A01 | PASS | simple | read_only_research | 3 | 5144 | 0 | 8.98 |
| A04 | PASS | simple | read_only_research | 3 | 3210 | 0 | 5.45 |
| A05 | PASS | simple | read_only_research | 3 | 4141 | 0 | 6.98 |
| A06 | PASS | simple | read_only_research | 3 | 4021 | 0 | 7.64 |
| A08 | PASS | simple | read_only_research | 3 | 3345 | 0 | 6.24 |
| A10 | PASS | simple | code_analysis | 3 | 4505 | 0 | 7.46 |
| A11 | PASS | trivial | direct_response | 0 | 0 | 0 | 1.21 |
| A12 | PASS | simple | read_only_research | 3 | 4510 | 0 | 7.38 |
| A13 | PASS | simple | read_only_research | 3 | 4054 | 0 | 9.02 |
| A15 | PASS | simple | read_only_research | 3 | 3698 | 0 | 8.51 |

## STANDARD

- Gate: PASS (9/10)
- Calls avg / median / P95: 4.2 / 4.0 / 5.0
- Average tokens / rework / latency: 5891 / 0 / 10.92s

| Case | Result | Complexity | Shape | Calls | Tokens | Rework | Latency |
|---|---|---|---|---:|---:|---:|---:|
| B01 | PASS | standard | read_only_research | 5 | 10227 | 0 | 20.2 |
| B03 | PASS | standard | code_analysis | 4 | 7794 | 0 | 13.07 |
| B05 | PASS | standard | code_analysis | 4 | 5637 | 0 | 12.66 |
| B06 | PASS | standard | code_analysis | 4 | 4764 | 0 | 9.84 |
| B07 | PASS | standard | read_only_research | 4 | 4992 | 0 | 10.54 |
| B09 | FAIL | standard | read_only_research | 5 | 5990 | 0 | 7.8 |

Failure B09: `{"stage": "unknown", "agent": "unknown", "code": "budget_exceeded", "root_cause": "role call limit reached: researcher=4", "recovery": "none", "decision": "failed"}`

| B11 | PASS | standard | code_analysis | 4 | 5055 | 0 | 9.77 |
| B15 | PASS | standard | read_only_research | 4 | 4658 | 0 | 7.24 |
| B19 | PASS | standard | read_only_research | 4 | 4880 | 0 | 8.18 |
| B20 | PASS | standard | read_only_research | 4 | 4913 | 0 | 9.87 |

## COMPLEX

- Gate: PASS (5/5)
- Calls avg / median / P95: 5.6 / 5 / 7.6
- Average tokens / rework / latency: 10478.2 / 0 / 20.12s

| Case | Result | Complexity | Shape | Calls | Tokens | Rework | Latency |
|---|---|---|---|---:|---:|---:|---:|
| C01 | PASS | complex | read_only_research | 5 | 7721 | 0 | 17.56 |
| C05 | PASS | complex | read_only_research | 8 | 16735 | 0 | 22.24 |
| C07 | PASS | complex | read_only_research | 6 | 12762 | 0 | 28.45 |
| C11 | PASS | complex | read_only_research | 4 | 7499 | 0 | 15.33 |
| C15 | PASS | complex | read_only_research | 5 | 7674 | 0 | 17.04 |

## SESSION

- Gate: PASS (10/10)
- Calls avg / median / P95: 3.5 / 3.0 / 6.55
- Average tokens / rework / latency: 8553.4 / 0.1 / 11.19s

| Case | Result | Complexity | Shape | Calls | Tokens | Rework | Latency |
|---|---|---|---|---:|---:|---:|---:|
| T01 | PASS | simple | conversation | 3 | 4693 | 0 | 8.01 |
| T02 | PASS | simple | conversation | 3 | 11801 | 0 | 10.61 |
| T03 | PASS | simple | conversation | 3 | 4571 | 0 | 7.62 |
| T04 | PASS | simple | conversation | 3 | 9207 | 0 | 9.58 |
| T05 | PASS | conversation | conversation | 0 | 0 | 0 | 0.01 |
| T06 | PASS | complex | conversation | 6 | 17040 | 0 | 24.8 |
| T07 | PASS | complex | conversation | 6 | 20274 | 1 | 22.54 |
| T08 | PASS | standard | conversation | 7 | 12451 | 0 | 20.28 |
| T09 | PASS | conversation | conversation | 0 | 0 | 0 | 0.01 |
| T10 | PASS | standard | conversation | 4 | 5497 | 0 | 8.47 |

```json
{
  "phase": "PRODUCT-02",
  "provider": "DeepSeek Official",
  "model": "",
  "model_mode": "real",
  "fake_fallback": 0,
  "executed": "2026-08-13 19:49:53",
  "summary": {
    "simple": {
      "passed": 10,
      "total": 10,
      "average_calls": 2.7,
      "median_calls": 3.0,
      "p95_calls": 3.0,
      "average_tokens": 3662.8,
      "average_rework": 0,
      "average_latency": 6.89,
      "gate": true
    },
    "standard": {
      "passed": 9,
      "total": 10,
      "average_calls": 4.2,
      "median_calls": 4.0,
      "p95_calls": 5.0,
      "average_tokens": 5891,
      "average_rework": 0,
      "average_latency": 10.92,
      "gate": true
    },
    "complex": {
      "passed": 5,
      "total": 5,
      "average_calls": 5.6,
      "median_calls": 5,
      "p95_calls": 7.6,
      "average_tokens": 10478.2,
      "average_rework": 0,
      "average_latency": 20.12,
      "gate": true
    },
    "session": {
      "passed": 10,
      "total": 10,
      "average_calls": 3.5,
      "median_calls": 3.0,
      "p95_calls": 6.55,
      "average_tokens": 8553.4,
      "average_rework": 0.1,
      "average_latency": 11.19,
      "gate": true
    }
  },
  "suites": {
    "simple": [
      {
        "id": "A01",
        "goal": "帮我找几个最近热门的 GitHub AI Agent 项目。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "08d60fb5211e",
        "run_id": "dd6112c155344f80",
        "complexity": "simple",
        "shape": "read_only_research",
        "subtasks": 1,
        "roles": [
          "researcher"
        ],
        "calls": 3,
        "tokens": 5144,
        "cost": 0.000793,
        "tools": 1,
        "rework": 0,
        "replan": 0,
        "latency": 8.98,
        "fake_calls": 0
      },
      {
        "id": "A04",
        "goal": "这个项目主要用了什么技术？",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "303d9ad10184",
        "run_id": "83f787427ceb4923",
        "complexity": "simple",
        "shape": "read_only_research",
        "subtasks": 1,
        "roles": [
          "researcher"
        ],
        "calls": 3,
        "tokens": 3210,
        "cost": 0.000479,
        "tools": 1,
        "rework": 0,
        "replan": 0,
        "latency": 5.45,
        "fake_calls": 0
      },
      {
        "id": "A05",
        "goal": "帮我整理一下这个文件夹里的 Python 文件。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "16c6ba3a996c",
        "run_id": "ba072a497e344857",
        "complexity": "simple",
        "shape": "read_only_research",
        "subtasks": 1,
        "roles": [
          "researcher"
        ],
        "calls": 3,
        "tokens": 4141,
        "cost": 0.000631,
        "tools": 2,
        "rework": 0,
        "replan": 0,
        "latency": 6.98,
        "fake_calls": 0
      },
      {
        "id": "A06",
        "goal": "看看这个页面有什么。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "50a06709bbc0",
        "run_id": "c3f65488d32a466a",
        "complexity": "simple",
        "shape": "read_only_research",
        "subtasks": 1,
        "roles": [
          "researcher"
        ],
        "calls": 3,
        "tokens": 4021,
        "cost": 0.000629,
        "tools": 2,
        "rework": 0,
        "replan": 0,
        "latency": 7.64,
        "fake_calls": 0
      },
      {
        "id": "A08",
        "goal": "总结这个项目。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "3c0dd29efb25",
        "run_id": "8c04db588b224989",
        "complexity": "simple",
        "shape": "read_only_research",
        "subtasks": 1,
        "roles": [
          "researcher"
        ],
        "calls": 3,
        "tokens": 3345,
        "cost": 0.000518,
        "tools": 1,
        "rework": 0,
        "replan": 0,
        "latency": 6.24,
        "fake_calls": 0
      },
      {
        "id": "A10",
        "goal": "运行一下测试看看有没有报错。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "e49e13996f75",
        "run_id": "6432789263e0416a",
        "complexity": "simple",
        "shape": "code_analysis",
        "subtasks": 1,
        "roles": [
          "researcher"
        ],
        "calls": 3,
        "tokens": 4505,
        "cost": 0.000671,
        "tools": 2,
        "rework": 0,
        "replan": 0,
        "latency": 7.46,
        "fake_calls": 0
      },
      {
        "id": "A11",
        "goal": "现在几点了？",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "780da8c92127",
        "run_id": "1b998e89ed9f4697",
        "complexity": "trivial",
        "shape": "direct_response",
        "subtasks": 0,
        "roles": [],
        "calls": 0,
        "tokens": 0,
        "cost": 0.0,
        "tools": 0,
        "rework": 0,
        "replan": 0,
        "latency": 1.21,
        "fake_calls": 0
      },
      {
        "id": "A12",
        "goal": "帮我查一下 GitHub 上 stars 最多的 Agent 框架。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "c45aadad2443",
        "run_id": "779ee3ce31324c93",
        "complexity": "simple",
        "shape": "read_only_research",
        "subtasks": 1,
        "roles": [
          "researcher"
        ],
        "calls": 3,
        "tokens": 4510,
        "cost": 0.000663,
        "tools": 1,
        "rework": 0,
        "replan": 0,
        "latency": 7.38,
        "fake_calls": 0
      },
      {
        "id": "A13",
        "goal": "列出当前目录下的文件。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "92f8f067d9be",
        "run_id": "e7884620f33948aa",
        "complexity": "simple",
        "shape": "read_only_research",
        "subtasks": 1,
        "roles": [
          "researcher"
        ],
        "calls": 3,
        "tokens": 4054,
        "cost": 0.000657,
        "tools": 1,
        "rework": 0,
        "replan": 0,
        "latency": 9.02,
        "fake_calls": 0
      },
      {
        "id": "A15",
        "goal": "帮我看看这个仓库是干什么的。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "27915b472a7d",
        "run_id": "9676a34044524718",
        "complexity": "simple",
        "shape": "read_only_research",
        "subtasks": 1,
        "roles": [
          "researcher"
        ],
        "calls": 3,
        "tokens": 3698,
        "cost": 0.000577,
        "tools": 2,
        "rework": 0,
        "replan": 0,
        "latency": 8.51,
        "fake_calls": 0
      }
    ],
    "standard": [
      {
        "id": "B01",
        "goal": "去 GitHub 找几个类似我们的多 Agent 项目，对比一下优缺点。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "05246db1f248",
        "run_id": "3fd7bcabd98c4eb1",
        "complexity": "standard",
        "shape": "read_only_research",
        "subtasks": 2,
        "roles": [
          "researcher"
        ],
        "calls": 5,
        "tokens": 10227,
        "cost": 0.001672,
        "tools": 5,
        "rework": 0,
        "replan": 0,
        "latency": 20.2,
        "fake_calls": 0
      },
      {
        "id": "B03",
        "goal": "检查项目代码结构，告诉我哪里设计得不好。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "6f760cbc4957",
        "run_id": "9c79a37663d545ca",
        "complexity": "standard",
        "shape": "code_analysis",
        "subtasks": 2,
        "roles": [
          "researcher"
        ],
        "calls": 4,
        "tokens": 7794,
        "cost": 0.001217,
        "tools": 3,
        "rework": 0,
        "replan": 0,
        "latency": 13.07,
        "fake_calls": 0
      },
      {
        "id": "B05",
        "goal": "看看项目依赖有没有明显重复。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "420d76ac5d25",
        "run_id": "c91681588c404a39",
        "complexity": "standard",
        "shape": "code_analysis",
        "subtasks": 2,
        "roles": [
          "researcher"
        ],
        "calls": 4,
        "tokens": 5637,
        "cost": 0.000899,
        "tools": 2,
        "rework": 0,
        "replan": 0,
        "latency": 12.66,
        "fake_calls": 0
      },
      {
        "id": "B06",
        "goal": "找出这个项目里最重要的几个模块。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "c51fda5ce9ad",
        "run_id": "ce1678586e014517",
        "complexity": "standard",
        "shape": "code_analysis",
        "subtasks": 2,
        "roles": [
          "researcher"
        ],
        "calls": 4,
        "tokens": 4764,
        "cost": 0.000739,
        "tools": 2,
        "rework": 0,
        "replan": 0,
        "latency": 9.84,
        "fake_calls": 0
      },
      {
        "id": "B07",
        "goal": "帮我分析一下这个项目的性能瓶颈可能在哪。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "358cd99b50af",
        "run_id": "2959af1c41114b12",
        "complexity": "standard",
        "shape": "read_only_research",
        "subtasks": 2,
        "roles": [
          "researcher"
        ],
        "calls": 4,
        "tokens": 4992,
        "cost": 0.000782,
        "tools": 2,
        "rework": 0,
        "replan": 0,
        "latency": 10.54,
        "fake_calls": 0
      },
      {
        "id": "B09",
        "goal": "对比 langgraph 和 crewai 的 license 和活跃度。",
        "passed": false,
        "status": "failed",
        "failure": {
          "stage": "unknown",
          "agent": "unknown",
          "code": "budget_exceeded",
          "root_cause": "role call limit reached: researcher=4",
          "recovery": "none",
          "decision": "failed"
        },
        "task_id": "2f2c6e7b7dfa",
        "run_id": "365935dc12174efc",
        "complexity": "standard",
        "shape": "read_only_research",
        "subtasks": 0,
        "roles": [],
        "calls": 5,
        "tokens": 5990,
        "cost": 0.000919,
        "tools": 4,
        "rework": 0,
        "replan": 0,
        "latency": 7.8,
        "fake_calls": 0
      },
      {
        "id": "B11",
        "goal": "检查一下代码里有没有明显安全问题。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "ee7fa585ffbd",
        "run_id": "8dad6b5dac0c4934",
        "complexity": "standard",
        "shape": "code_analysis",
        "subtasks": 2,
        "roles": [
          "researcher"
        ],
        "calls": 4,
        "tokens": 5055,
        "cost": 0.000796,
        "tools": 2,
        "rework": 0,
        "replan": 0,
        "latency": 9.77,
        "fake_calls": 0
      },
      {
        "id": "B15",
        "goal": "这个项目支持哪些权限模式？分别是什么？",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "33d6f0f4b37f",
        "run_id": "320d3a758f6e44e9",
        "complexity": "standard",
        "shape": "read_only_research",
        "subtasks": 2,
        "roles": [
          "researcher"
        ],
        "calls": 4,
        "tokens": 4658,
        "cost": 0.000718,
        "tools": 2,
        "rework": 0,
        "replan": 0,
        "latency": 7.24,
        "fake_calls": 0
      },
      {
        "id": "B19",
        "goal": "帮我梳理一下这个项目的错误处理逻辑。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "075655252a2d",
        "run_id": "57e15c887f9046ae",
        "complexity": "standard",
        "shape": "read_only_research",
        "subtasks": 2,
        "roles": [
          "researcher"
        ],
        "calls": 4,
        "tokens": 4880,
        "cost": 0.000769,
        "tools": 2,
        "rework": 0,
        "replan": 0,
        "latency": 8.18,
        "fake_calls": 0
      },
      {
        "id": "B20",
        "goal": "评估一下项目对 GitHub API 的依赖是否合理。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "c90dd061c146",
        "run_id": "db8296a4f130464f",
        "complexity": "standard",
        "shape": "read_only_research",
        "subtasks": 2,
        "roles": [
          "researcher"
        ],
        "calls": 4,
        "tokens": 4913,
        "cost": 0.000776,
        "tools": 2,
        "rework": 0,
        "replan": 0,
        "latency": 9.87,
        "fake_calls": 0
      }
    ],
    "complex": [
      {
        "id": "C01",
        "goal": "研究三个 GitHub 项目，然后结合我们的项目提出架构方案，不要直接改代码。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "9e0f5c41ea5b",
        "run_id": "d49717d5abf4413d",
        "complexity": "complex",
        "shape": "read_only_research",
        "subtasks": 3,
        "roles": [
          "researcher"
        ],
        "calls": 5,
        "tokens": 7721,
        "cost": 0.001309,
        "tools": 4,
        "rework": 0,
        "replan": 0,
        "latency": 17.56,
        "fake_calls": 0
      },
      {
        "id": "C05",
        "goal": "调研三种记忆方案，结合项目现状写一份技术选型报告。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "0d10a7bf616d",
        "run_id": "e004b0327cbb4cf8",
        "complexity": "complex",
        "shape": "read_only_research",
        "subtasks": 3,
        "roles": [
          "researcher"
        ],
        "calls": 8,
        "tokens": 16735,
        "cost": 0.002658,
        "tools": 10,
        "rework": 0,
        "replan": 0,
        "latency": 22.24,
        "fake_calls": 0
      },
      {
        "id": "C07",
        "goal": "对比国内外 5 个多 Agent 框架，写对比报告并给落地建议。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "e23388c041c5",
        "run_id": "f269d130322c4ca4",
        "complexity": "complex",
        "shape": "read_only_research",
        "subtasks": 3,
        "roles": [
          "researcher"
        ],
        "calls": 6,
        "tokens": 12762,
        "cost": 0.002234,
        "tools": 6,
        "rework": 0,
        "replan": 0,
        "latency": 28.45,
        "fake_calls": 0
      },
      {
        "id": "C11",
        "goal": "评估引入向量数据库的收益与风险，给出决策建议。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "388985169e18",
        "run_id": "f67d94a57e05447e",
        "complexity": "complex",
        "shape": "read_only_research",
        "subtasks": 3,
        "roles": [
          "researcher"
        ],
        "calls": 4,
        "tokens": 7499,
        "cost": 0.001202,
        "tools": 4,
        "rework": 0,
        "replan": 0,
        "latency": 15.33,
        "fake_calls": 0
      },
      {
        "id": "C15",
        "goal": "制定项目下一阶段里程碑，按风险排序并给出实施顺序。",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "0e6f37a8ec64",
        "run_id": "1c7c7bb3eab743d2",
        "complexity": "complex",
        "shape": "read_only_research",
        "subtasks": 3,
        "roles": [
          "researcher"
        ],
        "calls": 5,
        "tokens": 7674,
        "cost": 0.001271,
        "tools": 4,
        "rework": 0,
        "replan": 0,
        "latency": 17.04,
        "fake_calls": 0
      }
    ],
    "session": [
      {
        "id": "T01",
        "goal": "找几个最近热门的 Agent 项目",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "9b9c8250de3e",
        "run_id": "5d9b43d7053b4b73",
        "complexity": "simple",
        "shape": "conversation",
        "subtasks": 0,
        "roles": [],
        "calls": 3,
        "tokens": 4693,
        "cost": 0.0,
        "tools": 1,
        "rework": 0,
        "replan": 0,
        "latency": 8.01,
        "fake_calls": 0
      },
      {
        "id": "T02",
        "goal": "第二个详细看看",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "de56300bc13d",
        "run_id": "7a11e6933f06490b",
        "complexity": "simple",
        "shape": "conversation",
        "subtasks": 0,
        "roles": [],
        "calls": 3,
        "tokens": 11801,
        "cost": 0.0,
        "tools": 3,
        "rework": 0,
        "replan": 0,
        "latency": 10.61,
        "fake_calls": 0
      },
      {
        "id": "T03",
        "goal": "跟我们的项目比较一下",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "02ae98665519",
        "run_id": "515f9a5d95be4cd8",
        "complexity": "simple",
        "shape": "conversation",
        "subtasks": 0,
        "roles": [],
        "calls": 3,
        "tokens": 4571,
        "cost": 0.0,
        "tools": 1,
        "rework": 0,
        "replan": 0,
        "latency": 7.62,
        "fake_calls": 0
      },
      {
        "id": "T04",
        "goal": "哪些东西值得我们借鉴",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "cb4b435b7d79",
        "run_id": "bca21a771a684dff",
        "complexity": "simple",
        "shape": "conversation",
        "subtasks": 0,
        "roles": [],
        "calls": 3,
        "tokens": 9207,
        "cost": 0.0,
        "tools": 2,
        "rework": 0,
        "replan": 0,
        "latency": 9.58,
        "fake_calls": 0
      },
      {
        "id": "T05",
        "goal": "先别改代码",
        "passed": true,
        "status": "confirmed",
        "failure": null,
        "task_id": null,
        "run_id": null,
        "complexity": "conversation",
        "shape": "conversation",
        "subtasks": 0,
        "roles": [],
        "calls": 0,
        "tokens": 0,
        "cost": 0.0,
        "tools": 0,
        "rework": 0,
        "replan": 0,
        "latency": 0.01,
        "fake_calls": 0
      },
      {
        "id": "T06",
        "goal": "那先写个方案",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "79c2eb41b37c",
        "run_id": "e04430595bca42ab",
        "complexity": "complex",
        "shape": "conversation",
        "subtasks": 0,
        "roles": [],
        "calls": 6,
        "tokens": 17040,
        "cost": 0.0,
        "tools": 2,
        "rework": 0,
        "replan": 0,
        "latency": 24.8,
        "fake_calls": 0
      },
      {
        "id": "T07",
        "goal": "继续",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "c7d923dc8772",
        "run_id": "a5c729ef53d349bc",
        "complexity": "complex",
        "shape": "conversation",
        "subtasks": 0,
        "roles": [],
        "calls": 6,
        "tokens": 20274,
        "cost": 0.0,
        "tools": 2,
        "rework": 1,
        "replan": 0,
        "latency": 22.54,
        "fake_calls": 0
      },
      {
        "id": "T08",
        "goal": "把第一项实施",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "d2f500983611",
        "run_id": "21078d9240194263",
        "complexity": "standard",
        "shape": "conversation",
        "subtasks": 0,
        "roles": [],
        "calls": 7,
        "tokens": 12451,
        "cost": 0.0,
        "tools": 4,
        "rework": 0,
        "replan": 0,
        "latency": 20.28,
        "fake_calls": 0
      },
      {
        "id": "T09",
        "goal": "看一下结果",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": null,
        "run_id": null,
        "complexity": "conversation",
        "shape": "conversation",
        "subtasks": 0,
        "roles": [],
        "calls": 0,
        "tokens": 0,
        "cost": 0.0,
        "tools": 0,
        "rework": 0,
        "replan": 0,
        "latency": 0.01,
        "fake_calls": 0
      },
      {
        "id": "T10",
        "goal": "还有没有问题",
        "passed": true,
        "status": "completed",
        "failure": null,
        "task_id": "eef3853b6cdd",
        "run_id": "4bb444c2cd864548",
        "complexity": "standard",
        "shape": "conversation",
        "subtasks": 0,
        "roles": [],
        "calls": 4,
        "tokens": 5497,
        "cost": 0.0,
        "tools": 1,
        "rework": 0,
        "replan": 0,
        "latency": 8.47,
        "fake_calls": 0
      }
    ]
  }
}
```
