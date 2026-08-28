"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ShieldCheck, LogOut } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/videos", label: "Videos" },
  { href: "/investigate", label: "Investigate" },
  { href: "/investigations", label: "Investigations" },
  { href: "/policies", label: "Policies" },
];

export function AppHeader() {
  const { user, logout } = useAuth();
  const pathname = usePathname();

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4">
        <div className="flex items-center gap-6">
          <Link href="/dashboard" className="flex items-center gap-2 font-semibold text-navy">
            <ShieldCheck className="h-6 w-6 text-accent" />
            <span>AI Forensic Investigation</span>
          </Link>
          <nav className="hidden items-center gap-1 md:flex">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  pathname === item.href
                    ? "bg-navy text-white"
                    : "text-slate-600 hover:bg-slate-100"
                )}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          {user && (
            <span className="hidden text-sm text-slate-600 sm:block">
              {user.name} · <span className="font-medium text-navy">{user.role}</span>
            </span>
          )}
          <Button variant="outline" size="sm" onClick={() => logout()}>
            <LogOut className="h-4 w-4" /> Logout
          </Button>
        </div>
      </div>
    </header>
  );
}
