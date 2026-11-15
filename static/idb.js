/* Minimal promise wrapper around IndexedDB (data stays on this device). */
export function openDb(name, stores) {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(name, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      for (const [s, opts] of Object.entries(stores)) {
        if (!db.objectStoreNames.contains(s)) {
          const os = db.createObjectStore(s, opts.key ? { keyPath: opts.key, autoIncrement: !!opts.auto } : undefined);
          for (const ix of opts.indexes || []) os.createIndex(ix, ix);
        }
      }
    };
    req.onsuccess = () => resolve(wrap(req.result));
    req.onerror = () => reject(req.error);
  });
}

function wrap(db) {
  const run = (store, mode, fn) => new Promise((resolve, reject) => {
    const tx = db.transaction(store, mode);
    const r = fn(tx.objectStore(store));
    tx.oncomplete = () => resolve(r && "result" in r ? r.result : undefined);
    tx.onerror = () => reject(tx.error);
  });
  return {
    get: (s, k) => run(s, "readonly", (os) => os.get(k)),
    put: (s, v, k) => run(s, "readwrite", (os) => (k === undefined ? os.put(v) : os.put(v, k))),
    del: (s, k) => run(s, "readwrite", (os) => os.delete(k)),
    all: (s) => run(s, "readonly", (os) => os.getAll()),
    byIndex: (s, ix, v) => run(s, "readonly", (os) => os.index(ix).getAll(v)),
    raw: db,
  };
}
