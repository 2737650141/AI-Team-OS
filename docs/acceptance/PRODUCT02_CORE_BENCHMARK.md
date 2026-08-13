# PRODUCT-02 Core Benchmark

- Executed: 2026-08-13 19:14:57
- Provider / model: DeepSeek Official / 
- Fake fallback: 0
- Gate: PASS (9/9)
- Average calls: 5.22; P95(max for this small gate): 7

| Round | Case | Result | Shape | Roles | Calls | Tokens | Cost | Rework | Latency |
|---|---|---|---|---|---:|---:|---:|---:|---:|
| 1 | A | PASS | read_only_research | researcher | 5 | 11127 | 0.001851 | 0 | 22.31 |
| 1 | B | PASS | code_change | executor,researcher | 6 | 10482 | 0.001653 | 0 | 15.44 |
| 1 | C | PASS | code_analysis | researcher | 4 | 13418 | 0.002108 | 0 | 14.18 |
| 2 | A | PASS | read_only_research | researcher | 5 | 10846 | 0.001772 | 0 | 19.16 |
| 2 | B | PASS | code_change | executor,researcher | 6 | 10148 | 0.001577 | 0 | 12.82 |
| 2 | C | PASS | code_analysis | researcher | 5 | 15584 | 0.002450 | 0 | 16.05 |
| 3 | A | PASS | read_only_research | researcher | 5 | 10174 | 0.001654 | 0 | 18.34 |
| 3 | B | PASS | code_change | executor,researcher | 7 | 12471 | 0.002016 | 0 | 22.48 |
| 3 | C | PASS | code_analysis | researcher | 4 | 13553 | 0.002147 | 0 | 16.76 |

```json
{
  "phase": "PRODUCT-02",
  "mode": "9",
  "provider": "DeepSeek Official",
  "model": "",
  "fake_fallback": 0,
  "limits": {
    "requests": 72,
    "tokens": 270000,
    "cost": 3.0,
    "wall_time": 1200.0
  },
  "rounds": [
    true,
    true,
    true
  ],
  "passed": 9,
  "total": 9,
  "average_calls": 5.22,
  "p95_calls": 7,
  "rows": [
    {
      "case": "A",
      "passed": true,
      "status": "completed",
      "failure": null,
      "task_id": "f3cee43cd2a2",
      "run_id": "daf8fb45360b4f04",
      "shape": "read_only_research",
      "subtasks": 2,
      "roles": [
        "researcher"
      ],
      "calls": 5,
      "tokens": 11127,
      "cost": 0.001851,
      "tools": 4,
      "writes": [],
      "rework": 0,
      "replan": 0,
      "latency": 22.31,
      "fake_calls": 0
    },
    {
      "case": "B",
      "passed": true,
      "status": "completed",
      "failure": null,
      "task_id": "377540f573dd",
      "run_id": "211fc273f9c3479d",
      "shape": "code_change",
      "subtasks": 4,
      "roles": [
        "executor",
        "researcher"
      ],
      "calls": 6,
      "tokens": 10482,
      "cost": 0.001653,
      "tools": 5,
      "writes": [],
      "rework": 0,
      "replan": 0,
      "latency": 15.44,
      "fake_calls": 0
    },
    {
      "case": "C",
      "passed": true,
      "status": "completed",
      "failure": null,
      "task_id": "6d12862d2639",
      "run_id": "2f91114287304158",
      "shape": "code_analysis",
      "subtasks": 2,
      "roles": [
        "researcher"
      ],
      "calls": 4,
      "tokens": 13418,
      "cost": 0.002108,
      "tools": 10,
      "writes": [],
      "rework": 0,
      "replan": 0,
      "latency": 14.18,
      "fake_calls": 0
    },
    {
      "case": "A",
      "passed": true,
      "status": "completed",
      "failure": null,
      "task_id": "43521bf63e32",
      "run_id": "f0d49d9bf83641aa",
      "shape": "read_only_research",
      "subtasks": 2,
      "roles": [
        "researcher"
      ],
      "calls": 5,
      "tokens": 10846,
      "cost": 0.001772,
      "tools": 4,
      "writes": [],
      "rework": 0,
      "replan": 0,
      "latency": 19.16,
      "fake_calls": 0
    },
    {
      "case": "B",
      "passed": true,
      "status": "completed",
      "failure": null,
      "task_id": "e0ea5091d4d1",
      "run_id": "1c946a75280f4d56",
      "shape": "code_change",
      "subtasks": 4,
      "roles": [
        "executor",
        "researcher"
      ],
      "calls": 6,
      "tokens": 10148,
      "cost": 0.001577,
      "tools": 5,
      "writes": [],
      "rework": 0,
      "replan": 0,
      "latency": 12.82,
      "fake_calls": 0
    },
    {
      "case": "C",
      "passed": true,
      "status": "completed",
      "failure": null,
      "task_id": "8efbae9c3d67",
      "run_id": "38d60aca3fa74a71",
      "shape": "code_analysis",
      "subtasks": 2,
      "roles": [
        "researcher"
      ],
      "calls": 5,
      "tokens": 15584,
      "cost": 0.00245,
      "tools": 7,
      "writes": [],
      "rework": 0,
      "replan": 0,
      "latency": 16.05,
      "fake_calls": 0
    },
    {
      "case": "A",
      "passed": true,
      "status": "completed",
      "failure": null,
      "task_id": "c330eb6137ff",
      "run_id": "b6283fa882044c8b",
      "shape": "read_only_research",
      "subtasks": 2,
      "roles": [
        "researcher"
      ],
      "calls": 5,
      "tokens": 10174,
      "cost": 0.001654,
      "tools": 3,
      "writes": [],
      "rework": 0,
      "replan": 0,
      "latency": 18.34,
      "fake_calls": 0
    },
    {
      "case": "B",
      "passed": true,
      "status": "completed",
      "failure": null,
      "task_id": "e6b7a075c440",
      "run_id": "2f52777970e34ff6",
      "shape": "code_change",
      "subtasks": 4,
      "roles": [
        "executor",
        "researcher"
      ],
      "calls": 7,
      "tokens": 12471,
      "cost": 0.002016,
      "tools": 5,
      "writes": [],
      "rework": 0,
      "replan": 0,
      "latency": 22.48,
      "fake_calls": 0
    },
    {
      "case": "C",
      "passed": true,
      "status": "completed",
      "failure": null,
      "task_id": "ee3c224aeab4",
      "run_id": "d953ca8053484fae",
      "shape": "code_analysis",
      "subtasks": 2,
      "roles": [
        "researcher"
      ],
      "calls": 4,
      "tokens": 13553,
      "cost": 0.002147,
      "tools": 10,
      "writes": [],
      "rework": 0,
      "replan": 0,
      "latency": 16.76,
      "fake_calls": 0
    }
  ],
  "gate": true
}
```
