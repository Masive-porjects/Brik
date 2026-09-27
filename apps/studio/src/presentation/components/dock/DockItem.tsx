"use client";

import type { LucideIcon } from "lucide-react";
import PedestalBase from "./PedestalBase";

interface DockItemProps {
  icon: LucideIcon;
  label: string;
  active: boolean;
  onSelect: () => void;
  /** Callback-ref so the dock can drive fisheye transforms via GSAP. */
  buttonRef?: (el: HTMLButtonElement | null) => void;
  /** Onboarding: briefly show EVERY label regardless of hover/active. */
  revealLabels?: boolean;
  /** E2E test id (e.g. dock-tab-live) */
  testId?: string;
}

/* ── DockItem ───────────────────────────────────────────
   One module entry: pedestal + icon + active state. The fisheye
   scale is applied to the BUTTON only (origin bottom) so the
   tooltip lives outside the transformed node.

   Active clarity: the active module keeps its label pill VISIBLE
   without hover ("sé cuál estoy mirando aunque no mueva el mouse"),
   plus a stronger teal halo + dot on the pedestal. */
export default function DockItem({
  icon: Icon,
  label,
  active,
  onSelect,
  buttonRef,
  revealLabels = false,
  testId,
}: DockItemProps) {
  const labelVisible = active || revealLabels;

  return (
    <div className="group relative flex flex-col items-center">
      {/* Label pill — persistent for the active module (or during the
          onboarding reveal), hover/focus for the rest. Sibling of the
          scaled node so the fisheye transform doesn't lift it. */}
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute bottom-full mb-2 z-50 whitespace-nowrap rounded-md px-2 py-1 text-[10px] font-medium transition-all duration-200 ${
          labelVisible
            ? "opacity-100 scale-100"
            : "opacity-0 scale-95 group-hover:opacity-100 group-hover:scale-100 group-focus-within:opacity-100"
        } ${
          active
            ? "text-[var(--accent-primary)] bg-[var(--bg-elevated)] border border-[var(--accent-primary)]/40 shadow-[0_0_14px_rgba(98,126,132,0.35)]"
            : "text-[var(--text-primary)] bg-[var(--bg-elevated)] border border-[var(--border-subtle)] shadow-lg"
        }`}
      >
        {label}
      </span>

      <button
        ref={buttonRef}
        type="button"
        data-testid={testId}
        onClick={onSelect}
        aria-label={`Módulo ${label}`}
        aria-current={active ? "true" : undefined}
        className="relative origin-bottom rounded-full outline-none will-change-transform focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-app)]"
      >
        {/* Active halo — bright ring around the pedestal so the current
            module reads instantly even against the glass blur. */}
        {active && (
          <span
            aria-hidden="true"
            className="absolute -inset-1 rounded-full"
            style={{
              background:
                "radial-gradient(circle, color-mix(in srgb, var(--accent-primary) 45%, transparent) 0%, transparent 70%)",
              filter: "blur(2px)",
            }}
          />
        )}
        <PedestalBase active={active}>
          <Icon size={18} strokeWidth={active ? 2.25 : 2} />
        </PedestalBase>

        {/* Active dot — small teal pip on the pedestal corner. */}
        <span
          aria-hidden="true"
          className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-[var(--accent-secondary)] shadow-[0_0_8px_rgba(130,156,161,0.9)] transition-transform duration-200"
          style={{ transform: active ? "scale(1)" : "scale(0)" }}
        />
      </button>
    </div>
  );
}