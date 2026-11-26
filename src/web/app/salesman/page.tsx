import type { Metadata } from "next";
import { SalesmanWorkspace } from "./salesman-workspace";
import "./salesman.css";

export const metadata: Metadata = { title: "Salesman · Synee AI", description: "Xem lịch sử Chat và Voice đã lưu.", robots: { index: false, follow: false } };

export default function SalesmanPage() {
  return <SalesmanWorkspace />;
}
