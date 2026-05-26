import { Sidebar } from "./Sidebar";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="min-h-screen flex-1 overflow-auto bg-slate-950 p-6">
        {children}
      </main>
    </div>
  );
}
