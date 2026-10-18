import { useEffect, useState } from "react";
import { Activity, RefreshCw, TerminalSquare } from "lucide-react";
import {
  api,
  AgentTaskHistory,
  BackgroundJob,
  ManagedProcess,
  Project,
} from "../../services/api";
import "./background.css";

function timestamp(value: string | null) {
  return value ? new Date(value).toLocaleString() : "—";
}

export default function BackgroundPage({ project }: { project: Project | null }) {
  if (!project) return <section className="panel settingsEmpty"><Activity /><h3>No project selected</h3><p>Select a project to monitor its background work.</p></section>;
  return <ProjectBackground key={project.id} project={project} />;
}

function ProjectBackground({ project }: { project: Project }) {
  const [jobs, setJobs] = useState<BackgroundJob[]>([]);
  const [history, setHistory] = useState<AgentTaskHistory[]>([]);
  const [processes, setProcesses] = useState<ManagedProcess[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [filter, setFilter] = useState("all");
  const [historyAgent, setHistoryAgent] = useState("all");
  const [historyStatus, setHistoryStatus] = useState("all");
  const [selectedProcess, setSelectedProcess] = useState("");
  const [updated, setUpdated] = useState("");

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const results = await Promise.allSettled([
        api.backgroundJobs(project.id),
        api.taskHistory(project.id),
        api.managedProcesses(project.id),
      ]);
      if (disposed) return;
      const failures: string[] = [];
      if (results[0].status === "fulfilled") setJobs(results[0].value);
      else failures.push("Jobs: " + String(results[0].reason));
      if (results[1].status === "fulfilled") setHistory(results[1].value);
      else failures.push("History: " + String(results[1].reason));
      if (results[2].status === "fulfilled") setProcesses(results[2].value);
      else failures.push("Processes: " + String(results[2].reason));
      setErrors(failures);
      if (!failures.length) setUpdated(new Date().toLocaleTimeString());
      setLoading(false);
      timer = setTimeout(() => void poll(), 2000);
    }
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [project.id, refresh]);

  const active = jobs.filter((job) => ["queued", "running"].includes(job.status));
  const visible = jobs.filter((job) => filter === "all" || (filter === "active" ? ["queued", "running"].includes(job.status) : job.status === filter));
  const historyAgents = Array.from(
    new Map(
      history.map((item) => [
        item.agent_id,
        { id: item.agent_id, name: item.agent_name },
      ]),
    ).values(),
  ).sort((a, b) => a.name.localeCompare(b.name));
  const historyStatuses = Array.from(
    new Set(history.map((item) => item.status)),
  ).sort();
  const visibleHistory = history.filter(
    (item) =>
      (historyAgent === "all" || item.agent_id === historyAgent) &&
      (historyStatus === "all" || item.status === historyStatus),
  );
  const selected = processes.find((process) => process.id === selectedProcess);

  return (
    <section className="backgroundPage">
      <div className="sectionHeading">
        <div><h2>Background activity</h2><p>Monitor agent jobs and managed processes for {project.name}.</p></div>
        <button className="secondaryButton" onClick={() => setRefresh((value) => value + 1)}><RefreshCw size={14} />Refresh</button>
      </div>
      <div className="backgroundSummary panel">
        <span><b>{active.length}</b> active agent jobs</span>
        <span><b>{history.length}</b> recorded agent tasks</span>
        <span><b>{processes.filter((process) => process.status === "running").length}</b> running processes</span>
        <span>{loading ? "Loading activity…" : `Refreshes every 2 seconds · Last synced ${updated || "not yet"}`}</span>
      </div>
      {errors.length > 0 && <div className="connectionStatus" role="alert">Updates unavailable; showing the last received data. {errors.join(" · ")}</div>}
      <section className="panel backgroundSection">
        <div className="backgroundHeading"><h3><Activity size={18} /> Agent jobs</h3>
          <label>Status <select value={filter} onChange={(event) => setFilter(event.target.value)}>
            <option value="all">All jobs</option><option value="active">Active</option>
            {Array.from(new Set(jobs.map((job) => job.status))).sort().map((status) => <option key={status} value={status}>{status.replaceAll("_", " ")}</option>)}
          </select></label>
        </div>
        {!loading && visible.length === 0 && <p className="muted">{jobs.length ? "No jobs match this filter." : "No background jobs yet. Ask Executive to delegate a task to an agent."}</p>}
        <div className="backgroundJobs">
          {visible.map((job) => (
            <article className="backgroundJob" key={job.id}>
              <header><div><h4>{job.agent_name}</h4><small>{job.agent_role}</small></div><span className="taskStatus">{job.status.replaceAll("_", " ")}</span></header>
              <p className="backgroundTask">{job.task}</p>
              <dl>
                <dt>Current action</dt><dd>{job.current_action || job.current_phase || "—"}</dd>
                <dt>Tool</dt><dd>{job.current_tool || "—"}</dd>
                <dt>Steps</dt><dd>{job.step_count}</dd>
                <dt>Last update</dt><dd>{timestamp(job.updated_at)}</dd>
              </dl>
              {job.current_detail && <pre className="backgroundOutput">{job.current_detail}</pre>}
              {job.error && <p className="backgroundError" role="alert">{job.error}</p>}
              <details><summary>Job details and result</summary>
                <dl><dt>Job ID</dt><dd>{job.id}</dd><dt>Queued</dt><dd>{timestamp(job.created_at)}</dd><dt>Started</dt><dd>{timestamp(job.started_at)}</dd><dt>Finished</dt><dd>{timestamp(job.completed_at)}</dd></dl>
                <pre className="backgroundOutput">{job.result_text || "No result reported yet."}</pre>
              </details>
            </article>
          ))}
        </div>
      </section>
      <section className="panel backgroundSection">
        <div className="backgroundHeading">
          <div>
            <h3><Activity size={18} /> Agent work history</h3>
            <p className="muted">
              Persistent record of which agent worked on each delegated task.
            </p>
          </div>
          <div className="historyFilters">
            <label>
              Agent
              <select
                value={historyAgent}
                onChange={(event) => setHistoryAgent(event.target.value)}
              >
                <option value="all">All agents</option>
                {historyAgents.map((item) => (
                  <option value={item.id} key={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Status
              <select
                value={historyStatus}
                onChange={(event) => setHistoryStatus(event.target.value)}
              >
                <option value="all">All statuses</option>
                {historyStatuses.map((status) => (
                  <option value={status} key={status}>
                    {status.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {!loading && visibleHistory.length === 0 && (
          <p className="muted">
            {history.length
              ? "No recorded tasks match these filters."
              : "No persistent agent task history yet."}
          </p>
        )}

        {visibleHistory.length > 0 && (
          <div className="agentHistoryTableWrap">
            <table className="agentHistoryTable">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Task</th>
                  <th>Status</th>
                  <th>Started</th>
                  <th>Finished</th>
                  <th>Steps</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {visibleHistory.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{item.agent_name}</strong>
                      <small>{item.agent_role || "Worker"}</small>
                    </td>
                    <td>
                      <span className="historyTask">{item.task}</span>
                      {item.current_tool && (
                        <code>{item.current_tool}</code>
                      )}
                    </td>
                    <td>
                      <span className={"taskStatus status-" + item.status}>
                        {item.status.replaceAll("_", " ")}
                      </span>
                    </td>
                    <td>{timestamp(item.started_at || item.created_at)}</td>
                    <td>{timestamp(item.completed_at)}</td>
                    <td>{item.step_count}</td>
                    <td>
                      <details>
                        <summary>
                          {item.result_text
                            ? "View result"
                            : item.error
                              ? "View error"
                              : "View activity"}
                        </summary>
                        <div className="historyDetail">
                          <b>Current / final action</b>
                          <p>{item.current_action || "—"}</p>
                          {item.result_text && (
                            <>
                              <b>Result</b>
                              <pre className="backgroundOutput">
                                {item.result_text}
                              </pre>
                            </>
                          )}
                          {item.error && (
                            <>
                              <b>Error</b>
                              <pre className="backgroundOutput backgroundError">
                                {item.error}
                              </pre>
                            </>
                          )}
                          <small>Job ID: {item.id}</small>
                        </div>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel backgroundSection">
        <div className="backgroundHeading"><h3><TerminalSquare size={18} /> Managed processes</h3></div>
        <p className="muted">Commands started by Agent Man in this project's workspace. Select a process to follow its output.</p>
        {!loading && processes.length === 0 && <p className="muted">No managed processes in this workspace.</p>}
        <div className="backgroundProcesses">
          {processes.map((process) => <button key={process.id} className={"backgroundProcess" + (selectedProcess === process.id ? " selected" : "")} aria-pressed={selectedProcess === process.id} onClick={() => setSelectedProcess(process.id)}>
            <code>{process.command}</code><span>{process.status} · PID {process.pid}{process.port !== null ? ` · Port ${process.port}` : ""}{process.exit_code !== null ? ` · Exit ${process.exit_code}` : ""}</span>
          </button>)}
        </div>
        {selected && <ProcessOutput key={selected.id} projectId={project.id} process={selected} />}
      </section>
      <p className="muted">
        Agent task history is persisted in the project database. Live job and
        managed-process telemetry remains runtime scoped.
      </p>
    </section>
  );
}

function ProcessOutput({ projectId, process }: { projectId: string; process: ManagedProcess }) {
  const [output, setOutput] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await api.processOutput(projectId, process.id);
        if (disposed) return;
        setOutput(result.output);
        setError("");
      } catch (failure) {
        if (disposed) return;
        setError(failure instanceof Error ? failure.message : String(failure));
      }
      if (disposed) return;
      setLoading(false);
      timer = setTimeout(() => void poll(), 2000);
    }
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [projectId, process.id]);
  return <div className="backgroundProcessOutput"><h4>Latest output · PID {process.pid}</h4>
    {error && <p role="alert">Unable to refresh output: {error}</p>}
    <pre className="backgroundOutput">{output || (loading ? "Loading output…" : "No output yet.")}</pre>
  </div>;
}
