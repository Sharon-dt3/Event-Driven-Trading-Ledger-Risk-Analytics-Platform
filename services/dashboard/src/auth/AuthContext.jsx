import { createContext, useContext, useState, useCallback } from 'react';
import { api } from '../api/client';

const AuthContext = createContext(null);

const TOKEN_KEY = 'tp_token';
const USER_KEY = 'tp_user';
const ACCOUNT_KEY = 'tp_account';
const DEFAULT_ACCOUNT = 'acct_123'; // seeded demo account

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState(() => {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  });
  const [account, setAccountState] = useState(
    () => localStorage.getItem(ACCOUNT_KEY) || DEFAULT_ACCOUNT,
  );

  const login = useCallback(async (username, password) => {
    const res = await api.login(username, password);
    localStorage.setItem(TOKEN_KEY, res.access_token);
    const u = { username, role: res.role };
    localStorage.setItem(USER_KEY, JSON.stringify(u));
    setToken(res.access_token);
    setUser(u);
    return u;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUser(null);
  }, []);

  const setAccount = useCallback((a) => {
    const v = (a || '').trim() || DEFAULT_ACCOUNT;
    localStorage.setItem(ACCOUNT_KEY, v);
    setAccountState(v);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        account,
        setAccount,
        isAuthenticated: !!token,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
