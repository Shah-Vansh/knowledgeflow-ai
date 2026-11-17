"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getHealth } from "@/lib/api";
import { logout, logoutEverywhere } from "@/lib/auth";
import { useWorkspace } from "@/lib/workspace-context";
import { Alert, Loading, cx } from "@/components/ui";
import {
  AgentIcon,
  BeakerIcon,
  ChartIcon,
  ChatIcon,
  CloseIcon,
  DocumentsIcon,
  FlaskIcon,
  GraphIcon,
  HomeIcon,
  InspectIcon,
  LayersIcon,
  LogoutIcon,
  MenuIcon,
  ScissorsIcon,
  SearchIcon,
  UploadIcon,
} from "@/components/icons";

interface NavItem {
  href: string;
  label: string;
  icon: (props: React.SVGProps<SVGSVGElement>) => JSX.Element;
}

export const NAV: Array<{ section: string; items: NavItem[] }> = [
  { section: "", items: [{ href: "/", label: "Dashboard", icon: HomeIcon }] },
  {
    section: "Ask",
    items: [
      { href: "/chat", label: "Chat", icon: ChatIcon },
      { href: "/query", label: "Quick answer", icon: SearchIcon },
      { href: "/agent", label: "Agent", icon: AgentIcon },
      { href: "/graph", label: "Knowledge graph", icon: GraphIcon },
    ],
  },
  {
    section: "Library",
    items: [
      { href: "/upload", label: "Upload", icon: UploadIcon },
      { href: "/documents", label: "Documents", icon: DocumentsIcon },
      { href: "/inspector", label: "Inspector", icon: InspectIcon },
      { href: "/workspaces", label: "Workspaces", icon: LayersIcon },
    ],
  },
  {
    section: "Labs",
    items: [
      { href: "/chunking-lab", label: "Chunking lab", icon: ScissorsIcon },
      { href: "/retrieval-lab", label: "Retrieval lab", icon: FlaskIcon },
      { href: "/eval", label: "Evaluation", icon: ChartIcon },
      { href: "/experiments", label: "Experiments", icon: BeakerIcon },
    ],
  },
];

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5">
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-sm font-bold text-white shadow-sm">
        K
      </span>
      <span className="leading-tight">
        <span className="block text-sm font-semibold text-slate-900">KnowledgeFlow</span>
        <span className="block text-[11px] text-slate-500">Research copilot</span>
      </span>
    </Link>
  );
}

function WorkspaceSwitcher() {
  const { workspaces, workspaceId, setWorkspaceId, workspace } = useWorkspace();
  return (
    <div className="px-3">
      <label htmlFor="kf-workspace" className="mb-1 block px-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
        Workspace
      </label>
      <select
        id="kf-workspace"
        value={workspaceId}
        onChange={(e) => setWorkspaceId(Number(e.target.value))}
        className="block w-full rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-sm font-medium text-slate-900 shadow-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
      >
        {workspaces.length === 0 && <option value={workspaceId}>General</option>}
        {workspaces.map((w) => (
          <option key={w.id} value={w.id}>
            {w.name}
          </option>
        ))}
      </select>
      {workspace && (
        <p className="mt-1 px-1 text-[11px] text-slate-500">
          {workspace.document_count} document{workspace.document_count === 1 ? "" : "s"}
          {workspace.role ? ` · ${workspace.role}` : ""}
        </p>
      )}
    </div>
  );
}

function HealthDot() {
  const [state, setState] = useState<"checking" | "ok" | "down">("checking");
  useEffect(() => {
    let alive = true;
    const check = () =>
      getHealth()
        .then((h) => alive && setState(h.db_connected ? "ok" : "down"))
        .catch(() => alive && setState("down"));
    check();
    const timer = setInterval(check, 30000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);
  const tone = state === "ok" ? "bg-emerald-500" : state === "down" ? "bg-red-500" : "bg-slate-300";
  const label = state === "ok" ? "Backend connected" : state === "down" ? "Backend unreachable" : "Checking backend…";
  return (
    <span className="flex items-center gap-2 text-xs text-slate-500">
      <span className={cx("h-2 w-2 rounded-full", tone, state === "ok" && "shadow-[0_0_0_3px_rgb(16_185_129/0.15)]")} />
      {label}
    </span>
  );
}

function Sidebar({ email, onNavigate }: { email: string | null; onNavigate?: () => void }) {
  const pathname = usePathname() ?? "/";
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center px-5">
        <Logo />
      </div>
      <WorkspaceSwitcher />
      <nav className="scrollbar-thin mt-4 flex-1 space-y-5 overflow-y-auto px-3 pb-4" aria-label="Main">
        {NAV.map((group) => (
          <div key={group.section || "home"}>
            {group.section && (
              <p className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{group.section}</p>
            )}
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = isActive(pathname, item.href);
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      className={cx(
                        "group flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm font-medium transition-colors",
                        active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                      )}
                    >
                      <Icon className={cx("h-[18px] w-[18px]", active ? "text-brand-600" : "text-slate-400 group-hover:text-slate-600")} />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
      <div className="space-y-3 border-t border-slate-200 px-5 py-4">
        <HealthDot />
        {email ? (
          <div className="flex items-center justify-between gap-2">
            <span className="flex min-w-0 items-center gap-2">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold uppercase text-slate-700">
                {email[0]}
              </span>
              <span className="truncate text-xs text-slate-700" title={email}>
                {email}
              </span>
            </span>
            <button
              onClick={logout}
              className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900"
              title="Log out"
              aria-label="Log out"
            >
              <LogoutIcon className="h-4 w-4" />
            </button>
          </div>
        ) : null}
        {email ? (
          <button
            onClick={() => {
              if (window.confirm("Sign out on every browser and device where you're signed in?")) logoutEverywhere();
            }}
            className="text-[11px] text-slate-400 hover:text-slate-700"
          >
            Sign out everywhere
          </button>
        ) : (
          <p className="text-xs text-slate-400">Local mode · sign-in is off</p>
        )}
      </div>
    </div>
  );
}

export default function AppShell({ email, children }: { email: string | null; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const { loading, error } = useWorkspace();

  useEffect(() => setOpen(false), [pathname]);

  return (
    <div className="min-h-screen">
      {/* desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-slate-200 bg-white lg:block">
        <Sidebar email={email} />
      </aside>

      {/* mobile top bar + drawer */}
      <div className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-slate-200 bg-white/90 px-4 backdrop-blur lg:hidden">
        <Logo />
        <button
          onClick={() => setOpen(true)}
          className="rounded-md p-2 text-slate-600 hover:bg-slate-100"
          aria-label="Open navigation"
        >
          <MenuIcon />
        </button>
      </div>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-slate-900/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 max-w-[85%] bg-white shadow-xl">
            <button
              onClick={() => setOpen(false)}
              className="absolute right-3 top-4 rounded-md p-1.5 text-slate-500 hover:bg-slate-100"
              aria-label="Close navigation"
            >
              <CloseIcon />
            </button>
            <Sidebar email={email} onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}

      <main className="lg:pl-64">
        <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {error && (
            <Alert tone="error" title="Can't reach the backend" className="mb-6">
              {error}. Check that the API is running and NEXT_PUBLIC_API_URL points at it.
            </Alert>
          )}
          {loading ? <Loading label="Loading workspace…" /> : children}
        </div>
      </main>
    </div>
  );
}
