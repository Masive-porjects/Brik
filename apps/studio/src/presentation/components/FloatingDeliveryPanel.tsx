"use client";

import { useState } from "react";
import type { MasteringParameters } from "@/lib/api";
import DeliveryPanel from "@/components/DeliveryPanel";
import IconButton from "@/components/ui/IconButton";
import { SlidersVertical, X } from "lucide-react";
import { useTranslation } from "@/i18n";

/* ── FloatingDeliveryPanel ────────────────────────────────
   FAB + floating sheet for the delivery controls. The studio canvas
   stays clean: nothing pushes the module column down — the sheet is a
   fixed overlay (z-50, por debajo de modales/error y del ModuleSheet)
   que el usuario abre solo cuando quiere configurar la entrega. */

interface FloatingDeliveryPanelProps {
  params: MasteringParameters;
  onChange: (updater: (prev: MasteringParameters) => MasteringParameters) => void;
}

export default function FloatingDeliveryPanel({
  params,
  onChange,
}: FloatingDeliveryPanelProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  return (
    <>
      {/* FAB — alterna el sheet de entrega */}
      <div className="fixed right-4 bottom-20 z-50 flex flex-col items-center gap-1">
        <IconButton
          label={t("delivery.delivery", "Entrega")}
          icon={SlidersVertical}
          active={open}
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          size="lg"
        />
        <span className="text-[9px] font-semibold uppercase tracking-widest text-[var(--text-muted)]">
          {t("delivery.delivery", "Entrega")}
        </span>
      </div>

      {/* Sheet flotante — los controles de entrega sobre el lienzo */}
      {open && (
        <div
          role="dialog"
          aria-label={t("delivery.configTitle", "Configuración de entrega")}
          className="fixed right-4 bottom-24 z-50 overflow-y-auto rounded-2xl p-4"
          style={{
            width: "min(320px, calc(100vw - 2rem))",
            maxHeight: "calc(100vh - 140px)",
            background: "var(--bg-glass)",
            border: "1px solid var(--border-subtle)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
          }}
        >
          <div className="mb-3 flex items-center justify-between">
            <span className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest">
              {t("delivery.delivery", "Entrega")}
            </span>
            <button
              type="button"
              aria-label={t("delivery.closePanel", "Cerrar panel de entrega")}
              onClick={() => setOpen(false)}
              className="flex h-6 w-6 items-center justify-center rounded-md text-[var(--text-muted)] transition-all hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]"
            >
              <X size={14} />
            </button>
          </div>
          <DeliveryPanel params={params} onChange={onChange} />
        </div>
      )}
    </>
  );
}