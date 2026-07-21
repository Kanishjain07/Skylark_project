import { useEffect, useRef, useState } from "react";
import Message from "./components/Message.jsx";
import Composer from "./components/Composer.jsx";
import { sendChat, generateLeadershipUpdate, getHealth } from "./api.js";

const SUGGESTIONS = [
  "How's our pipeline looking for the energy sector this quarter?",
  "What's our total pipeline value and how is it split by stage?",
  "Which work orders are at risk of slipping?",
  "Summarize revenue by sector.",
];

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [health, setHealth] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth({ status: "unreachable" }));
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  async function runTurn(userText) {
    setError(null);
    const nextMessages = [...messages, { role: "user", content: userText }];
    setMessages(nextMessages);
    setInput("");
    setBusy(true);
    try {
      const payload = nextMessages.map((m) => ({ role: m.role, content: m.content }));
      const res = await sendChat(payload);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: res.reply,
          dataQuality: res.data_quality,
          toolsUsed: res.tools_used,
        },
      ]);
    } catch (e) {
      setError(e.message || "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  function handleSend() {
    const text = input.trim();
    if (text) runTurn(text);
  }

  async function handleLeadershipUpdate() {
    setError(null);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: "Generate a leadership update." },
    ]);
    setBusy(true);
    try {
      const res = await generateLeadershipUpdate();
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: res.reply, dataQuality: res.data_quality },
      ]);
    } catch (e) {
      setError(e.message || "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const connOk =
    health &&
    health.monday_connection === "ok" &&
    health.groq_configured;
  const statusClass = !health
    ? ""
    : connOk
    ? "ok"
    : "error";
  const statusLabel = !health
    ? "Checking…"
    : health.status === "unreachable"
    ? "Backend unreachable"
    : connOk
    ? "Connected to monday.com"
    : "Setup needed";

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>Skylark Business Intelligence</h1>
          <p className="subtitle">
            Ask questions about your work orders and deals.
          </p>
        </div>
        <span className="status" role="status" aria-live="polite">
          <span className={`dot ${statusClass}`} aria-hidden="true" />
          {statusLabel}
        </span>
      </header>

      <main className="messages" ref={scrollRef} aria-live="polite" aria-busy={busy}>
        {messages.length === 0 && !busy && (
          <div className="empty">
            <h2>What would you like to know?</h2>
            <p>Ask in plain language — the agent reads your live monday.com data.</p>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" onClick={() => runTurn(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <Message key={i} message={m} />
        ))}

        {busy && (
          <div className="msg assistant">
            <span className="role">Agent</span>
            <div className="bubble">
              <span className="typing" aria-label="Agent is thinking">
                <span></span>
                <span></span>
                <span></span>
              </span>
            </div>
          </div>
        )}

        {error && (
          <div className="error-banner" role="alert">
            {error}
          </div>
        )}
      </main>

      <Composer
        value={input}
        onChange={setInput}
        onSend={handleSend}
        onLeadershipUpdate={handleLeadershipUpdate}
        disabled={busy}
      />
    </div>
  );
}
