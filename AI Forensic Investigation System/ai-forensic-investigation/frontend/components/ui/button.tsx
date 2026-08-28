import * as React from "react";
import { cn } from "@/lib/utils";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "outline" | "ghost" | "destructive";
  size?: "default" | "sm" | "lg";
};

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:pointer-events-none disabled:opacity-50",
        variant === "default" && "bg-navy text-white hover:bg-navy/90",
        variant === "outline" && "border border-slate-300 bg-white hover:bg-slate-50",
        variant === "ghost" && "hover:bg-slate-100",
        variant === "destructive" && "bg-red-600 text-white hover:bg-red-700",
        size === "default" && "h-10 px-4 py-2",
        size === "sm" && "h-8 px-3 text-xs",
        size === "lg" && "h-11 px-6",
        className
      )}
      {...props}
    />
  )
);
Button.displayName = "Button";

export { Button };
