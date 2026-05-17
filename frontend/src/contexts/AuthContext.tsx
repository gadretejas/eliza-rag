import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import { jwtDecode } from "jwt-decode";
import type { AuthUser, Role } from "../types";

const TOKEN_KEY = "auth_token";

interface JwtPayload {
  sub:             string;
  email:           string;
  role:            Role;
  allowed_tickers: string;
  exp:             number;
}

function decodeUser(token: string): AuthUser | null {
  try {
    const payload = jwtDecode<JwtPayload>(token);
    if (payload.exp * 1000 < Date.now()) return null;
    return {
      id:              parseInt(payload.sub),
      email:           payload.email,
      role:            payload.role,
      allowed_tickers: payload.allowed_tickers,
    };
  } catch {
    return null;
  }
}

function loadToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

interface AuthContextValue {
  token:   string | null;
  user:    AuthUser | null;
  login:   (token: string) => void;
  logout:  () => void;
  isAdmin: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(loadToken);
  const user = token ? decodeUser(token) : null;

  const login = useCallback((newToken: string) => {
    localStorage.setItem(TOKEN_KEY, newToken);
    setToken(newToken);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
  }, []);

  return (
    <AuthContext.Provider value={{
      token,
      user:    user,
      login,
      logout,
      isAdmin: user?.role === "admin",
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
