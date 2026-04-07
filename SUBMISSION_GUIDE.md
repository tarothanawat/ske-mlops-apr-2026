# Assignment Submission Guide

## If You Cloned This Repo — Start Here

Follow these steps in order. Total time: **~30–40 minutes** (mostly waiting).

---

### Step 1 — Prerequisites (~5 min to verify)
- Docker Desktop installed and **running** with at least 8 GB RAM allocated
- Python 3.11+ installed
- Git installed

---

### Step 2 — Start all services (~10 min first time) ⏱️ WAIT HERE
```bash
docker-compose up -d
```
The first run downloads images and installs ML packages inside the Airflow containers. This takes **5–10 minutes**. Check when ready:
```bash
docker-compose ps
```
All containers should show `Up` or `healthy`. Do not proceed until they do.

---

### Step 3 — Seed training data (~1 min)
```bash
pip install minio pandas numpy
python generate_initial_data.py
```
Expected output: `Uploaded initial_data.csv (20,000 rows)` and `Uploaded data.csv (20,000 rows)`.

---

### Step 4 — Run the pretrain DAG (~5–10 min) ⏱️ WAIT HERE
1. Open Airflow UI → http://localhost:8080 (login: `airflow` / `airflow`)
2. Find the `pretrain` DAG → toggle it **ON** → click **Trigger DAG ▶**
3. Wait until all tasks turn **green** (~5–10 min)
4. Open MLflow → http://localhost:5005 → **Models → house_price_prediction** → should show stage: **Production**

---

### Step 5 — Trigger retrain (run it twice for the assignment) (~5 min each) ⏱️ WAIT HERE
1. Airflow UI → `retrain_if_drift_found` DAG → toggle **ON** → click **Trigger DAG ▶**
2. Wait ~5 min for it to turn green
3. **Trigger it a second time** (assignment requires at least 2 retrain runs in MLflow)
4. After the second run completes, restart the serving container:
```bash
docker-compose restart model-serving
```

---

### Step 6 — Update the drift report path for your machine
The drift report path in screenshot #6 is machine-specific. Find yours at:
```
<your-clone-folder>/airflow/drift_reports/data_drift_report.html
```
Open it directly in your browser (drag and drop the file onto a browser tab).

---

### Time Summary

| Step | What happens | Time |
|------|-------------|------|
| `docker-compose up -d` | Downloads images, installs packages | 5–10 min (first run only) |
| `generate_initial_data.py` | Generates 20K rows, uploads to MinIO | ~30 sec |
| Pretrain DAG | Trains 4 models, registers best to MLflow | ~5–10 min |
| Retrain DAG (×2) | Drift check + retrain + promote | ~5 min each |
| **Total** | | **~30–40 min** |

---

## GitHub Secrets — Where to Find Them

The secrets are already configured in your local `docker-compose.yml`. For the GitHub Actions **deploy** job to work, MLflow and MinIO must be publicly reachable. For the **test** and **build** jobs (lint + pytest + Docker image push), no secrets are needed.

| Secret | Value | Where it comes from |
|--------|-------|---------------------|
| `MLFLOW_TRACKING_URI` | `http://2001:fb1:71:2feb:85e7:a179:aa48:3962:5005` | MLflow server — port 5005 on your machine |
| `MLFLOW_S3_ENDPOINT_URL` | `http://2001:fb1:71:2feb:85e7:a179:aa48:3962:9000` | MinIO server — port 9000 on your machine |
| `AWS_ACCESS_KEY_ID` | `admin` | Hardcoded in `docker-compose.yml` |
| `AWS_SECRET_ACCESS_KEY` | `1qaz2wsx` | Hardcoded in `docker-compose.yml` |

> **Find your public IP:** Run `curl ifconfig.me` in your terminal.  
> **For the test/build jobs only:** You can set the secrets to any placeholder value — they are only consumed by the `deploy` job.

**How to add secrets:**  
GitHub repo → Settings → Secrets and variables → Actions → **New repository secret**

---

## Screenshot Checklist

### 2 — All running containers
**Where:** Open a terminal and run:
```bash
docker-compose ps
```
Take a screenshot showing all containers with `Up` / `healthy` status.

---

### 3 — MinIO with `initial_data.csv`
**Where:** Open http://localhost:9001 in your browser  
- Login: `admin` / `1qaz2wsx`  
- Navigate to **Buckets → data**  
- Take a screenshot showing `initial_data.csv` and `data.csv` in the bucket.

---

### 4 — Airflow DAGs
**Where:** Open http://localhost:8080 in your browser  
- Login: `airflow` / `airflow`  
- Take a screenshot of the DAGs list showing both `pretrain` and `retrain_if_drift_found` with green (success) run indicators.  
- Optionally click into the `retrain_if_drift_found` DAG → Graph view to show the branching pipeline.

---

### 5 — MLflow after retraining at least 2 times
**Where:** Open http://localhost:5005 in your browser  
- Click **Experiments → retrain**  
- Take a screenshot showing **at least 2 parent runs** listed (each retrain trigger creates one parent run with 4 nested child runs).  
- Also go to **Models → house_price_prediction** and screenshot the model versions showing multiple versions promoted to Production.

> To trigger a second retrain manually: Airflow UI → `retrain_if_drift_found` → **Trigger DAG**  
> Wait ~5 minutes for it to complete, then refresh MLflow.

---

### 6 — Drift report output
**Where:** After a retrain run completes, the HTML report is saved to `airflow/drift_reports/data_drift_report.html`  
Open it in your browser by dragging the file onto a browser tab:
```
<your-clone-folder>/airflow/drift_reports/data_drift_report.html
```
Take a screenshot of the Evidently drift report showing the test results (passed/failed tests per feature).

---

### 7 — Corrected DAG code with 10-minute schedule
**What was fixed:** Both `dag_pretrain.py` and `dag_retrain.py` had heavy ML imports (`sklearn`, `mlflow`, `numpy`, `pandas`, `synthia`) at the top of the file. This caused Airflow's DagBag import to time out (30-second limit) and triggered a pandas circular import crash. The fix was to move all heavy imports **inside** each task function.

The retrain schedule was also updated from 60 minutes to **10 minutes**.

**Where to show this:**  
- Open `airflow/dags/dag_retrain.py` in your editor and screenshot the `schedule_interval=timedelta(minutes=10)` line.  
- Screenshot the Airflow UI showing `retrain_if_drift_found` with `Schedule: 0/10 * * * *`.

**GitHub Actions (bonus):**  
- Go to https://github.com/tarothanawat/ske-mlops-apr-2026/actions  
- Click **ml-cicd → Run workflow** to manually trigger the pipeline  
- Screenshot the passing `lint-and-test` and `build-and-push` jobs.
