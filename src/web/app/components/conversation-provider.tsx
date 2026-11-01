"use client";

import { createContext, useContext, type ReactNode } from "react";
import { apiBase, useConversation, type Conversation } from "@/utils/use-conversation";
import VoicePanel from "@/components/voice-panel";
import { InfoDialog } from "./info-dialog";

const ConversationContext = createContext<Conversation | null>(null);

/** Keep the existing conversation alive across catalog/PDP client navigation. */
export function ConversationProvider({ children }: { children: ReactNode }) {
  const conversation = useConversation();
  return <ConversationContext.Provider value={conversation}>
    {children}
    {/* One voice surface survives inline/floating chat changes and route navigation. */}
    {conversation.voicePreview && <InfoDialog title="Trò chuyện trực tiếp cùng Synee" className="voice-dialog" onClose={() => conversation.setVoicePreview(false)}>
      <VoicePanel apiBase={apiBase} customerPhone={conversation.customerPhone} onActiveChange={conversation.setVoiceActive} />
    </InfoDialog>}
  </ConversationContext.Provider>;
}

export function useSharedConversation() {
  const conversation = useContext(ConversationContext);
  if (!conversation) throw new Error("ConversationProvider is required");
  return conversation;
}
