import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Clock3,
  FileText,
  RefreshCw,
  Sparkles,
  Trash2,
} from "lucide-react";

import HudModal from "../../components/HudModal";
import { api, LLMLog, Project } from "../../services/api";

type Props = {
  project: Project | null;
};

export default function LLMLogsPage({ project }: Props) {
  const [logs, setLogs] = useState<LLMLog[]>([]);
  const [busy, setBusy] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [actorFilter, setActorFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [clearDialog, setClearDialog] = useState(false);
  const [status, setStatus] = useState("");

  async function load() {
    if (!project) {
      setLogs([]);
      return;
    }

    setBusy(true);
    setStatus("");
    try {
      setLogs(await api.llmLogs(project.id, 300));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load();
  }, [project?.id]);

  const actors = useMemo(
    () =>
      Array.from(
        new Set(logs.map((log) => log.actor_name)),
      ).sort(),
    [logs],
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return logs.filter((log) => {
      if (statusFilter !== "all" && log.status !== statusFilter) {
        return false;
      }
      if (actorFilter !== "all" && log.actor_name !== actorFilter) {
        return false;
      }
      if (!needle) return true;
      return [
        log.actor_name,
        log.actor_role,
        log.provider_id,
        log.model,
        log.request_json,
        log.response_text,
        log.error_text,
      ]
        .join("\n")
        .toLowerCase()
        .includes(needle);
    });
  }, [logs, statusFilter, actorFilter, query]);

  async function clearLogs() {
    if (!project) return;
    setBusy(true);
    try {
      const result = await api.clearLLMLogs(project.id);
      setLogs([]);
      setClearDialog(false);
      setStatus("Cleared " + result.count + " LLM log entries.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  if (!project) {
    return (
      <section className="panel logsEmpty">
        <FileText size={24} />
        <h3>No project selected</h3>
        <p className="muted">
          Select or create a project to inspect its LLM calls.
        </p>
      </section>
    );
  }

  return (
    <section className="llmLogsPage">
      <div className="sectionHeading">
        <div>
          <h2>LLM Logs</h2>
          <p>
            Inspect Agent Man and worker model calls, latency, failures,
            prompts, and responses. Secrets and API keys are not logged.
          </p>
        </div>
        <span className="connectionCount">
          {logs.length} entries
        </span>
      </div>

      <div className="panel logsToolbar">
        <label>
          Status
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="all">All</option>
            <option value="success">Success</option>
            <option value="error">Error</option>
          </select>
        </label>

        <label>
          Agent
          <select
            value={actorFilter}
            onChange={(event) => setActorFilter(event.target.value)}
          >
            <option value="all">All agents</option>
            {actors.map((actor) => (
              <option value={actor} key={actor}>
                {actor}
              </option>
            ))}
          </select>
        </label>

        <label className="logsSearch">
          Search
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="agent, model, prompt, response..."
          />
        </label>

        <button
          className="secondaryButton"
          onClick={() => void load()}
          disabled={busy}
        >
          <RefreshCw
            size={14}
            className={busy ? "spinIcon" : ""}
          />
          Refresh
        </button>

        <button
          className="secondaryButton dangerAction"
          onClick={() => setClearDialog(true)}
          disabled={busy || logs.length === 0}
        >
          <Trash2 size={14} />
          Clear
        </button>
      </div>

      {status && <div className="connectionStatus">{status}</div>}

      <div className="logsList">
        {filtered.length === 0 && (
          <div className="panel logsEmpty">
            <FileText size={22} />
            <h3>No LLM calls match</h3>
            <p className="muted">
              Run Agent Man or a worker, then refresh this page.
            </p>
          </div>
        )}

        {filtered.map((log) => (
          <details className={"llmLogCard " + log.status} key={log.id}>
            <summary>
              <span className="llmLogActorIcon">
                {log.actor_role === "Executive" ? (
                  <Sparkles size={15} />
                ) : (
                  <Bot size={15} />
                )}
              </span>

              <span className="llmLogIdentity">
                <b>{log.actor_name}</b>
                <small>{log.actor_role}</small>
              </span>

              <span className="llmLogModel">
                <small>{log.provider_id}</small>
                <b>{log.model}</b>
              </span>

              <span className="llmLogTiming">
                <Clock3 size={12} />
                {formatDuration(log.duration_ms)}
              </span>

              <span className={"llmLogStatus " + log.status}>
                {log.status === "success" ? "SUCCESS" : "ERROR"}
              </span>

              <time>{formatTime(log.created_at)}</time>
            </summary>

            <div className="llmLogDetails">
              <div className="llmLogMeta">
                <span>
                  <small>PROVIDER</small>
                  <b>{log.provider_id}</b>
                </span>
                <span>
                  <small>MODEL</small>
                  <b>{log.model}</b>
                </span>
                <span>
                  <small>LATENCY</small>
                  <b>{formatDuration(log.duration_ms)}</b>
                </span>
                <span>
                  <small>ENDPOINT</small>
                  <code>{log.endpoint || "provider default"}</code>
                </span>
              </div>

              <LogPayload
                title="REQUEST / MESSAGES"
                value={prettyRequest(log.request_json)}
              />

              {log.response_text && (
                <LogPayload
                  title="RESPONSE"
                  value={log.response_text}
                />
              )}

              {log.error_text && (
                <div className="llmErrorPayload">
                  <header>
                    <AlertTriangle size={13} />
                    ERROR
                  </header>
                  <pre>{log.error_text}</pre>
                </div>
              )}
            </div>
          </details>
        ))}
      </div>

      <HudModal
        open={clearDialog}
        onClose={() => setClearDialog(false)}
        title="Clear LLM Logs"
        eyebrow="LOGS / DESTRUCTIVE ACTION"
        tone="danger"
        footer={
          <>
            <button
              className="secondaryButton"
              onClick={() => setClearDialog(false)}
            >
              Keep logs
            </button>
            <button
              className="primaryButton dangerAction"
              onClick={() => void clearLogs()}
              disabled={busy}
            >
              <Trash2 size={14} />
              Clear all logs
            </button>
          </>
        }
      >
        <p className="systemMessage">
          This removes the stored LLM request and response history for
          {project.name}. It does not affect agents, workflows, or AI
          connections.
        </p>
      </HudModal>
    </section>
  );
}

function LogPayload({
  title,
  value,
}: {
  title: string;
  value: string;
}) {
  return (
    <section className="llmPayload">
      <header>{title}</header>
      <pre>{value || "(empty)"}</pre>
    </section>
  );
}

function prettyRequest(value: string) {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function formatDuration(ms: number) {
  if (ms < 1000) return ms + " ms";
  return (ms / 1000).toFixed(2) + " s";
}

function formatTime(value: string) {
  const date = new Date(value);
  return date.toLocaleString();
}
