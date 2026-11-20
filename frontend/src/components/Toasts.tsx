/** Feedback for every action: a small spring toast, bottom right, gone after 3.5 s. */
import { AnimatePresence, motion } from "motion/react";
import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { cx } from "./ui";

type Tone = "ok" | "bad" | "info";
interface Toast {
  id: number;
  text: string;
  tone: Tone;
}

const ToastContext = createContext<(text: string, tone?: Tone) => void>(() => {});

export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: Tone = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, text, tone }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3500);
  }, []);
  const value = useMemo(() => push, [push]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      {createPortal(
        <div aria-live="polite" className="pointer-events-none fixed right-4 bottom-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col items-end gap-2">
          <AnimatePresence initial={false}>
            {toasts.map((t) => (
              <motion.div
                key={t.id}
                layout
                role="status"
                initial={{ opacity: 0, y: 24, scale: 0.92 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, x: 40, transition: { duration: 0.18 } }}
                transition={{ type: "spring", stiffness: 480, damping: 30 }}
                className="pointer-events-auto flex items-center gap-2.5 rounded-[10px] border border-rule-2 bg-raised px-4 py-3 text-sm text-ink shadow-[0_18px_40px_-18px_rgb(0_0_0/0.7)]"
              >
                <span
                  aria-hidden="true"
                  className={cx("grid h-5 w-5 shrink-0 place-items-center rounded-full text-[0.7rem] font-bold", t.tone === "ok" ? "bg-ok text-[#090b0f]" : t.tone === "bad" ? "bg-critical text-white" : "bg-primary text-on-primary")}
                >
                  {t.tone === "ok" ? (
                    <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
                      <motion.path d="M3 8.5l3.2 3L13 4.5" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.3, delay: 0.1 }} />
                    </svg>
                  ) : t.tone === "bad" ? (
                    "!"
                  ) : (
                    "i"
                  )}
                </span>
                {t.text}
              </motion.div>
            ))}
          </AnimatePresence>
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}
