# RamanHub on Replit

The **Backend API** workflow launches FastAPI on port 8000. The web app is a
Next.js workspace at the repo root — run it with `pnpm dev:web` (it rewrites
`/api/*` to the local FastAPI service, so no API base URL config is needed in
the browser). The old React/Vite `frontend/` was removed in M4.

The app uses Replit's managed PostgreSQL connection. Database migrations and
the required reference seed data have been applied. Development file uploads
use local filesystem storage (`STORAGE_BACKEND=local`) rather than MinIO.

Google sign-in and Anthropic-powered header parsing are optional and are not
configured. Add their credentials only when testing those features. The
backend uses the existing Replit `SESSION_SECRET` as its JWT signing secret at
runtime.

For backend commands outside the workflow, run them from `backend/` with the
available runtime explicitly selected, for example:

```bash
uv run --python 3.12 pytest
```