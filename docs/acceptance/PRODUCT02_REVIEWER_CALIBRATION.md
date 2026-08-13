# PRODUCT-02 Reviewer Calibration

- Model mode: real
- Fake fallback: 0
- Gate: PASS
- Actual counts: {'PASS': 5, 'PASS_WITH_NOTES': 5, 'REWORK': 5, 'BLOCK': 3}
- False reject rate on explicit PASS cases: 0%

| Case | Expected | Actual | Calls | Tokens | Result |
|---|---|---|---:|---:|---|
| P1 | PASS | PASS | 1 | 898 | PASS |
| P2 | PASS | PASS | 1 | 908 | PASS |
| P3 | PASS | PASS | 1 | 906 | PASS |
| P4 | PASS | PASS | 1 | 908 | PASS |
| P5 | PASS | PASS | 1 | 914 | PASS |
| N1 | PASS_WITH_NOTES | PASS_WITH_NOTES | 1 | 919 | PASS |
| N2 | PASS_WITH_NOTES | PASS_WITH_NOTES | 1 | 935 | PASS |
| N3 | PASS_WITH_NOTES | PASS_WITH_NOTES | 1 | 920 | PASS |
| N4 | PASS_WITH_NOTES | PASS_WITH_NOTES | 2 | 2337 | PASS |
| N5 | PASS_WITH_NOTES | PASS_WITH_NOTES | 1 | 919 | PASS |
| R1 | REWORK | REWORK | 1 | 1087 | PASS |
| R2 | REWORK | REWORK | 1 | 1073 | PASS |
| R3 | REWORK | REWORK | 1 | 1072 | PASS |
| R4 | REWORK | REWORK | 1 | 1073 | PASS |
| R5 | REWORK | REWORK | 1 | 1073 | PASS |
| B1 | BLOCK | BLOCK | 1 | 954 | PASS |
| B2 | BLOCK | BLOCK | 1 | 952 | PASS |
| B3 | BLOCK | BLOCK | 1 | 973 | PASS |

```json
{
  "phase": "PRODUCT-02",
  "model_mode": "real",
  "fake_fallback": 0,
  "gate": true,
  "expected_cases": 18,
  "actual_counts": {
    "PASS": 5,
    "PASS_WITH_NOTES": 5,
    "REWORK": 5,
    "BLOCK": 3
  },
  "false_rejects": 0,
  "false_reject_rate": 0.0,
  "rows": [
    {
      "id": "P1",
      "expected": "PASS",
      "actual": "PASS",
      "passed": true,
      "calls": 1,
      "tokens": 898,
      "latency": 2.91,
      "summary": "",
      "issues": []
    },
    {
      "id": "P2",
      "expected": "PASS",
      "actual": "PASS",
      "passed": true,
      "calls": 1,
      "tokens": 908,
      "latency": 2.72,
      "summary": "",
      "issues": []
    },
    {
      "id": "P3",
      "expected": "PASS",
      "actual": "PASS",
      "passed": true,
      "calls": 1,
      "tokens": 906,
      "latency": 2.77,
      "summary": "",
      "issues": []
    },
    {
      "id": "P4",
      "expected": "PASS",
      "actual": "PASS",
      "passed": true,
      "calls": 1,
      "tokens": 908,
      "latency": 2.64,
      "summary": "",
      "issues": []
    },
    {
      "id": "P5",
      "expected": "PASS",
      "actual": "PASS",
      "passed": true,
      "calls": 1,
      "tokens": 914,
      "latency": 2.79,
      "summary": "",
      "issues": []
    },
    {
      "id": "N1",
      "expected": "PASS_WITH_NOTES",
      "actual": "PASS_WITH_NOTES",
      "passed": true,
      "calls": 1,
      "tokens": 919,
      "latency": 2.8,
      "summary": "",
      "issues": []
    },
    {
      "id": "N2",
      "expected": "PASS_WITH_NOTES",
      "actual": "PASS_WITH_NOTES",
      "passed": true,
      "calls": 1,
      "tokens": 935,
      "latency": 3.13,
      "summary": "",
      "issues": []
    },
    {
      "id": "N3",
      "expected": "PASS_WITH_NOTES",
      "actual": "PASS_WITH_NOTES",
      "passed": true,
      "calls": 1,
      "tokens": 920,
      "latency": 2.97,
      "summary": "",
      "issues": []
    },
    {
      "id": "N4",
      "expected": "PASS_WITH_NOTES",
      "actual": "PASS_WITH_NOTES",
      "passed": true,
      "calls": 2,
      "tokens": 2337,
      "latency": 4.61,
      "summary": "",
      "issues": []
    },
    {
      "id": "N5",
      "expected": "PASS_WITH_NOTES",
      "actual": "PASS_WITH_NOTES",
      "passed": true,
      "calls": 1,
      "tokens": 919,
      "latency": 3.1,
      "summary": "",
      "issues": []
    },
    {
      "id": "R1",
      "expected": "REWORK",
      "actual": "REWORK",
      "passed": true,
      "calls": 1,
      "tokens": 1087,
      "latency": 3.81,
      "summary": "",
      "issues": []
    },
    {
      "id": "R2",
      "expected": "REWORK",
      "actual": "REWORK",
      "passed": true,
      "calls": 1,
      "tokens": 1073,
      "latency": 4.14,
      "summary": "",
      "issues": []
    },
    {
      "id": "R3",
      "expected": "REWORK",
      "actual": "REWORK",
      "passed": true,
      "calls": 1,
      "tokens": 1072,
      "latency": 4.03,
      "summary": "",
      "issues": []
    },
    {
      "id": "R4",
      "expected": "REWORK",
      "actual": "REWORK",
      "passed": true,
      "calls": 1,
      "tokens": 1073,
      "latency": 3.48,
      "summary": "",
      "issues": []
    },
    {
      "id": "R5",
      "expected": "REWORK",
      "actual": "REWORK",
      "passed": true,
      "calls": 1,
      "tokens": 1073,
      "latency": 3.85,
      "summary": "",
      "issues": []
    },
    {
      "id": "B1",
      "expected": "BLOCK",
      "actual": "BLOCK",
      "passed": true,
      "calls": 1,
      "tokens": 954,
      "latency": 3.21,
      "summary": "",
      "issues": []
    },
    {
      "id": "B2",
      "expected": "BLOCK",
      "actual": "BLOCK",
      "passed": true,
      "calls": 1,
      "tokens": 952,
      "latency": 2.95,
      "summary": "",
      "issues": []
    },
    {
      "id": "B3",
      "expected": "BLOCK",
      "actual": "BLOCK",
      "passed": true,
      "calls": 1,
      "tokens": 973,
      "latency": 3.24,
      "summary": "",
      "issues": []
    }
  ]
}
```
