// Memory 占位（010 四十：M4 前不实现长期保存）
import { useI18n } from "../i18n";

export function Memory() {
  const { t } = useI18n();
  return (
    <div className="page">
      <h1>{t("mem.title")}</h1>
      <div className="card placeholder">
        <h2>{t("mem.longTerm")}</h2>
        <p className="muted">{t("mem.comingM4")}</p>
        <ul className="muted">
          <li>{t("mem.prefs")}</li>
          <li>{t("mem.projectMemory")}</li>
          <li>{t("mem.confirmations")}</li>
          <li>{t("mem.forget")}</li>
          <li>{t("mem.trace")}</li>
        </ul>
      </div>
    </div>
  );
}
