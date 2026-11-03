import type { Metadata, Viewport } from "next";
import { AiChatExperience, type AiChatMode } from "./ai-chat-experience";
import "./ai-chat.css";

export const metadata: Metadata = {
  title: "Trò chuyện cùng Synee AI",
  description: "Chat, gửi ghi âm và trò chuyện realtime cùng Synee AI.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  interactiveWidget: "resizes-content",
};

export default async function AiChatPage({ searchParams }: {
  searchParams: Promise<{ mode?: string | string[] }>;
}) {
  const { mode } = await searchParams;
  const initialMode: AiChatMode = mode === "realtime" ? "realtime" : "text";
  return <AiChatExperience mode={initialMode} />;
}
