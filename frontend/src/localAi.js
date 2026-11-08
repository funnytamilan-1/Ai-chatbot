export const LOCAL_MODEL_ID = "Qwen2.5-0.5B-Instruct-q4f16_1-MLC";
let enginePromise;

export async function checkLocalAiSupport() {
  if (typeof window === "undefined" || !("gpu" in navigator)) {
    throw new Error("This browser does not expose WebGPU. Use a recent WebGPU-capable browser/device to run JustAI locally.");
  }
  const adapter = await navigator.gpu.requestAdapter();
  if (!adapter) throw new Error("No compatible GPU adapter was found. This device cannot load the local AI model.");
  return true;
}

export async function getLocalAiEngine(onProgress = () => {}) {
  await checkLocalAiSupport();
  if (!enginePromise) {
    const { CreateWebWorkerMLCEngine } = await import("@mlc-ai/web-llm");
    const worker = new Worker(new URL("./local-ai.worker.js", import.meta.url), { type: "module" });
    enginePromise = CreateWebWorkerMLCEngine(worker, LOCAL_MODEL_ID, {
      initProgressCallback: (progress) => onProgress(progress),
    }).catch((error) => {
      worker.terminate();
      enginePromise = undefined;
      throw error;
    });
  }
  return enginePromise;
}

export async function streamLocalAiReply({ history = [], prompt, onToken, onProgress }) {
  const engine = await getLocalAiEngine(onProgress);
  const messages = [
    {
      role: "system",
      content: "You are JustAI, a helpful and accurate AI assistant. Reply in the user's language. Understand Tamil written in Latin letters (Tanglish) and reply naturally in Tanglish when appropriate. Explain technical topics clearly, help with coding, and use Markdown when useful. Be honest about uncertainty and never claim to perform actions you did not perform.",
    },
    ...history.slice(-12).map((item) => ({
      role: item.role === "assistant" ? "assistant" : "user",
      content: item.content,
    })),
    { role: "user", content: prompt },
  ];
  const stream = await engine.chat.completions.create({
    messages,
    temperature: 0.7,
    max_tokens: 1024,
    stream: true,
  });
  let reply = "";
  for await (const chunk of stream) {
    const token = chunk.choices?.[0]?.delta?.content || "";
    if (token) {
      reply += token;
      onToken(token, reply);
    }
  }
  if (!reply.trim()) throw new Error("The local AI model returned an empty response. Try again.");
  return reply;
}
