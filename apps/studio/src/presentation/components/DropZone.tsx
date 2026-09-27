"use client";

import { useCallback, useRef, useState } from "react";
import { motion } from "framer-motion";
import { fadeUp } from "@/shared/motion";
import { useTranslation } from "@/i18n/useTranslation";

const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024; // 50 MB

interface DropZoneProps {
  onFileSelected: (file: File) => void;
  onError?: (title: string, message: string) => void;
  disabled?: boolean;
  compact?: boolean;
}

export default function DropZone({ onFileSelected, onError, disabled, compact }: DropZoneProps) {
  const { t } = useTranslation();
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleClick = useCallback(() => {
    if (!disabled) {
      inputRef.current?.click();
    }
  }, [disabled]);

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDragIn = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      setIsDragging(true);
    }
  }, []);

  const handleDragOut = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);

      if (disabled) return;

      const files = e.dataTransfer.files;
      if (files && files.length > 0) {
        const file = files[0];
        const ext = file.name.split(".").pop()?.toLowerCase();
        if (ext !== "wav" && ext !== "mp3" && ext !== "flac") {
          onError?.(
            t("common.error"),
            t("upload.invalidFormat"),
          );
          return;
        }
        if (file.size > MAX_FILE_SIZE_BYTES) {
          onError?.(
            t("common.error"),
            t("upload.fileTooLarge"),
          );
          return;
        }
        setTimeout(() => {
          onFileSelected(file);
        }, 0);
      }
    },
    [onFileSelected, disabled, onError, t]
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (files && files.length > 0) {
        const file = files[0];
        const ext = file.name.split(".").pop()?.toLowerCase();
        if (ext !== "wav" && ext !== "mp3" && ext !== "flac") {
          onError?.(
            t("common.error"),
            t("upload.invalidFormat"),
          );
          return;
        }
        if (file.size > MAX_FILE_SIZE_BYTES) {
          onError?.(
            t("common.error"),
            t("upload.fileTooLarge"),
          );
          return;
        }
        // Reset input value so re-selecting same file triggers change
        e.target.value = "";
        // Yield to browser main thread so INP (Interaction to Next Paint) completes instantly
        setTimeout(() => {
          onFileSelected(file);
        }, 0);
      }
    },
    [onFileSelected, onError, t]
  );

  if (compact) {
    return (
      <div
        onClick={handleClick}
        onDragEnter={handleDragIn}
        onDragLeave={handleDragOut}
        onDrop={handleDrop}
        className={`
          relative border border-dashed rounded-xl p-6
          text-center transition-all duration-200 cursor-pointer
          ${isDragging
            ? "border-[var(--accent-primary)] bg-[rgba(98,126,132,0.05)]"
            : "border-[var(--border-subtle)] hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)]"
          }
          ${disabled ? "opacity-50 cursor-not-allowed" : ""}
        `}
        style={{
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".wav,.mp3,.flac"
          onChange={handleFileInput}
          disabled={disabled}
          className="absolute inset-0 w-full h-full opacity-0 pointer-events-none z-20"
        />
        <p className="text-xs text-[var(--text-muted)]">
          {isDragging ? t("upload.dropHere") : t("upload.changeTrack")}
        </p>
        <p className="text-[10px] text-[var(--text-muted)] mt-1 opacity-60">WAV, MP3, FLAC</p>
      </div>
    );
  }


  return (
    <motion.div
      onClick={handleClick}
      onDragEnter={handleDragIn}
      onDragLeave={handleDragOut}
      onDragOver={handleDrag}
      onDrop={handleDrop}
        className={`
        relative rounded-2xl p-5 md:p-6 text-center cursor-pointer
        transition-all duration-300 overflow-hidden
        ${isDragging
          ? "scale-[1.01]"
          : "hover:scale-[1.005]"
        }
        ${disabled ? "opacity-50 cursor-not-allowed" : ""}
      `}
      {...fadeUp(0)}
      style={{
        background: "var(--bg-glass)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
      }}
    >
      {/* Animated gradient background */}
      <div
        className="absolute inset-0 transition-opacity duration-500"
        style={{
          opacity: isDragging ? 1 : 0.6,
          background: isDragging
            ? "linear-gradient(135deg, rgba(98,126,132,0.15) 0%, rgba(130,156,161,0.15) 50%, rgba(130,156,161,0.15) 100%)"
            : "linear-gradient(135deg, rgba(98,126,132,0.06) 0%, rgba(130,156,161,0.04) 50%, rgba(130,156,161,0.03) 100%)",
          backgroundSize: "200% 200%",
          animation: isDragging ? "gradientShift 3s ease infinite" : "gradientShift 12s ease-in-out infinite",
        }}
      />

      {/* Border */}
      <div
        className={`
          absolute inset-0 rounded-3xl border-2 border-dashed transition-all duration-300
          ${isDragging
            ? "border-[var(--accent-primary)]"
            : "border-[var(--border-subtle)] hover:border-[var(--border-strong)]"
          }
        `}
      />

      {/* Geometric decoration */}
      <div className="absolute top-4 left-6 w-10 h-10 rounded-full border border-[rgba(98,126,132,0.08)]" />
      <div className="absolute bottom-5 right-8 w-16 h-16 rounded-full border border-[rgba(130,156,161,0.06)]" />
      <div className="absolute top-1/2 left-1/4 w-2 h-2 rounded-full bg-[rgba(98,126,132,0.15)]" />
      <div className="absolute top-1/3 right-1/3 w-1.5 h-1.5 rounded-full bg-[rgba(130,156,161,0.15)]" />

      <input
        ref={inputRef}
        type="file"
        accept=".wav,.mp3,.flac"
        onChange={handleFileInput}
        disabled={disabled}
        className="absolute inset-0 w-full h-full opacity-0 pointer-events-none z-20"
      />


      <div className="relative z-10 flex flex-col items-center gap-3">
        {/* Icon */}
        <div className="relative">
          <div
            className="w-14 h-14 rounded-xl flex items-center justify-center transition-all duration-300"
            style={{
              background: "linear-gradient(135deg, rgba(98,126,132,0.15) 0%, rgba(130,156,161,0.12) 100%)",
              boxShadow: isDragging ? "0 0 40px rgba(98,126,132,0.15)" : "0 4px 20px rgba(0,0,0,0.2)",
            }}
          >
            <svg className="w-7 h-7 text-[var(--accent-primary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
            </svg>
          </div>
          <div className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-[var(--accent-primary)] flex items-center justify-center shadow-lg">
            <svg className="w-2 h-2 text-[var(--bg-primary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
          </div>
        </div>

        <div>
          <h2 className="text-lg font-bold text-[var(--text-primary)] mb-1">
            {isDragging ? t("upload.dropHere") : t("upload.dropzoneTitle")}
          </h2>
          <p className="text-xs text-[var(--text-secondary)] max-w-sm mx-auto">
            {t("upload.dropzoneSubtitle")}
            <br />
            <span className="text-[var(--text-muted)]">{t("upload.supportedFormats")}</span>
          </p>
        </div>
      </div>
    </motion.div>
  );
}
