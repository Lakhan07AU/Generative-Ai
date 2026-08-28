"use client";

import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";
import { api, clearToken, getToken, getUser, setToken, setUser, User } from "./api";

type AuthContextType = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  register: (data: { email: string; name: string; password: string; role?: string }) => Promise<User>;
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Initialize from localStorage
    const token = getToken();
    if (token) {
      setUserState(getUser());
    }
    setLoading(false);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.login(email, password);
    setToken(res.access_token);
    setUser(res.user);
    setUserState(res.user);
    return res.user;
  }, []);

  const register = useCallback(
    async (data: { email: string; name: string; password: string; role?: string }) => {
      const user = await api.register(data);
      return user;
    },
    []
  );

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      /* ignore */
    }
    clearToken();
    setUserState(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, register }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
