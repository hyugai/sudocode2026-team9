"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useConversation, type Conversation } from "@/utils/use-conversation";

const ConversationContext = createContext<Conversation | null>(null);

/** Keep the existing conversation alive across catalog/PDP client navigation. */
export function ConversationProvider({ children }: { children: ReactNode }) {
  const conversation = useConversation();
  return <ConversationContext.Provider value={conversation}>{children}</ConversationContext.Provider>;
}

export function useSharedConversation() {
  const conversation = useContext(ConversationContext);
  if (!conversation) throw new Error("ConversationProvider is required");
  return conversation;
}
