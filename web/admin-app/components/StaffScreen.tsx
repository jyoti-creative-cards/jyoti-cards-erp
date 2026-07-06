"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl, authHeaders, fetchApi, formatApiError, jsonAuthHeaders } from "@/lib/api";
import type { AuthState, StaffPublic, ALL_PERMISSIONS } from "@/lib/types";
import { ALL_PERMISSIONS as PERMS } from "@/lib/types";

const INPUT = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
const LABEL = "mb-1 block text-xs font-semibold text-slate-500 uppercase tracking-wider";
const BTN = "inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-50";

interface Props { auth: AuthState; }

function PermissionGrid({ selected, onChange }: { selected: string[]; onChange: (p: string[]) => void }) {
  const groups = [...new Set(PERMS.map(p => p.group))];
  const toggle = (id: string) =>
    onChange(selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id]);

  return (
    <div className="space-y-3">
      {groups.map(g => {
        const groupPerms = PERMS.filter(p => p.group === g);
        const allChecked = groupPerms.every(p => selected.includes(p.id));
        return (
          <div key={g}>
            <div className="mb-1 flex items-center gap-2">
              <input type="checkbox" checked={allChecked}
                onChange={() => {
                  if (allChecked) onChange(selected.filter(x => !groupPerms.some(p => p.id === x)));
                  else onChange([...selected, ...groupPerms.filter(p => !selected.includes(p.id)).map(p => p.id)]);
                }}
                className="h-3.5 w-3.5 rounded"
              />
              <span className="text-xs font-bold uppercase tracking-wider text-slate-500">{g}</span>
            </div>
            <div className="ml-5 flex flex-wrap gap-x-4 gap-y-1">
              {groupPerms.map(p => (
                <label key={p.id} className="flex cursor-pointer items-center gap-1.5 text-sm text-slate-700">
                  <input type="checkbox" checked={selected.includes(p.id)} onChange={() => toggle(p.id)} className="h-3.5 w-3.5 rounded" />
                  {p.label}
                </label>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function StaffScreen({ auth }: Props) {
  const [staff, setStaff] = useState<StaffPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [editing, setEditing] = useState<StaffPublic | null>(null);
  const [showForm, setShowForm] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("staff");
  const [permissions, setPermissions] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 4000); };

  const load = useCallback(async () => {
    if (auth.type === "none") return;
    setLoading(true);
    const r = await fetchApi(apiUrl("staff"), { headers: authHeaders(auth) });
    if (r.ok) setStaff(await r.json());
    setLoading(false);
  }, [auth]);

  useEffect(() => { void load(); }, [load]);

  function openCreate() {
    setEditing(null);
    setName(""); setUsername(""); setPassword(""); setRole("staff"); setPermissions([]);
    setShowForm(true);
  }

  function openEdit(s: StaffPublic) {
    setEditing(s);
    setName(s.name); setUsername(s.username); setPassword(""); setRole(s.role);
    setPermissions(s.role === "admin" ? [] : s.permissions);
    setShowForm(true);
  }

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    const body: Record<string, unknown> = { name, username, role, permissions };
    if (password.trim()) body.password = password;
    if (!editing) body.password = password;

    const url = editing ? apiUrl(`staff/${editing.id}`) : apiUrl("staff");
    const method = editing ? "PATCH" : "POST";
    const r = await fetchApi(url, { method, headers: jsonAuthHeaders(auth), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast(editing ? "Updated." : "Staff created.", true);
    setShowForm(false);
    void load();
  }

  async function deactivate(s: StaffPublic) {
    if (!confirm(`Deactivate ${s.name}? They won't be able to log in.`)) return;
    const r = await fetchApi(apiUrl(`staff/${s.id}`), { method: "DELETE", headers: authHeaders(auth) });
    if (r.ok || r.status === 204) { showToast("Deactivated.", true); void load(); }
    else showToast(formatApiError(await r.json().catch(() => ({}))), false);
  }

  async function reactivate(s: StaffPublic) {
    const r = await fetchApi(apiUrl(`staff/${s.id}`), {
      method: "PATCH", headers: jsonAuthHeaders(auth), body: JSON.stringify({ is_active: true }),
    });
    if (r.ok) { showToast("Reactivated.", true); void load(); }
    else showToast(formatApiError(await r.json().catch(() => ({}))), false);
  }

  return (
    <div>
      {toast && (
        <div className={`fixed right-4 top-20 z-[200] rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-base font-semibold text-slate-800">Staff Accounts</h3>
        <button type="button" onClick={openCreate} className={BTN}>+ Add Staff</button>
      </div>

      {/* Create/Edit form */}
      {showForm && (
        <form onSubmit={onSave} className="mb-6 rounded-xl border border-slate-200 bg-slate-50 p-5">
          <h4 className="mb-4 font-semibold text-slate-800">{editing ? `Edit ${editing.name}` : "New Staff Account"}</h4>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className={LABEL}>Full name *</label>
              <input required value={name} onChange={e => setName(e.target.value)} className={INPUT} placeholder="e.g. Rahul Sharma" />
            </div>
            <div>
              <label className={LABEL}>Username * (used to login)</label>
              <input required value={username} onChange={e => setUsername(e.target.value.toLowerCase().replace(/[^a-z0-9_\-\.]/g, ""))} className={INPUT} placeholder="e.g. rahul.sharma" />
              <p className="mt-1 text-xs text-slate-400">Only letters, numbers, dots, hyphens. Staff will type this to sign in.</p>
            </div>
            <div>
              <label className={LABEL}>{editing ? "New password (leave blank to keep)" : "Password *"}</label>
              <input type="password" required={!editing} value={password} onChange={e => setPassword(e.target.value)} className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Role</label>
              <select value={role} onChange={e => setRole(e.target.value)} className={INPUT}>
                <option value="staff">Staff (custom permissions)</option>
                <option value="admin">Admin (all permissions)</option>
              </select>
            </div>
          </div>

          {role === "staff" && (
            <div className="mt-4 rounded-lg border border-slate-200 bg-white p-4">
              <p className={LABEL}>Permissions</p>
              <PermissionGrid selected={permissions} onChange={setPermissions} />
            </div>
          )}

          {role === "admin" && (
            <p className="mt-3 text-xs text-slate-500">Admin role has all permissions automatically.</p>
          )}

          <div className="mt-4 flex gap-3">
            <button type="submit" disabled={saving} className={BTN}>{saving ? "Saving…" : "Save"}</button>
            <button type="button" onClick={() => setShowForm(false)}
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Staff list */}
      {loading ? (
        <div className="py-8 text-center text-slate-400">Loading…</div>
      ) : staff.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 py-12 text-center text-slate-400">
          No staff accounts yet. Create one above.
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-600">Name</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-600">Username</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-600">Role</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-600">Permissions</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-600">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {staff.map(s => (
                <tr key={s.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium text-slate-800">{s.name}</td>
                  <td className="px-4 py-3 font-mono text-slate-600">{s.username}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${s.role === "admin" ? "bg-purple-100 text-purple-700" : "bg-slate-100 text-slate-600"}`}>
                      {s.role}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-500">
                    {s.role === "admin" ? "All" : (
                      s.permissions.length > 0
                        ? s.permissions.map(p => PERMS.find(x => x.id === p)?.label || p).join(", ")
                        : <span className="text-red-400">None</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${s.is_active ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-600"}`}>
                      {s.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      <button onClick={() => openEdit(s)}
                        className="rounded px-2 py-1 text-xs font-medium bg-slate-100 text-slate-700 hover:bg-slate-200">
                        Edit
                      </button>
                      {s.is_active ? (
                        <button onClick={() => deactivate(s)}
                          className="rounded px-2 py-1 text-xs font-medium bg-red-50 text-red-600 hover:bg-red-100">
                          Deactivate
                        </button>
                      ) : (
                        <button onClick={() => reactivate(s)}
                          className="rounded px-2 py-1 text-xs font-medium bg-emerald-50 text-emerald-700 hover:bg-emerald-100">
                          Reactivate
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
