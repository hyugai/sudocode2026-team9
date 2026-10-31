"use client";

import { createContext, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { createPurchaseStore } from "@/utils/commerce";

type Store = ReturnType<typeof createPurchaseStore>;
const PurchaseContext = createContext<Store | null>(null);
export function PurchaseProvider({ children }: { children: ReactNode }) {
  const [store] = useState(() => createPurchaseStore(() => window.localStorage, () => window.sessionStorage));
  useEffect(() => { store.hydrate(); }, [store]);
  return <PurchaseContext.Provider value={store}>{children}</PurchaseContext.Provider>;
}
export function usePurchase() {
  const store = useContext(PurchaseContext);
  if (!store) throw new Error("PurchaseProvider is required");
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getServerSnapshot);
  return { ...state, store };
}
