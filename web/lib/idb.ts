/* Minimal promise wrapper around IndexedDB (data stays on this device).
   Port of static/idb.js; keep it in step with that file. */

type StoreOpts = { key?: string; auto?: boolean; indexes?: string[] };

export interface Db {
  get<T = unknown>(store: string, key: IDBValidKey): Promise<T | undefined>;
  put(store: string, value: unknown, key?: IDBValidKey): Promise<IDBValidKey | undefined>;
  del(store: string, key: IDBValidKey): Promise<undefined>;
  all<T = unknown>(store: string): Promise<T[]>;
  raw: IDBDatabase;
}

export function openDb(name: string, stores: Record<string, StoreOpts>): Promise<Db> {
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

function wrap(db: IDBDatabase): Db {
  const run = <T>(store: string, mode: IDBTransactionMode, fn: (os: IDBObjectStore) => IDBRequest | void) =>
    new Promise<T>((resolve, reject) => {
      const tx = db.transaction(store, mode);
      const r = fn(tx.objectStore(store));
      tx.oncomplete = () => resolve((r && "result" in r ? r.result : undefined) as T);
      tx.onerror = () => reject(tx.error);
    });
  return {
    get: (s, k) => run(s, "readonly", (os) => os.get(k)),
    put: (s, v, k) => run(s, "readwrite", (os) => (k === undefined ? os.put(v) : os.put(v, k))),
    del: (s, k) => run(s, "readwrite", (os) => os.delete(k)),
    all: (s) => run(s, "readonly", (os) => os.getAll()),
    raw: db,
  };
}
