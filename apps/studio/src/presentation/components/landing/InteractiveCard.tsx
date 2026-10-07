"use client";

import { motion, HTMLMotionProps } from "framer-motion";
import { useInView } from "framer-motion";
import { useRef } from "react";
import { transitions, easings } from "@/shared/lib/animations";

interface InteractiveCardProps extends Omit<HTMLMotionProps<"div">, "initial" | "animate" | "whileInView" | "viewport" | "transition"> {
  /** Index in grid for stagger delay */
  index?: number;
  /** If expanded (for drawer open state) */
  isExpanded?: boolean;
  /** Accent color for corner glow */
  glowColor?: "primary" | "secondary" | "tertiary";
  /** Children content */
  children: React.ReactNode;
  /** Click handler (enables tap feedback on mobile) */
  onClick?: () => void;
  /** Disable hover effects on mobile (for clickable cards) */
  disableHoverOnMobile?: boolean;
  /** Additional className */
  className?: string;
}

const glowColorClasses = {
  primary: "bg-primary/5 group-hover:scale-125",
  secondary: "bg-secondary/5 group-hover:scale-125",
  tertiary: "bg-tertiary-container/10 group-hover:scale-125",
} as const;

export function InteractiveCard({
  index = 0,
  isExpanded = false,
  glowColor = "primary",
  children,
  onClick,
  disableHoverOnMobile = false,
  className = "",
  style,
  ...props
}: InteractiveCardProps) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, amount: 0.15, margin: "-50px" });

  // Mobile tap feedback using Web Animations API (no layout thrash)
  const handleTap = onClick
    ? (e: React.MouseEvent<HTMLDivElement>) => {
        const target = e.currentTarget;
        target.animate(
          [
            { transform: "scale(1)" },
            { transform: "scale(0.98)" },
            { transform: "scale(1)" },
          ],
          { duration: 120, easing: "cubic-bezier(0.25, 0.46, 0.45, 0.94)" }
        );
        onClick();
      }
    : undefined;

  const baseClass = `
    group flex flex-col justify-between h-full p-6 sm:p-8 rounded-2xl bg-[#1a1b20]
    border transition-all duration-300 shadow-xl relative overflow-hidden
    ${isExpanded
      ? "border-primary/40 bg-[#1f1f24] shadow-[0_0_30px_rgba(110,233,224,0.1)]"
      : "border-white/[0.05] hover:border-white/10"
    }
    ${disableHoverOnMobile ? "" : "hover:bg-[#1f1f24]"}
    ${className}
  `.trim();

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 20 }}
      animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 20 }}
      transition={{ duration: 0.5, delay: index * 0.08, ease: easings.expoOut }}
      whileHover={!disableHoverOnMobile ? { y: -4, transition: transitions.cardHover } : undefined}
      whileTap={onClick ? { scale: 0.98, transition: transitions.cardTap } : undefined}
      onClick={handleTap}
      className={baseClass}
      style={{
        willChange: "transform, box-shadow, border-color",
        ...style,
      }}
      {...props}
    >
      {/* Corner Glow - GPU accelerated via transform */}
      <motion.div
        className={`absolute top-0 right-0 w-32 h-32 ${glowColorClasses[glowColor]} rounded-bl-full pointer-events-none transition-transform duration-500`}
        animate={{ scale: isExpanded ? 1.15 : 1 }}
        transition={transitions.cardHover}
        style={{ willChange: "transform" }}
      />

      <div className="relative z-10 flex flex-col flex-1">{children}</div>
    </motion.div>
  );
}