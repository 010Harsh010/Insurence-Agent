import React, { useState, useRef, useEffect } from "react";
import {
  Send,
  Paperclip,
  Upload,
  FileText,
  X,
  ShieldCheck,
  CheckCircle,
  AlertCircle,
  Clock,
  Loader2,
  Bot,
  User,
  ChevronDown,
  Sparkles,
  FilePlus2,
  XCircle,
} from "lucide-react";

const MEMBER_ID = "EMP001";
const BASE_URL = ""; // Vite proxy forwards /chat and /upload to Flask:8000

// ─── Typing Indicator ───────────────────────────────────────────────────────
const TypingDots = () => (
  <div className="typing-dots">
    <span />
    <span />
    <span />
  </div>
);

// ─── File Badge ──────────────────────────────────────────────────────────────
const FileBadge = ({ file, onRemove, status }) => {
  const icons = {
    pending: <FileText size={14} className="text-zinc-400" />,
    uploading: <Loader2 size={14} className="text-blue-400 animate-spin" />,
    done: <CheckCircle size={14} className="text-green-400" />,
    error: <XCircle size={14} className="text-red-400" />,
  };
  const colors = {
    pending: "border-zinc-700",
    uploading: "border-blue-500/40",
    done: "border-green-500/40",
    error: "border-red-500/40",
  };

  return (
    <div className={`file-badge ${colors[status] || "border-zinc-700"}`}>
      {icons[status] || icons.pending}
      <span className="file-badge-name">{file.name}</span>
      {onRemove && status === "pending" && (
        <button
          onClick={onRemove}
          className="file-badge-remove"
          title="Remove file"
        >
          <X size={12} />
        </button>
      )}
    </div>
  );
};

// ─── Message Bubble ──────────────────────────────────────────────────────────
const MessageBubble = ({ msg }) => {
  const isUser = msg.role === "user";

  return (
    <div className={`message-row ${isUser ? "message-row--user" : "message-row--ai"}`}>
      {!isUser && (
        <div className="avatar avatar--ai">
          <Bot size={16} />
        </div>
      )}

      <div className={`bubble ${isUser ? "bubble--user" : "bubble--ai"}`}>
        {/* Attached files */}
        {msg.files && msg.files.length > 0 && (
          <div className="bubble-files">
            {msg.files.map((f, i) => (
              <FileBadge key={i} file={f} status={msg.fileStatuses?.[i] || "pending"} />
            ))}
          </div>
        )}

        {/* Text */}
        {msg.loading ? (
          <TypingDots />
        ) : (
          <div className="bubble-text">{msg.text}</div>
        )}

        {/* Claim Decision Card */}
        {msg.claim && (
          <div className="claim-card">
            <div className="claim-card__header">
              <ShieldCheck size={16} className="text-green-400" />
              <span>Claim Analysis</span>
            </div>

            <div className="claim-card__grid">
              <div className="claim-stat">
                <span className="claim-stat__label">Status</span>
                <span
                  className={`claim-stat__value ${
                    msg.claim.decision === "APPROVED"
                      ? "text-green-400"
                      : msg.claim.decision === "DENIED"
                      ? "text-red-400"
                      : "text-yellow-400"
                  }`}
                >
                  {msg.claim.decision}
                </span>
              </div>

              {msg.claim.approved_amount !== undefined && (
                <div className="claim-stat">
                  <span className="claim-stat__label">Approved Amount</span>
                  <span className="claim-stat__value">
                    ₹{msg.claim.approved_amount?.toLocaleString("en-IN")}
                  </span>
                </div>
              )}

              {msg.claim.confidence !== undefined && (
                <div className="claim-stat">
                  <span className="claim-stat__label">Confidence</span>
                  <span className="claim-stat__value">
                    {(msg.claim.confidence * 100).toFixed(0)}%
                  </span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Timestamp */}
        <div className="bubble-time">{msg.time}</div>
      </div>

      {isUser && (
        <div className="avatar avatar--user">
          <User size={16} />
        </div>
      )}
    </div>
  );
};

// ─── Right Panel ─────────────────────────────────────────────────────────────
const ClaimPanel = ({ lastClaim, uploadedCount, isUploading }) => (
  <aside className="right-panel">
    {/* Member info */}
    <div className="panel-section">
      <p className="panel-label">Member ID</p>
      <p className="panel-value emp-badge">{MEMBER_ID}</p>
    </div>

    <div className="divider" />

    {/* Upload status */}
    <div className="panel-section">
      <div className="panel-section__header">
        <FilePlus2 size={16} className="text-blue-400" />
        <span className="panel-section__title">Documents</span>
      </div>
      {isUploading ? (
        <div className="status-row status-row--uploading">
          <Loader2 size={14} className="animate-spin" />
          <span>Uploading…</span>
        </div>
      ) : uploadedCount > 0 ? (
        <div className="status-row status-row--done">
          <CheckCircle size={14} />
          <span>{uploadedCount} document{uploadedCount > 1 ? "s" : ""} processed</span>
        </div>
      ) : (
        <p className="panel-hint">No documents uploaded yet.</p>
      )}
    </div>

    <div className="divider" />

    {/* Claim Decision */}
    <div className="panel-section">
      <div className="panel-section__header">
        <ShieldCheck size={16} className="text-green-400" />
        <span className="panel-section__title">Latest Decision</span>
      </div>

      {lastClaim ? (
        <div className="decision-card">
          <div
            className={`decision-badge ${
              lastClaim.decision === "APPROVED"
                ? "decision-badge--approved"
                : lastClaim.decision === "DENIED"
                ? "decision-badge--denied"
                : "decision-badge--pending"
            }`}
          >
            {lastClaim.decision}
          </div>

          {lastClaim.approved_amount !== undefined && (
            <div className="decision-row">
              <span className="decision-label">Amount</span>
              <span className="decision-val">
                ₹{lastClaim.approved_amount?.toLocaleString("en-IN")}
              </span>
            </div>
          )}

          {lastClaim.confidence !== undefined && (
            <div className="decision-row">
              <span className="decision-label">Confidence</span>
              <div className="confidence-bar-wrap">
                <div className="confidence-bar">
                  <div
                    className="confidence-bar__fill"
                    style={{ width: `${(lastClaim.confidence * 100).toFixed(0)}%` }}
                  />
                </div>
                <span className="decision-val">
                  {(lastClaim.confidence * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          )}

          {lastClaim.reasoning && (
            <div className="decision-reasoning">
              <p className="decision-label">Reasoning</p>
              <p className="decision-reasoning__text">{lastClaim.reasoning}</p>
            </div>
          )}
        </div>
      ) : (
        <p className="panel-hint">
          Send a message to start a claim analysis.
        </p>
      )}
    </div>
  </aside>
);

// ─── Main App ────────────────────────────────────────────────────────────────
const App = () => {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text: "👋 Hello! I'm Plum Claims AI. You can describe your medical expense, attach supporting documents, and I'll help process your claim.",
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ]);
  const [inputText, setInputText] = useState("");
  const [files, setFiles] = useState([]);         // staged files
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadedCount, setUploadedCount] = useState(0);
  const [lastClaim, setLastClaim] = useState(null);
  const [dragOver, setDragOver] = useState(false);

  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);

  // Scroll to bottom whenever messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 140) + "px";
    }
  }, [inputText]);

  const addMessage = (msg) => {
    setMessages((prev) => [...prev, msg]);
  };

  const updateLastMessage = (updater) => {
    setMessages((prev) => {
      const copy = [...prev];
      copy[copy.length - 1] = updater(copy[copy.length - 1]);
      return copy;
    });
  };

  const now = () =>
    new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  // ── Upload files one by one ───────────────────────────────────────────────
  const uploadFiles = async (filesToUpload) => {
    setIsUploading(true);
    const results = [];

    for (const file of filesToUpload) {
      const formData = new FormData();
      formData.append("document", file);

      try {
        const res = await fetch(`${BASE_URL}/upload?member_id=${MEMBER_ID}`, {
          method: "POST",
          body: formData,
        });
        const data = await res.json();
        results.push({ file, ok: res.ok, data });
      } catch (err) {
        results.push({ file, ok: false, error: err.message });
      }
    }

    const successCount = results.filter((r) => r.ok).length;
    setUploadedCount((prev) => prev + successCount);
    setIsUploading(false);
    return results;
  };

  // ── Send message & handle full flow ──────────────────────────────────────
  const handleSend = async () => {
    const text = inputText.trim();
    if (!text && files.length === 0) return;
    if (isLoading || isUploading) return;

    const stagedFiles = [...files];
    setInputText("");
    setFiles([]);

    // Show user message
    addMessage({
      role: "user",
      text: text || "(Documents submitted)",
      files: stagedFiles,
      fileStatuses: stagedFiles.map(() => "uploading"),
      time: now(),
    });

    // Show AI "typing"
    const thinkingId = Date.now();
    addMessage({
      role: "assistant",
      text: "",
      loading: true,
      time: now(),
      id: thinkingId,
    });

    setIsLoading(true);

    // 1. Upload documents first
    let uploadSummary = "";
    if (stagedFiles.length > 0) {
      try {
        const uploadResults = await uploadFiles(stagedFiles);
        const successes = uploadResults.filter((r) => r.ok);
        const failures = uploadResults.filter((r) => !r.ok);

        if (successes.length > 0) {
          uploadSummary = `✅ Successfully uploaded ${successes.length} document(s). `;
        }
        if (failures.length > 0) {
          uploadSummary += `⚠️ ${failures.length} document(s) failed to upload. `;
        }

        // Update file statuses in user message
        setMessages((prev) => {
          const copy = [...prev];
          const userMsgIdx = copy.findLastIndex((m) => m.role === "user");
          if (userMsgIdx !== -1) {
            copy[userMsgIdx] = {
              ...copy[userMsgIdx],
              fileStatuses: uploadResults.map((r) => (r.ok ? "done" : "error")),
            };
          }
          return copy;
        });
      } catch (err) {
        uploadSummary = `⚠️ Upload error: ${err.message}. `;
      }
    }

    // 2. Send chat query
    // Backend returns: { status, data: { ui: { type, message } } }
    // Types: "message" | "decision" | "error" | "answer"
    let responseText = uploadSummary;
    let claimData = null;

    if (text) {
      try {
        const res = await fetch(
          `${BASE_URL}/chat?query=${encodeURIComponent(text)}`
        );
        const data = await res.json();

        if (res.ok && data.status === 200) {
          const ui = data.data?.ui;

          if (!ui) {
            // Fallback: raw string
            responseText += typeof data.data === "string"
              ? data.data
              : JSON.stringify(data.data, null, 2);

          } else if (ui.type === "message") {
            // Greeting or guardrail — plain text
            responseText += ui.message;

          } else if (ui.type === "answer") {
            // Question-answering response
            responseText += ui.message;

          } else if (ui.type === "decision") {
            // Claim processing result — show decision card
            responseText += ui.message?.explanation
              || ui.message?.summary
              || (typeof ui.message === "string" ? ui.message : "Claim processed.");
            claimData = ui.message;   // full decision object for the panel
            setLastClaim(ui.message);

          } else if (ui.type === "error") {
            // Backend-side processing error
            responseText += `⚠️ ${ui.message || "An error occurred while processing."}`;

          } else {
            // Unknown type — show raw
            responseText += typeof ui.message === "string"
              ? ui.message
              : JSON.stringify(ui, null, 2);
          }

        } else {
          responseText += `❌ ${data.message || "Something went wrong."}`;
        }
      } catch (err) {
        responseText += `❌ Could not reach backend: ${err.message}`;
      }
    } else if (!uploadSummary) {
      responseText = "Please describe your claim or attach documents.";
    }

    // Replace typing indicator
    updateLastMessage(() => ({
      role: "assistant",
      text: responseText || "Done! Anything else I can help you with?",
      loading: false,
      claim: claimData,
      time: now(),
    }));

    setIsLoading(false);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileSelect = (newFiles) => {
    setFiles((prev) => [...prev, ...Array.from(newFiles)]);
  };

  const removeFile = (index) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  // ── Drag & Drop ───────────────────────────────────────────────────────────
  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const dropped = Array.from(e.dataTransfer.files);
    if (dropped.length) handleFileSelect(dropped);
  };

  return (
    <div className="app-shell">
      {/* ── Header ── */}
      <header className="app-header">
        <div className="app-header__brand">
          <div className="brand-icon">
            <Sparkles size={18} />
          </div>
          <div>
            <h1 className="brand-title">Plum Claims AI</h1>
            <p className="brand-sub">Intelligent Claims Processing</p>
          </div>
        </div>

        <div className="app-header__status">
          <div className="status-dot" />
          <span>Online</span>
          <div className="member-pill">{MEMBER_ID}</div>
        </div>
      </header>

      {/* ── Body ── */}
      <div className="app-body">
        {/* ── Chat Column ── */}
        <div className="chat-column">
          {/* Messages */}
          <div
            className={`messages-area ${dragOver ? "messages-area--dragover" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
          >
            {dragOver && (
              <div className="drop-overlay">
                <Upload size={32} />
                <p>Drop files here</p>
              </div>
            )}

            <div className="messages-inner">
              {messages.map((msg, i) => (
                <MessageBubble key={i} msg={msg} />
              ))}
              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Staged files preview */}
          {files.length > 0 && (
            <div className="staged-files">
              {files.map((f, i) => (
                <FileBadge
                  key={i}
                  file={f}
                  status="pending"
                  onRemove={() => removeFile(i)}
                />
              ))}
            </div>
          )}

          {/* Input Bar */}
          <div className="input-bar">
            <div className={`input-wrap ${isLoading ? "input-wrap--disabled" : ""}`}>
              {/* File attach button */}
              <button
                className="attach-btn"
                onClick={() => fileInputRef.current?.click()}
                title="Attach documents"
                disabled={isLoading}
              >
                <Paperclip size={18} />
                {files.length > 0 && (
                  <span className="attach-count">{files.length}</span>
                )}
              </button>

              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                accept=".pdf,.png,.jpg,.jpeg"
                onChange={(e) => handleFileSelect(e.target.files)}
              />

              <textarea
                ref={textareaRef}
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Describe your medical claim or ask a question… (Shift+Enter for newline)"
                className="chat-input"
                disabled={isLoading}
                rows={1}
              />

              <button
                className={`send-btn ${
                  (inputText.trim() || files.length > 0) && !isLoading
                    ? "send-btn--active"
                    : ""
                }`}
                onClick={handleSend}
                disabled={isLoading || (!inputText.trim() && files.length === 0)}
                title="Send"
              >
                {isLoading ? (
                  <Loader2 size={18} className="animate-spin" />
                ) : (
                  <Send size={18} />
                )}
              </button>
            </div>

            <p className="input-hint">
              Drag &amp; drop files onto the chat, or use the{" "}
              <Paperclip size={11} className="inline" /> button
            </p>
          </div>
        </div>

        {/* ── Right Panel ── */}
        <ClaimPanel
          lastClaim={lastClaim}
          uploadedCount={uploadedCount}
          isUploading={isUploading}
        />
      </div>
    </div>
  );
};

export default App;