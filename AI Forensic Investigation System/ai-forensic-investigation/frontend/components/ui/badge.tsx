import * as React from "react";
import { cn } from "@/lib/utils";

type BadgeProps = React.HTMLAttributes<HTMLSpanElement> & {
  variant?: "default" | "success" | "warning" | "danger" | "muted";
};

const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant = "default", ...props }, ref) => (
    <span
      ref={ref}
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        variant === "default" && "bg-navy text-white",
        variant === "success" && "bg-emerald-100 text-emerald-800",
        variant === "warning" && "bg-amber-100 text-amber-800",
        variant === "danger" && "bg-red-100 text-red-800",
        variant === "muted" && "bg-slate-100 text-slate-700",
        className
      )}
      {...props}
    />
  )
);
Badge.displayName = "Badge";

export { Badge };

export function statusBadge(status: string) {
  const s = (status || "").toUpperCase();
  if (s === "READY") return <Badge variant="success">READY</Badge>;
  if (s === "PROCESSING" || s === "QUEUED" || s === "UPLOADED")
    return <Badge variant="warning">{status}</Badge>;
  if (s === "FAILED") return <Badge variant="danger">FAILED</Badge>;
  return <Badge variant="muted">{status}</Badge>;
}
