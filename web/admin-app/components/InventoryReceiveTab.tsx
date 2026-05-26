"use client";

import type { CatalogProductPublic, PurchaseOrderPublic } from "@/lib/types";

type Props = {
  inventoryStep: null | "pick" | "po" | "manual";
  setInventoryStep: (s: null | "pick" | "po" | "manual") => void;
  invPickCatalog: CatalogProductPublic[];
  invManualCatalogId: string;
  setInvManualCatalogId: (s: string) => void;
  invManualQty: string;
  setInvManualQty: (s: string) => void;
  invManualMsg: string;
  onManualStock: (e: React.FormEvent<HTMLFormElement>) => void | Promise<void>;
  recvPoList: PurchaseOrderPublic[];
  recvSelPoId: string;
  setRecvSelPoId: (s: string) => void;
  recvPoDetail: PurchaseOrderPublic | null;
  recvPartial: boolean;
  setRecvPartial: (b: boolean) => void;
  recvReceiptNo: string;
  setRecvReceiptNo: (s: string) => void;
  recvContactNo: string;
  setRecvContactNo: (s: string) => void;
  recvFile: File | null;
  setRecvFile: (f: File | null) => void;
  recvShipmentNotes: string;
  setRecvShipmentNotes: (s: string) => void;
  recvQty: Record<number, string>;
  setRecvQty: React.Dispatch<React.SetStateAction<Record<number, string>>>;
  onRecvStock: (e: React.FormEvent<HTMLFormElement>) => void | Promise<void>;
  recvMsg: string;
  recvOk: string;
  vendorLabel: (id: number) => string;
};

export function InventoryReceiveTab(p: Props) {
  return (
    <>
      <p className="mt-3 text-sm text-neutral-600">
        Receive a PO shipment (receipt ID + contact per shipment) or add units without a PO. Partial receipts move the PO
        to <strong>in progress</strong>; after the last quantities you can close the PO.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {p.inventoryStep === null ? (
          <button
            type="button"
            className="rounded bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-800"
            onClick={() => p.setInventoryStep("pick")}
          >
            Add inventory
          </button>
        ) : null}
        {p.inventoryStep === "pick" ? (
          <>
            <button
              type="button"
              className="rounded border border-neutral-300 bg-white px-4 py-2 text-sm hover:bg-neutral-50"
              onClick={() => p.setInventoryStep("po")}
            >
              Receive from purchase order
            </button>
            <button
              type="button"
              className="rounded border border-neutral-300 bg-white px-4 py-2 text-sm hover:bg-neutral-50"
              onClick={() => p.setInventoryStep("manual")}
            >
              Add manually (no PO)
            </button>
            <button type="button" className="text-sm text-neutral-600 underline" onClick={() => p.setInventoryStep(null)}>
              Cancel
            </button>
          </>
        ) : null}
        {p.inventoryStep === "po" || p.inventoryStep === "manual" ? (
          <button type="button" className="text-sm text-neutral-600 underline" onClick={() => p.setInventoryStep("pick")}>
            Back
          </button>
        ) : null}
      </div>

      {p.inventoryStep === "manual" ? (
        <div className="mt-6 rounded border border-neutral-200 bg-neutral-50/80 p-4">
          <h3 className="text-sm font-semibold text-neutral-800">Manual stock (no PO)</h3>
          <form onSubmit={p.onManualStock} className="mt-3 max-w-md space-y-3">
            <label className="block text-sm">
              Catalog product *
              <select
                required
                value={p.invManualCatalogId}
                onChange={(e) => p.setInvManualCatalogId(e.target.value)}
                className="mt-1 w-full rounded border border-neutral-300 px-3 py-2 text-sm"
              >
                <option value="">—</option>
                {p.invPickCatalog.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.our_product_id} — {row.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              Quantity *
              <input
                type="number"
                min={1}
                required
                value={p.invManualQty}
                onChange={(e) => p.setInvManualQty(e.target.value)}
                className="mt-1 w-full rounded border border-neutral-300 px-3 py-2 text-sm"
              />
            </label>
            <button type="submit" className="rounded bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-800">
              Add to inventory
            </button>
            {p.invManualMsg ? <p className="text-sm text-red-700">{p.invManualMsg}</p> : null}
          </form>
        </div>
      ) : null}

      {p.inventoryStep === "po" ? (
        <div className="mt-6 rounded border border-neutral-200 bg-neutral-50/80 p-4">
          <h3 className="text-sm font-semibold text-neutral-800">Receive against PO</h3>
          <form onSubmit={(e) => void p.onRecvStock(e)} className="mt-3 max-w-lg space-y-3">
            <label className="block text-sm">
              Purchase order *
              <select
                required
                value={p.recvSelPoId}
                onChange={(e) => p.setRecvSelPoId(e.target.value)}
                className="mt-1 w-full rounded border border-neutral-300 px-3 py-2 text-sm"
              >
                <option value="">—</option>
                {p.recvPoList
                  .filter((row) => row.status === "booked" || row.status === "in_progress")
                  .map((row) => (
                    <option key={row.id} value={row.id}>
                      PO #{row.id} — {p.vendorLabel(row.vendor_id)} ({row.status})
                    </option>
                  ))}
              </select>
            </label>
            {p.recvPoDetail ? (
              <>
                <p className="rounded border border-neutral-200 bg-white px-3 py-2 text-sm">
                  PO status: <strong>{p.recvPoDetail.status}</strong>
                  {p.recvPoDetail.items.map((it) => {
                    const pend =
                      it.quantity_pending ?? Math.max(0, it.quantity - (it.received_quantity ?? 0));
                    const recv = it.received_quantity ?? Math.max(0, it.quantity - pend);
                    return (
                      <span key={it.catalog_product_id} className="mt-1 block text-xs text-neutral-700">
                        {it.name || it.our_product_id}: received <strong>{recv}</strong>, left <strong>{pend}</strong>{" "}
                        (ordered {it.quantity})
                      </span>
                    );
                  })}
                </p>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={p.recvPartial} onChange={(e) => p.setRecvPartial(e.target.checked)} />
                  Partial shipment (upload required if cloud storage is configured)
                </label>
                <label className="block text-sm">
                  Receipt ID *
                  <input
                    value={p.recvReceiptNo}
                    onChange={(e) => p.setRecvReceiptNo(e.target.value)}
                    className="mt-1 w-full rounded border border-neutral-300 px-3 py-2 text-sm"
                    placeholder="Stock receipt id"
                    required
                  />
                </label>
                <label className="block text-sm">
                  Contact number *
                  <input
                    value={p.recvContactNo}
                    onChange={(e) => p.setRecvContactNo(e.target.value)}
                    className="mt-1 w-full rounded border border-neutral-300 px-3 py-2 text-sm"
                    placeholder="Phone / WhatsApp for this shipment"
                    required
                  />
                </label>
                <label className="block text-sm">
                  Receipt scan / PDF {p.recvPartial ? "(required if storage configured)" : "(optional)"}
                  <input
                    type="file"
                    accept=".pdf,.png,.jpg,.jpeg,.webp"
                    className="mt-1 block w-full text-sm"
                    onChange={(e) => p.setRecvFile(e.target.files?.[0] ?? null)}
                  />
                </label>
                <label className="block text-sm">
                  Notes (this shipment)
                  <textarea
                    value={p.recvShipmentNotes}
                    onChange={(e) => p.setRecvShipmentNotes(e.target.value)}
                    rows={2}
                    className="mt-1 w-full rounded border border-neutral-300 px-3 py-2 text-sm"
                    placeholder="Abstract notes…"
                  />
                </label>
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium">Quantities to receive</p>
                    <button
                      type="button"
                      className="text-xs text-neutral-700 underline"
                      onClick={() => {
                        const detail = p.recvPoDetail;
                        if (!detail) return;
                        const next: Record<number, string> = {};
                        for (const it of detail.items) {
                          const pend =
                            it.quantity_pending ??
                            Math.max(0, it.quantity - (it.received_quantity ?? 0));
                          if (pend > 0) next[it.catalog_product_id] = String(pend);
                        }
                        p.setRecvQty(next);
                      }}
                    >
                      Fill all pending
                    </button>
                  </div>
                  {p.recvPoDetail.items.map((it) => {
                    const pend =
                      it.quantity_pending ?? Math.max(0, it.quantity - (it.received_quantity ?? 0));
                    if (pend < 1)
                      return (
                        <p key={it.catalog_product_id} className="text-xs text-neutral-500">
                          {it.name || it.our_product_id}: fully received
                        </p>
                      );
                    return (
                      <label key={it.catalog_product_id} className="flex flex-wrap items-center gap-2 text-sm">
                        <span className="min-w-[10rem] flex-1">
                          {it.name || it.our_product_id} <span className="text-neutral-500">(pending {pend})</span>
                        </span>
                        <input
                          type="number"
                          min={0}
                          placeholder="0"
                          value={p.recvQty[it.catalog_product_id] ?? ""}
                          onChange={(e) =>
                            p.setRecvQty((prev) => ({
                              ...prev,
                              [it.catalog_product_id]: e.target.value,
                            }))
                          }
                          className="w-24 rounded border border-neutral-300 px-2 py-1 text-sm"
                        />
                      </label>
                    );
                  })}
                </div>
                <button type="submit" className="rounded bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-800">
                  Record receipt
                </button>
              </>
            ) : null}
            {p.recvMsg ? <p className="text-sm text-red-700">{p.recvMsg}</p> : null}
            {p.recvOk ? <p className="text-sm text-green-800">{p.recvOk}</p> : null}
          </form>
        </div>
      ) : null}
    </>
  );
}
