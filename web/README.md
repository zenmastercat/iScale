# iScale web (Next.js)

New frontend for iScale. The backend (`../civil`, FastAPI) is unchanged; the old UI in `../static` stays.

```bash
# backend, from the repo root
uv sync && uv run civil serve        # http://127.0.0.1:8765

# frontend, dev
cd web && pnpm install && pnpm dev   # http://localhost:3000 (/api proxied to :8765)

# frontend, pitch / production-like
pnpm build && pnpm serve             # static export in out/, served + /api proxied on http://127.0.0.1:3000
```

`CIVIL_API` changes the backend URL (both `pnpm dev` and `pnpm serve`). If the backend says
"Invalid host", add your host to `CIVIL_ALLOWED_HOSTS` on the backend.

See `CONTRACT.md` (how the code is organised) and `STATUS.md` (progress).
