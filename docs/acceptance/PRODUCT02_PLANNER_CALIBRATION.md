# PRODUCT-02 Planner Calibration

- Source: 10 real STANDARD task traces
- Gate: PASS
- Max subtasks observed: 2 (limit 4)
- Executable role/capability correctness: 100%
- Budget compliance: 100%
- No unnecessary Executor on read-only work: 100%

| Case | Subtasks | Bounded | Role/capability | Budget | No unnecessary agent |
|---|---:|---|---|---|---|
| B01 | 2 | True | True | True | True |
| B03 | 2 | True | True | True | True |
| B05 | 2 | True | True | True | True |
| B06 | 2 | True | True | True | True |
| B07 | 2 | True | True | True | True |
| B09 | 2 | True | True | True | True |
| B11 | 2 | True | True | True | True |
| B15 | 2 | True | True | True | True |
| B19 | 2 | True | True | True | True |
| B20 | 2 | True | True | True | True |

```json
{
  "phase": "PRODUCT-02",
  "source": "real_standard_trace",
  "total": 10,
  "passed": 10,
  "standard_max_subtasks": 2,
  "gate": true,
  "rows": [
    {
      "id": "B01",
      "run_id": "3fd7bcabd98c4eb1",
      "subtasks": 2,
      "bounded": true,
      "role_capability": true,
      "budget": true,
      "executable": true,
      "no_unnecessary_agents": true,
      "passed": true
    },
    {
      "id": "B03",
      "run_id": "9c79a37663d545ca",
      "subtasks": 2,
      "bounded": true,
      "role_capability": true,
      "budget": true,
      "executable": true,
      "no_unnecessary_agents": true,
      "passed": true
    },
    {
      "id": "B05",
      "run_id": "c91681588c404a39",
      "subtasks": 2,
      "bounded": true,
      "role_capability": true,
      "budget": true,
      "executable": true,
      "no_unnecessary_agents": true,
      "passed": true
    },
    {
      "id": "B06",
      "run_id": "ce1678586e014517",
      "subtasks": 2,
      "bounded": true,
      "role_capability": true,
      "budget": true,
      "executable": true,
      "no_unnecessary_agents": true,
      "passed": true
    },
    {
      "id": "B07",
      "run_id": "2959af1c41114b12",
      "subtasks": 2,
      "bounded": true,
      "role_capability": true,
      "budget": true,
      "executable": true,
      "no_unnecessary_agents": true,
      "passed": true
    },
    {
      "id": "B09",
      "run_id": "365935dc12174efc",
      "subtasks": 2,
      "bounded": true,
      "role_capability": true,
      "budget": true,
      "executable": true,
      "no_unnecessary_agents": true,
      "passed": true
    },
    {
      "id": "B11",
      "run_id": "8dad6b5dac0c4934",
      "subtasks": 2,
      "bounded": true,
      "role_capability": true,
      "budget": true,
      "executable": true,
      "no_unnecessary_agents": true,
      "passed": true
    },
    {
      "id": "B15",
      "run_id": "320d3a758f6e44e9",
      "subtasks": 2,
      "bounded": true,
      "role_capability": true,
      "budget": true,
      "executable": true,
      "no_unnecessary_agents": true,
      "passed": true
    },
    {
      "id": "B19",
      "run_id": "57e15c887f9046ae",
      "subtasks": 2,
      "bounded": true,
      "role_capability": true,
      "budget": true,
      "executable": true,
      "no_unnecessary_agents": true,
      "passed": true
    },
    {
      "id": "B20",
      "run_id": "db8296a4f130464f",
      "subtasks": 2,
      "bounded": true,
      "role_capability": true,
      "budget": true,
      "executable": true,
      "no_unnecessary_agents": true,
      "passed": true
    }
  ]
}
```
