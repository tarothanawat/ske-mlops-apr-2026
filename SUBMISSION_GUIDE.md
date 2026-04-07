# Assignment Submission Guide

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
Open it in your browser:
```
D:\work\AI-Enabled\april_week_1\ske-mlops-apr-2026\airflow\drift_reports\data_drift_report.html
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
