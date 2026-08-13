export function RuntimeRecoveryView({
  kind,
  onReload,
  onDiagnostics,
}: {
  kind: "ui" | "core";
  onReload?: () => void;
  onDiagnostics?: () => void;
}) {
  const ui = kind === "ui";
  return (
    <main className="runtime-recovery" role="alert">
      <div className="card">
        <span className="eyebrow">Runtime Recovery</span>
        <h1>{ui ? "AI Team OS 遇到了界面错误" : "AI Core 连接已中断"}</h1>
        <p>{ui ? "后台任务没有被自动终止。重新加载界面后会恢复当前任务状态。" : "正在进行有限次数的自动恢复。界面和已有任务记录仍然保留。"}</p>
        <div className="provider-actions">
          <button className="btn btn-primary" onClick={onReload ?? (() => window.location.reload())}>重新加载界面</button>
          <button className="btn" onClick={onDiagnostics ?? (() => window.location.assign("/settings"))}>查看诊断</button>
        </div>
      </div>
    </main>
  );
}
