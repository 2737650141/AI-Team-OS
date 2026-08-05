# Evidence 系统（docs/architecture/EVIDENCE_SYSTEM.md）

对应总管令 006 五。M3-B 实现。

## 1. EvidenceRecord（14 字段）

evidence_id / task_id / subtask_id / tool_name / source_type / source_uri / title /
retrieved_at / content_type / content_hash / content_length / summary / snapshot_ref /
reliability / freshness / metadata（+truncated / page_range / ocr_required）。

## 2. 原则（5.1）

- Evidence ID 全局唯一（uuid）。
- 原始内容与摘要分离：快照在 `runtime/evidence/<task_id>/<evidence_id>.<ext>`，摘要入记录。
- Claim 只引用 Evidence ID；Reviewer 可经 ID 找到原始快照。
- 内容哈希（sha256 前 32 位）用于发现变化与去重；同一内容不重复存储
  （重复来源记入 metadata.duplicates）。
- 用户最终报告显示来源（source_uri）与读取时间（retrieved_at）。

## 3. 快照安全（5.2）

- 目录 Git 忽略（.gitignore: runtime/）。
- 快照与摘要均过统一脱敏（app/core/secrets.py）——API Key/Token/私钥不落盘。

## 4. 上限与截断（5.3）

- 每项快照默认 512KB；超限保存受限快照并标记 `truncated=true`。
- 每任务 Evidence 数上限（默认 200）；读取字节总量上限（网关配额）。
- 不静默假装内容完整：截断/配额超限均有明确标记与审计。

## 5. 固化时机

工具结果必须**先固化 Evidence 再交给模型**（Tool Gateway 第 11 步执行）；
模型只接收 Evidence ID 与摘要引用。
