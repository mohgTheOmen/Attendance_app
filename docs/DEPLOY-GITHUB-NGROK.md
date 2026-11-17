# Deploy with GitHub Pages and ngrok on a Windows PC

GitHub Actions builds and publishes the React frontend to GitHub Pages. The existing CI workflow builds and pushes the backend image to GitHub Container Registry (GHCR) on pushes to `main`. Docker Desktop on the Windows PC runs PostgreSQL, the backend, ngrok, Prometheus, and Grafana. Keep the PC and Docker Desktop running for the API and dashboards to stay online.

## 1. Get an ngrok domain

Create an ngrok account and copy its authtoken and assigned HTTPS dev domain from the [ngrok dashboard](https://dashboard.ngrok.com/domains). Use the same domain every time; the frontend build embeds this URL. The assigned domain looks like `https://example.ngrok-free.dev`.

## 2. Configure the repository

1. In GitHub, open **Settings → Secrets and variables → Actions → Variables**. Add `NGROK_API_ORIGIN` with the HTTPS ngrok URL, without `/api` or a trailing slash. This is a public URL, so it is a variable, not a secret.
2. Open **Settings → Pages** and choose **GitHub Actions** as the build and deployment source.
3. Push this change to `main`, or manually run **Publish frontend to GitHub Pages** from the Actions tab. The frontend will be at `https://mohgtheomen.github.io/Attendance_app/` if the repository keeps its current owner and name.
4. The existing **CI/CD** workflow pushes `ghcr.io/mohgtheomen/attendance_app-backend:latest` after its checks pass. Make that GHCR package public, or sign in to GHCR from Docker Desktop before pulling it.

GitHub Pages serves static files. The API, PostgreSQL, and uploaded photos stay on the Windows PC.

## 3. Configure the Windows PC

Install Docker Desktop and keep it running. From the repo root in PowerShell:

```powershell
Copy-Item .env.deploy.example .env.deploy
```

Edit `.env.deploy`:

- Set `NGROK_URL` to the exact domain in `NGROK_API_ORIGIN`, including `https://`.
- Set `NGROK_AUTHTOKEN` to your ngrok token. Keep `.env.deploy` private.
- Set a strong `POSTGRES_PASSWORD` and use the same password in `DATABASE_URL`. If it contains URL-special characters, percent-encode them in `DATABASE_URL`.
- Generate a long random `JWT_SECRET`, and set a strong `ADMIN_PASSWORD` and your `ADMIN_EMAIL`.
- Set `CORS_ORIGINS` to the GitHub Pages *origin*, for example `["https://mohgtheomen.github.io"]`. Do not include `/Attendance_app/`.
- Adjust `BACKEND_IMAGE` if the GitHub owner or repository name changes.
- Set different strong passwords for `GRAFANA_ADMIN_PASSWORD` and `GRAFANA_DB_PASSWORD`. Grafana is available only on your PC at `http://localhost:3000` by default; change `GRAFANA_PORT` if port 3000 is taken.

Start the local services:

```powershell
docker compose --env-file .env.deploy -f compose.deploy.yml pull
docker compose --env-file .env.deploy -f compose.deploy.yml up -d
docker compose --env-file .env.deploy -f compose.deploy.yml ps
docker compose --env-file .env.deploy -f compose.deploy.yml logs ngrok --tail 50
```

Open `https://YOUR-DOMAIN.ngrok-free.dev/health` to check the API, then open the Pages URL and sign in with the admin credentials from `.env.deploy`. The public API URL is embedded in the frontend at build time; if it changes, update `NGROK_API_ORIGIN` and rerun the Pages workflow.

## Attendance reports in Grafana

Open `http://localhost:3000` on the Windows PC and sign in as `admin` with `GRAFANA_ADMIN_PASSWORD` from `.env.deploy`. Open the **Attendance** folder. The dashboards include **Report 1 - Individual Attendance Record** (select a student and date range), **Report 5 - Class Session Attendance Sheet** (select a session), **Attendance Overview**, and **Attendance API Health**.

To export a report, open the report's table panel menu, choose **Inspect → Data**, enable **Download for Excel** if needed, then choose **Download CSV**. The CSV opens in Excel. Grafana OSS does not provide native dashboard PDF export; use your browser's print-to-PDF for a visual snapshot, or the application's existing Excel export where applicable. Grafana stays local on the PC and is not exposed through ngrok.

The attendance record counts approved and pending check-ins as present and rejected check-ins as missed. It lists past sessions in the selected date range that currently target the student's groups (or everyone). The session sheet includes current expected students plus any extra attendees. Group membership is current, not a historical snapshot. Course, semester, excuse documents, grades, and check-out times are not stored yet, so the other recommended reports require data-model work before they can be accurate.

## Updates and data

Each push to `main` runs CI and publishes a new backend image. On the PC, run the `pull` and `up -d` commands above to update the backend. The Pages workflow republishes frontend changes automatically.

The `pgdata`, `uploads`, and `grafana` Docker volumes persist across container recreation. Back up these volumes before upgrades and test restoring them. Do not run `docker compose down -v` against this deployment, because that removes the data volumes.

The backend image includes Tesseract for paper-list OCR. OCR imports and their attendance records are stored in PostgreSQL; imported sheet images use the existing `uploads` volume. The backend starts by applying Alembic migrations, including the OCR schema migration. A local roster spreadsheet is not part of the image and should be imported separately if its users are needed. Azure OCR is optional and requires separate credentials.

GitHub Actions cannot keep the backend online after a workflow ends. The ngrok free plan has usage limits and may show an interstitial to direct browser visits; the frontend sets ngrok's skip-warning request header for API calls. For a public service with uptime requirements, use an always-on server and a production domain.
