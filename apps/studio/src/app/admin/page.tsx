import type { Metadata } from "next";
import { AdminDashboard } from "@/features/admin";

export const metadata: Metadata = {
  title: "Admin Panel | WaveIA Studio",
  description: "Panel de administración y gestión de roles de usuarios en WaveIA Studio",
};

export default function AdminPage() {
  return <AdminDashboard />;
}
