import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { ArrowUp, MessageSquarePlus, Plus, Sparkles, Sun, Moon, Menu, X, Trash2, Copy, Check, LogOut, UserRound } from "lucide-react";

const API = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "justai_token_v1";
const THEME_KEY = "justai_theme_v1";

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || "");
  const [user, setUser] = useState(null);
  const [authMode, setAuthMode] = useState("login");
  const [authName, setAuthName] = useState("");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authReady, setAuthReady] = useState(false);
  const [chats, setChats] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [light, setLight] = useState(() => localStorage.getItem(THEME_KEY) === "light");
  const [copied, setCopied] = useState("");
  const bottomRef = useRef(null);
  const active = useMemo(() => chats.find(c => c.id === activeId) || null, [chats, activeId]);

  const authHeaders = () => ({ "Content-Type": "application/json", Authorization: "Bearer " + token });

  async function loadChats(currentToken = token) {
    const response = await fetch(API + "/api/chats", { headers: { Authorization: "Bearer " + currentToken } });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Could not load your chats.");
    const items = (data.chats || []).map(c => ({ id: c.id, title: c.title, messages: [], updatedAt: Date.parse(c.updated_at) || Date.now() }));
    setChats(items);
    setActiveId(items[0]?.id || null);
  }

  useEffect(() => {
    let cancelled = false;
    async function restore() {
      if (!token) { setAuthReady(true); return; }
      try {
        const response = await fetch(API + "/api/auth/me", { headers: { Authorization: "Bearer " + token } });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error("Session expired");
        if (!cancelled) {
          setUser(data.user);
          const chatsResponse = await fetch(API + "/api/chats", { headers: { Authorization: "Bearer " + token } });
          const chatsData = await chatsResponse.json().catch(() => ({}));
          if (!chatsResponse.ok) throw new Error(chatsData.detail || "Could not load chats.");
          const items = (chatsData.chats || []).map(c => ({ id: c.id, title: c.title, messages: [], updatedAt: Date.parse(c.updated_at) || Date.now() }));
          setChats(items);
          setActiveId(items[0]?.id || null);
        }
      } catch {
        localStorage.removeItem(TOKEN_KEY);
        if (!cancelled) { setToken(""); setUser(null); }
      } finally { if (!cancelled) setAuthReady(true); }
    }
    restore();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [active?.messages, busy]);
  useEffect(() => { localStorage.setItem(THEME_KEY, light ? "light" : "dark"); }, [light]);
  useEffect(() => {
    if (!token || !activeId || active?.messages?.length || activeId.startsWith("pending-")) return;
    let cancelled = false;
    fetch(API + "/api/chats/" + encodeURIComponent(activeId), { headers: { Authorization: "Bearer " + token } })
      .then(async response => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || "Could not open this chat.");
        return data;
      })
      .then(data => {
        if (!cancelled) setChats(prev => prev.map(c => c.id === activeId ? { ...c, title: data.title, messages: (data.messages || []).map((m, i) => ({ id: activeId + "-" + i, role: m.role === "model" ? "assistant" : "user", content: m.content })) } : c));
      })
      .catch(e => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [activeId, token]);

  async function submitAuth(event) {
    event.preventDefault();
    setAuthBusy(true);
    setAuthError("");
    try {
      const endpoint = authMode === "register" ? "/api/auth/register" : "/api/auth/login";
      const body = authMode === "register"
        ? { name: authName.trim(), email: authEmail.trim(), password: authPassword }
        : { email: authEmail.trim(), password: authPassword };
      const response = await fetch(API + endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Could not sign in.");
      localStorage.setItem(TOKEN_KEY, data.token);
      setToken(data.token);
      setUser(data.user);
      setAuthPassword("");
      await loadChats(data.token);
    } catch (e) { setAuthError(typeof e.message === "string" ? e.message : "Something went wrong."); }
    finally { setAuthBusy(false); }
  }

  function signOut() {
    localStorage.removeItem(TOKEN_KEY);
    setToken("");
    setUser(null);
    setChats([]);
    setActiveId(null);
    setInput("");
  }

  function newChat() {
    setActiveId(null);
    setInput("");
    setError("");
    setSidebarOpen(false);
  }

  function openChat(id) {
    setActiveId(id);
    setSidebarOpen(false);
    setError("");
  }

  async function sendMessage(value) {
    const prompt = (value === undefined ? input : value).trim();
    if (!prompt || busy) return;
    const previous = active?.messages || [];
    const userMessage = { id: crypto.randomUUID(), role: "user", content: prompt };
    const localId = activeId || "pending-" + crypto.randomUUID();
    const title = active?.title || prompt.slice(0, 48);
    setChats(prev => {
      const found = prev.some(c => c.id === localId);
      const next = found
        ? prev.map(c => c.id === localId ? { ...c, title, messages: [...c.messages, userMessage], updatedAt: Date.now() } : c)
        : [{ id: localId, title, messages: [userMessage], updatedAt: Date.now() }, ...prev];
      return next;
    });
    setActiveId(localId);
    setInput("");
    setBusy(true);
    setError("");
    try {
      const history = previous.slice(-20).map(m => ({ role: m.role === "assistant" ? "model" : "user", content: m.content }));
      const body = { message: prompt, history };
      if (active?.id && !active.id.startsWith("pending-")) body.chat_id = active.id;
      const response = await fetch(API + "/api/chat", { method: "POST", headers: authHeaders(), body: JSON.stringify(body) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 401) signOut();
        throw new Error(data.detail || "Could not get a response. Please try again.");
      }
      const serverId = data.chat_id;
      const assistantMessage = { id: crypto.randomUUID(), role: "assistant", content: data.reply, model: data.model };
      setChats(prev => {
        const current = prev.find(c => c.id === localId);
        const updated = { ...(current || { title }), id: serverId, title, messages: [...(current?.messages || [userMessage]), assistantMessage], updatedAt: Date.now() };
        return [updated, ...prev.filter(c => c.id !== localId && c.id !== serverId)];
      });
      setActiveId(serverId);
    } catch (e) {
      setError(e.message || "Could not reach the JustAI server.");
    } finally { setBusy(false); }
  }

  async function deleteChat(id) {
    try {
      const response = await fetch(API + "/api/chats/" + encodeURIComponent(id), { method: "DELETE", headers: { Authorization: "Bearer " + token } });
      if (!response.ok && response.status !== 404) throw new Error("Could not delete this chat.");
      setChats(prev => prev.filter(c => c.id !== id));
      if (activeId === id) setActiveId(null);
    } catch (e) { setError(e.message); }
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

  if (!authReady) return <div className="loading-screen"><div className="brand-mark"><Sparkles size={19} /></div><span>Preparing JustAI…</span></div>;

  if (!user) return (
    <div className={"auth-shell " + (light ? "light" : "")}>
      <div className="auth-brand"><div className="brand-mark"><Sparkles size={19} /></div><span className="brand-name">just<span>ai</span></span></div>
      <div className="auth-card">
        <div className="welcome-orb auth-orb"><Sparkles size={25} /></div>
        <p className="eyebrow">YOUR PERSONAL AI SPACE</p>
        <h1>{authMode === "register" ? "Create your account" : "Welcome back"}</h1>
        <p className="auth-subtitle">{authMode === "register" ? "Start a space for your ideas and conversations." : "Sign in to continue your conversations."}</p>
        <form onSubmit={submitAuth}>
          {authMode === "register" && <label>Your name<input autoComplete="name" value={authName} onChange={e => setAuthName(e.target.value)} minLength={2} maxLength={40} required placeholder="Your name" /></label>}
          <label>Email address<input type="email" autoComplete="email" value={authEmail} onChange={e => setAuthEmail(e.target.value)} required placeholder="you@example.com" /></label>
          <label>Password<input type="password" autoComplete={authMode === "register" ? "new-password" : "current-password"} value={authPassword} onChange={e => setAuthPassword(e.target.value)} minLength={8} maxLength={128} required placeholder="At least 8 characters" /></label>
          {authError && <div className="auth-error">{authError}</div>}
          <button className="auth-submit" disabled={authBusy}>{authBusy ? "Please wait…" : authMode === "register" ? "Create account" : "Sign in"} <ArrowUp size={17} /></button>
        </form>
        <p className="auth-switch">{authMode === "register" ? "Already have an account?" : "New to JustAI?"} <button onClick={() => { setAuthMode(authMode === "register" ? "login" : "register"); setAuthError(""); }}>{authMode === "register" ? "Sign in" : "Create account"}</button></p>
        <p className="auth-footnote">Your conversations are saved to your account.</p>
      </div>
      <div className="auth-bottom">MADE FOR CURIOUS MINDS <span>·</span> JUSTAI</div>
    </div>
  );

  return (
    <div className={"app-shell " + (light ? "light" : "")}>
      {sidebarOpen && <button className="scrim" aria-label="Close menu" onClick={() => setSidebarOpen(false)} />}
      <aside className={"sidebar " + (sidebarOpen ? "sidebar-open" : "")}>
        <div className="brand-row"><div className="brand-mark"><Sparkles size={19} /></div><span className="brand-name">just<span>ai</span></span><button className="icon-btn sidebar-close" onClick={() => setSidebarOpen(false)} aria-label="Close sidebar"><X size={18} /></button></div>
        <button className="new-chat" onClick={newChat}><Plus size={17} /> New chat</button>
        <div className="side-label">YOUR SPACE</div>
        <div className="chat-list">
          {chats.length === 0 && <p className="empty-history">Your conversations will appear here.</p>}
          {chats.map(c => <div key={c.id} className={"chat-item " + (c.id === activeId ? "selected" : "")}>
            <button className="chat-select" onClick={() => openChat(c.id)}><MessageSquarePlus size={15} /><span>{c.title}</span></button>
            <button className="delete-chat" aria-label="Delete chat" onClick={() => deleteChat(c.id)}><Trash2 size={14} /></button>
          </div>)}
        </div>
        <div className="sidebar-bottom">
          <div className="profile-chip"><div className="avatar"><UserRound size={15} /></div><div><b>{user.name}</b><small>{user.email}</small></div></div>
          <button className="theme-toggle" onClick={() => setLight(v => !v)}>{light ? <Moon size={16} /> : <Sun size={16} />} {light ? "Dark appearance" : "Light appearance"}</button>
          <button className="theme-toggle" onClick={signOut}><LogOut size={16} /> Sign out</button>
        </div>
      </aside>
      <main className="main-panel">
        <header className="topbar"><div className="top-left"><button className="icon-btn menu-btn" onClick={() => setSidebarOpen(true)} aria-label="Open menu"><Menu size={20} /></button><span className="mobile-brand">just<span>ai</span></span><span className="model-pill"><span className="status-dot" /> JustAI <span className="model-muted">· Assistant</span></span></div><button className="icon-btn desktop-new" onClick={newChat} aria-label="New chat"><MessageSquarePlus size={18} /></button></header>
        <section className="conversation">
          {!active?.messages?.length ? <div className="welcome">
            <div className="welcome-orb"><Sparkles size={28} /></div><p className="eyebrow">YOUR IDEAS, IN MOTION</p><h1>What can I help<br /><em>you explore?</em></h1><p className="welcome-copy">Ask anything. Build something. Figure it out.<br />Let's make a little progress today.</p>
            <div className="prompt-grid">{[["✦","Explain something","Explain how artificial intelligence works in simple words."],["⌘","Help me code","Help me build a simple responsive website."],["↗","Explore an idea","Give me 5 creative ideas for a mobile app."],["文","Learn something new","Teach me three useful Python concepts with examples."]].map(([icon,title,prompt]) => <button className="prompt-card" key={title} onClick={() => sendMessage(prompt)}><span>{icon}</span><b>{title}</b><small>{prompt}</small></button>)}</div>
          </div> : <div className="messages">
            {active.messages.map(m => <article className={"message " + m.role} key={m.id}><div className="message-avatar">{m.role === "assistant" ? <Sparkles size={15} /> : "Y"}</div><div className="message-body"><div className="message-name">{m.role === "assistant" ? "JustAI" : "You"}</div><div className="message-content">{m.role === "assistant" ? <ReactMarkdown>{m.content}</ReactMarkdown> : <p>{m.content}</p>}</div>{m.role === "assistant" && <button className="copy-btn" onClick={() => copyText(m.id,m.content)}>{copied === m.id ? <Check size={14} /> : <Copy size={14} />} {copied === m.id ? "Copied" : "Copy"}</button>}</div></article>)}
            {busy && <article className="message assistant"><div className="message-avatar"><Sparkles size={15} /></div><div className="message-body"><div className="message-name">JustAI</div><div className="typing"><i /><i /><i /></div></div></article>}<div ref={bottomRef} />
          </div>}
        </section>
        <div className="composer-wrap">{error && <div className="error-note"><span>{error}</span><button onClick={() => setError("")}><X size={14} /></button></div>}<div className="composer"><textarea rows="1" value={input} onChange={e => setInput(e.target.value)} onKeyDown={keyDown} placeholder="Message JustAI..." aria-label="Message JustAI" /><div className="composer-footer"><span className="composer-hint">JustAI can make mistakes. Check important information.</span><button className="send-btn" disabled={!input.trim() || busy} onClick={() => sendMessage()} aria-label="Send message"><ArrowUp size={19} /></button></div></div><div className="powered">MADE FOR CURIOUS MINDS <span>·</span> JUSTAI</div></div>
      </main>
    </div>
  );
}
