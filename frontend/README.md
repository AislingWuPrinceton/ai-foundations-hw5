# Campus Customs dashboard

React + Vite + TypeScript operations desk for the Campus Customs agent team.

```bash
npm install
npm run dev        # http://localhost:5173
```

It talks to the FastAPI backend from Problem 7, which must be running:

```bash
cd ../backend && ../.venv/bin/uvicorn main:app --reload --port 8000
```

The backend URL defaults to `http://localhost:8000`. To change it, copy `.env.example` to `.env` and set `VITE_API_BASE_URL`. The backend allows the `http://localhost:5173` origin by default; set `CAMPUS_CUSTOMS_FRONTEND_ORIGINS` on the backend for other ports.

`npm run build` runs the TypeScript check (`tsc -b`) and the production build. See `../output/design.md` for the layout and design decisions.
