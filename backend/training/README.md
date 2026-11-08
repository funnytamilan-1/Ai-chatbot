# JustAI model training worker

The FastAPI service stores datasets and queues jobs. Actual model training runs in this separate worker process, not inside the Render web service. The first version fine-tunes the small open-weight `Qwen/Qwen2.5-0.5B-Instruct` model with LoRA adapters.

## Requirements

- Python 3.11+
- A dedicated machine with sufficient RAM; a CUDA GPU is strongly recommended.
- Persistent storage for model artifacts. Do not use an ephemeral filesystem for production model files.
- The same MongoDB database configured for the JustAI API.

Install a PyTorch build that matches your machine (use the official PyTorch install selector for CUDA-enabled systems), then install the optional training dependencies from `backend/`:

```bash
pip install -r requirements-training.txt
```

Copy `backend/training/.env.example` as a reference, then set these environment variables in the worker environment:

- `MONGODB_URI`: the same MongoDB Atlas connection string as the API.
- `MONGODB_DATABASE=justai`
- `MODEL_OUTPUT_DIR`: persistent directory for saved adapters.
- Optional: `TRAINING_POLL_SECONDS=10`
- Optional: `TRAINING_JOB_TIMEOUT_SECONDS=21600`

Start the worker from the `backend/` directory:

```bash
python -m training.worker
```

Keep this process running. When a signed-in user queues a job in Training Studio, the worker claims it, downloads the base model, trains a LoRA adapter, and records the artifact path in the model registry.

## Dataset format

Each JSONL line is one conversation example:

```json
{"messages":[{"role":"user","content":"What is Python?"},{"role":"assistant","content":"Python is a programming language."}]}
```

The API accepts 2–2,000 examples per dataset, up to 1 MB of text per upload. Each example must include a user message and end with an assistant answer. Use data you created or have permission to use. Remove personal, private, and confidential information before uploading.

## Important boundaries

- This worker creates and registers an adapter. It does not replace Gemini in the live chat endpoint yet.
- Adapter inference/activation, artifact backup, worker authentication, cancellation, and detailed training metrics are future stages.
- QLoRA 4-bit loading is enabled automatically when CUDA and bitsandbytes are available; otherwise the worker uses standard LoRA.
- Training on a CPU can be very slow. The Render API service is not a training machine.
