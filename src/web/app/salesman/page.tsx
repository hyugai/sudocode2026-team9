import type { Metadata } from "next";
import { SalesmanWorkspace } from "./salesman-workspace";
import "./salesman.css";

export const metadata: Metadata = { title: "Salesman demo · Synee AI", description: "Xem trước giao diện quản lý hội thoại với dữ liệu mẫu.", robots: { index: false, follow: false } };

export default function SalesmanPage() {
  return <SalesmanWorkspace />;
}
