/** In-memory cache with TTL for fast repeat loads */
const Cache = (() => {
  const store = new Map();
  const DEFAULT_TTL = 5 * 60 * 1000;

  function key(path, params) {
    return path + (params ? "?" + new URLSearchParams(params).toString() : "");
  }

  function get(path, params) {
    const k = key(path, params);
    const e = store.get(k);
    if (!e) return null;
    if (Date.now() > e.expires) { store.delete(k); return null; }
    return e.data;
  }

  function set(path, data, params, ttl = DEFAULT_TTL) {
    store.set(key(path, params), { data, expires: Date.now() + ttl });
  }

  function invalidate(prefix) {
    for (const k of store.keys()) {
      if (k.startsWith(prefix)) store.delete(k);
    }
  }

  function clear() { store.clear(); }

  return { get, set, invalidate, clear };
})();
