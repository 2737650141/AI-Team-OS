// Diff 查看器（010 十七/十三）：Unified/Split；逐行渲染，不用整段 <pre> 展示
import { useMemo, useState } from "react";

import { useI18n } from "../i18n";

interface Line {
  kind: "ctx" | "add" | "del" | "hunk";
  text: string;
  oldNo: number | null;
  newNo: number | null;
}

function parseDiff(diff: string): Line[] {
  const out: Line[] = [];
  let oldNo = 0;
  let newNo = 0;
  for (const raw of diff.split("\n")) {
    const line = raw;
    if (line.startsWith("@@")) {
      out.push({ kind: "hunk", text: line, oldNo: null, newNo: null });
      const m = line.match(/^-(\d+)(?:,\d+)? \+(\d+)/);
      if (m) {
        oldNo = parseInt(m[1], 10);
        newNo = parseInt(m[2], 10);
      }
      continue;
    }
    if (line.startsWith("+")) {
      out.push({ kind: "add", text: line, oldNo: null, newNo: newNo > 0 ? newNo : null });
      if (newNo > 0) newNo += 1;
    } else if (line.startsWith("-")) {
      out.push({ kind: "del", text: line, oldNo: oldNo > 0 ? oldNo : null, newNo: null });
      if (oldNo > 0) oldNo += 1;
    } else {
      out.push({ kind: "ctx", text: line, oldNo: oldNo > 0 ? oldNo : null, newNo: newNo > 0 ? newNo : null });
      if (oldNo > 0) oldNo += 1;
      if (newNo > 0) newNo += 1;
    }
  }
  return out;
}

export function DiffViewer({ diff, files }: { diff: string; files?: string[] }) {
  const { t } = useI18n();
  const [mode, setMode] = useState<"unified" | "split">("unified");
  const lines = useMemo(() => parseDiff(diff || ""), [diff]);
  const stats = useMemo(() => {
    let add = 0;
    let del = 0;
    for (const l of lines) {
      if (l.kind === "add") add += 1;
      if (l.kind === "del") del += 1;
    }
    return { add, del };
  }, [lines]);

  return (
    <div className="diff">
      <div className="diff-toolbar">
        <div className="diff-stats">
          {files?.length ? <span>{files.length} file(s)</span> : null}
          <span className="add">+{stats.add}</span>
          <span className="del">-{stats.del}</span>
        </div>
        <div className="seg">
          <button className={mode === "unified" ? "on" : ""} onClick={() => setMode("unified")}>
            {t("diff.unified")}
          </button>
          <button className={mode === "split" ? "on" : ""} onClick={() => setMode("split")}>
            {t("diff.split")}
          </button>
        </div>
      </div>
      <div className={`diff-body ${mode}`}>
        {lines.map((l, i) => (
          <div key={i} className={`dl dl-${l.kind}`}>
            <span className="dl-no">{l.oldNo ?? ""}</span>
            <span className="dl-no">{l.newNo ?? ""}</span>
            <span className="dl-text">{l.text || " "}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
