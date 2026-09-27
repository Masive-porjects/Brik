import { Suspense } from "react";
import type { Metadata } from "next";
import { RegisterForm } from "@/features/auth";
import AuthLayout from "@/features/auth/components/AuthLayout";

export const metadata: Metadata = {
  title: "Registro | WaveIA Studio",
  description: "Crea una cuenta en WaveIA Studio y lleva tus producciones musicales al siguiente nivel.",
};

export default function RegisterPage() {
  return (
    <AuthLayout>
      <Suspense
        fallback={
          <div className="w-full max-w-md h-96 rounded-3xl animate-pulse bg-[var(--surface-elevated)] border border-[var(--border-subtle)]" />
        }
      >
        <RegisterForm />
      </Suspense>
    </AuthLayout>
  );
}
