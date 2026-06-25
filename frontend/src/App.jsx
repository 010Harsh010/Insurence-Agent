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
  Lock,
  RefreshCw,
  Trash2,
  DatabaseZap,
  FileUp,
  FlaskConical,
  Play,
  ChevronRight,
  ArrowLeft,
} from "lucide-react";

const BASE_URL = ""; // Vite proxy forwards /chat and /upload to Flask:8000

// ─── Typing Indicator ───────────────────────────────────────────────────────
const TypingDots = () => (
  <div className="typing-dots">
    <span />
    <span />
    <span />
  </div>
);

// ─── Answer Table (multi-section, recursive) ─────────────────────────────────
const _fmtKey = (k) =>
  k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const _isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

const getDecisionVariant = (decision) => {
  switch (decision) {
    case "APPROVED":
      return "approved";
    case "REJECTED":
      return "denied";
    case "PARTIALLY_APPROVED":
      return "partial";
    case "MANUAL_REVIEW":
      return "pending";
    default:
      return "pending";
  }
};

const formatDecisionLabel = (decision) =>
  typeof decision === "string" ? decision.replace(/_/g, " ") : "UNKNOWN";

const _renderPrimitive = (v) => {
  if (v === null || v === undefined) return <span className="ans-null">—</span>;
  if (typeof v === "boolean") return <span className={v ? "ans-bool-true" : "ans-bool-false"}>{v ? "Yes" : "No"}</span>;
  return <span>{String(v)}</span>;
};

const _renderAnyValue = (v, depth = 0) => {
  if (v === null || v === undefined) return <span className="ans-null">—</span>;

  // Array
  if (Array.isArray(v)) {
    if (v.length === 0) return <span className="ans-null">empty</span>;
    // Array of objects → mini table
    if (_isObj(v[0])) {
      const cols = Object.keys(v[0]);
      return (
        <div className="ans-mini-wrap">
          <table className="ans-mini-table">
            <thead>
              <tr>{cols.map((c) => <th key={c} className="ans-mini-th">{_fmtKey(c)}</th>)}</tr>
            </thead>
            <tbody>
              {v.map((row, i) => (
                <tr key={i} className={i % 2 === 0 ? "ans-mini-tr" : "ans-mini-tr ans-mini-tr--alt"}>
                  {cols.map((c) => (
                    <td key={c} className="ans-mini-td">
                      {_isObj(row[c]) || Array.isArray(row[c])
                        ? _renderAnyValue(row[c], depth + 1)
                        : _renderPrimitive(row[c])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    // Array of primitives → tag list
    return (
      <div className="ans-tag-list">
        {v.map((item, i) => (
          <span key={i} className="ans-tag">{_renderPrimitive(item)}</span>
        ))}
      </div>
    );
  }

  // Plain object → recursive key-value rows
  if (_isObj(v)) {
    return (
      <div className={depth === 0 ? "ans-kv-grid" : "ans-kv-sub"}>
        {Object.entries(v).map(([k, val]) => (
          <div key={k} className={depth === 0 ? "ans-kv-row" : "ans-kv-sub__row"}>
            <span className={depth === 0 ? "ans-kv-key" : "ans-kv-sub__key"}>{_fmtKey(k)}</span>
            <span className={depth === 0 ? "ans-kv-val" : "ans-kv-sub__val"}>
              {_renderAnyValue(val, depth + 1)}
            </span>
          </div>
        ))}
      </div>
    );
  }

  return _renderPrimitive(v);
};

const AnswerTable = ({ data }) => {
  if (!Array.isArray(data) || data.length === 0) return null;

  return (
    <div className="ans-root">
      {data.map((record, ri) => {
        const flatEntries = Object.entries(record).filter(
          ([, v]) => !_isObj(v) && !Array.isArray(v)
        );
        const nestedEntries = Object.entries(record).filter(
          ([, v]) => _isObj(v) || Array.isArray(v)
        );

        return (
          <div key={ri} className="ans-record">
            {data.length > 1 && (
              <div className="ans-record__header">Record {ri + 1} of {data.length}</div>
            )}

            {/* ── Overview: flat primitive fields ── */}
            {flatEntries.length > 0 && (
              <div className="ans-section">
                <div className="ans-section__title">Overview</div>
                <div className="ans-kv-grid">
                  {flatEntries.map(([k, v]) => (
                    <div key={k} className="ans-kv-row">
                      <span className="ans-kv-key">{_fmtKey(k)}</span>
                      <span className="ans-kv-val">{_renderPrimitive(v)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── One section per nested field ── */}
            {nestedEntries.map(([k, v]) => (
              <div key={k} className="ans-section">
                <div className="ans-section__title">{_fmtKey(k)}</div>
                <div className="ans-section__body">{_renderAnyValue(v, 0)}</div>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
};

// ─── Financial Breakdown Ledger ─────────────────────────────────────────────
const FinancialBreakdown = ({ claim, compact = false }) => {
  const breakdown = claim?.financial_breakdown || [];
  const claimedAmt  = claim?.claimed_amount  ?? 0;
  const approvedAmt = claim?.approved_amount ?? 0;

  // Only show deduction rows where amount > 0
  const activeDeductions = breakdown.filter((d) => d.amount > 0);

  const fmt = (n) =>
    `₹${Number(n).toLocaleString("en-IN", { minimumFractionDigits: 0 })}`;

  return (
    <div className={`fb-wrap${compact ? " fb-wrap--compact" : ""}`}>
      {/* Header row */}
      <div className="fb-row fb-row--header">
        <span className="fb-label">Claim Amount</span>
        <span className="fb-amount">{fmt(claimedAmt)}</span>
      </div>

      {/* Deduction rows */}
      {activeDeductions.length > 0 && (
        <>
          {activeDeductions.map((d, i) => (
            <div key={i} className="fb-row fb-row--deduction">
              <span className="fb-label">{d.step}</span>
              <span className="fb-amount fb-amount--deduction">− {fmt(d.amount)}</span>
            </div>
          ))}
        </>
      )}

      {/* Divider */}
      <div className="fb-divider" />

      {/* Approved total */}
      <div className="fb-row fb-row--total">
        <span className="fb-label fb-label--total">Approved Amount</span>
        <span className="fb-amount fb-amount--total">{fmt(approvedAmt)}</span>
      </div>
    </div>
  );
};

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

// ─── Update Result Card ────────────────────────────────────────────────────
// updateResult shape:
//   success: bool
//   claimId: string
//   claimStatus?: string   (on success)
//   approveAmt?: number    (on success, optional)
//   message?: string       (backend message)
//   errorMsg?: string      (on failure)
const UpdateResultCard = ({ result }) => {
  if (!result) return null;
  const { success, claimId, claimStatus, approveAmt, message, errorMsg, authFailed } = result;

  const fmt = (n) =>
    `₹${Number(n).toLocaleString("en-IN", { minimumFractionDigits: 0 })}`;

  if (success) {
    return (
      <div className="ur-card ur-card--success">
        <div className="ur-card__header">
          <div className="ur-card__icon ur-card__icon--success">
            <CheckCircle size={15} />
          </div>
          <span className="ur-card__title">Claim Updated</span>
          <span className="ur-badge ur-badge--success">SUCCESS</span>
        </div>

        <div className="ur-rows">
          <div className="ur-row">
            <span className="ur-row__label">Claim ID</span>
            <span className="ur-row__value ur-row__value--mono">{claimId}</span>
          </div>
          <div className="ur-row">
            <span className="ur-row__label">New Status</span>
            <span className={`ur-status ur-status--${claimStatus?.toLowerCase().replace(/_/g, "-")}`}>
              {claimStatus?.replace(/_/g, " ")}
            </span>
          </div>
          {approveAmt > 0 && (
            <div className="ur-row">
              <span className="ur-row__label">Approved Amount</span>
              <span className="ur-row__value ur-row__value--amount">{fmt(approveAmt)}</span>
            </div>
          )}
        </div>

        {message && (
          <div className="ur-footnote">{message}</div>
        )}
      </div>
    );
  }

  // Failure variants
  const variant = authFailed ? "auth" : "error";
  const icon    = authFailed ? <Lock size={15} /> : <AlertCircle size={15} />;
  const title   = authFailed ? "Authentication Failed" : "Update Failed";

  return (
    <div className={`ur-card ur-card--${variant}`}>
      <div className="ur-card__header">
        <div className={`ur-card__icon ur-card__icon--${variant}`}>{icon}</div>
        <span className="ur-card__title">{title}</span>
        <span className={`ur-badge ur-badge--${variant}`}>
          {authFailed ? "UNAUTHORIZED" : "FAILED"}
        </span>
      </div>
      <p className="ur-error-msg">{errorMsg}</p>
    </div>
  );
};

// ─── Message Bubble ──────────────────────────────────────────────────────────
const MessageBubble = ({ msg }) => {
  const isUser = msg.role === "user";
  const claimDecisionVariant = msg.claim ? getDecisionVariant(msg.claim.decision) : null;

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
          <>
            {msg.text && <div className="bubble-text">{msg.text}</div>}
            {msg.tableData && <AnswerTable data={msg.tableData} />}
          </>
        )}

        {/* Update Result Card */}
        {msg.updateResult && <UpdateResultCard result={msg.updateResult} />}

        {/* Claim Decision Card */}
        {msg.claim && (
          <div className="claim-card">
            <div className="claim-card__header">
              <ShieldCheck size={16} className="text-green-400" />
              <span>Claim Analysis</span>
              <span
                className={`claim-card__badge claim-card__badge--${claimDecisionVariant}`}
              >
                {formatDecisionLabel(msg.claim.decision)}
              </span>
            </div>
            {
              msg.claim.decision !== "REJECTED" &&
                <FinancialBreakdown claim={msg.claim} />
            }
            
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

// ─── Admin Auth Panel (Update Claim) ────────────────────────────────────────
const AdminAuthPanel = ({ onSubmit, onCancel, isSubmitting }) => {
  const [claimId, setClaimId]         = useState("");
  const [claimStatus, setClaimStatus] = useState("APPROVED");
  const [approveAmt, setApproveAmt]   = useState("");
  const [password, setPassword]       = useState("");

  const canSubmit = claimId.trim() && claimStatus && password.trim() && !isSubmitting;

  return (
    <div className="admin-auth-panel">
      {/* Header */}
      <div className="admin-auth-panel__header">
        <div className="admin-auth-panel__icon">
          <Lock size={15} />
        </div>
        <div>
          <p className="admin-auth-panel__title">Update Claim</p>
          <p className="admin-auth-panel__sub">Admin authentication required</p>
        </div>
        <button className="admin-auth-panel__close" onClick={onCancel} title="Cancel">
          <X size={14} />
        </button>
      </div>

      {/* Fields */}
      <div className="admin-auth-panel__body">
        <label className="admin-field-label">Claim ID</label>
        <input
          className="admin-field-input"
          placeholder="e.g. CLM-00123"
          value={claimId}
          onChange={(e) => setClaimId(e.target.value)}
          spellCheck={false}
        />

        <label className="admin-field-label">New Status</label>
        <select
          className="admin-field-input admin-field-select"
          value={claimStatus}
          onChange={(e) => setClaimStatus(e.target.value)}
        >
          <option value="APPROVED">APPROVED</option>
          <option value="REJECTED">REJECTED</option>
          <option value="PARTIALLY_APPROVED">PARTIALLY APPROVED</option>
          <option value="MANUAL_REVIEW">MANUAL REVIEW</option>
          <option value="PENDING">PENDING</option>
        </select>

        <label className="admin-field-label">Approved Amount <span className="admin-field-optional">(optional)</span></label>
        <input
          className="admin-field-input"
          type="number"
          placeholder="₹ 0"
          value={approveAmt}
          onChange={(e) => setApproveAmt(e.target.value)}
        />

        <label className="admin-field-label">Admin Password</label>
        <input
          className="admin-field-input admin-field-password"
          type="password"
          placeholder="Enter admin password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && canSubmit)
              onSubmit({ claimId, claimStatus, approveAmt, password });
          }}
        />
      </div>

      {/* Actions */}
      <div className="admin-auth-panel__footer">
        <button
          className="admin-btn admin-btn--cancel"
          onClick={onCancel}
          disabled={isSubmitting}
        >
          Cancel
        </button>
        <button
          className={`admin-btn admin-btn--submit${canSubmit ? " admin-btn--active" : ""}`}
          onClick={() => canSubmit && onSubmit({ claimId, claimStatus, approveAmt, password })}
          disabled={!canSubmit}
        >
          {isSubmitting ? (
            <><RefreshCw size={13} className="admin-btn__spinner" /> Processing…</>
          ) : (
            <><Lock size={13} /> Authenticate & Update</>
          )}
        </button>
      </div>
    </div>
  );
};

// ─── Panel Action Bar ─────────────────────────────────────────────────────────
// 3 admin utility buttons pinned to the bottom of the right panel.
const PanelActionBar = ({ memberId, onDeleteDb, onDeleteDocs, onAddPolicy }) => {
  const [active, setActive]     = useState(null); // "resetdb" | "deletedocs" | "addpolicy"
  const [password, setPassword] = useState("");
  const [policyFile, setPolicyFile] = useState(null);
  const [busy, setBusy]         = useState(false);
  const [result, setResult]     = useState(null); // { ok, msg }
  const policyFileRef           = useRef(null);

  const close = () => {
    setActive(null);
    setPassword("");
    setPolicyFile(null);
    setResult(null);
    setBusy(false);
  };

  const showResult = (ok, msg) => {
    setResult({ ok, msg });
    setBusy(false);
    setTimeout(close, 2800);
  };

  const handleResetDb = async () => {
    if (!password.trim()) return;
    setBusy(true);
    try {
      const res = await fetch(`${BASE_URL}/resetDB`, {
        method: "POST",
        headers: { "X-Admin-Password": password },
      });
      const data = await res.json();
      showResult(res.ok && data.success !== false, data.message || (res.ok ? "Database reset." : "Reset failed."));
      if (res.ok) onDeleteDb?.();
    } catch (e) { showResult(false, e.message); }
  };

  const handleDeleteDocs = async () => {
    if (!memberId) return;
    setBusy(true);
    try {
      const res = await fetch(`${BASE_URL}/member/${encodeURIComponent(memberId)}/documents`, {
        method: "DELETE",
      });
      const data = await res.json();
      showResult(res.ok && data.success !== false, data.message || (res.ok ? "Documents deleted." : "Delete failed."));
      if (res.ok) onDeleteDocs?.();
    } catch (e) { showResult(false, e.message); }
  };

  const handleAddPolicy = async () => {
    if (!policyFile || !password.trim()) return;
    setBusy(true);
    try {
      const formData = new FormData();
      formData.append("policy", policyFile);
      const res = await fetch(`${BASE_URL}/addPolicy`, {
        method: "POST",
        headers: { "X-Admin-Password": password },
        body: formData,
      });
      const data = await res.json();
      showResult(res.ok && data.success !== false, data.message || (res.ok ? "Policy added." : "Upload failed."));
      if (res.ok) onAddPolicy?.();
    } catch (e) { showResult(false, e.message); }
  };

  return (
    <div className="pab-wrap">
      <div className="divider" style={{ marginBottom: "14px" }} />

      {/* ── Collapsed: 3 icon buttons ── */}
      {!active && (
        <div className="pab-buttons">
          <button
            className="pab-btn pab-btn--danger"
            onClick={() => setActive("resetdb")}
            title="Reset Database"
          >
            <DatabaseZap size={14} />
            <span>Reset DB</span>
          </button>
          <button
            className="pab-btn pab-btn--warn"
            onClick={() => setActive("deletedocs")}
            title="Delete Member Documents"
          >
            <Trash2 size={14} />
            <span>Del Docs</span>
          </button>
          <button
            className="pab-btn pab-btn--accent"
            onClick={() => setActive("addpolicy")}
            title="Add Policy"
          >
            <FileUp size={14} />
            <span>Add Policy</span>
          </button>
        </div>
      )}

      {/* ── Expanded: Reset DB ── */}
      {active === "resetdb" && (
        <div className="pab-modal pab-modal--danger">
          <div className="pab-modal__header">
            <DatabaseZap size={13} />
            <span>Reset Database</span>
            <button className="pab-modal__close" onClick={close}><X size={12} /></button>
          </div>
          {result ? (
            <div className={`pab-result ${result.ok ? "pab-result--ok" : "pab-result--err"}`}>
              {result.ok ? <CheckCircle size={13} /> : <AlertCircle size={13} />}
              <span>{result.msg}</span>
            </div>
          ) : (
            <>
              <p className="pab-modal__warn">⚠️ This will erase ALL data. Enter admin password to confirm.</p>
              <input
                className="pab-field"
                type="password"
                placeholder="Admin password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleResetDb()}
              />
              <div className="pab-modal__actions">
                <button className="pab-action pab-action--cancel" onClick={close} disabled={busy}>Cancel</button>
                <button
                  className={`pab-action pab-action--danger${password.trim() && !busy ? " pab-action--active" : ""}`}
                  onClick={handleResetDb}
                  disabled={!password.trim() || busy}
                >
                  {busy ? <><RefreshCw size={11} className="admin-btn__spinner" /> Resetting…</> : <><DatabaseZap size={11} /> Reset Now</>}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Expanded: Delete Docs ── */}
      {active === "deletedocs" && (
        <div className="pab-modal pab-modal--warn">
          <div className="pab-modal__header">
            <Trash2 size={13} />
            <span>Delete Documents</span>
            <button className="pab-modal__close" onClick={close}><X size={12} /></button>
          </div>
          {result ? (
            <div className={`pab-result ${result.ok ? "pab-result--ok" : "pab-result--err"}`}>
              {result.ok ? <CheckCircle size={13} /> : <AlertCircle size={13} />}
              <span>{result.msg}</span>
            </div>
          ) : (
            <>
              <p className="pab-modal__warn">
                Delete all documents for <strong style={{ color: "#a5b4fc" }}>{memberId || "—"}</strong>?
                This cannot be undone.
              </p>
              <div className="pab-modal__actions">
                <button className="pab-action pab-action--cancel" onClick={close} disabled={busy}>Cancel</button>
                <button
                  className={`pab-action pab-action--warn${memberId && !busy ? " pab-action--active" : ""}`}
                  onClick={handleDeleteDocs}
                  disabled={!memberId || busy}
                >
                  {busy ? <><RefreshCw size={11} className="admin-btn__spinner" /> Deleting…</> : <><Trash2 size={11} /> Delete</>}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Expanded: Add Policy ── */}
      {active === "addpolicy" && (
        <div className="pab-modal pab-modal--accent">
          <div className="pab-modal__header">
            <FileUp size={13} />
            <span>Add Policy</span>
            <button className="pab-modal__close" onClick={close}><X size={12} /></button>
          </div>
          {result ? (
            <div className={`pab-result ${result.ok ? "pab-result--ok" : "pab-result--err"}`}>
              {result.ok ? <CheckCircle size={13} /> : <AlertCircle size={13} />}
              <span>{result.msg}</span>
            </div>
          ) : (
            <>
              <input ref={policyFileRef} type="file" accept=".json" className="hidden"
                onChange={(e) => setPolicyFile(e.target.files[0] || null)} />
              <button
                className={`pab-file-pick${policyFile ? " pab-file-pick--selected" : ""}`}
                onClick={() => policyFileRef.current?.click()}
              >
                <FileText size={13} />
                <span>{policyFile ? policyFile.name : "Choose .json policy file"}</span>
              </button>
              <input
                className="pab-field"
                type="password"
                placeholder="Admin password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleAddPolicy()}
              />
              <div className="pab-modal__actions">
                <button className="pab-action pab-action--cancel" onClick={close} disabled={busy}>Cancel</button>
                <button
                  className={`pab-action pab-action--accent${policyFile && password.trim() && !busy ? " pab-action--active" : ""}`}
                  onClick={handleAddPolicy}
                  disabled={!policyFile || !password.trim() || busy}
                >
                  {busy ? <><RefreshCw size={11} className="admin-btn__spinner" /> Uploading…</> : <><FileUp size={11} /> Upload Policy</>}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

// ─── Right Panel ─────────────────────────────────────────────────────────────
const ClaimPanel = ({
  lastClaim, uploadedCount, isUploading, memberId, claimCategory,
  onMemberIdChange, onClaimCategoryChange,
  showAdminAuth, onAdminSubmit, onAdminCancel, isAdminSubmitting,
  onDeleteDb, onDeleteDocs, onAddPolicy,
}) => (
  <aside className="right-panel">
    {/* ── Admin Auth Overlay ── */}
    {showAdminAuth ? (
      <AdminAuthPanel
        onSubmit={onAdminSubmit}
        onCancel={onAdminCancel}
        isSubmitting={isAdminSubmitting}
      />
    ) : (
      <>
        {/* Member ID – editable */}
        <div className="panel-section">
          <p className="panel-label">Member ID</p>
          <input
            id="member-id-input"
            className="panel-editable-input emp-input"
            value={memberId}
            onChange={(e) => onMemberIdChange(e.target.value)}
            placeholder="e.g. EMP001"
            spellCheck={false}
          />
        </div>

        <div className="divider" />

        {/* Claim Category – editable */}
        <div className="panel-section">
          <p className="panel-label">Claim Category</p>
          <input
            id="claim-category-input"
            className="panel-editable-input category-input"
            value={claimCategory}
            onChange={(e) => onClaimCategoryChange(e.target.value.toUpperCase())}
            placeholder="e.g. PHARMACY"
            spellCheck={false}
          />
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
                className={`decision-badge decision-badge--${getDecisionVariant(lastClaim.decision)}`}
              >
                {formatDecisionLabel(lastClaim.decision)}
              </div>

              <FinancialBreakdown claim={lastClaim} compact />

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
      </>
    )}

    {/* ── Admin Action Bar ── */}
    {!showAdminAuth && (
      <PanelActionBar
        memberId={memberId}
        onDeleteDb={onDeleteDb}
        onDeleteDocs={onDeleteDocs}
        onAddPolicy={onAddPolicy}
      />
    )}
  </aside>
);

// ─── Detect Update-Claim intent ──────────────────────────────────────────────
const isUpdateClaimQuery = (text) => {
  const lower = text.toLowerCase();
  return (
    (lower.includes("update") || lower.includes("change") || lower.includes("modify") || lower.includes("edit")) &&
    (lower.includes("claim"))
  );
};

// ─── Test Page ───────────────────────────────────────────────────────────────

// ── Sub-components for the rich test card ──────────────────────────────────

const StatusPill = ({ passed, label }) => (
  <span className={`tc-status-pill tc-status-pill--${passed ? "pass" : "fail"}`}>
    {passed ? <CheckCircle size={11} /> : <XCircle size={11} />}
    {label || (passed ? "PASSED" : "FAILED")}
  </span>
);

const ConfidenceBar = ({ value }) => {
  const pct = Math.round((value ?? 0) * 100);
  return (
    <div className="tc-conf-wrap">
      <div className="tc-conf-bar">
        <div className="tc-conf-fill" style={{ width: `${pct}%`, background: pct === 100 ? "#22c55e" : pct >= 60 ? "#f59e0b" : "#ef4444" }} />
      </div>
      <span className="tc-conf-label">{pct}%</span>
    </div>
  );
};


// ─── Shared: Result status header bar ────────────────────────────────────────
const ResultBar = ({ result }) => {
  if (!result) return null;
  const pct = Math.round((result.confidence ?? 0) * 100);
  return (
    <div className={`tc-result-bar tc-result-bar--${result.passed ? "pass" : "fail"}`}>
      <span className="tc-result-bar__name">{result.step_name}</span>
      <div className="tc-result-bar__right">
        <ConfidenceBar value={result.confidence} />
        <StatusPill passed={result.passed} label={result.status} />
      </div>
      {result.reason && <p className="tc-result-bar__reason">{result.reason}</p>}
    </div>
  );
};

// ─── Shared: generic key-value table ─────────────────────────────────────────
const KVTable = ({ rows }) => (
  <table className="tc-table">
    <tbody>
      {rows.filter(([, v]) => v !== undefined).map(([k, v]) => (
        <tr key={k} className="tc-table__row">
          <td className="tc-table__key">{k}</td>
          <td className="tc-table__val">
            {typeof v === "boolean"
              ? <span className={v ? "tc-bool-true" : "tc-bool-false"}>{v ? "Yes" : "No"}</span>
              : Array.isArray(v) && v.length === 0
                ? <span className="tc-null-pill">none</span>
                : Array.isArray(v)
                  ? <div className="tc-tag-row">{v.map((x, i) => <span key={i} className="tc-tag tc-tag--blue">{String(x)}</span>)}</div>
                  : v == null ? <span className="tc-null-pill">—</span>
                    : <span>{String(v)}</span>}
          </td>
        </tr>
      ))}
    </tbody>
  </table>
);

// ─── Shared: warn / issue list ────────────────────────────────────────────────
const WarnList = ({ items, icon: Icon = AlertCircle, cls = "tc-warn" }) =>
  items?.length > 0 ? (
    <div className={`${cls}-list`}>
      {items.map((w, i) => (
        <div key={i} className={`${cls}-item`}>
          <Icon size={12} className={`${cls}-icon`} />
          <span>{w}</span>
        </div>
      ))}
    </div>
  ) : null;

// ─── 1. Member Section ────────────────────────────────────────────────────────
const MemberSection = ({ member, memberResult }) => {
  if (!member && !memberResult) return null;
  const fmt = (v) => v ?? "—";
  return (
    <div className="tc-data-section">
      <ResultBar result={memberResult} />
      {member && (
        <KVTable rows={[
          ["Member ID",      member.member_id],
          ["Name",           member.name],
          ["Policy ID",      member.policy_id],
          ["Relationship",   member.relationship],
          ["Join Date",      member.join_date],
          ["Primary Member", member.primary_member_id ?? "—"],
        ]} />
      )}
    </div>
  );
};

// ─── 2. Policy Section (result only, no raw policy dump) ─────────────────────
const PolicySection = ({ policyResult }) => {
  if (!policyResult) return null;
  return (
    <div className="tc-data-section">
      <ResultBar result={policyResult} />
      {policyResult.details && (
        <KVTable rows={Object.entries(policyResult.details).map(([k, v]) => [
          k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()), v
        ])} />
      )}
    </div>
  );
};

// ─── 3. Document Section ──────────────────────────────────────────────────────
const DocumentSection = ({ document: doc, documentResult }) => {
  if (!doc && !documentResult) return null;
  return (
    <div className="tc-data-section">
      <ResultBar result={documentResult} />
      {doc && (
        <>
          <KVTable rows={[
            ["Patient",         doc.patient_name],
            ["Hospital",        doc.hospital_name],
            ["Claim Category",  doc.inferred_claim_category],
            ["Validation",      doc.validation_passed],
          ]} />
          {doc.uploaded_document_types?.length > 0 && (
            <div className="tc-doc-tags">
              <span className="tc-doc-tags__label">Uploaded Docs</span>
              <div className="tc-tag-row">
                {doc.uploaded_document_types.map((d, i) => (
                  <span key={i} className="tc-tag tc-tag--blue">{d}</span>
                ))}
              </div>
            </div>
          )}
          {doc.missing_document_types?.length > 0 && (
            <div className="tc-doc-tags">
              <span className="tc-doc-tags__label tc-doc-tags__label--warn">Missing Docs</span>
              <div className="tc-tag-row">
                {doc.missing_document_types.map((d, i) => (
                  <span key={i} className="tc-tag tc-tag--red">{d}</span>
                ))}
              </div>
            </div>
          )}
          <WarnList items={doc.warnings} icon={AlertCircle} cls="tc-warn" />
          <WarnList items={doc.issues}   icon={XCircle}     cls="tc-issue" />
        </>
      )}
    </div>
  );
};

// ─── 4. Coverage Section ──────────────────────────────────────────────────────
const CoverageSection = ({ coverage, coverageResult }) => {
  if (!coverage && !coverageResult) return null;
  return (
    <div className="tc-data-section">
      <ResultBar result={coverageResult} />
      {coverage && (
        <>
          <KVTable rows={[
            ["Relationship Covered",          coverage.relationship_covered],
            ["Waiting Period Passed",          coverage.waiting_period_passed],
            ["Specific Waiting Period Passed", coverage.specific_waiting_period_passed],
            ["Submission Window Passed",       coverage.submission_window_passed],
            ["Minimum Amount Passed",          coverage.minimum_amount_passed],
            ["Exclusion Found",                coverage.exclusion_found],
          ]} />
          {coverage.rejection_reasons?.length > 0 && (
            <div className="tc-doc-tags">
              <span className="tc-doc-tags__label tc-doc-tags__label--warn">Rejection Reasons</span>
              <div className="tc-tag-row">
                {coverage.rejection_reasons.map((r, i) => (
                  <span key={i} className="tc-tag tc-tag--red">{r}</span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

// ─── 5. Finance Section ───────────────────────────────────────────────────────
const FinanceSection = ({ finance, financeResult }) => {
  if (!finance && !financeResult) return null;
  const fmt = (n) => n != null ? `₹${Number(n).toLocaleString("en-IN", { minimumFractionDigits: 0 })}` : "—";
  return (
    <div className="tc-data-section">
      <ResultBar result={financeResult} />
      {finance && (
        <>
          <KVTable rows={[
            ["Claimed Amount",           fmt(finance.claimed_amount)],
            ["Eligible Amount",          fmt(finance.eligible_amount)],
            ["Approved Amount",          fmt(finance.approved_amount)],
            ["Co-pay",                   fmt(finance.co_pay)],
            ["Annual Limit Remaining",   fmt(finance.annual_limit_remaining)],
            ["Family Limit Remaining",   fmt(finance.family_limit_remaining)],
            ["Per Claim Limit Applied",  finance.per_claim_limit_applied],
            ["Annual Limit Applied",     finance.annual_limit_applied],
            ["Family Floater Applied",   finance.family_floater_limit_applied],
          ]} />
          {finance.rejection_reasons?.length > 0 && (
            <div className="tc-doc-tags">
              <span className="tc-doc-tags__label tc-doc-tags__label--warn">Rejection Reasons</span>
              <div className="tc-tag-row">
                {finance.rejection_reasons.map((r, i) => (
                  <span key={i} className="tc-tag tc-tag--red">{r}</span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

// ─── 6. Fraud Section ─────────────────────────────────────────────────────────
const FraudSection = ({ fraud, fraudResult }) => {
  if (!fraud && !fraudResult) return null;
  const scorePct = fraud?.fraud_score != null ? Math.round(fraud.fraud_score * 100) : null;
  return (
    <div className="tc-data-section">
      <ResultBar result={fraudResult} />
      {fraud && (
        <>
          <KVTable rows={[
            ["Fraud Score",          scorePct != null ? `${scorePct}%` : "—"],
            ["Monthly Claims",       fraud.monthly_claims_count],
            ["Same-day Claims",      fraud.same_day_claims_count],
            ["Manual Review Needed", fraud.manual_review_required],
          ]} />
          <WarnList items={fraud.warnings} icon={AlertCircle} cls="tc-warn" />
        </>
      )}
    </div>
  );
};

// ─── 7. Decision Section ──────────────────────────────────────────────────────
const DecisionSection = ({ decision, decisionResult }) => {
  if (!decision && !decisionResult) return null;
  const fmt = (n) => n != null ? `₹${Number(n).toLocaleString("en-IN", { minimumFractionDigits: 0 })}` : "—";
  const dec = decision || {};
  const decStr = dec.decision || "—";
  const activeBreakdown = dec.financial_breakdown?.filter(b => b.amount > 0) || [];
  return (
    <div className="tc-data-section">
      <ResultBar result={decisionResult} />
      {decision && (
        <>
          <KVTable rows={[
            ["Decision",           decStr],
            ["Claimed Amount",     fmt(dec.claimed_amount)],
            ["Approved Amount",    fmt(dec.approved_amount)],
            ["Fraud Score",        dec.fraud_score != null ? `${Math.round(dec.fraud_score * 100)}%` : undefined],
            ["Needs Manual Review",dec.needs_manual_review],
          ]} />
          {dec.explanation && (
            <div className="tc-explanation">{dec.explanation}</div>
          )}
          {activeBreakdown.length > 0 && (
            <div className="tc-breakdown">
              <div className="tc-breakdown__title">Financial Deductions</div>
              {activeBreakdown.map((b, i) => (
                <div key={i} className="tc-breakdown__row">
                  <span>{b.step}</span>
                  <span className="tc-breakdown__amt">− {fmt(b.amount)}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
};

// ─── Error Boundary (prevents one bad card blanking the whole page) ────────
class CardErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { hasError: false, msg: "" }; }
  static getDerivedStateFromError(err) { return { hasError: true, msg: err?.message || "Render error" }; }
  componentDidCatch() {}
  render() {
    if (this.state.hasError) {
      return (
        <div className="tc-error-box" style={{ margin: "10px 0" }}>
          <AlertCircle size={14} />
          <span>Card render failed: {this.state.msg}</span>
        </div>
      );
    }
    return this.props.children;
  }
}

/** Normalize decision: actual.decision can be a plain string OR a {decision:"APPROVED",...} object */
const normalizeDecision = (raw) => {
  if (!raw) return { str: null, obj: null };
  if (typeof raw === "string") return { str: raw, obj: null };
  if (typeof raw === "object" && raw !== null) {
    return { str: raw.decision || null, obj: raw };
  }
  return { str: String(raw), obj: null };
};

/** Expected vs Actual comparison table — handles decision as string or object */
const OutcomeComparisonTable = ({ expected, actual }) => {
  const expDecision = expected.decision;    // always null or string in the JSON
  const { str: actStr, obj: actObj } = normalizeDecision(actual.decision);

  // Match logic: expected null means "no decision expected", match if actual also has none
  const decisionMatch =
    (expDecision == null && !actStr) ||
    (typeof expDecision === "string" && expDecision === actStr);

  const fmt = (n) =>
    n != null ? `₹${Number(n).toLocaleString("en-IN", { minimumFractionDigits: 0 })}` : "—";

  return (
    <div className="tc-outcome-grid">
      {/* Expected column */}
      <div className="tc-outcome-col tc-outcome-col--exp">
        <div className="tc-outcome-col__header">
          <span className="tc-outcome-col__label">🎯 Expected</span>
        </div>
        <table className="tc-table">
          <tbody>
            <tr className="tc-table__row">
              <td className="tc-table__key">Decision</td>
              <td className="tc-table__val">
                {expDecision == null
                  ? <span className="tc-null-pill">No decision expected</span>
                  : <span className="tc-decision-pill">{expDecision}</span>}
              </td>
            </tr>
          </tbody>
        </table>
        {expected.system_must?.length > 0 && (
          <>
            <div className="tc-outcome-subsection">System Must</div>
            <ul className="tc-must-list">
              {expected.system_must.map((m, i) => (
                <li key={i} className="tc-must-item">
                  <ChevronRight size={11} className="tc-must-arrow" />
                  {m}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      {/* Actual column */}
      <div className={`tc-outcome-col tc-outcome-col--act${decisionMatch ? " tc-outcome-col--match" : " tc-outcome-col--mismatch"}`}>
        <div className="tc-outcome-col__header">
          <span className="tc-outcome-col__label">⚡ Actual</span>
          {decisionMatch
            ? <span className="tc-match-badge tc-match-badge--ok">✓ Match</span>
            : <span className="tc-match-badge tc-match-badge--fail">✗ Mismatch</span>}
        </div>
        <table className="tc-table">
          <tbody>
            <tr className="tc-table__row">
              <td className="tc-table__key">Decision</td>
              <td className="tc-table__val">
                {actStr
                  ? <span className={`tc-decision-pill tc-decision-pill--${actStr.toLowerCase().replace(/_/g, "-")}`}>{actStr}</span>
                  : <span className="tc-null-pill">No decision returned</span>}
              </td>
            </tr>
            {/* For object decisions: show financials */}
            {actObj?.approved_amount != null && (
              <tr className="tc-table__row">
                <td className="tc-table__key">Approved</td>
                <td className="tc-table__val" style={{ color: "var(--green)", fontWeight: 600 }}>
                  {fmt(actObj.approved_amount)}
                </td>
              </tr>
            )}
            {actObj?.claimed_amount != null && (
              <tr className="tc-table__row">
                <td className="tc-table__key">Claimed</td>
                <td className="tc-table__val">{fmt(actObj.claimed_amount)}</td>
              </tr>
            )}
            {actObj?.fraud_score != null && (
              <tr className="tc-table__row">
                <td className="tc-table__key">Fraud Score</td>
                <td className="tc-table__val">{(actObj.fraud_score * 100).toFixed(0)}%</td>
              </tr>
            )}
            {/* Error step/message for failed pipelines */}
            {actual.error_step && (
              <tr className="tc-table__row">
                <td className="tc-table__key">Failed Step</td>
                <td className="tc-table__val tc-table__val--warn">{actual.error_step}</td>
              </tr>
            )}
            {actual.error_message && (
              <tr className="tc-table__row">
                <td className="tc-table__key">Error Message</td>
                <td className="tc-table__val tc-table__val--error">{actual.error_message}</td>
              </tr>
            )}
            {/* Explanation from decision object */}
            {actObj?.explanation && (
              <tr className="tc-table__row">
                <td className="tc-table__key">Explanation</td>
                <td className="tc-table__val" style={{ fontSize: "11px", lineHeight: 1.5 }}>{actObj.explanation}</td>
              </tr>
            )}
          </tbody>
        </table>
        {actual.error_issues?.length > 0 && (
          <div className="tc-issue-list">
            {actual.error_issues.map((e, i) => (
              <div key={i} className="tc-issue-item">
                <XCircle size={11} className="tc-issue-icon" />
                <span>{e}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

const PIPELINE_SECTIONS = [
  { key: "member",   label: "Member",   icon: User,        DataComp: MemberSection,   dataKey: "member",   resultKey: "member_result"   },
  { key: "policy",   label: "Policy",   icon: ShieldCheck, DataComp: PolicySection,   dataKey: null,       resultKey: "policy_result"   },
  { key: "document", label: "Document", icon: FileText,    DataComp: DocumentSection, dataKey: "document", resultKey: "document_result" },
  { key: "coverage", label: "Coverage", icon: CheckCircle, DataComp: CoverageSection, dataKey: "coverage", resultKey: "coverage_result" },
  { key: "finance",  label: "Finance",  icon: DatabaseZap, DataComp: FinanceSection,  dataKey: "finance",  resultKey: "finance_result"  },
  { key: "fraud",    label: "Fraud",    icon: AlertCircle, DataComp: FraudSection,    dataKey: "fraud",    resultKey: "fraud_result"    },
  { key: "decision", label: "Decision", icon: Sparkles,    DataComp: DecisionSection, dataKey: "decision", resultKey: "decision_result" },
];

const TestCaseCard = ({ result, index }) => {
  const [expanded, setExpanded] = useState(false);
  const hasError = Boolean(result.error);
  const expected = result.expected || {};
  const actual = result.actual || {};

  return (
    <div className="tc-card">
      {/* Header — no pass/fail badge, just case ID */}
      <button className="tc-header" onClick={() => setExpanded(v => !v)}>
        <div className="tc-badge tc-badge--neutral">
          <FileText size={14} />
          <span>{result.case_id}</span>
        </div>
        {hasError && (
          <span className="tc-err-pill">Pipeline Error</span>
        )}
        <ChevronRight
          size={16}
          className={`tc-chevron${expanded ? " tc-chevron--open" : ""}`}
        />
      </button>

      {/* Expanded body */}
      {expanded && (
        <div className="tc-body">
          {/* Pipeline error banner */}
          {hasError && (
            <div className="tc-error-box">
              <AlertCircle size={14} />
              <span>{result.error}</span>
            </div>
          )}

          {/* ── Section 1: Outcome Comparison ── */}
          <div className="tc-section">
            <div className="tc-section__title">
              <ShieldCheck size={14} className="tc-section__icon" />
              Outcome Comparison
            </div>
            <OutcomeComparisonTable expected={expected} actual={actual} />
          </div>

          {/* ── Sections 2-8: Pipeline stages (data + result) ── */}
          {PIPELINE_SECTIONS.map(({ key, label, icon: Icon, DataComp, dataKey, resultKey }) => {
            const dataObj    = dataKey   ? actual[dataKey]   : null;
            const resultObj  = resultKey ? actual[resultKey] : null;
            if (!dataObj && !resultObj) return null;
            return (
              <div key={key} className="tc-section">
                <div className="tc-section__title">
                  <Icon size={14} className="tc-section__icon" />
                  {label}
                </div>
                <DataComp
                  {...(dataKey   ? { [dataKey]:   dataObj   } : {})}
                  {...(resultKey ? { [resultKey]: resultObj } : {})}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};






const TestPage = ({ onBack }) => {
  const [status, setStatus]   = useState("idle"); // idle | loading | running | done | error
  const [results, setResults] = useState(null);
  const [errMsg, setErrMsg]   = useState("");
  const [stdout, setStdout]   = useState("");
  const [stderr, setStderr]   = useState("");
  const [showLogs, setShowLogs] = useState(false);

  // Load existing results on mount
  useEffect(() => {
    setStatus("loading");
    fetch("/test")
      .then(r => r.json())
      .then(d => {
        if (d.success) { setResults(d.results); setStatus("done"); }
        else { setStatus("idle"); }
      })
      .catch(() => setStatus("idle"));
  }, []);

  const runTests = async () => {
    setStatus("running");
    setErrMsg("");
    setStdout("");
    setStderr("");
    try {
      const res = await fetch("/test", { method: "POST" });
      const data = await res.json();
      if (data.success) {
        setResults(data.results);
        setStdout(data.stdout || "");
        setStderr(data.stderr || "");
        setStatus("done");
      } else {
        setErrMsg(data.message || "Test run failed");
        setStdout(data.stdout || "");
        setStderr(data.stderr || "");
        setStatus("error");
      }
    } catch (e) {
      setErrMsg(`Could not reach backend: ${e.message}`);
      setStatus("error");
    }
  };

  const total = results?.length || 0;

  return (
    <div className="tp-shell">
      {/* Header */}
      <header className="app-header">
        <div className="app-header__brand">
          <button className="tp-back-btn" onClick={onBack} title="Back to chat">
            <ArrowLeft size={16} />
          </button>
          <div className="brand-icon">
            <FlaskConical size={18} />
          </div>
          <div>
            <h1 className="brand-title">Test Suite Runner</h1>
            <p className="brand-sub">Backend pipeline integration tests</p>
          </div>
        </div>
        <div className="app-header__status">
          {status === "done" && results && (
            <span className="tp-stat tp-stat--neutral">{total} test case{total !== 1 ? "s" : ""}</span>
          )}
          <button
            className={`tp-run-btn${status === "running" ? " tp-run-btn--busy" : ""}`}
            onClick={runTests}
            disabled={status === "running" || status === "loading"}
          >
            {status === "running" ? (
              <><Loader2 size={14} className="animate-spin" /> Running…</>
            ) : (
              <><Play size={14} /> Run Tests</>
            )}
          </button>
        </div>
      </header>

      {/* Body */}
      <div className="tp-body">
        {/* Loading skeleton */}
        {(status === "loading" || status === "running") && (
          <div className="tp-center">
            <Loader2 size={36} className="animate-spin tp-spinner" />
            <p className="tp-loading-text">
              {status === "loading" ? "Loading existing results…" : "Running test suite, please wait…"}
            </p>
          </div>
        )}

        {/* Error */}
        {status === "error" && (
          <div className="tp-error-banner">
            <AlertCircle size={18} />
            <div>
              <p className="tp-error-banner__title">Test Run Failed</p>
              <p className="tp-error-banner__msg">{errMsg}</p>
            </div>
          </div>
        )}

        {/* Results */}
        {(status === "done" || (status === "error" && results)) && results && (
          <>
            {/* Summary bar */}
            <div className="tp-summary">
              <div className="tp-summary__item">
                <span className="tp-summary__num">{total}</span>
                <span className="tp-summary__label">Test Cases</span>
              </div>
            </div>

            {/* Cards */}
            <div className="tp-cards">
              {results.map((r, i) => (
                <CardErrorBoundary key={r.case_id || i}>
                  <TestCaseCard result={r} index={i} />
                </CardErrorBoundary>
              ))}
            </div>

            {/* Logs toggle */}
            {(stdout || stderr) && (
              <div className="tp-logs-wrap">
                <button className="tp-logs-toggle" onClick={() => setShowLogs(v => !v)}>
                  <ChevronRight size={14} className={showLogs ? "tc-chevron--open" : ""} />
                  {showLogs ? "Hide" : "Show"} stdout / stderr
                </button>
                {showLogs && (
                  <div className="tp-logs">
                    {stdout && (
                      <>
                        <div className="tp-logs__label">stdout</div>
                        <pre className="tp-logs__pre">{stdout}</pre>
                      </>
                    )}
                    {stderr && (
                      <>
                        <div className="tp-logs__label tp-logs__label--err">stderr</div>
                        <pre className="tp-logs__pre tp-logs__pre--err">{stderr}</pre>
                      </>
                    )}
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {/* Idle state */}
        {status === "idle" && (
          <div className="tp-center">
            <div className="tp-idle-icon"><FlaskConical size={40} /></div>
            <p className="tp-idle-title">No results yet</p>
            <p className="tp-idle-sub">Click <strong>Run Tests</strong> to execute the test suite.</p>
          </div>
        )}
      </div>
    </div>
  );
};

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
  const [memberId, setMemberId] = useState("EMP001");
  const [claimCategory, setClaimCategory] = useState("PHARMACY");

  // ── Update-Claim admin auth state ─────────────────────────────────────────
  const [showAdminAuth, setShowAdminAuth]       = useState(false);
  const [isAdminSubmitting, setIsAdminSubmitting] = useState(false);
  // Pending AI typing-indicator message index (so we can resolve it after auth)
  const pendingAdminMsgIdxRef = useRef(null);

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
        const res = await fetch(`${BASE_URL}/upload?member_id=${encodeURIComponent(memberId)}`, {
          method: "POST",
          body: formData,
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(
            data.error || "Upload failed"
          );
        }
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

  // ── Admin submit: call /updateClaim ──────────────────────────────────────
  const handleAdminSubmit = async ({ claimId, claimStatus, approveAmt, password }) => {
    setIsAdminSubmitting(true);

    // Capture the pending message ID NOW (outside any state updater)
    const pendingId = pendingAdminMsgIdxRef.current;
    pendingAdminMsgIdxRef.current = null;

    const resolveMsg = (updateResult) => {
      if (pendingId !== null) {
        setMessages((prev) =>
          prev.map((m) =>
            m.adminMsgId === pendingId
              ? { ...m, text: "", updateResult, loading: false, time: now() }
              : m
          )
        );
      } else {
        addMessage({ role: "assistant", text: "", updateResult, loading: false, time: now() });
      }
    };

    try {
      const res = await fetch(`${BASE_URL}/updateClaim`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Admin-Password": password,
        },
        body: JSON.stringify({
          claim_id: claimId,
          claim_status: claimStatus,
          approve_amount: approveAmt ? Number(approveAmt) : 0,
        }),
      });

      const data = await res.json();

      if (res.ok && data.success !== false) {
        resolveMsg({
          success: true,
          claimId,
          claimStatus,
          approveAmt: approveAmt ? Number(approveAmt) : 0,
          message: data.message || "",
        });
      } else if (res.status === 401) {
        resolveMsg({ success: false, authFailed: true, errorMsg: "Incorrect admin password. Access denied." });
      } else if (res.status === 400) {
        resolveMsg({ success: false, errorMsg: data.message || "Missing required claim details." });
      } else {
        resolveMsg({ success: false, errorMsg: data.message || "Unknown error occurred." });
      }
    } catch (err) {
      resolveMsg({ success: false, errorMsg: `Could not reach backend: ${err.message}` });
    } finally {
      setIsAdminSubmitting(false);
      setShowAdminAuth(false);
      setIsLoading(false);
    }
  };

  const handleAdminCancel = () => {
    setShowAdminAuth(false);
    // Capture and clear the pending ID outside any state updater
    const pendingId = pendingAdminMsgIdxRef.current;
    pendingAdminMsgIdxRef.current = null;
    if (pendingId !== null) {
      // Remove the loading bubble by its unique ID
      setMessages((prev) => prev.filter((m) => m.adminMsgId !== pendingId));
    }
    setIsLoading(false);
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

    // ── Intercept update-claim queries ─────────────────────────────────────
    if (text && isUpdateClaimQuery(text)) {
      // Stamp a unique ID on the loading bubble so we can find it by ID later
      const adminMsgId = Date.now();
      pendingAdminMsgIdxRef.current = adminMsgId;   // store ID, NOT index
      addMessage({
        adminMsgId,
        role: "assistant",
        text: "",
        loading: true,
        time: now(),
      });
      setIsLoading(true);
      setShowAdminAuth(true);
      return; // wait for admin auth panel submission
    }

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
          uploadSummary = `✅ Successfully uploaded ${successes.length} document(s). \n`;
        }
        if (failures.length > 0) {
          uploadSummary += `⚠️ ${failures.length} document(s) failed to upload. \n`;
        }
        uploadResults.map(r => {
          if(!r.ok){
            uploadSummary+= `${r.error}`
          }
        })
        
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
    let tableData = null;

    if (text) {
      try {
        const res = await fetch(
          `${BASE_URL}/chat?query=${encodeURIComponent(text)}&member_id=${encodeURIComponent(memberId)}&claim_category=${encodeURIComponent(claimCategory)}`
        );
        const data = await res.json();

        console.log(`Chat Data: ${data}`)

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
            if (Array.isArray(ui.message)) {
              // Array data → render as table, no raw text
              tableData = ui.message;
            } else if (typeof ui.message === "string") {
              responseText += ui.message;
            } else {
              responseText += JSON.stringify(ui.message, null, 2);
            }

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
      text: tableData ? responseText : (responseText || "Done! Anything else I can help you with?"),
      loading: false,
      claim: claimData,
      tableData: tableData,
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

  const [page, setPage] = useState("chat"); // "chat" | "test"

  if (page === "test") {
    return <TestPage onBack={() => setPage("chat")} />;
  }

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
          <div className="member-pill">{memberId || "—"}</div>
          <button
            className="tp-nav-btn"
            onClick={() => setPage("test")}
            title="Test Suite"
          >
            <FlaskConical size={14} />
            <span>Tests</span>
          </button>
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
          memberId={memberId}
          claimCategory={claimCategory}
          onMemberIdChange={setMemberId}
          onClaimCategoryChange={setClaimCategory}
          showAdminAuth={showAdminAuth}
          onAdminSubmit={handleAdminSubmit}
          onAdminCancel={handleAdminCancel}
          isAdminSubmitting={isAdminSubmitting}
          onDeleteDb={() => { setLastClaim(null); }}
          onDeleteDocs={() => { setUploadedCount(0); }}
          onAddPolicy={() => {}}
        />
      </div>
    </div>
  );
};

export default App;
