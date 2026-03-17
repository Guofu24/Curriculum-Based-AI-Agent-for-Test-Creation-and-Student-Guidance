"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import { useRouter, usePathname } from "next/navigation";
import { auth as authApi, type User, ApiError } from "@/lib/api";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (data: {
    email: string;
    password: string;
    full_name: string;
    department?: string;
    university?: string;
  }) => Promise<string>; // Returns message (e.g. "check email")
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  // Load user on mount if token exists
  useEffect(() => {
    let cancelled = false;

    async function bootstrapAuth() {
      const token = localStorage.getItem("token");
      const refreshToken = localStorage.getItem("refresh_token");

      if (!token && !refreshToken) {
        setLoading(false);
        return;
      }

      const clearStoredSession = () => {
        localStorage.removeItem("token");
        localStorage.removeItem("refresh_token");
        if (!cancelled) setUser(null);
      };

      try {
        if (!token && refreshToken) {
          const refreshed = await authApi.refreshToken(refreshToken);
          localStorage.setItem("token", refreshed.access_token);
        }

        const me = await authApi.me();
        if (!cancelled) setUser(me);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401 && refreshToken) {
          try {
            const refreshed = await authApi.refreshToken(refreshToken);
            localStorage.setItem("token", refreshed.access_token);
            const me = await authApi.me();
            if (!cancelled) setUser(me);
            return;
          } catch {
            clearStoredSession();
            return;
          }
        }

        clearStoredSession();
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void bootstrapAuth();

    return () => {
      cancelled = true;
    };
  }, []);

  // Redirect to login if not authenticated and on a protected route
  useEffect(() => {
    if (loading) return;
    const isProtected = pathname.startsWith("/dashboard");
    if (isProtected && !user) {
      router.replace("/");
    }
  }, [loading, user, pathname, router]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await authApi.login(email, password);
      localStorage.setItem("token", res.access_token);
      localStorage.setItem("refresh_token", res.refresh_token);
      const me = await authApi.me();
      setUser(me);
      router.push("/dashboard");
    },
    [router],
  );

  const register = useCallback(
    async (data: {
      email: string;
      password: string;
      full_name: string;
      department?: string;
      university?: string;
    }): Promise<string> => {
      const user = await authApi.register(data);

      if (user.is_email_verified) {
        // Development mode: auto-verified → auto-login
        const res = await authApi.login(data.email, data.password);
        localStorage.setItem("token", res.access_token);
        localStorage.setItem("refresh_token", res.refresh_token);
        const me = await authApi.me();
        setUser(me);
        router.push("/dashboard");
        return "Đăng ký thành công!";
      }

      // Production mode: cần verify email trước
      return "Đăng ký thành công! Vui lòng kiểm tra email để xác thực tài khoản trước khi đăng nhập.";
    },
    [router],
  );

  const logout = useCallback(async () => {
    // Call backend logout to blacklist tokens
    const refreshToken = localStorage.getItem("refresh_token");
    if (refreshToken) {
      try {
        await authApi.logout(refreshToken);
      } catch {
        // Even if backend logout fails, still clear client state
      }
    }
    localStorage.removeItem("token");
    localStorage.removeItem("refresh_token");
    setUser(null);
    router.push("/");
  }, [router]);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
