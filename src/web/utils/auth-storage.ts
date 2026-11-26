import { CART_KEY, SESSION_KEY, type StoragePort } from "./commerce.ts";
import { conversationStorageKey } from "./conversation-session.ts";
import { accountConversationKey } from "./conversation-api.ts";

const ownerKey = "synee.auth.owner.v1";

/** Only the public user ID is stored here, never a password or session token. */
export function syncAuthOwner(userId: string | null, session: StoragePort, local: StoragePort, reset = false) {
  const owner = userId ?? "guest";
  const previous = session.getItem(ownerKey);
  if (reset || (previous !== owner && (previous !== null || userId !== null))) {
    session.removeItem(conversationStorageKey);
    session.removeItem(accountConversationKey);
    session.removeItem(SESSION_KEY);
    local.removeItem(CART_KEY);
  }
  session.setItem(ownerKey, owner);
}
