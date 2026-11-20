import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { flushSync } from "react-dom";
import { SPRING } from "../lib/motion";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { cx } from "./ui";

export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <img src="/favicon.svg" alt="" className="h-7 w-7" />
      <span className="font-display text-xl leading-none font-semibold tracking-[-0.01em] text-ink">HAR Triage</span>
    </div>
  );
}

// ------------------------------------------------------------------ theme

type Theme = "dark" | "light" | "system";
const THEME_KEY = "hartriage.theme";

export function readTheme(): Theme {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === "light" || value === "system" ? value : "dark";
  } catch {
    return "dark";
  }
}

export function applyTheme(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    applyTheme(theme);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      // Private mode: the choice lasts for this page only.
    }
  }, [theme]);
  return [theme, setTheme];
}

export function ThemeToggle() {
  const [theme, setTheme] = useTheme();
  const options: { value: Theme; label: string; icon: string }[] = [
    { value: "dark", label: "Dark theme", icon: "☾" },
    { value: "light", label: "Light theme", icon: "☀" },
    { value: "system", label: "Use system theme", icon: "◐" },
  ];
  return (
    <div role="radiogroup" aria-label="Theme" className="relative inline-flex rounded-full border border-rule bg-paper p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={theme === o.value}
          aria-label={o.label}
          title={o.label}
          onClick={(e) => {
            const start = (document as Document & { startViewTransition?: (cb: () => void) => { ready: Promise<void> } }).startViewTransition;
            if (!start || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
              setTheme(o.value);
              return;
            }
            const x = e.clientX, y = e.clientY;
            const r = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
            const t = start.call(document, () => flushSync(() => setTheme(o.value)));
            void t.ready.then(() =>
              document.documentElement.animate(
                { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${r}px at ${x}px ${y}px)`] },
                { duration: 480, easing: "cubic-bezier(0.2, 0.7, 0.2, 1)", pseudoElement: "::view-transition-new(root)" },
              ),
            );
          }}
          className={cx("relative h-7 w-8 rounded-full text-sm transition-colors duration-150", theme === o.value ? "text-ink" : "text-ink-4 hover:text-ink")}
        >
          {theme === o.value && <motion.span layoutId="theme-pill" className="absolute inset-0 rounded-full bg-raised" transition={SPRING} />}
          <span aria-hidden="true" className="relative">
            {o.icon}
          </span>
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ layout

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
}

export function Layout() {
  const { session, role, isAdmin, switchOrg, logout } = useAuth();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [location.pathname]);

  const work: NavItem[] = [
    { to: "/", label: "Analyse a file", end: true },
    { to: "/analyses", label: "History" },
    { to: "/kb", label: "Knowledge base" },
  ];
  const admin: NavItem[] = isAdmin
    ? [
        { to: "/connections", label: "Helpdesk connections" },
        { to: "/team", label: "Team" },
        { to: "/audit", label: "Audit log" },
      ]
    : [];
  const orgName = session?.orgs.find((o) => o.id === session.org_id)?.name;

  const link = (item: NavItem) => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        cx(
          "relative flex items-center rounded-[6px] px-3 py-2 text-[0.9375rem] transition-colors duration-150",
          isActive ? "font-bold text-ink" : "text-ink-3 hover:text-ink",
        )
      }
    >
      {({ isActive }) => (
        <>
          {/* One indicator that springs from item to item (shared layout). */}
          {isActive && (
            <motion.span layoutId="nav-indicator" className="absolute inset-0 rounded-[6px] bg-raised" transition={SPRING}>
              <span className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-primary" />
            </motion.span>
          )}
          <span className="relative">{item.label}</span>
        </>
      )}
    </NavLink>
  );

  return (
    <div className="min-h-screen md:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50 focus:rounded focus:bg-card focus:px-3 focus:py-2 focus:text-sm">
        Skip to content
      </a>
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-rule bg-card/95 px-4 py-3 backdrop-blur-sm md:hidden">
        <Logo />
        <button
          type="button"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          aria-controls="sidebar"
          onClick={() => setOpen((v) => !v)}
          className="rounded-[6px] p-2 text-ink hover:bg-paper-2"
        >
          <svg aria-hidden="true" viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round">
            {open ? <path d="M5 5l10 10M15 5L5 15" /> : <path d="M3 5.5h14M3 10h14M3 14.5h14" />}
          </svg>
        </button>
      </header>
      {open && <div className="animate-fade fixed inset-0 z-30 bg-black/40 md:hidden" onClick={() => setOpen(false)} />}
      <aside
        id="sidebar"
        className={cx(
          "fixed inset-y-0 left-0 z-40 flex w-72 max-w-[85vw] flex-col border-r border-rule bg-card transition-transform duration-200 ease-out md:sticky md:top-0 md:z-auto md:h-screen md:w-64 md:shrink-0 md:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full max-md:invisible",
        )}
      >
        <div className="hidden px-5 pt-6 pb-7 md:block">
          <Logo />
        </div>
        <nav aria-label="Main" className="flex-1 space-y-0.5 overflow-y-auto px-3 py-4 md:py-0">
          {work.map(link)}
          {admin.length > 0 && (
            <>
              <p className="eyebrow px-3 pt-6 pb-1.5">Administration</p>
              {admin.map(link)}
            </>
          )}
        </nav>
        <div className="space-y-3 border-t border-rule px-5 py-4 text-sm">
          {session && session.orgs.length > 1 ? (
            <label className="block">
              <span className="eyebrow mb-1 block">Organisation</span>
              <select
                className="h-9 w-full rounded-[5px] border border-rule-2 bg-card px-2 text-sm text-ink"
                value={session.org_id}
                onChange={(e) => void switchOrg(e.target.value)}
              >
                {session.orgs.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <p className="eyebrow truncate" title={orgName}>
              {orgName}
            </p>
          )}
          <div className="min-w-0">
            <p className="truncate font-bold text-ink" title={session?.user.name}>
              {session?.user.name || session?.user.email}
            </p>
            <p className="truncate text-xs text-ink-3" title={session?.user.email}>
              {session?.user.email}
            </p>
          </div>
          <div className="flex items-center justify-between gap-2">
            <ThemeToggle />
            {role && <span className="rounded-full bg-paper-2 px-2 py-0.5 text-xs font-bold text-ink-3">{role}</span>}
          </div>
          <button type="button" onClick={() => void logout()} className="text-sm text-ink-3 underline-offset-2 hover:text-ink hover:underline">
            Sign out
          </button>
        </div>
      </aside>
      <main id="main" className="min-w-0 flex-1 px-4 py-6 sm:px-6 md:px-10 md:py-10">
        {/* Keyed by path: every page change gets a short fade-and-rise. */}
        <div key={location.pathname} className="animate-page mx-auto max-w-6xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
