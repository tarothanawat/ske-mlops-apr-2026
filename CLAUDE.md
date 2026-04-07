# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **house price prediction MLOps system** demonstrating a complete ML lifecycle: synthetic data generation → initial training → automated drift-detection-triggered retraining → model serving via FastAPI. The stack uses Apache Airflow for orchestration, MLflow for experiment tracking and model registry, and MinIO for S3-compatible object storage.

## Commands

### Start all services
```bash
docker-compose up -d
docker-compose ps   # verify all 11 services are running
```

### Bootstrap (run once after first startup)
```bash
pip install minio pandas numpy synthia
python generate_initial_data.py
```

### Linting
```bash
ruff check serving/ airflow/dags/
```

### Tests
```bash
pytest tests/ -v
pytest tests/test_serving.py -v   # single test file
```

### Service UIs
- Airflow: http://localhost:8080 (credentials from `.env`)
- MLflow: http://localhost:5005
- MinIO Console: http://localhost:9001

### Trigger DAGs
Use the Airflow UI or CLI:
```bash
docker-compose exec airflow-webserver airflow dags trigger dag_pretrain
docker-compose exec airflow-webserver airflow dags trigger dag_retrain
```

### Serving endpoint
```bash
curl http://localhost:8000/health
curl http://localhost:8000/docs   # Swagger UI
```

## Architecture

### Service Layer (docker-compose.yml)
11 services total:
- **postgres** – Airflow metadata DB (port 5432)
- **redis** – Celery broker for Airflow workers
- **airflow-webserver / scheduler / worker / triggerer** – Airflow cluster (CeleryExecutor, port 8080)
- **mlflow-db** – MLflow backend PostgreSQL (port 5433)
- **mlflow-server** – MLflow tracking + Model Registry (port 5005, custom Dockerfile in `docker/mlflow/`)
- **s3 (MinIO)** – Artifact/data store (ports 9000/9001)
- **create_buckets** – One-shot MinIO bucket initializer
- **model-serving** – FastAPI inference service (port 8000)

### Data Flow
1. `generate_initial_data.py` → 20K synthetic rows → MinIO `data/initial_data.csv` + `data/data.csv` (reference)
2. `dag_pretrain` (manual trigger) → reads from MinIO → trains 4 RF hyperparameter combos → registers best to MLflow → promotes to **Production**
3. `dag_retrain` (every 60 min) → generates 5K new synthetic rows → Evidently drift test vs. reference → if drift: blend data, retrain, promote new version
4. FastAPI (`serving/main.py`) loads the **Production** model from MLflow on startup and serves `/predict`

### Shared Utilities
- **`utils.py`** (project root) – ML pipeline definition and MinIO helpers; mounted into Airflow at `/opt/project/utils.py`
- **`airflow/dags/utils.py`** – DAG-level helpers (download/upload S3, build pipeline)
- Both are on `PYTHONPATH` (`/opt/airflow/dags:/opt/project`)

### ML Pipeline (defined in `utils.py`)
```
DropConstantFeatures → DropDuplicateFeatures → DropCorrelatedFeatures(0.85)
→ QualityTransformer (ordinal encode) → MeanMedianImputer → RandomSampleImputer
→ RobustScaler → OneHotEncoder → RandomForestRegressor
```

### DAG Patterns
- **`dag_pretrain.py`**: Linear — `start → pretrain → register_best_model → end`
- **`dag_retrain.py`**: Branching — `start → load_new_data → drift_analysis → branch_selection → [do_nothing | re_data → re_train → register_best_model → promote_model]`
- All training runs 4 hyperparameter combos (`n_estimators=[300,750]` × `max_depth=[5,7]`), logged as MLflow nested runs; best model selected by lowest MAPE
- XComs pass `run_id`, metrics, and timestamps between tasks

### Model Registry Pattern
- Best run → registered as `HousePriceModel` in MLflow Model Registry → transitioned to **Production** stage
- `serving/main.py` loads via `mlflow.pyfunc.load_model("models:/HousePriceModel/Production")` on FastAPI startup (lifespan context manager)

### CI/CD (`.github/workflows/ml-cicd.yml`)
Triggers on push to `main` when `serving/`, `airflow/dags/`, or `tests/` change:
1. **lint-and-test**: `ruff` + `pytest` (MLflow mocked with `MagicMock`, FastAPI `TestClient`)
2. **build-and-push**: Docker image → `ghcr.io` with SHA + latest tags
3. **deploy**: Pull image, restart container, smoke-test `/health`

Required GitHub secrets: `MLFLOW_TRACKING_URI`, `MLFLOW_S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`

## Key Design Decisions

- **Rolling window data management**: `re_data()` blends new synthetic rows into the reference dataset, keeping the latest `N_NEW_ROWS` to prevent unbounded growth
- **Drift branching**: Evidently `DataDriftTestPreset` result (failed test count > 0) controls whether retraining happens; HTML reports saved to `airflow/drift_reports/`
- **Model warm-loading**: The FastAPI app loads the model once at startup; the `/health` endpoint reports whether the model is cached
