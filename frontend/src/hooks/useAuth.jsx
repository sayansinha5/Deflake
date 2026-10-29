import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, normalizeError } from "../lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const response = await api.get("/auth/me");
    setUser(response.data);
    return response.data;
  }, []);

  useEffect(() => {
    let live = true;
    api
      .get("/auth/me")
      .then((response) => {
        if (live) setUser(response.data);
      })
      .catch(() => {
        if (live) setUser(null);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, []);

  const signIn = useCallback(
    async (email, password) => {
      try {
        await api.post("/auth/session", { email, password });
        return await refresh();
      } catch (error) {
        throw error.normalized || normalizeError(error);
      }
    },
    [refresh],
  );

  const register = useCallback(async (body) => {
    try {
      const response = await api.post("/auth/register", body);
      setUser(response.data);
      return response.data;
    } catch (error) {
      throw error.normalized || normalizeError(error);
    }
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.delete("/auth/session");
    } catch {
      /* The cookie is cleared locally even if the request fails. */
    }
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, signIn, register, signOut, refresh }),
    [user, loading, signIn, register, signOut, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
