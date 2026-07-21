import { useRef } from "react";

export default function Composer({ value, onChange, onSend, disabled, onLeadershipUpdate }) {
  const taRef = useRef(null);

  function handleKeyDown(e) {
    // Enter sends; Shift+Enter inserts a newline.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!disabled && value.trim()) onSend();
    }
  }

  function autoGrow(e) {
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
    onChange(el.value);
  }

  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        if (!disabled && value.trim()) onSend();
      }}
    >
      <div className="row">
        <label htmlFor="composer-input" className="sr-only">
          Ask a business question
        </label>
        <textarea
          id="composer-input"
          ref={taRef}
          rows={1}
          value={value}
          placeholder="Ask about pipeline, revenue, sectors, or operations…"
          onChange={autoGrow}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          aria-label="Ask a business question"
        />
        <button className="btn" type="submit" disabled={disabled || !value.trim()}>
          Send
        </button>
      </div>
      <div className="toolbar">
        <span className="hint">Enter to send · Shift+Enter for a new line</span>
        <button
          type="button"
          className="btn secondary"
          onClick={onLeadershipUpdate}
          disabled={disabled}
        >
          Generate leadership update
        </button>
      </div>
    </form>
  );
}
