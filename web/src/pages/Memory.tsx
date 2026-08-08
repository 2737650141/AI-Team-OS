// Memory 占位（010 四十：M4 前不实现长期保存）
export function Memory() {
  return (
    <div className="page">
      <h1>Memory</h1>
      <div className="card placeholder">
        <h2>Long-term Memory</h2>
        <p className="muted">Coming in M4</p>
        <ul className="muted">
          <li>User Preferences</li>
          <li>Project Memory</li>
          <li>Memory Confirmations</li>
          <li>Forget</li>
          <li>Memory Trace</li>
        </ul>
      </div>
    </div>
  );
}
