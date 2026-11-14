import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { Badge, Button, cx } from "./ui";

export function Logo() {
  return (
    <div className="flex items-center gap-2">
      <img src="/favicon.svg" alt="" className="h-7 w-7" />
      <span className="text-base font-semibold text-slate-900">HAR Triage</span>
    </div>
  );
}

export function Layout() {
  const { session, role, isAdmin, switchOrg, logout } = useAuth();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [location.pathname]);

  const nav = [
    { to: "/", label: "Analyse a file", end: true },
    { to: "/analyses", label: "History" },
    { to: "/kb", label: "Knowledge base" },
    ...(isAdmin
      ? [
          { to: "/connections", label: "Helpdesk connections" },
          { to: "/team", label: "Team" },
          { to: "/audit", label: "Audit log" },
        ]
      : []),
  ];

  return (
    <div className="min-h-screen md:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:shadow">
        Skip to content
      </a>
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 md:hidden">
        <Logo />
        <button
          type="button"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          aria-controls="sidebar"
          onClick={() => setOpen((v) => !v)}
          className="rounded-md p-2 text-slate-600 hover:bg-slate-100"
        >
          <svg aria-hidden="true" viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round">
            {open ? <path d="M5 5l10 10M15 5L5 15" /> : <path d="M3 5.5h14M3 10h14M3 14.5h14" />}
          </svg>
        </button>
      </header>
      {open && <div className="fixed inset-0 z-30 bg-slate-900/40 md:hidden" onClick={() => setOpen(false)} />}
      <aside
        id="sidebar"
        className={cx(
          "fixed inset-y-0 left-0 z-40 flex w-64 max-w-[85vw] flex-col border-r border-slate-200 bg-white transition-transform duration-200 md:static md:z-auto md:w-60 md:shrink-0 md:translate-x-0",
          open ? "translate-x-0" : "max-md:invisible -translate-x-full",
        )}
      >
        <div className="hidden px-4 py-4 md:block">
          <Logo />
        </div>
        <nav aria-label="Main" className="flex-1 space-y-0.5 px-2 py-2 md:py-0">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cx("block rounded-md px-3 py-2 text-sm font-medium", isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900")
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-200 p-4 text-sm">
          {session && session.orgs.length > 1 ? (
            <label className="mb-2 block">
              <span className="mb-1 block text-xs text-slate-500">Organisation</span>
              <select className="w-full rounded-md border-slate-300 text-sm" value={session.org_id} onChange={(e) => void switchOrg(e.target.value)}>
                {session.orgs.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <p className="mb-2 truncate font-medium text-slate-900">{session?.orgs.find((o) => o.id === session.org_id)?.name}</p>
          )}
          <p className="truncate text-slate-600" title={session?.user.email}>
            {session?.user.email}
          </p>
          <div className="mt-2 flex items-center justify-between">
            {role && <Badge tone="blue">{role}</Badge>}
            <Button size="sm" variant="ghost" onClick={() => void logout()}>
              Sign out
            </Button>
          </div>
        </div>
      </aside>
      <main id="main" className="min-w-0 flex-1 px-4 py-6 md:px-8">
        <Outlet />
      </main>
    </div>
  );
}
