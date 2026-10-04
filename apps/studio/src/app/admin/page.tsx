import type { Metadata } from "next";
import { AdminDashboard } from "@/features/admin";

export const metadata: Metadata = {
  title: "Admin Panel | Brik Studio",
  description: "Panel de administración y gestión de roles de usuarios en Brik Studio",
};

export default function AdminPage() {
  return <AdminDashboard />;
}
