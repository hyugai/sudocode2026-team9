export interface ChatMessage {
  id?: string;
  role: "user" | "agent";
  text: string;
}

export function upsertChatTurn(messages: ChatMessage[], id: string, transcript: string, answer: string): ChatMessage[] {
  if (!messages.some((message) => message.id === id)) {
    return [...messages, { id: `${id}-user`, role: "user", text: transcript },
      { id, role: "agent", text: answer }];
  }
  return messages.map((message) => message.id === id ? { ...message, text: answer }
    : message.id === `${id}-user` ? { ...message, text: transcript } : message);
}
