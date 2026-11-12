import { BookOpen, FlaskConical, LogOut, SunMedium, Users, Zap } from "lucide-react";
import type { ReactNode } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router";

import { useAuth } from "../auth/AuthContext";
import { ROLE_LABEL } from "../lib/labels";
import { cx } from "../lib/cx";

function NavItem({ to, icon, children }: { to: string; icon: ReactNode; children: ReactNode }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cx(
          "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium",
          isActive ? "bg-white/15 text-white" : "text-ink-200 hover:bg-white/10 hover:text-white",
        )
      }
    >
      {icon}
      {children}
    </NavLink>
  );
}

export function Brand({ className }: { className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      <span className="grid size-7 place-items-center rounded-md bg-sun-400 text-ink-950">
        <SunMedium className="size-4.5" aria-hidden />
      </span>
      SolarWise <span className="font-normal opacity-70">DZ</span>
    </span>
  );
}

export function Layout() {
  const { user, meta, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to the content
      </a>
      <header className="no-print bg-ink-900 text-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
          <Link to="/plants" className="text-white" aria-label="SolarWise DZ - plants">
            <Brand />
          </Link>
          <nav aria-label="Main" className="flex flex-1 flex-wrap items-center gap-1">
            <NavItem to="/plants" icon={<Zap className="size-4" aria-hidden />}>Plants</NavItem>
            <NavItem to="/reference" icon={<BookOpen className="size-4" aria-hidden />}>Rules and data</NavItem>
            {user?.role === "ADMIN" && (
              <NavItem to="/users" icon={<Users className="size-4" aria-hidden />}>Accounts</NavItem>
            )}
          </nav>
          {user && (
            <div className="flex items-center gap-3 text-sm">
              <div className="text-right leading-tight">
                <div className="max-w-[14rem] truncate font-medium">{user.full_name || user.email}</div>
                <div className="text-xs text-ink-300">
                  {user.is_demo ? "Demonstration session" : (ROLE_LABEL[user.role] ?? user.role)}
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  logout();
                  navigate("/login");
                }}
                className="inline-flex items-center gap-1.5 rounded-md border border-white/25 px-2.5 py-1.5 text-sm hover:bg-white/10"
              >
                <LogOut className="size-4" aria-hidden />
                Sign out
              </button>
            </div>
          )}
        </div>
      </header>

      {user?.is_demo && (
        <div role="note" className="simulated-stripes border-b border-violet-300 bg-violet-50 text-violet-950">
          <div className="mx-auto flex max-w-7xl items-start gap-2 px-4 py-2 text-sm sm:px-6">
            <FlaskConical className="mt-0.5 size-4 shrink-0" aria-hidden />
            <p>
              <strong className="font-semibold">Demonstration session.</strong> Every dataset here is synthetic and every
              decision is simulated. Nothing describes the operation of a real plant and nothing is an operational
              instruction.
            </p>
          </div>
        </div>
      )}

      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6">
        <Outlet />
      </main>

      <footer className="no-print border-t border-ink-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-4 text-xs text-ink-500 sm:px-6">
          <p>
            Decisions are produced by a deterministic rule engine. A production gap is an observation, not a diagnosis.
          </p>
          {meta && (
            <p className="font-mono">
              v{meta.version} · engine {meta.engine_version}
            </p>
          )}
        </div>
      </footer>
    </div>
  );
}
