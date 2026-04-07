import os
import random
import pytz
from datetime import datetime, timedelta

from airflow import DAG
from airflow.utils.dates import days_ago
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.operators.empty import EmptyOperator

from utils import download_from_s3, upload_to_s3, pipeline_prep

MLFLOW_URI       = "http://mlflow-server:5005"
MODEL_NAME       = "house_price_prediction"
PRODUCTION_STAGE = "Production"
N_NEW_ROWS       = 5_000
PARAM_GRID       = [(n, d) for n in [300, 750] for d in [5, 7]]

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 0,
    "retry_delay": timedelta(minutes=3),
    "email_on_failure": False,
    "provide_context": True,
}


def load_new_data(**context) -> None:
    """Generate synthetic data using GaussianCopula and upload to MinIO."""
    import numpy as np
    import pandas as pd
    import synthia as syn

    initial_data = download_from_s3("data", "initial_data.csv")

    numeric_cols = initial_data.drop(columns=["quality", "direction", "target"]).columns
    df_num       = initial_data[numeric_cols].dropna()

    generator = syn.CopulaDataGenerator()
    generator.fit(
        df_num,
        copula=syn.GaussianCopula(),
        parameterize_by=syn.QuantileParameterizer(n_quantiles=10),
    )
    samples   = generator.generate(n_samples=N_NEW_ROWS, uniformization_ratio=1, stretch_factor=1)
    synthetic = pd.DataFrame(samples, columns=numeric_cols)

    for col in ["quality", "direction", "target"]:
        values = [v for v in initial_data[col].unique() if v not in [np.nan, None]]
        synthetic[col] = random.choices(values, k=len(synthetic))

    dt_string = datetime.now(tz=pytz.timezone("Asia/Bangkok")).strftime("%d%m%Y_%H%M%S")
    upload_to_s3(synthetic, "data", f"new_data_{dt_string}.csv")
    context["ti"].xcom_push(key="dt_string", value=dt_string)


def drift_analysis(**context) -> None:
    """Run Evidently DataDriftTestPreset and push pass/fail counts via XComs."""
    from evidently.test_suite import TestSuite
    from evidently.test_preset import DataDriftTestPreset

    dt_string = context["ti"].xcom_pull(key="dt_string")
    new_df    = download_from_s3("data", f"new_data_{dt_string}.csv").drop(columns=["target"])
    ref_df    = download_from_s3("data", "data.csv").drop(columns=["target"])

    suite = TestSuite(tests=[DataDriftTestPreset()])
    suite.run(reference_data=ref_df, current_data=new_df)

    report_dir = "/opt/airflow/drift_reports"
    os.makedirs(report_dir, exist_ok=True)
    suite.save_html(os.path.join(report_dir, "data_drift_report.html"))

    summary = suite.as_dict()["summary"]
    context["ti"].xcom_push(key="num_success_tests", value=summary["success_tests"])
    context["ti"].xcom_push(key="num_failed_tests",  value=summary["failed_tests"])
    print(f"Drift check — passed: {summary['success_tests']}, failed: {summary['failed_tests']}")


def choose_branch(**context) -> str:
    """Route to 're_data' if drift detected, else 'do_nothing'."""
    failed = context["ti"].xcom_pull(key="num_failed_tests")
    result = "re_data" if failed != 0 else "do_nothing"
    print(f"Drift failed tests: {failed} -> branch: {result}")
    return result


def re_data(**context) -> None:
    """
    Blend new data into the reference dataset (rolling window).
    Only executed when drift is detected — Bug #1 fix.
    """
    import pandas as pd

    dt_string = context["ti"].xcom_pull(key="dt_string")
    new_df    = download_from_s3("data", f"new_data_{dt_string}.csv")
    ref_df    = download_from_s3("data", "data.csv")
    blended   = pd.concat([ref_df, new_df], ignore_index=True)
    updated   = blended.iloc[N_NEW_ROWS:].copy()
    upload_to_s3(updated, "data", "data.csv")
    print(f"data.csv updated: {len(updated):,} rows")


def re_train(**context) -> None:
    """Retrain all PARAM_GRID combinations on the updated dataset."""
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

    dt_string         = context["ti"].xcom_pull(key="dt_string")
    num_success_tests = context["ti"].xcom_pull(key="num_success_tests")
    num_failed_tests  = context["ti"].xcom_pull(key="num_failed_tests")

    df = download_from_s3("data", "data.csv")
    X  = df.drop(columns=["target"])
    y  = df["target"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    mlflow.set_tracking_uri(MLFLOW_URI)
    experiment  = mlflow.set_experiment("retrain")
    mlflow.sklearn.autolog(log_models=False)

    with mlflow.start_run(run_name=dt_string) as parent_run:
        mlflow.log_params({
            "drift_passed": num_success_tests,
            "drift_failed": num_failed_tests,
        })
        mlflow.log_artifact(os.path.join("/opt/airflow/drift_reports", "data_drift_report.html"))

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
    """
    Register the lowest-MAPE child run.
    Uses experiment_id + parent_run_id filter
    """
    import mlflow

    experiment_id = context["ti"].xcom_pull(key="experiment_id")
    parent_run_id = context["ti"].xcom_pull(key="parent_run_id")

    mlflow.set_tracking_uri(MLFLOW_URI)
    runs = mlflow.search_runs(
        experiment_ids=[experiment_id],
        filter_string=f"tags.mlflow.parentRunId = '{parent_run_id}'",
        order_by=["metrics.testing_mape ASC"],
    )

    if runs.empty:
        raise ValueError(f"No child runs found for parent_run_id={parent_run_id}")

    best_run_id = runs.iloc[0]["run_id"]
    mv = mlflow.register_model(f"runs:/{best_run_id}/mlflow", MODEL_NAME)
    print(f"Registered {MODEL_NAME} v{mv.version} (run_id={best_run_id})")
    context["ti"].xcom_push(key="model_version", value=mv.version)


def promote_model(**context) -> None:
    """Transition the newly registered model version to Production."""
    from mlflow.tracking import MlflowClient

    model_version = context["ti"].xcom_pull(key="model_version")
    client = MlflowClient(tracking_uri=MLFLOW_URI)
    client.transition_model_version_stage(
        name=MODEL_NAME,
        version=model_version,
        stage=PRODUCTION_STAGE,
        archive_existing_versions=True,
    )
    print(f"{MODEL_NAME} v{model_version} -> {PRODUCTION_STAGE}")


with DAG(
    default_args=default_args,
    dag_id="retrain_if_drift_found",
    description="Auto-retrain when data drift is detected",
    start_date=days_ago(1),
    schedule_interval=timedelta(minutes=60),
    catchup=False,
) as dag:

    start      = EmptyOperator(task_id="start")
    do_nothing = EmptyOperator(task_id="do_nothing")
    end        = EmptyOperator(task_id="end", trigger_rule="none_failed")

    t_load   = PythonOperator(task_id="load_new_data",       python_callable=load_new_data)
    t_drift  = PythonOperator(task_id="drift_analysis",      python_callable=drift_analysis)
    t_branch = BranchPythonOperator(task_id="branch_selection", python_callable=choose_branch)
    t_redata = PythonOperator(task_id="re_data",             python_callable=re_data)
    t_train  = PythonOperator(task_id="re_train",            python_callable=re_train)
    t_reg    = PythonOperator(task_id="register_best_model", python_callable=register_best_model)
    t_promo  = PythonOperator(task_id="promote_model",       python_callable=promote_model)

    start >> t_load >> t_drift >> t_branch >> [do_nothing, t_redata]
    t_redata >> t_train >> t_reg >> t_promo
    [do_nothing, t_promo] >> end
