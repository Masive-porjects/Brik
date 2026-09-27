import { Suspense } from "react";
import type { Metadata } from "next";
import { LoginForm } from "@/features/auth";
import AuthLayout from "@/features/auth/components/AuthLayout";

export const metadata: Metadata = {
  title: "Login | WaveIA Studio",
  description: "Accede a tu cuenta de WaveIA Studio para masterizar tus pistas.",
};

export default function LoginPage() {
  return (
    <AuthLayout>
      <Suspense
        fallback={
          <div className="w-full max-w-md h-96 rounded-3xl animate-pulse bg-[var(--surface-elevated)] border border-[var(--border-subtle)]" />
        }
      >
        <LoginForm />
      </Suspense>
    </AuthLayout>
  );
}
