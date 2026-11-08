import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { ArrowUp, MessageSquarePlus, Plus, Sparkles, Sun, Moon, Menu, X, Trash2, Copy, Check } from "lucide-react";

const API = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const KEY = "justai_chats_v1";
const makeChat = () => ({ id: crypto.randomUUID(), title: "New chat", messages: [], updatedAt: Date.now() });

export default function App() {
  const [chats, setChats] = useState(() => {
    try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { return []; }
  });
  const [activeId, setActiveId] = useState(() => chats[0]?.id || null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [light, setLight] = useState(false);
  const [copied, setCopied] = useState("");
  const bottomRef = useRef(null);
  const active = useMemo(() => chats.find(c => c.id === activeId) || null, [chats, activeId]);

  useEffect(() => { localStorage.setItem(KEY, JSON.stringify(chats)); }, [chats]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [active?.messages, busy]);

  function newChat() {
    const c = makeChat();
    setChats(prev => [c, ...prev]);
    setActiveId(c.id);
    setInput("");
    setError("");
    setSidebarOpen(false);
  }
  function updateChat(id, fn) { setChats(prev => prev.map(c => c.id === id ? fn(c) : c)); }
  async function sendMessage(value) {
    const prompt = (value === undefined ? input : value).trim();
    if (!prompt || busy) return;
    let chat = active;
    if (!chat) {
      chat = makeChat();
      setChats(prev => [chat, ...prev]);
      setActiveId(chat.id);
    }
    const previous = chat.messages;
    const userMessage = { id: crypto.randomUUID(), role: "user", content: prompt };
    updateChat(chat.id, c => ({ ...c, title: c.messages.length ? c.title : prompt.slice(0, 36), messages: [...c.messages, userMessage], updatedAt: Date.now() }));
    setInput("");
    setBusy(true);
    setError("");
    try {
      const history = previous.slice(-20).map(m => ({ role: m.role === "assistant" ? "model" : "user", content: m.content }));
      const response = await fetch(API + "/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: prompt, history })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Could not get a response. Please try again.");
      updateChat(chat.id, c => ({ ...c, messages: [...c.messages, { id: crypto.randomUUID(), role: "assistant", content: data.reply, model: data.model }], updatedAt: Date.now() }));
    } catch (e) {
      setError(e.message || "Could not reach the JustAI server.");
    } finally { setBusy(false); }
  }
  function deleteChat(id) {
    setChats(prev => {
      const next = prev.filter(c => c.id !== id);
      if (activeId === id) setActiveId(next[0]?.id || null);
      return next;
    });
  }
  async function copyText(id, value) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(id);
      setTimeout(() => setCopied(""), 1300);
    } catch { setError("Clipboard is not available in this browser."); }
  }
  function keyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  }

  return (
    <div className={"app-shell " + (light ? "light" : "")}>
      {sidebarOpen && <button className="scrim" aria-label="Close menu" onClick={() => setSidebarOpen(false)} />}
      <aside className={"sidebar " + (sidebarOpen ? "sidebar-open" : "")}>
        <div className="brand-row">
          <div className="brand-mark"><Sparkles size={19} /></div>
          <span className="brand-name">just<span>ai</span></span>
          <button className="icon-btn sidebar-close" onClick={() => setSidebarOpen(false)} aria-label="Close sidebar"><X size={18} /></button>
        </div>
        <button className="new-chat" onClick={newChat}><Plus size={17} /> New chat</button>
        <div className="side-label">YOUR SPACE</div>
        <div className="chat-list">
          {chats.length === 0 && <p className="empty-history">Your conversations will appear here.</p>}
          {chats.map(c => (
            <div key={c.id} className={"chat-item " + (c.id === activeId ? "selected" : "")}>
              <button className="chat-select" onClick={() => { setActiveId(c.id); setSidebarOpen(false); }}>
                <MessageSquarePlus size={15} /><span>{c.title}</span>
              </button>
              <button className="delete-chat" aria-label="Delete chat" onClick={() => deleteChat(c.id)}><Trash2 size={14} /></button>
            </div>
          ))}
        </div>
        <div className="sidebar-bottom">
          <div className="profile-chip"><div className="avatar">J</div><div><b>JustAI</b><small>Personal assistant</small></div></div>
          <button className="theme-toggle" onClick={() => setLight(v => !v)}>{light ? <Moon size={16} /> : <Sun size={16} />} {light ? "Dark appearance" : "Light appearance"}</button>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div className="top-left">
            <button className="icon-btn menu-btn" onClick={() => setSidebarOpen(true)} aria-label="Open menu"><Menu size={20} /></button>
            <span className="mobile-brand">just<span>ai</span></span>
            <span className="model-pill"><span className="status-dot" /> JustAI <span className="model-muted">· Assistant</span></span>
          </div>
          <button className="icon-btn desktop-new" onClick={newChat} aria-label="New chat"><MessageSquarePlus size={18} /></button>
        </header>

        <section className="conversation">
          {!active?.messages?.length ? (
            <div className="welcome">
              <div className="welcome-orb"><Sparkles size={28} /></div>
              <p className="eyebrow">YOUR IDEAS, IN MOTION</p>
              <h1>What can I help<br /><em>you explore?</em></h1>
              <p className="welcome-copy">Ask anything. Build something. Figure it out.<br />Let's make a little progress today.</p>
              <div className="prompt-grid">
                {[
                  ["✦", "Explain something", "Explain how artificial intelligence works in simple words."],
                  ["⌘", "Help me code", "Help me build a simple responsive website."],
                  ["↗", "Explore an idea", "Give me 5 creative ideas for a mobile app."],
                  ["文", "Learn something new", "Teach me three useful Python concepts with examples."]
                ].map(([icon, title, prompt]) => (
                  <button className="prompt-card" key={title} onClick={() => sendMessage(prompt)}>
                    <span>{icon}</span><b>{title}</b><small>{prompt}</small>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="messages">
              {active.messages.map(m => (
                <article className={"message " + m.role} key={m.id}>
                  <div className="message-avatar">{m.role === "assistant" ? <Sparkles size={15} /> : "Y"}</div>
                  <div className="message-body">
                    <div className="message-name">{m.role === "assistant" ? "JustAI" : "You"}</div>
                    <div className="message-content">{m.role === "assistant" ? <ReactMarkdown>{m.content}</ReactMarkdown> : <p>{m.content}</p>}</div>
                    {m.role === "assistant" && <button className="copy-btn" onClick={() => copyText(m.id, m.content)}>{copied === m.id ? <Check size={14} /> : <Copy size={14} />} {copied === m.id ? "Copied" : "Copy"}</button>}
                  </div>
                </article>
              ))}
              {busy && <article className="message assistant"><div className="message-avatar"><Sparkles size={15} /></div><div className="message-body"><div className="message-name">JustAI</div><div className="typing"><i /><i /><i /></div></div></article>}
              <div ref={bottomRef} />
            </div>
          )}
        </section>

        <div className="composer-wrap">
          {error && <div className="error-note"><span>{error}</span><button onClick={() => setError("")}><X size={14} /></button></div>}
          <div className="composer">
            <textarea rows="1" value={input} onChange={e => setInput(e.target.value)} onKeyDown={keyDown} placeholder="Message JustAI..." aria-label="Message JustAI" />
            <div className="composer-footer">
              <span className="composer-hint">JustAI can make mistakes. Check important information.</span>
              <button className="send-btn" disabled={!input.trim() || busy} onClick={() => sendMessage()} aria-label="Send message"><ArrowUp size={19} /></button>
            </div>
          </div>
          <div className="powered">MADE FOR CURIOUS MINDS <span>·</span> JUSTAI</div>
        </div>
      </main>
    </div>
  );
}
