"use client";

import type { ReactNode } from "react";

/** Section title inside work area (SAP object page style) */
export function ErpPageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-6 border-b border-[var(--erp-border)] pb-4">
      <h2 className="text-lg font-semibold tracking-tight text-[var(--erp-text)]">{title}</h2>
      {subtitle ? <p className="mt-1 max-w-3xl text-sm leading-relaxed text-[var(--erp-text-muted)]">{subtitle}</p> : null}
    </div>
  );
}

/** Horizontal sub-navigation (tabs) */
export function ErpSubTabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string }[];
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="mb-6 flex flex-wrap gap-1 border-b border-[var(--erp-border)]">
      {tabs.map((t) => {
        const on = active === t.id;
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => onChange(t.id)}
            className={`relative -mb-px border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${
              on
                ? "border-[var(--erp-highlight)] text-[var(--erp-highlight)]"
                : "border-transparent text-[var(--erp-text-muted)] hover:border-slate-300 hover:text-[var(--erp-text)]"
            }`}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

export function ErpAlert({ variant, children }: { variant: "error" | "success" | "info"; children: ReactNode }) {
  const cls =
    variant === "error"
      ? "border-red-200 bg-red-50 text-red-900"
      : variant === "success"
        ? "border-emerald-200 bg-emerald-50 text-emerald-900"
        : "border-sky-200 bg-sky-50 text-sky-900";
  return <div className={`rounded-md border px-3 py-2 text-sm ${cls}`}>{children}</div>;
}

export function ErpToolbar({ children }: { children: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end gap-3 rounded-md border border-[var(--erp-border)] bg-[var(--erp-toolbar)] p-3">{children}</div>
  );
}

export function ErpPrimaryButton({ className = "", type = "button", ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type={type}
      className={`inline-flex items-center justify-center rounded-md bg-[var(--erp-highlight)] px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-[var(--erp-highlight-hover)] focus:outline-none focus:ring-2 focus:ring-[var(--erp-highlight)] focus:ring-offset-1 disabled:opacity-50 ${className}`}
      {...rest}
    />
  );
}

export function ErpSecondaryButton({ className = "", type = "button", ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type={type}
      className={`inline-flex items-center justify-center rounded-md border border-[var(--erp-border)] bg-white px-3 py-2 text-sm font-medium text-[var(--erp-text)] shadow-sm transition hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-300 focus:ring-offset-1 ${className}`}
      {...rest}
    />
  );
}

export function ErpInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const { className = "", ...rest } = props;
  return (
    <input
      className={`erp-input rounded-md border border-[var(--erp-border)] bg-white px-2.5 py-1.5 text-sm text-[var(--erp-text)] shadow-inner focus:border-[var(--erp-highlight)] focus:outline-none focus:ring-1 focus:ring-[var(--erp-highlight)] ${className}`}
      {...rest}
    />
  );
}

export function ErpSelect(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  const { className = "", ...rest } = props;
  return (
    <select
      className={`erp-input rounded-md border border-[var(--erp-border)] bg-white px-2 py-1.5 text-sm text-[var(--erp-text)] shadow-inner focus:border-[var(--erp-highlight)] focus:outline-none focus:ring-1 focus:ring-[var(--erp-highlight)] ${className}`}
      {...rest}
    />
  );
}

export function ErpLabel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <label className={`block text-xs font-medium uppercase tracking-wide text-[var(--erp-text-muted)] ${className}`}>{children}</label>;
}

/** Standard field wrapper with label */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</label>
      {children}
    </div>
  );
}

/** Status pill badge */
export function Badge({
  label,
  color,
}: {
  label: string;
  color: "green" | "yellow" | "red" | "blue" | "slate" | "orange";
}) {
  const cls: Record<string, string> = {
    green:  "bg-emerald-50 text-emerald-700 ring-emerald-200",
    yellow: "bg-amber-50 text-amber-700 ring-amber-200",
    red:    "bg-red-50 text-red-700 ring-red-200",
    blue:   "bg-blue-50 text-blue-700 ring-blue-200",
    slate:  "bg-slate-100 text-slate-600 ring-slate-200",
    orange: "bg-orange-50 text-orange-700 ring-orange-200",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${cls[color]}`}>
      {label}
    </span>
  );
}

/** Standard data grid */
export function ErpTable({ children }: { children: ReactNode }) {
  return (
    <div className="erp-table-wrap overflow-x-auto rounded-md border border-[var(--erp-border)]">
      <table className="erp-table min-w-full border-collapse text-sm">{children}</table>
    </div>
  );
}
