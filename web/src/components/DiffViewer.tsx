import { useMemo, useRef, useState } from "react";

import type { DiffFile } from "../api/types";
import { useI18n } from "../i18n";

type Kind = "ctx" | "add" | "del" | "hunk";
interface Line { kind: Kind; text: string; oldNo: number | null; newNo: number | null }
interface FileBlock { path: string; status: string; lines: Line[] }
interface SplitRow { left: Line | null; right: Line | null }

export function DiffViewer({ diff, files }: { diff: string; files?: Array<DiffFile | string> }) {
  const { t } = useI18n();
  const [mode, setMode] = useState<"unified" | "split">("split");
  const [sync, setSync] = useState(true);
  const [activeFile, setActiveFile] = useState(0);
  const leftRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);
  const syncing = useRef(false);
  const parsed = useMemo(() => parseDiff(diff || ""), [diff]);
  const fileList = useMemo(() => mergeFiles(parsed, files), [parsed, files]);
  const stats = useMemo(() => {
    const lines = parsed.flatMap((file) => file.lines);
    return {
      add: lines.filter((line) => line.kind === "add").length,
      del: lines.filter((line) => line.kind === "del").length,
    };
  }, [parsed]);
  const splitRows = useMemo(() => parsed[activeFile] ? splitFile(parsed[activeFile]) : [], [parsed, activeFile]);

  const mirrorScroll = (source: HTMLDivElement, target: HTMLDivElement | null) => {
    if (!sync || !target || syncing.current) return;
    syncing.current = true;
    const maxSource = Math.max(source.scrollHeight - source.clientHeight, 1);
    const maxTarget = Math.max(target.scrollHeight - target.clientHeight, 0);
    target.scrollTop = (source.scrollTop / maxSource) * maxTarget;
    target.scrollLeft = source.scrollLeft;
    requestAnimationFrame(() => { syncing.current = false; });
  };

  return (
    <div className="diff diff-v2">
      <div className="diff-toolbar">
        <div className="diff-stats">
          <strong>{fileList.length} {t("diff.filesChanged")}</strong>
          <span className="add">+{stats.add}</span>
          <span className="del">−{stats.del}</span>
        </div>
        <div className="diff-controls">
          {mode === "split" && (
            <label className="check-row compact">
              <input type="checkbox" checked={sync} onChange={(event) => setSync(event.target.checked)} />
              {t("diff.syncScroll")}
            </label>
          )}
          <div className="seg">
            <button className={mode === "unified" ? "on" : ""} onClick={() => setMode("unified")}>{t("diff.unified")}</button>
            <button className={mode === "split" ? "on" : ""} onClick={() => setMode("split")}>{t("diff.split")}</button>
          </div>
        </div>
      </div>
      <div className="changed-files" aria-label={t("diff.changedFiles")}>
        <span className="changed-files-title">{t("diff.changedFiles")}</span>
        {fileList.map((file, index) => (
          <button className={mode === "split" && activeFile === index ? "active" : ""} key={`${file.path}-${index}`} onClick={() => {
            setActiveFile(index);
            if (mode === "unified") document.getElementById(`diff-file-${index}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
          }}>
            <span className={`file-status status-${file.status.toLowerCase()}`}>{file.status}</span>
            {file.path}
          </button>
        ))}
      </div>
      {mode === "unified" ? (
        <div className="diff-body unified">
          {parsed.map((file, fileIndex) => (
            <section key={`${file.path}-${fileIndex}`} id={`diff-file-${fileIndex}`} className="diff-file-block">
              <div className="diff-file-header"><span className={`file-status status-${file.status.toLowerCase()}`}>{file.status}</span>{file.path}</div>
              {file.lines.map((line, index) => <UnifiedLine key={index} line={line} />)}
            </section>
          ))}
        </div>
      ) : (
        <div className="split-diff">
          <div className="split-title"><span>{t("diff.before")}</span><span>{t("diff.after")}</span></div>
          <div className="split-panes">
            <div ref={leftRef} className="split-pane" onScroll={(event) => mirrorScroll(event.currentTarget, rightRef.current)}>
              {splitRows.map((row, index) => <SplitLine key={index} line={row.left} side="left" />)}
            </div>
            <div ref={rightRef} className="split-pane" onScroll={(event) => mirrorScroll(event.currentTarget, leftRef.current)}>
              {splitRows.map((row, index) => <SplitLine key={index} line={row.right} side="right" />)}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function UnifiedLine({ line }: { line: Line }) {
  return <div className={`dl dl-${line.kind}`}><span className="dl-no">{line.oldNo ?? ""}</span><span className="dl-no">{line.newNo ?? ""}</span><span className="dl-text">{line.text || " "}</span></div>;
}

function SplitLine({ line, side }: { line: Line | null; side: "left" | "right" }) {
  if (!line) return <div className="split-line split-empty"><span className="dl-no" /><span className="dl-text"> </span></div>;
  const number = side === "left" ? line.oldNo : line.newNo;
  return <div className={`split-line dl-${line.kind}`}><span className="dl-no">{number ?? ""}</span><span className="dl-text">{line.text || " "}</span></div>;
}

function parseDiff(diff: string): FileBlock[] {
  const blocks: FileBlock[] = [];
  let current: FileBlock = { path: "changes", status: "M", lines: [] };
  let oldNo = 0;
  let newNo = 0;
  let oldPath = "";
  const pushCurrent = () => {
    if (current.lines.length || blocks.length === 0) blocks.push(current);
  };
  for (const raw of diff.split("\n")) {
    if (raw.startsWith("diff --git ")) {
      if (current.lines.length) pushCurrent();
      const parts = raw.split(" ");
      current = { path: parts[3]?.replace(/^b\//, "") || `file-${blocks.length + 1}`, status: "M", lines: [] };
      oldNo = 0;
      newNo = 0;
      continue;
    }
    if (raw.startsWith("--- ")) {
      oldPath = raw.slice(4).trim().replace(/^a\//, "");
      continue;
    }
    if (raw.startsWith("+++ ")) {
      const newPath = raw.slice(4).trim().replace(/^b\//, "");
      current.path = newPath !== "/dev/null" ? newPath : oldPath;
      current.status = oldPath === "/dev/null" ? "A" : newPath === "/dev/null" ? "D" : "M";
      continue;
    }
    if (raw.startsWith("@@")) {
      current.lines.push({ kind: "hunk", text: raw, oldNo: null, newNo: null });
      const match = raw.match(/^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@/);
      if (match) {
        oldNo = Number(match[1]);
        newNo = Number(match[2]);
      }
      continue;
    }
    if (raw.startsWith("+") && !raw.startsWith("+++")) {
      current.lines.push({ kind: "add", text: raw.slice(1), oldNo: null, newNo: newNo || null });
      if (newNo) newNo += 1;
    } else if (raw.startsWith("-") && !raw.startsWith("---")) {
      current.lines.push({ kind: "del", text: raw.slice(1), oldNo: oldNo || null, newNo: null });
      if (oldNo) oldNo += 1;
    } else if (oldNo || newNo) {
      current.lines.push({ kind: "ctx", text: raw.startsWith(" ") ? raw.slice(1) : raw, oldNo: oldNo || null, newNo: newNo || null });
      if (oldNo) oldNo += 1;
      if (newNo) newNo += 1;
    }
  }
  if (current.lines.length || blocks.length === 0) pushCurrent();
  return blocks.filter((block) => block.lines.length > 0);
}

function splitFile(file: FileBlock): SplitRow[] {
  const rows: SplitRow[] = [{ left: { kind: "hunk", text: `${file.status} ${file.path}`, oldNo: null, newNo: null }, right: { kind: "hunk", text: `${file.status} ${file.path}`, oldNo: null, newNo: null } }];
  for (let index = 0; index < file.lines.length;) {
    const line = file.lines[index];
    if (line.kind === "del") {
      const deleted: Line[] = [];
      const added: Line[] = [];
      while (file.lines[index]?.kind === "del") deleted.push(file.lines[index++]);
      while (file.lines[index]?.kind === "add") added.push(file.lines[index++]);
      const count = Math.max(deleted.length, added.length);
      for (let pair = 0; pair < count; pair += 1) rows.push({ left: deleted[pair] ?? null, right: added[pair] ?? null });
      continue;
    }
    if (line.kind === "add") rows.push({ left: null, right: line });
    else rows.push({ left: line, right: line });
    index += 1;
  }
  return rows;
}

function mergeFiles(parsed: FileBlock[], supplied: Array<DiffFile | string> | undefined): Array<{ path: string; status: string }> {
  if (!supplied?.length) return parsed.map(({ path, status }) => ({ path, status }));
  return supplied.map((item) => typeof item === "string" ? { path: item, status: "M" } : item);
}
