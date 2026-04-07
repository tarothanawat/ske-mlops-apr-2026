import pytz
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator
from airflow.utils.dates import days_ago

from utils import download_from_s3, pipeline_prep

MLFLOW_URI  = "http://mlflow-server:5005"
MODEL_NAME  = "house_price_prediction"
PARAM_GRID  = [(n, d) for n in [300, 750] for d in [5, 7]]

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 0,
    "retry_delay": timedelta(minutes=1),
    "email_on_failure": False,
    "provide_context": True,
}


def pretrain(**context) -> None:
    """Train all hyperparameter combinations and log to MLflow."""
    import numpy as np
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import (
        r2_score,
        mean_absolute_error,
        mean_squared_error,
        mean_absolute_percentage_error,
    )
    import mlflow
    from mlflow.models import infer_signature

    df = download_from_s3("data", "initial_data.csv")
    X  = df.drop(columns=["target"])
    y  = df["target"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    mlflow.set_tracking_uri(MLFLOW_URI)
    experiment  = mlflow.set_experiment("pretrain")
    mlflow.sklearn.autolog(log_models=False)

    dt_string = datetime.now(tz=pytz.timezone("Asia/Bangkok")).strftime("%d%m%Y_%H%M%S")

    with mlflow.start_run(run_name=dt_string) as parent_run:
        for n_est, max_d in PARAM_GRID:
            with mlflow.start_run(run_name=f"n{n_est}_d{max_d}", nested=True):
                pipe   = pipeline_prep(n_estimators=n_est, max_depth=max_d)
                pipe.fit(X_train, y_train)
                y_pred = pipe.predict(X_test)

                mlflow.log_metrics({
                    "testing_rmse": float(np.sqrt(mean_squared_error(y_test, y_pred))),
                    "testing_r2":   float(r2_score(y_test, y_pred)),
                    "testing_mae":  float(mean_absolute_error(y_test, y_pred)),
                    "testing_mape": float(mean_absolute_percentage_error(y_test, y_pred) * 100),
                })
                mlflow.sklearn.log_model(
                    sk_model=pipe,
                    artifact_path="mlflow",
                    signature=infer_signature(X_test, y_pred),
                    code_paths=[],
                )

        context["ti"].xcom_push(key="experiment_id", value=experiment.experiment_id)
        context["ti"].xcom_push(key="parent_run_id", value=parent_run.info.run_id)


def register_best_model(**context) -> None:
    """Select the lowest-MAPE child run, register and promote to Production."""
    import mlflow
    from mlflow.tracking import MlflowClient

    experiment_id = context["ti"].xcom_pull(key="experiment_id")
    parent_run_id = context["ti"].xcom_pull(key="parent_run_id")

    mlflow.set_tracking_uri(MLFLOW_URI)
    runs = mlflow.search_runs(
        experiment_ids=[experiment_id],
        filter_string=f"tags.mlflow.parentRunId = '{parent_run_id}'",
        order_by=["metrics.testing_mape ASC"],
    )

    if runs.empty:
        raise ValueError("No child runs found — check pretrain task logs.")

    best_run_id = runs.iloc[0]["run_id"]
    mv = mlflow.register_model(f"runs:/{best_run_id}/mlflow", MODEL_NAME)

    client = MlflowClient(tracking_uri=MLFLOW_URI)
    client.transition_model_version_stage(
        name=MODEL_NAME,
        version=mv.version,
        stage="Production",
        archive_existing_versions=True,
    )
    print(f"Registered and promoted {MODEL_NAME} v{mv.version} -> Production")


with DAG(
    default_args=default_args,
    dag_id="pretrain",
    description="Initial training — run once",
    start_date=days_ago(1),
    schedule_interval=None,
    catchup=False,
) as dag:

    start  = EmptyOperator(task_id="start")
    end    = EmptyOperator(task_id="end")

    t_pretrain = PythonOperator(task_id="pretrain",            python_callable=pretrain)
    t_register = PythonOperator(task_id="register_best_model", python_callable=register_best_model)

    start >> t_pretrain >> t_register >> end
