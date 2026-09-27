"use client";

import { useTranslation } from "@/i18n/useTranslation";
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";

export interface PaginationProps {
  page: number;
  pageSize: number;
  totalCount: number;
  pageSizeOptions?: number[];
  onPageChange: (newPage: number) => void;
  onPageSizeChange?: (newPageSize: number) => void;
  isLoading?: boolean;
  className?: string;
}

export default function Pagination({
  page,
  pageSize,
  totalCount,
  pageSizeOptions = [10, 25, 50],
  onPageChange,
  onPageSizeChange,
  isLoading = false,
  className = "",
}: PaginationProps) {
  const { t } = useTranslation();

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const safePage = Math.min(Math.max(1, page), totalPages);

  const from = totalCount === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const to = Math.min(totalCount, safePage * pageSize);

  const canPrev = safePage > 1 && !isLoading;
  const canNext = safePage < totalPages && !isLoading;

  return (
    <div
      className={`flex flex-col sm:flex-row items-center justify-between gap-3.5 px-4 py-3.5 border-t border-[var(--border-subtle)] text-xs text-[var(--text-secondary)] select-none ${className}`}
    >
      {/* Left: Summary text */}
      <div className="flex items-center gap-2">
        <span className="font-medium text-[var(--text-secondary)]">
          {t("common.paginationShowing", { from, to, total: totalCount }, `Mostrando ${from} - ${to} de ${totalCount}`)}
        </span>
        {isLoading && (
          <span className="inline-block size-2 rounded-full bg-[var(--accent-primary)] animate-pulse" />
        )}
      </div>

      {/* Right: Page Size & Controls */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Page size selector pills */}
        {onPageSizeChange && pageSizeOptions.length > 1 && (
          <div className="flex items-center gap-1 bg-[var(--surface-elevated)] p-0.5 rounded-xl border border-[var(--border-subtle)]">
            {pageSizeOptions.map((opt) => (
              <button
                key={opt}
                type="button"
                onClick={() => {
                  if (opt !== pageSize) {
                    onPageSizeChange(opt);
                  }
                }}
                disabled={isLoading}
                className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-all cursor-pointer ${
                  opt === pageSize
                    ? "bg-[var(--accent-primary)]/20 text-[var(--accent-primary)] shadow-xs"
                    : "text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                }`}
              >
                {opt} {t("common.paginationPerPage", "por pág.")}
              </button>
            ))}
          </div>
        )}

        {/* Navigation Buttons */}
        <div className="flex items-center gap-1">
          {/* First page */}
          <button
            type="button"
            onClick={() => onPageChange(1)}
            disabled={!canPrev}
            title={t("common.paginationFirst", "Primera página")}
            className="size-7.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)] disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all cursor-pointer shadow-xs"
          >
            <ChevronsLeft size={13} />
          </button>

          {/* Previous page */}
          <button
            type="button"
            onClick={() => onPageChange(safePage - 1)}
            disabled={!canPrev}
            title={t("common.paginationPrevious", "Página anterior")}
            className="size-7.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)] disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all cursor-pointer shadow-xs"
          >
            <ChevronLeft size={13} />
          </button>

          {/* Page Badge */}
          <div className="px-3 py-1 rounded-xl text-xs font-semibold bg-[var(--surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)] shadow-xs min-w-[70px] text-center">
            {t("common.paginationPageOf", { page: safePage, totalPages }, `Pág. ${safePage} / ${totalPages}`)}
          </div>

          {/* Next page */}
          <button
            type="button"
            onClick={() => onPageChange(safePage + 1)}
            disabled={!canNext}
            title={t("common.paginationNext", "Página siguiente")}
            className="size-7.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)] disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all cursor-pointer shadow-xs"
          >
            <ChevronRight size={13} />
          </button>

          {/* Last page */}
          <button
            type="button"
            onClick={() => onPageChange(totalPages)}
            disabled={!canNext}
            title={t("common.paginationLast", "Última página")}
            className="size-7.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)] disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all cursor-pointer shadow-xs"
          >
            <ChevronsRight size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}
