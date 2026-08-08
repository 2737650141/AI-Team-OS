// i18n React 上下文（010-B 九）：useI18n() 提供 { lang, setLang, t }，选择持久化到 localStorage。
import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { LANG_KEY, detectLang, dicts } from "./dict";
import type { Lang } from "./dict";
export type { Lang } from "./dict";

interface I18nCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string) => string;
}

const Ctx = createContext<I18nCtx>({ lang: "zh", setLang: () => {}, t: (k) => k });

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectLang);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(LANG_KEY, l);
    } catch {
      /* ignore */
    }
  }, []);
  const t = useCallback((key: string) => dicts[lang][key] ?? key, [lang]);
  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18nCtx {
  return useContext(Ctx);
}

// 状态值 → 显示文案（StatusBadge 等；数据值保持英文，显示层翻译）
export function useStatusLabel(): (status: string) => string {
  const { t } = useI18n();
  return useCallback((status: string) => t(`st.${status}`), [t]);
}
