import { useEffect, useState } from "react";
import { ArrowLeft, BrainCircuit, Database, RefreshCw, Upload, Play, Cpu, Clock3, CheckCircle2, AlertCircle, Layers3 } from "lucide-react";

const SAMPLE = [
  { messages: [{ role: "user", content: "What is Python?" }, { role: "assistant", content: "Python is a general-purpose programming language used to build applications, automate tasks, and work with data." }] },
  { messages: [{ role: "user", content: "What is an API?" }, { role: "assistant", content: "An API is a defined way for software systems to communicate and exchange information." }] },
  { messages: [{ role: "user", content: "Explain a database simply." }, { role: "assistant", content: "A database stores and organizes information so an application can find, add, update, and manage it." }] },
];

function Status({ value }) {
  const status = (value || "queued").toLowerCase();
  return <span className={"training-status status-" + status}>{status}</span>;
}

export default function TrainingStudio({ api, csrf, onBack }) {
  const [overview, setOverview] = useState(null);
  const [datasets, setDatasets] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [models, setModels] = useState([]);
  const [datasetName, setDatasetName] = useState("My first dataset");
  const [datasetText, setDatasetText] = useState(SAMPLE.map(row => JSON.stringify(row)).join("\n"));
  const [selectedDataset, setSelectedDataset] = useState("");
  const [epochs, setEpochs] = useState(1);
  const [rank, setRank] = useState(8);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function request(path, options = {}) {
    const response = await fetch(api + path, {
      credentials: "include",
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.method && options.method !== "GET" ? { "X-CSRF-Token": csrf } : {}),
        ...(options.headers || {}),
      },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Training Studio request failed.");
    return data;
  }

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const [o, d, j, m] = await Promise.all([
        request("/api/training/overview"),
        request("/api/training/datasets"),
        request("/api/training/jobs"),
        request("/api/training/models"),
      ]);
      setOverview(o);
      setDatasets(d.datasets || []);
      setJobs(j.jobs || []);
      setModels(m.models || []);
      if (!selectedDataset && d.datasets?.length) setSelectedDataset(d.datasets[0].id);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  useEffect(() => { refresh(); }, []);

  async function createDataset(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const rows = datasetText.split("\n").map(line => line.trim()).filter(Boolean).map((line, index) => {
        try { return JSON.parse(line); }
        catch { throw new Error("Line " + (index + 1) + " is not valid JSON."); }
      });
      const data = await request("/api/training/datasets", {
        method: "POST",
        body: JSON.stringify({ name: datasetName.trim(), examples: rows }),
      });
      setSelectedDataset(data.dataset.id);
      setNotice("Dataset saved with " + data.dataset.example_count + " examples.");
      await refresh();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function startTraining() {
    if (!selectedDataset) { setError("Create or select a dataset first."); return; }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const data = await request("/api/training/jobs", {
        method: "POST",
        body: JSON.stringify({ dataset_id: selectedDataset, epochs: Number(epochs), lora_rank: Number(rank) }),
      });
      setNotice("Training job queued. It will start when your separate training worker is online.");
      await refresh();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  return (
    <section className="training-studio">
      <div className="training-heading">
        <button className="training-back" onClick={onBack}><ArrowLeft size={17} /> Back to chat</button>
        <div className="training-heading-row">
          <div><p className="eyebrow">JUSTAI LABS</p><h1>Training Studio</h1><p className="training-subtitle">Build a dataset, queue a fine-tuning job, and track your own model adapters.</p></div>
          <div className="training-emblem"><BrainCircuit size={25} /></div>
        </div>
      </div>

      {(error || notice) && <div className={error ? "training-alert" : "training-notice"}>{error ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}<span>{error || notice}</span></div>}

      <div className="training-stats">
        <div className="training-stat"><Database size={17} /><span>Datasets</span><b>{overview?.datasets ?? "–"}</b></div>
        <div className="training-stat"><Clock3 size={17} /><span>Queued</span><b>{overview?.queued_jobs ?? "–"}</b></div>
        <div className="training-stat"><Cpu size={17} /><span>Completed</span><b>{overview?.completed_jobs ?? "–"}</b></div>
        <div className="training-stat"><Layers3 size={17} /><span>Adapters</span><b>{overview?.models ?? "–"}</b></div>
      </div>

      <div className="training-grid">
        <div className="training-panel dataset-panel">
          <div className="training-panel-title"><div className="training-icon"><Database size={17} /></div><div><h2>Dataset manager</h2><p>Import chat examples as JSONL, one example per line.</p></div></div>
          <form onSubmit={createDataset} className="training-form">
            <label>Dataset name<input value={datasetName} onChange={e => setDatasetName(e.target.value)} minLength={2} maxLength={60} required /></label>
            <label>JSONL examples<textarea value={datasetText} onChange={e => setDatasetText(e.target.value)} spellCheck="false" rows={10} required /></label>
            <p className="training-hint">Each line needs a <code>messages</code> array with user and assistant messages. 2–2,000 examples, maximum 1 MB per upload.</p>
            <button className="training-primary" disabled={busy}><Upload size={16} /> {busy ? "Working…" : "Save dataset"}</button>
          </form>
          <div className="training-list-title">Your datasets</div>
          {datasets.length === 0 ? <p className="training-empty">No datasets saved yet.</p> : datasets.map(item => (
            <button key={item.id} className={"dataset-row " + (selectedDataset === item.id ? "active" : "")} onClick={() => setSelectedDataset(item.id)}>
              <Database size={15} /><span><b>{item.name}</b><small>{item.example_count} examples</small></span><span className="dataset-check">{selectedDataset === item.id ? "Selected" : "Select"}</span>
            </button>
          ))}
        </div>

        <div className="training-column">
          <div className="training-panel">
            <div className="training-panel-title"><div className="training-icon"><Cpu size={17} /></div><div><h2>Fine-tune a model</h2><p>Start with a small open-weight model and LoRA.</p></div></div>
            <div className="base-model-card"><span>BASE MODEL</span><b>Qwen 2.5 · 0.5B Instruct</b><small>Qwen/Qwen2.5-0.5B-Instruct</small></div>
            <div className="training-controls">
              <label>Training epochs<select value={epochs} onChange={e => setEpochs(e.target.value)}><option value={1}>1 epoch</option><option value={2}>2 epochs</option><option value={3}>3 epochs</option></select></label>
              <label>LoRA rank<select value={rank} onChange={e => setRank(e.target.value)}><option value={8}>8 · Lightweight</option><option value={16}>16 · Balanced</option><option value={32}>32 · Larger adapter</option></select></label>
            </div>
            <button className="training-primary training-start" disabled={busy || !selectedDataset} onClick={startTraining}><Play size={16} /> Queue training job</button>
            <p className="training-hint">A separate training worker with sufficient RAM and preferably a CUDA GPU must be online. Render's API service only queues the job.</p>
          </div>

          <div className="training-panel">
            <div className="training-panel-title"><div className="training-icon"><Clock3 size={17} /></div><div><h2>Training jobs</h2><p>Queue and job status from MongoDB.</p></div><button className="training-refresh" onClick={refresh} aria-label="Refresh training jobs"><RefreshCw size={15} /></button></div>
            {jobs.length === 0 ? <p className="training-empty">No training jobs yet.</p> : jobs.map(job => (
              <div className="job-row" key={job.id}>
                <div className="job-row-top"><b>{job.dataset_name}</b><Status value={job.status} /></div>
                <small>{job.epochs} epoch · LoRA rank {job.lora_rank}</small>
                <div className="job-progress"><span style={{ width: Math.max(0, Math.min(100, job.progress || 0)) + "%" }} /></div>
                {job.error && <p className="job-error">{job.error}</p>}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="training-panel training-models">
        <div className="training-panel-title"><div className="training-icon"><Layers3 size={17} /></div><div><h2>Model registry</h2><p>Saved adapter versions created by completed jobs.</p></div></div>
        {models.length === 0 ? <p className="training-empty">Your trained adapters will appear here after a worker completes a job.</p> : models.map(model => (
          <div className="model-row" key={model.id}><div className="model-row-mark"><BrainCircuit size={18} /></div><div><b>{model.name}</b><small>{model.base_model} · {model.method} · {model.dataset_name}</small></div><Status value="completed" /></div>
        ))}
      </div>
      <p className="training-disclaimer">Training creates a LoRA adapter. It does not switch the live chat away from Gemini yet. Only upload data you have permission to use, and remove private information first.</p>
    </section>
  );
}
