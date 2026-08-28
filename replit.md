# RamanHub on Replit

The **Start application** workflow launches the React/Vite preview on port
5000, and **Backend API** launches FastAPI on port 8000. The Vite server
proxies browser requests from `/api/*` to the local FastAPI service, so the
frontend can use `VITE_API_BASE_URL=/api`.

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