import { useState, useEffect, type FormEvent } from "react";
import {
  adminListUsers, adminCreateUser, adminUpdateUser, adminDeleteUser,
} from "../api";
import type { AdminUser, Role } from "../types";

const ROLES: Role[] = ["admin", "analyst", "viewer"];

const ROLE_BADGE: Record<Role, string> = {
  admin:   "bg-purple-100 text-purple-700 dark:bg-purple-950/50 dark:text-purple-400",
  analyst: "bg-blue-100 text-blue-700 dark:bg-blue-950/50 dark:text-blue-400",
  viewer:  "bg-gray-100 text-gray-600 dark:bg-slate-800 dark:text-slate-400",
};

export default function AdminPage() {
  const [users,   setUsers]   = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  // New user form state
  const [newEmail,    setNewEmail]    = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole,     setNewRole]     = useState<Role>("viewer");
  const [newTickers,  setNewTickers]  = useState("*");
  const [creating,    setCreating]    = useState(false);
  const [formError,   setFormError]   = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      setUsers(await adminListUsers());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setCreating(true);
    try {
      await adminCreateUser({
        email:           newEmail,
        password:        newPassword,
        role:            newRole,
        allowed_tickers: newTickers,
      });
      setNewEmail(""); setNewPassword(""); setNewRole("viewer"); setNewTickers("*");
      setShowForm(false);
      await load();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Failed to create user");
    } finally {
      setCreating(false);
    }
  }

  async function handleToggleActive(user: AdminUser) {
    try {
      await adminUpdateUser(user.id, { is_active: !user.is_active });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    }
  }

  async function handleRoleChange(user: AdminUser, role: Role) {
    try {
      await adminUpdateUser(user.id, { role });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    }
  }

  async function handleDelete(user: AdminUser) {
    if (!confirm(`Delete ${user.email}?`)) return;
    try {
      await adminDeleteUser(user.id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  return (
    <main className="max-w-4xl mx-auto px-4 py-10">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-slate-100">
            User Management
          </h1>
          <p className="text-sm text-gray-400 dark:text-slate-500 mt-0.5">
            Manage accounts, roles, and corpus access.
          </p>
        </div>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="px-3 py-1.5 rounded-lg text-sm font-medium
                     bg-gradient-to-r from-pink-500 to-purple-500
                     hover:from-pink-600 hover:to-purple-600
                     text-white shadow-sm transition-all"
        >
          {showForm ? "Cancel" : "+ New user"}
        </button>
      </div>

      {/* New user form */}
      {showForm && (
        <form onSubmit={handleCreate}
              className="mb-6 p-4 rounded-xl border border-gray-200 dark:border-slate-700
                         bg-gray-50 dark:bg-slate-900 flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-slate-300">
            Create user
          </h2>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-500 dark:text-slate-400">Email</label>
              <input type="email" required value={newEmail} onChange={(e) => setNewEmail(e.target.value)}
                     placeholder="user@example.com"
                     className="px-2.5 py-1.5 rounded-lg text-sm border border-gray-200 dark:border-slate-700
                                bg-white dark:bg-slate-800 text-gray-900 dark:text-slate-100
                                focus:outline-none focus:ring-2 focus:ring-pink-400" />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-500 dark:text-slate-400">Password</label>
              <input type="password" required value={newPassword} onChange={(e) => setNewPassword(e.target.value)}
                     placeholder="••••••••"
                     className="px-2.5 py-1.5 rounded-lg text-sm border border-gray-200 dark:border-slate-700
                                bg-white dark:bg-slate-800 text-gray-900 dark:text-slate-100
                                focus:outline-none focus:ring-2 focus:ring-pink-400" />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-500 dark:text-slate-400">Role</label>
              <select value={newRole} onChange={(e) => setNewRole(e.target.value as Role)}
                      className="px-2.5 py-1.5 rounded-lg text-sm border border-gray-200 dark:border-slate-700
                                 bg-white dark:bg-slate-800 text-gray-900 dark:text-slate-100
                                 focus:outline-none focus:ring-2 focus:ring-pink-400">
                {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-500 dark:text-slate-400">
                Allowed tickers
              </label>
              <input value={newTickers} onChange={(e) => setNewTickers(e.target.value)}
                     placeholder='* or ["AAPL","MSFT"]'
                     className="px-2.5 py-1.5 rounded-lg text-sm border border-gray-200 dark:border-slate-700
                                bg-white dark:bg-slate-800 text-gray-900 dark:text-slate-100
                                focus:outline-none focus:ring-2 focus:ring-pink-400" />
            </div>
          </div>
          {formError && (
            <p className="text-xs text-red-600 dark:text-red-400">{formError}</p>
          )}
          <div className="flex justify-end">
            <button type="submit" disabled={creating}
                    className="px-3 py-1.5 rounded-lg text-sm font-medium
                               bg-pink-500 hover:bg-pink-600 text-white
                               disabled:opacity-60 transition-colors">
              {creating ? "Creating…" : "Create"}
            </button>
          </div>
        </form>
      )}

      {/* Error banner */}
      {error && (
        <div className="mb-4 px-3 py-2 rounded-lg text-sm bg-red-50 border border-red-200
                        text-red-600 dark:bg-red-950/50 dark:border-red-800 dark:text-red-400">
          {error}
        </div>
      )}

      {/* Users table */}
      {loading ? (
        <div className="text-sm text-gray-400 dark:text-slate-500">Loading…</div>
      ) : (
        <div className="rounded-xl border border-gray-200 dark:border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-slate-900 text-xs font-medium
                              text-gray-500 dark:text-slate-400 uppercase tracking-wide">
              <tr>
                <th className="px-4 py-3 text-left">Email</th>
                <th className="px-4 py-3 text-left">Role</th>
                <th className="px-4 py-3 text-left">Corpus</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-slate-800">
              {users.map((u) => (
                <tr key={u.id}
                    className="bg-white dark:bg-slate-950 hover:bg-gray-50 dark:hover:bg-slate-900 transition-colors">
                  <td className="px-4 py-3 text-gray-800 dark:text-slate-200 font-medium">
                    {u.email}
                  </td>
                  <td className="px-4 py-3">
                    <select
                      value={u.role}
                      onChange={(e) => handleRoleChange(u, e.target.value as Role)}
                      className={`text-xs font-semibold px-2 py-0.5 rounded-full
                                  border-0 cursor-pointer focus:outline-none focus:ring-2 focus:ring-pink-400
                                  ${ROLE_BADGE[u.role]}`}
                    >
                      {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td className="px-4 py-3 text-gray-500 dark:text-slate-400 font-mono text-xs max-w-[160px] truncate">
                    {u.allowed_tickers === "*" ? "All companies" : u.allowed_tickers}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full
                                      ${u.is_active
                                        ? "bg-green-100 text-green-700 dark:bg-green-950/50 dark:text-green-400"
                                        : "bg-gray-100 text-gray-500 dark:bg-slate-800 dark:text-slate-500"
                                      }`}>
                      {u.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => handleToggleActive(u)}
                        className="text-xs px-2 py-1 rounded-md border
                                   border-gray-200 dark:border-slate-700
                                   text-gray-600 dark:text-slate-400
                                   hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                      >
                        {u.is_active ? "Deactivate" : "Activate"}
                      </button>
                      <button
                        onClick={() => handleDelete(u)}
                        className="text-xs px-2 py-1 rounded-md border
                                   border-red-200 dark:border-red-900
                                   text-red-600 dark:text-red-400
                                   hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
