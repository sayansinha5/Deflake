import { createContext, useContext } from "react";

const ShellContext = createContext(null);

export function ShellProvider({ value, children }) {
  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}

export function useShell() {
  const value = useContext(ShellContext);
  if (!value) throw new Error("useShell must be used inside the app shell");
  return value;
}
