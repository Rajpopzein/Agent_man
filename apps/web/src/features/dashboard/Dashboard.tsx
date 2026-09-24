import { FormEvent, useEffect, useState } from "react";
import { BrainCircuit, Home, Plus, TerminalSquare } from "lucide-react";

import { api, Agent, AgentRun, Project } from "../../services/api";

export default function Dashboard() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agent, setAgent] = useState<Agent | null>(null);
  const [prompt, setPrompt] = useState("");
  const [run, setRun] = useState<AgentRun | null>(null);
  const [online, setOnline] = useState(false);
  const [allowTerminal, setAllowTerminal] = useState(false);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      await api.health();
      setOnline(true);
      const loadedProjects = await api.projects();
      setProjects(loadedProjects);
      const currentProject = loadedProjects[0] || null;
      setProject(currentProject);

      if (currentProject) {
        const loadedAgents = await api.agents(currentProject.id);
        setAgents(loadedAgents);
        setAgent(loadedAgents[0] || null);
      } else {
        setAgents([]);
        setAgent(null);
      }
    } catch {
      setOnline(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function addProject() {
    const name = window.prompt("Project name", "Agent Man Dev");
    const workspace =
      name &&
      window.prompt("Windows workspace path", "D:\\AgentMan\\projects\\demo");

    if (name && workspace) {
      await api.createProject({ name, workspace_path: workspace });
      await load();
    }
  }

  async function addAgent() {
    if (!project) return;

    const name = window.prompt("Agent name", "Developer");
    const role = name && window.prompt("Role", "Developer");
    const model = role && window.prompt("Model", "qwen2.5-coder");
    const endpoint =
      model &&
      window.prompt("LM Studio endpoint", "http://localhost:1234/v1");

    if (name && role && model && endpoint) {
      await api.createAgent({
        project_id: project.id,
        name,
        role,
        llm: {
          provider_id: "lmstudio",
          connection_id: "local",
          model,
          endpoint,
          temperature: 0.2,
          cloud_fallback_allowed: false,
        },
      });
      await load();
    }
  }

  async function execute(event: FormEvent) {
    event.preventDefault();
    if (!agent || !prompt.trim()) return;

    setBusy(true);
    setRun(null);
    try {
      const result = await api.runAgent(
        agent.id,
        prompt,
        allowTerminal,
        agent.llm.endpoint,
      );
      setRun(result);
    } catch (error) {
      setRun({
        agent_id: agent.id,
        status: "error",
        text: error instanceof Error ? error.message : String(error),
        steps: [],
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <aside>
        <div className="brand">
          <BrainCircuit />
          <span>
            AGENT MAN
            <small>BUILD · AUTOMATE · EVOLVE</small>
          </span>
        </div>

        <nav>
          <button className="active">
            <Home /> Dashboard
          </button>
        </nav>

        <div className="sideActions">
          <button onClick={addProject}>
            <Plus /> New Project
          </button>
          <button disabled={!project} onClick={addAgent}>
            <Plus /> New Agent
          </button>
        </div>
      </aside>

      <main>
        <header>
          <div>
            <h2>{project?.name || "Agent Man V1+"}</h2>
            <small>{project?.workspace_path || "Create a project to begin"}</small>
          </div>
          <div className={online ? "healthy" : "offline"}>
            ● {online ? "Runtime Online" : "Runtime Offline"}
          </div>
        </header>

        <section className="metrics">
          <Card label="Projects" value={projects.length} />
          <Card label="Agents" value={agents.length} />
          <Card label="Selected" value={agent?.name || "—"} />
        </section>

        <section className="v1grid">
          <div className="panel">
            <h3>Agents</h3>
            {agents.length === 0 && (
              <p className="muted">Create an agent to start working.</p>
            )}
            {agents.map((item) => (
              <button
                key={item.id}
                className={
                  "agentRow " + (agent?.id === item.id ? "selected" : "")
                }
                onClick={() => setAgent(item)}
              >
                <BrainCircuit />
                <span>
                  <b>{item.name}</b>
                  <small>
                    {item.role} · {item.llm.model}
                  </small>
                </span>
                <em>{item.state}</em>
              </button>
            ))}
          </div>

          <div className="panel">
            <h3>{agent ? "Run " + agent.name : "Agent Runner"}</h3>
            <p className="muted">
              File reads/writes are restricted to the project workspace.
              Terminal execution requires explicit approval for each run.
            </p>

            <form onSubmit={execute}>
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Example: inspect this project and create a README describing it"
              />
              <button disabled={!agent || !prompt.trim() || busy}>
                {busy ? "Running..." : "Run"}
              </button>
            </form>

            <label className="approval">
              <input
                type="checkbox"
                checked={allowTerminal}
                onChange={(event) => setAllowTerminal(event.target.checked)}
              />
              <TerminalSquare size={16} />
              Allow terminal commands for this run
            </label>

            <div className="conversation">
              {run?.text ||
                "The agent can now inspect and modify files inside this project's sandbox."}
            </div>

            {run && (
              <div className="trace">
                <h4>Execution trace · {run.status}</h4>
                {run.steps.length === 0 && (
                  <p className="muted">No tool calls were made.</p>
                )}
                {run.steps.map((step, index) => (
                  <div className="traceRow" key={index}>
                    <b>{String(step.tool || "tool")}</b>
                    <span>{String(step.status || "")}</span>
                    <code>
                      {JSON.stringify(step.arguments || {}, null, 2)}
                    </code>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

function Card({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="card">
      <span>
        {label}
        <b>{value}</b>
      </span>
    </div>
  );
}
