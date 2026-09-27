"use client";

import type { LucideIcon } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

/* ── IconButton ────────────────────────────────────────────
   Single, consistent icon-button primitive for the studio chrome:
   dock access points, home / account / toggles, sheet & drawer
   closers. Guarantees a readable "plate" behind the glyph so icons
   never read as grey-on-glass, and a strong focus-visible ring for
   keyboard navigation.

   States: default / hover / active(pressed) / disabled / focus-visible.
   ─────────────────────────────────────────────────────────── */

type IconButtonVariant = "plate" | "ghost";
type IconButtonSize = "md" | "lg";

interface IconButtonProps extends Omit<ComponentProps<"button">, "children"> {
  /** Human-readable label — REQUIRED (a11y). The icon alone is never a label. */
  label: string;
  /** Simple glyph: pass a Lucide icon component. Overrides `children`. */
  icon?: LucideIcon;
  /** Custom glyph (e.g. GhostIcon, MusicNote). Takes precedence over `icon`. */
  children?: ReactNode;
  /** Plate = raised frosted chip (default). Ghost = quiet, no plate. */
  variant?: IconButtonVariant;
  /** md = 40px, lg = 44px hit area (WCAG 2.5.5 minimum ≥ 44px on touch). */
  size?: IconButtonSize;
  /** Visual + aria-pressed "on" state (active toggle / current module). */
  active?: boolean;
  /** Stroke weight applied to a passed Lucide `icon` (default 2). */
  strokeWidth?: number;
}

/* Shared tokens — kept as small private helpers so both variants stay in sync. */
const sizemap: Record<IconButtonSize, string> = {
  md: "h-10 w-10",
  lg: "h-11 w-11",
};

/* Icon glyph: 44×44 hit area with an 18px glyph reads strong at 1m. */
const iconSize: Record<IconButtonSize, number> = { md: 18, lg: 20 };

export default function IconButton({
  label,
  icon: Icon,
  children,
  variant = "plate",
  size = "md",
  active = false,
  strokeWidth = 2,
  className = "",
  type = "button",
  ...rest
}: IconButtonProps) {
  const glyph = Icon ? (
    <Icon size={iconSize[size]} strokeWidth={strokeWidth} aria-hidden="true" />
  ) : (
    children
  );

  const base = [
    "relative shrink-0 flex items-center justify-center rounded-full",
    "transition-all duration-200",
    // Hit area floor (44px on touch targets via lg)
    sizemap[size],
    // Focus: keyboard-only ring, teal for a clear "you are here" cue.
    "outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60 focus-visible:ring-offset-0",
    // Disabled: keep it legible but obvious it's off.
    "disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none",
  ].join(" ");

  if (variant === "ghost") {
    return (
      <button
        type={type}
        aria-label={label}
        title={label}
        aria-pressed={active || undefined}
        disabled={rest.disabled}
        className={[
          base,
          "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)]",
          active && "text-[var(--accent-primary)] hover:text-[var(--accent-primary)]",
          className,
        ].join(" ")}
        {...rest}
      >
        {glyph}
      </button>
    );
  }

  /* Plate — the default chrome style (dark studio: frosted chip). */
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      aria-pressed={active || undefined}
      className={[
        base,
        // Frosted plate separates the glyph from the ambient background.
        "bg-white/6 hover:bg-white/10 active:bg-white/12",
        "ring-1 ring-white/10 hover:ring-white/20",
        "shadow-[0_8px_30px_rgba(0,0,0,.35)]",
        "backdrop-blur-md",
        // Glyph legibility: bright by default, pure white on hover/active,
        // with a soft drop shadow that cuts it out of busy backgrounds.
        "text-white/85 hover:text-white active:text-white",
        "drop-shadow-[0_2px_6px_rgba(0,0,0,.45)]",
        active &&
          "bg-white/10 text-white ring-2 ring-teal-300/50 ring-teal-300/50 shadow-[0_8px_30px_rgba(0,0,0,.45)]",
        className,
      ].join(" ")}
      {...rest}
    >
      {/* Active underline dot — tiny teal pip under the plate for "on". */}
      {active && (
        <span
          aria-hidden="true"
          className="absolute bottom-[3px] left-1/2 -translate-x-1/2 h-[3px] w-[3px] rounded-full bg-teal-300/80 shadow-[0_0_6px_rgba(94,234,212,0.9)]"
        />
      )}
      {glyph}
    </button>
  );
}