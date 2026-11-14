import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { cx } from "./ui";

export function Logo({ inverted = false }: { inverted?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <img src="/favicon.svg" alt="" className="h-7 w-7" />
      <span className={cx("font-display text-lg leading-none font-bold tracking-tight", inverted ? "text-paper" : "text-ink")}>
        HAR<span className="text-signal">/</span>Triage
      </span>
    </div>
  );
}

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
          "flex items-center border-l-2 py-1.5 pr-3 pl-4 text-sm transition-colors",
          isActive ? "border-signal bg-white/[0.06] font-medium text-paper" : "border-transparent text-[#b8b19f] hover:text-paper",
        )
      }
    >
      {item.label}
    </NavLink>
  );

  return (
    <div className="min-h-screen md:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50 focus:bg-card focus:px-3 focus:py-2 focus:text-sm">
        Skip to content
      </a>
      <header className="sticky top-0 z-20 flex items-center justify-between bg-ink px-4 py-3 md:hidden">
        <Logo inverted />
        <button
          type="button"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          aria-controls="sidebar"
          onClick={() => setOpen((v) => !v)}
          className="p-2 text-paper hover:bg-white/10"
        >
          <svg aria-hidden="true" viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="square">
            {open ? <path d="M5 5l10 10M15 5L5 15" /> : <path d="M3 5.5h14M3 10h14M3 14.5h14" />}
          </svg>
        </button>
      </header>
      {open && <div className="fixed inset-0 z-30 bg-ink/50 md:hidden" onClick={() => setOpen(false)} />}
      <aside
        id="sidebar"
        className={cx(
          "fixed inset-y-0 left-0 z-40 flex w-64 max-w-[85vw] flex-col bg-ink text-paper transition-transform duration-200 md:sticky md:top-0 md:z-auto md:h-screen md:w-60 md:shrink-0 md:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full max-md:invisible",
        )}
      >
        <div className="hidden px-4 pt-5 pb-6 md:block">
          <Logo inverted />
        </div>
        <nav aria-label="Main" className="flex-1 overflow-y-auto py-4 md:py-0">
          <p className="eyebrow mb-1 px-4 text-[#8a8475]">Work</p>
          {work.map(link)}
          {admin.length > 0 && (
            <>
              <p className="eyebrow mt-6 mb-1 px-4 text-[#8a8475]">Administration</p>
              {admin.map(link)}
            </>
          )}
        </nav>
        <div className="border-t border-white/10 px-4 py-4 text-sm">
          {session && session.orgs.length > 1 ? (
            <label className="mb-3 block">
              <span className="eyebrow mb-1 block text-[#8a8475]">Organisation</span>
              <select
                className="w-full rounded-[2px] border border-white/20 bg-ink-2 px-2 py-1.5 text-sm text-paper"
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
            <p className="eyebrow mb-3 truncate text-[#8a8475]" title={orgName}>
              {orgName}
            </p>
          )}
          <p className="truncate font-medium text-paper" title={session?.user.name}>
            {session?.user.name || session?.user.email}
          </p>
          <p className="truncate font-mono text-xs text-[#8a8475]" title={session?.user.email}>
            {session?.user.email}
          </p>
          <div className="mt-3 flex items-center justify-between">
            {role && <span className="border border-white/25 px-1.5 py-px font-mono text-[0.7rem] text-[#d8d1c0]">{role}</span>}
            <button type="button" onClick={() => void logout()} className="text-xs text-[#b8b19f] underline-offset-2 hover:text-paper hover:underline">
              Sign out
            </button>
          </div>
        </div>
      </aside>
      <main id="main" className="min-w-0 flex-1 px-4 py-6 md:px-10 md:py-8">
        <div className="mx-auto max-w-6xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
