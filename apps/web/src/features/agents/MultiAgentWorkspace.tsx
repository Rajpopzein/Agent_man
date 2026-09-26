import { FormEvent, useEffect, useMemo, useState } from "react";
import { BrainCircuit, Play, RefreshCw, TerminalSquare, Users } from "lucide-react";

import { api, Agent, MultiAgentTask, Project } from "../../services/api";

type Props = {
  project: Project | null;
  agents: Agent[];
};

export default function MultiAgentWorkspace({ project, agents }: Props) {
  const [selected, setSelected] = useState<string[]>([]);
  const [title, setTitle] = useState("Peer implementation task");
  const [prompt, setPrompt] = useState("");
  const [maxRounds, setMaxRounds] = useState(12);
  const [allowTerminal, setAllowTerminal] = useState(false);
  const [allowDelete, setAllowDelete] = useState(false);
  const [tasks, setTasks] = useState<MultiAgentTask[]>([]);
  const [activeTask, setActiveTask] = useState<MultiAgentTask | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  async function loadTasks() {
    if (!project) {
      setTasks([]);
      setActiveTask(null);
      return;
    }
    const loaded = await api.multiAgentTasks(project.id);
    setTasks(loaded);
    if (activeTask) {
      const refreshed = loaded.find((item) => item.id === activeTask.id);
      if (refreshed) setActiveTask(refreshed);
    } else if (loaded[0]) {
      setActiveTask(loaded[0]);
    }
  }

  useEffect(() => {
    void loadTasks();
  }, [project?.id]);

  useEffect(() => {
    setSelected((current) =>
      current.filter((id) => agents.some((agent) => agent.id === id)),
    );
  }, [agents]);

  const canLaunch =
    Boolean(project) &&
    selected.length >= 2 &&
    title.trim().length > 0 &&
    prompt.trim().length > 0 &&
    !busy;

  const finals = useMemo(() => {
    const latest = new Map<string, MultiAgentTask["messages"][number]>();
    for (const message of activeTask?.messages || []) {
      if (message.kind === "final" && message.agent_id) {
        latest.set(message.agent_id, message);
      }
    }
    return Array.from(latest.values());
  }, [activeTask]);

  function toggleAgent(agentId: string) {
    setSelected((current) =>
      current.includes(agentId)
        ? current.filter((id) => id !== agentId)
        : [...current, agentId],
    );
  }

  async function launch(event: FormEvent) {
    event.preventDefault();
    if (!project || !canLaunch) return;
    setBusy(true);
    setStatus("Creating peer task...");
    try {
      const created = await api.createMultiAgentTask({
        project_id: project.id,
        title: title.trim(),
        prompt: prompt.trim(),
        agent_ids: selected,
        max_rounds: maxRounds,
      });
      setActiveTask(created);
      setStatus("Agents are collaborating...");
      const result = await api.runMultiAgentTask(
        created.id,
        allowTerminal,
        allowDelete,
      );
      setActiveTask(result);
      setStatus("Task finished with status: " + result.status);
      await loadTasks();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function resume(extendRounds = 0) {
    if (!activeTask) return;
    setBusy(true);
    setStatus(
      extendRounds > 0
        ? "Extending collaboration..."
        : "Resuming peer task...",
    );
    try {
      const result = await api.runMultiAgentTask(
        activeTask.id,
        allowTerminal,
        allowDelete,
        extendRounds,
      );
      setActiveTask(result);
      setStatus("Task status: " + result.status);
      await loadTasks();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  if (!project) {
    return (
      <section className="panel multiEmpty">
        <Users />
        <h3>Create a project first</h3>
        <p className="muted">Multi-agent tasks are scoped to one project sandbox.</p>
      </section>
    );
  }

  return (
    <section className="multiPage">
      <div className="sectionHeading">
        <div>
          <h2>Multi-Agent Workspace</h2>
          <p>
            Select peer agents. They keep discussing and reviewing the shared
            work until every healthy peer confirms completion across two stable
            rounds. Agent Man only schedules turns, shares context, persists
            messages, and enforces permissions.
          </p>
        </div>
        <span className="connectionCount">{tasks.length} tasks</span>
      </div>

      <div className="multiLayout">
        <div className="panel multiComposer">
          <h3>New peer task</h3>
          <form onSubmit={launch}>
            <label>
              Task title
              <input value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>

            <label>
              Shared objective
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Example: inspect this codebase, agree on the implementation gaps, make the required changes, and review the result."
              />
            </label>

            <div className="roundField">
              <label>
                Safety ceiling
                <input
                  type="number"
                  min={2}
                  max={30}
                  value={maxRounds}
                  onChange={(event) => setMaxRounds(Number(event.target.value))}
                />
              </label>
            </div>

            <div className="peerPicker">
              <span>Select at least two agents</span>
              {agents.map((agent) => (
                <label className="peerOption" key={agent.id}>
                  <input
                    type="checkbox"
                    checked={selected.includes(agent.id)}
                    onChange={() => toggleAgent(agent.id)}
                  />
                  <BrainCircuit size={16} />
                  <span>
                    <b>{agent.name}</b>
                    <small>{agent.role} · {agent.llm.model}</small>
                  </span>
                </label>
              ))}
            </div>

            <div className="runApprovals">
              <label className="approval">
                <input
                  type="checkbox"
                  checked={allowTerminal}
                  onChange={(event) => setAllowTerminal(event.target.checked)}
                />
                <TerminalSquare size={16} />
                Allow execute tools for this run
              </label>
              <label className="approval">
                <input
                  type="checkbox"
                  checked={allowDelete}
                  onChange={(event) => setAllowDelete(event.target.checked)}
                />
                <TerminalSquare size={16} />
                Allow destructive file deletion
              </label>
            </div>

            <button className="primaryButton" disabled={!canLaunch}>
              <Play size={16} />
              {busy ? "Running..." : "Launch peer task"}
            </button>
          </form>
          {status && <div className="connectionStatus">{status}</div>}
        </div>

        <div className="multiResults">
          <div className="panel taskHistory">
            <div className="historyHeader">
              <h3>Task history</h3>
              <button className="iconButton" onClick={() => void loadTasks()}>
                <RefreshCw size={15} />
              </button>
            </div>
            {tasks.length === 0 && <p className="muted">No multi-agent tasks yet.</p>}
            {tasks.map((task) => (
              <button
                key={task.id}
                className={
                  "taskHistoryRow " + (activeTask?.id === task.id ? "selectedTask" : "")
                }
                onClick={() => setActiveTask(task)}
              >
                <span>
                  <b>{task.title}</b>
                  <small>
                    round {task.current_round}/{task.max_rounds} safety ceiling · {task.participants.length} peers
                  </small>
                </span>
                <em>{task.status}</em>
              </button>
            ))}
          </div>

          {activeTask && (
            <div className="panel multiDiscussion">
              <div className="discussionHeader">
                <div>
                  <h3>{activeTask.title}</h3>
                  <p className="muted">{activeTask.prompt}</p>
                </div>
                <span className="taskStatus">{activeTask.status}</span>
              </div>

              <div className="participantStrip">
                {activeTask.participants.map((participant) => (
                  <div className="participantChip" key={participant.agent_id}>
                    <BrainCircuit size={14} />
                    <span>
                      <b>{participant.agent_name}</b>
                      <small>{participant.role} · {participant.status}</small>
                    </span>
                  </div>
                ))}
              </div>

              <div className="discussionThread">
                {activeTask.messages.length === 0 && (
                  <p className="muted">No discussion messages yet.</p>
                )}
                {activeTask.messages.map((message) => (
                  <article className={"peerMessage " + message.kind} key={message.id}>
                    <header>
                      <b>{message.agent_name}</b>
                      <span>
                        round {message.round_number} · {message.kind}
                      </span>
                    </header>
                    <p>{message.content}</p>
                  </article>
                ))}
              </div>

              {finals.length > 0 && (
                <div className="finalContributions">
                  <h4>Final peer contributions</h4>
                  {finals.map((message) => (
                    <div className="finalCard" key={message.id}>
                      <b>{message.agent_name}</b>
                      <p>{message.content}</p>
                    </div>
                  ))}
                </div>
              )}

              {activeTask.status === "waiting_approval" && (
                <button
                  className="primaryButton"
                  disabled={busy}
                  onClick={() => void resume()}
                >
                  <Play size={16} />
                  Resume with current approvals
                </button>
              )}

              {activeTask.status === "round_limit" && (
                <button
                  className="primaryButton"
                  disabled={busy}
                  onClick={() => void resume(5)}
                >
                  <Play size={16} />
                  Continue collaboration +5 rounds
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
