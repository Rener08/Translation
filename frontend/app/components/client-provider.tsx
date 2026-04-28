"use client";

import { useEffect } from "react";

export function ClientProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    if (typeof window !== "undefined" && !window.localStorage) {
      console.warn("localStorage not available");
    }
  }, []);

  return <>{children}</>;
}