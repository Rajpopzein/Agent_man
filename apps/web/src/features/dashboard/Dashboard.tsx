import { FormEvent, useEffect, useState } from "react";
import {
  BrainCircuit,
  Home,
  Plug,
  Plus,
  TerminalSquare,
} from "lucide-react";

import AIConnections from "../settings/AIConnections";
import {
  api,
  Agent,
  AgentRun,
  AIConnection,
  Project,
} from "../../services/api";

type View = "dashboard" | "connections";

export default function Dashboard() {
  const [view, setView] = useState<View>("dashboard");
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [connections, setConnections] = useState<AIConnection[]>([]);
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
      const loaded = await Promise.all([
        api.projects(),
        api.aiConnections(),
      ]);
      const loadedProjects = loaded[0];
      const loadedConnections = loaded[1];
      setProjects(loadedProjects);
      setConnections(loadedConnections);

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

  async function reloadConnections() {
    setConnections(await api.aiConnections());
  }

  useEffect(() => {
    void load();
  }, []);

  async function addProject() {
    const name = window.prompt("Project name", "Agent Man Dev");
    const workspace =
      name &&
      window.prompt(
        "Windows workspace path",
        "D:\\AgentMan\\projects\\demo",
      );

    if (name && workspace) {
      await api.createProject({
        name,
        workspace_path: workspace,
      });
      await load();
    }
  }

  async function addAgent() {
    if (!project) return;

    if (connections.length === 0) {
      setView("connections");
      window.alert("Create an AI connection before creating an agent.");
      return;
    }

    const menu = connections
      .map(
        (connection, index) =>
          String(index + 1) +
          ". " +
          connection.name +
          " (" +
          connection.provider_id +
          ")",
      )
      .join("\n");

    const selected = window.prompt(
      "Choose AI connection by number:\n" + menu,
      "1",
    );
    if (!selected) return;

    const connection = connections[Number(selected) - 1];
    if (!connection) {
      window.alert("Invalid connection selection.");
      return;
    }

    const name = window.prompt("Agent name", "Developer");
    const role = name && window.prompt("Role", "Developer");
    const model =
      role &&
      window.prompt(
        "Model",
        connection.default_model || "",
      );

    if (name && role && model) {
      await api.createAgent({
        project_id: project.id,
        name,
        role,
        llm: {
          provider_id: connection.provider_id,
          connection_id: connection.id,
          model,
          endpoint: connection.endpoint,
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
          <button
            className={view === "dashboard" ? "active" : ""}
            onClick={() => setView("dashboard")}
          >
            <Home /> Dashboard
          </button>
          <button
            className={view === "connections" ? "active" : ""}
            onClick={() => setView("connections")}
          >
            <Plug /> AI Connections
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
            <h2>
              {view === "dashboard"
                ? project?.name || "Agent Man"
                : "Provider Configuration"}
            </h2>
            <small>
              {view === "dashboard"
                ? project?.workspace_path || "Create a project to begin"
                : "Connections are reusable across agents."}
            </small>
          </div>
          <div className={online ? "healthy" : "offline"}>
            ● {online ? "Runtime Online" : "Runtime Offline"}
          </div>
        </header>

        {view === "connections" ? (
          <AIConnections
            connections={connections}
            onChanged={reloadConnections}
          />
        ) : (
          <>
            <section className="metrics">
              <Card label="Projects" value={projects.length} />
              <Card label="Agents" value={agents.length} />
              <Card label="AI Connections" value={connections.length} />
              <Card label="Selected" value={agent?.name || "—"} />
            </section>

            <section className="v1grid">
              <div className="panel">
                <h3>Agents</h3>
                {agents.length === 0 && (
                  <p className="muted">
                    Create an AI connection, then create an agent.
                  </p>
                )}
                {agents.map((item) => {
                  const linked = connections.find(
                    (connection) =>
                      connection.id === item.llm.connection_id,
                  );
                  return (
                    <button
                      key={item.id}
                      className={
                        "agentRow " +
                        (agent?.id === item.id ? "selected" : "")
                      }
                      onClick={() => setAgent(item)}
                    >
                      <BrainCircuit />
                      <span>
                        <b>{item.name}</b>
                        <small>
                          {item.role} ·{" "}
                          {linked?.name || item.llm.provider_id} ·{" "}
                          {item.llm.model}
                        </small>
                      </span>
                      <em>{item.state}</em>
                    </button>
                  );
                })}
              </div>

              <div className="panel">
                <h3>{agent ? "Run " + agent.name : "Agent Runner"}</h3>
                <p className="muted">
                  The selected agent uses its linked AI connection.
                  Credentials never enter the task prompt.
                </p>

                <form onSubmit={execute}>
                  <textarea
                    value={prompt}
                    onChange={(event) =>
                      setPrompt(event.target.value)
                    }
                    placeholder="Example: inspect this project and create a README describing it"
                  />
                  <button
                    disabled={!agent || !prompt.trim() || busy}
                  >
                    {busy ? "Running..." : "Run"}
                  </button>
                </form>

                <label className="approval">
                  <input
                    type="checkbox"
                    checked={allowTerminal}
                    onChange={(event) =>
                      setAllowTerminal(event.target.checked)
                    }
                  />
                  <TerminalSquare size={16} />
                  Allow terminal commands for this run
                </label>

                <div className="conversation">
                  {run?.text ||
                    "The agent can inspect and modify files inside this project's sandbox."}
                </div>

                {run && (
                  <div className="trace">
                    <h4>Execution trace · {run.status}</h4>
                    {run.steps.length === 0 && (
                      <p className="muted">
                        No tool calls were made.
                      </p>
                    )}
                    {run.steps.map((step, index) => (
                      <div className="traceRow" key={index}>
                        <b>{String(step.tool || "tool")}</b>
                        <span>{String(step.status || "")}</span>
                        <code>
                          {JSON.stringify(
                            step.arguments || {},
                            null,
                            2,
                          )}
                        </code>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>
          </>
        )}
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
