"""Poll JustAI's MongoDB queue and run LoRA jobs on a separate machine.

Set MONGODB_URI, MONGODB_DATABASE, and MODEL_OUTPUT_DIR before starting.
Use a machine with sufficient memory; a CUDA GPU is strongly recommended.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pymongo import MongoClient, ReturnDocument

BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
POLL_SECONDS = max(3, int(os.getenv("TRAINING_POLL_SECONDS", "10")))
OUTPUT_ROOT = Path(os.getenv("MODEL_OUTPUT_DIR", "./model-artifacts")).resolve()
MONGO_URI = os.getenv("MONGODB_URI", "").strip()
DATABASE_NAME = os.getenv("MONGODB_DATABASE", "justai").strip()


def utcnow():
    return datetime.now(timezone.utc)


def claim_job(db):
    return db.training_jobs.find_one_and_update(
        {"status": "queued"},
        {"$set": {"status": "running", "progress": 5, "started_at": utcnow(), "updated_at": utcnow()}},
        sort=[("created_at", 1)],
        return_document=ReturnDocument.AFTER,
    )


def run_job(db, job):
    dataset = db.training_datasets.find_one({"_id": job["dataset_id"], "user_id": job["user_id"]})
    if not dataset:
        raise RuntimeError("The training dataset no longer exists.")
    job_id = job["_id"]
    output = OUTPUT_ROOT / job_id
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="justai-dataset-") as temp_dir:
        dataset_path = Path(temp_dir) / "dataset.jsonl"
        with dataset_path.open("w", encoding="utf-8") as handle:
            for example in dataset["examples"]:
                handle.write(json.dumps(example, ensure_ascii=False) + "\n")

        db.training_jobs.update_one(
            {"_id": job_id},
            {"$set": {"progress": 15, "updated_at": utcnow()}},
        )
        command = [
            sys.executable, "-m", "training.train_lora",
            "--dataset", str(dataset_path),
            "--output", str(output),
            "--model", BASE_MODEL,
            "--epochs", str(job["epochs"]),
            "--rank", str(job["lora_rank"]),
        ]
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            timeout=int(os.getenv("TRAINING_JOB_TIMEOUT_SECONDS", "21600")),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "Training process failed.")[-4000:])

    model_id = str(uuid4())
    model_record = {
        "_id": model_id,
        "user_id": job["user_id"],
        "job_id": job_id,
        "name": f"JustAI {dataset['name']} adapter",
        "base_model": BASE_MODEL,
        "method": "LoRA",
        "dataset_name": dataset["name"],
        "artifact_path": str(output / "adapter"),
        "created_at": utcnow(),
    }
    db.training_models.insert_one(model_record)
    db.training_jobs.update_one(
        {"_id": job_id},
        {"$set": {
            "status": "completed", "progress": 100, "model_id": model_id,
            "completed_at": utcnow(), "updated_at": utcnow(),
        }},
    )


def main():
    if not MONGO_URI:
        raise SystemExit("MONGODB_URI is required for the training worker.")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    db = client[DATABASE_NAME]
    db.command("ping")
    print("JustAI training worker is online. Waiting for queued jobs.")
    try:
        while True:
            job = claim_job(db)
            if not job:
                time.sleep(POLL_SECONDS)
                continue
            print(f"Training job started: {job['_id']}")
            try:
                run_job(db, job)
                print(f"Training job completed: {job['_id']}")
            except Exception as exc:
                db.training_jobs.update_one(
                    {"_id": job["_id"]},
                    {"$set": {
                        "status": "failed", "progress": 0,
                        "error": str(exc)[-4000:], "updated_at": utcnow(),
                    }},
                )
                print(f"Training job failed: {job['_id']}: {exc}", file=sys.stderr)
    finally:
        client.close()


if __name__ == "__main__":
    main()
