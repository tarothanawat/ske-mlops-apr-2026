# MLOps Intensive — 3-Hour Session

**Stack:** Airflow 2.11.2 · MLflow 2.21.3 · MinIO · FastAPI · GitHub Actions

---

## Project structure

```
mlops-project/
├── airflow/
│   ├── dags/
│   │   ├── dag_pretrain.py       # Bootstrap — train and register initial model
│   │   ├── dag_retrain.py        # Scheduled — auto-retrain on drift detection
│   │   └── utils.py              # Shared helpers (MinIO, pipeline)
│   ├── config/                   # Airflow config (auto-created)
│   ├── drift_reports/            # Evidently HTML reports (auto-created)
│   ├── logs/                     # Airflow task logs (auto-created)
│   └── plugins/
├── serving/
│   ├── main.py                   # FastAPI prediction endpoint
│   ├── Dockerfile
│   └── requirements.txt
├── tests/
│   └── test_serving.py           # Unit tests used in CI
├── .github/
│   └── workflows/
│       └── ml-cicd.yml           # GitHub Actions: lint -> test -> build -> deploy
├── generate_initial_data.py      # One-time script to seed MinIO with training data
├── docker-compose.yml
└── .env
```

---

## Service ports

| Service        | URL                         | Credentials        |
|----------------|-----------------------------|--------------------|
| Airflow UI     | http://localhost:8080       |                    |
| MLflow UI      | http://localhost:5005       | —                  |
| MinIO Console  | http://localhost:9001       |                    |
| Serving API    | http://localhost:8000/docs  | —                  |

---

## Step-by-step setup

### Step 0 — Prerequisites

- Docker Desktop running with at least 8 GB RAM
- Python 3.11+ installed locally

```bash
cd mlops-project

# Linux/Mac only
echo "AIRFLOW_UID=$(id -u)" >> .env
```

---

### Step 1 — Start all services

```bash
docker-compose up -d
```

First run takes 5–10 minutes (Airflow installs ML packages on startup).
Check all containers are healthy:

```bash
docker-compose ps
```

---

### Step 2 — Seed training data

```bash
pip install minio pandas numpy
python generate_initial_data.py
```

Verify in MinIO Console (http://localhost:9001):
- bucket `data` contains `initial_data.csv` and `data.csv`

---

### Step 3 — Run pretrain DAG

1. Open Airflow UI → http://localhost:8080
2. Toggle DAG `pretrain` to ON
3. Click **Trigger DAG**
4. Wait ~5–10 minutes for all tasks to turn green
5. Open MLflow UI → Models → `house_price_prediction` → stage: **Production**

---

### Step 4 — Test the serving API

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d "{\"features\": [{\"area\": 120.5, \"bedrooms\": 3, \"bathrooms\": 2, \"floor\": 5, \"age\": 10, \"distance_bts\": 0.8, \"distance_center\": 5.2, \"parking\": 1, \"quality\": \"good\", \"direction\": \"north\"}]}"
```

Or open Swagger UI at http://localhost:8000/docs

---

### Step 5 — Trigger retrain DAG

1. Toggle DAG `retrain_if_drift_found` to ON
2. Click **Trigger DAG**
3. Watch Graph view — `branch_selection` routes to `re_data` or `do_nothing`
4. After retrain completes, reload serving:

```bash
docker-compose restart model-serving
```

---

### Step 6 — CI/CD push to GitHub

Set GitHub Secrets (Settings → Secrets and variables → Actions):

| Secret                   | Value                  |
|--------------------------|------------------------|
| `MLFLOW_TRACKING_URI`    | MLflow server URL      |
| `MLFLOW_S3_ENDPOINT_URL` | MinIO URL              |
| `AWS_ACCESS_KEY_ID`      | admin                  |
| `AWS_SECRET_ACCESS_KEY`  | 1qaz2wsx               |

```bash
git init
git remote add origin https://github.com/<username>/<repo>.git
git add .
git commit -m "feat: initial mlops project"
git push origin main
```

Watch GitHub Actions: lint → test → build → deploy
