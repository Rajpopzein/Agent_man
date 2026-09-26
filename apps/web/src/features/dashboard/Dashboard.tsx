import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Bot,
  Boxes,
  CircleDot,
  GitBranch,
  Globe2,
  Home,
  Network,
  Plug,
  Plus,
  Radio,
  Search,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  Trash2,
  Wrench,
  Zap,
} from "lucide-react";

import MultiAgentWorkspace from "../agents/MultiAgentWorkspace";
import OrchestrationPage from "../agents/OrchestrationPage";
import AIConnections from "../settings/AIConnections";
import ToolsPage from "../tools/ToolsPage";
import {
  api,
  Agent,
  AgentRun,
  AIConnection,
  Project,
  Tool,
} from "../../services/api";

type View =
  | "dashboard"
  | "orchestration"
  | "multi-agent"
  | "tools"
  | "connections";

const VIEW_META: Record<
  View,
  { label: string; eyebrow: string; description: string }
> = {
  dashboard: {
    label: "Command Core",
    eyebrow: "SYSTEM / OVERVIEW",
    description: "Live agent command, execution and system awareness.",
  },
  orchestration: {
    label: "Orchestration Grid",
    eyebrow: "SYSTEM / WORKFLOWS",
    description: "Deterministic stage handoffs with success and failure routing.",
  },
  "multi-agent": {
    label: "Peer Intelligence",
    eyebrow: "SYSTEM / MULTI-AGENT",
    description: "Shared task context with independent peer reasoning.",
  },
  tools: {
    label: "Capability Matrix",
    eyebrow: "SYSTEM / TOOLS",
    description: "Control which runtime capabilities each agent can access.",
  },
  connections: {
    label: "AI Uplink",
    eyebrow: "SYSTEM / PROVIDERS",
    description: "Configure local and cloud model connections.",
  },
};

export default function Dashboard() {
  const [view, setView] = useState<View>("dashboard");
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [connections, setConnections] = useState<AIConnection[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [agent, setAgent] = useState<Agent | null>(null);
  const [prompt, setPrompt] = useState("");
  const [run, setRun] = useState<AgentRun | null>(null);
  const [online, setOnline] = useState(false);
  const [allowTerminal, setAllowTerminal] = useState(false);
  const [allowDelete, setAllowDelete] = useState(false);
  const [allowNetwork, setAllowNetwork] = useState(false);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      await api.health();
      setOnline(true);
      const [loadedProjects, loadedConnections, loadedTools] =
        await Promise.all([
          api.projects(),
          api.aiConnections(),
          api.tools(),
        ]);
      setProjects(loadedProjects);
      setConnections(loadedConnections);
      setTools(loadedTools);

      const currentProject = loadedProjects[0] || null;
      setProject(currentProject);

      if (currentProject) {
        const loadedAgents = await api.agents(currentProject.id);
        setAgents(loadedAgents);
        setAgent((current) =>
          loadedAgents.find((item) => item.id === current?.id) ||
          loadedAgents[0] ||
          null,
        );
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
          `${index + 1}. ${connection.name} (${connection.provider_id})`,
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
        undefined,
        allowDelete,
        allowNetwork,
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


  async function deleteSelectedAgent() {
    if (!agent) return;
    const confirmed = window.confirm(
      "Delete agent '" +
        agent.name +
        "'? This is blocked if the agent is still referenced by workflow or multi-agent history.",
    );
    if (!confirmed) return;

    try {
      await api.deleteAgent(agent.id);
      setAgent(null);
      setRun(null);
      await load();
    } catch (error) {
      window.alert(
        error instanceof Error
          ? error.message
          : String(error),
      );
    }
  }

  const activeTools = tools.filter((tool) => tool.enabled).length;
  const providerLabel = useMemo(() => {
    if (!agent) return "NO AGENT";
    return (
      connections.find(
        (connection) => connection.id === agent.llm.connection_id,
      )?.name || agent.llm.provider_id
    );
  }, [agent, connections]);

  const meta = VIEW_META[view];

  return (
    <div className="jarvisShell">
      <div className="ambientGrid" aria-hidden="true" />
      <div className="scanline" aria-hidden="true" />

      <aside className="commandRail">
        <button
          className="coreMark"
          onClick={() => setView("dashboard")}
          title="Agent Man"
        >
          <span className="coreMarkRing">
            <Sparkles size={18} />
          </span>
        </button>

        <nav className="railNav">
          <RailButton
            active={view === "dashboard"}
            label="Core"
            icon={<Home />}
            onClick={() => setView("dashboard")}
          />
          <RailButton
            active={view === "orchestration"}
            label="Flow"
            icon={<GitBranch />}
            onClick={() => setView("orchestration")}
          />
          <RailButton
            active={view === "multi-agent"}
            label="Peers"
            icon={<Network />}
            onClick={() => setView("multi-agent")}
          />
          <RailButton
            active={view === "tools"}
            label="Tools"
            icon={<Wrench />}
            onClick={() => setView("tools")}
          />
          <RailButton
            active={view === "connections"}
            label="Uplink"
            icon={<Plug />}
            onClick={() => setView("connections")}
          />
        </nav>

        <div className="railFooter">
          <button className="railQuick" onClick={addProject} title="New project">
            <Plus />
          </button>
          <button
            className="railQuick"
            onClick={addAgent}
            disabled={!project}
            title="New agent"
          >
            <Bot />
          </button>
        </div>
      </aside>

      <section className="hudWorkspace">
        <header className="hudTopbar">
          <div className="systemIdentity">
            <div className="identityPulse">
              <span />
            </div>
            <div>
              <small>AGENT MAN / WINDOWS INTELLIGENCE RUNTIME</small>
              <strong>{meta.label}</strong>
            </div>
          </div>

          <div className="topCommand">
            <Search size={15} />
            <span>{meta.eyebrow}</span>
            <i />
            <span>{project?.name || "NO PROJECT"}</span>
          </div>

          <div className={online ? "runtimeBadge online" : "runtimeBadge offline"}>
            <Radio size={14} />
            <span>{online ? "RUNTIME ONLINE" : "RUNTIME OFFLINE"}</span>
            <b>{online ? "LIVE" : "DOWN"}</b>
          </div>
        </header>

        <div className="hudTitleRow">
          <div>
            <span className="hudEyebrow">{meta.eyebrow}</span>
            <h1>{meta.label}</h1>
            <p>{meta.description}</p>
          </div>

          <div className="projectReadout">
            <small>ACTIVE SANDBOX</small>
            <strong>{project?.name || "UNASSIGNED"}</strong>
            <code>{project?.workspace_path || "Create a project to initialize the workspace."}</code>
          </div>
        </div>

        {view === "connections" ? (
          <AIConnections
            connections={connections}
            onChanged={reloadConnections}
          />
        ) : view === "orchestration" ? (
          <OrchestrationPage project={project} agents={agents} />
        ) : view === "multi-agent" ? (
          <MultiAgentWorkspace project={project} agents={agents} />
        ) : view === "tools" ? (
          <ToolsPage agents={agents} />
        ) : (
          <div className="commandDeck">
            <section className="telemetryStrip">
              <Telemetry
                icon={<Bot />}
                label="Agents"
                value={agents.length}
                detail={agents.length ? "READY FOR TASKING" : "NONE CONFIGURED"}
              />
              <Telemetry
                icon={<Plug />}
                label="AI Uplinks"
                value={connections.length}
                detail="MODEL CONNECTIONS"
              />
              <Telemetry
                icon={<Wrench />}
                label="Tools"
                value={activeTools}
                detail={`${tools.length} REGISTERED`}
              />
              <Telemetry
                icon={<ShieldCheck />}
                label="Sandbox"
                value={project ? "LOCKED" : "IDLE"}
                detail="PROJECT BOUNDARY"
              />
            </section>

            <section className="coreGrid">
              <div className="hudPanel agentMatrix">
                <PanelLabel icon={<Boxes />} label="AGENT MATRIX" />
                <div className="agentMatrixList">
                  {agents.length === 0 && (
                    <div className="hudEmpty">
                      <Bot />
                      <strong>NO AGENTS ONLINE</strong>
                      <span>Create an AI connection and deploy an agent.</span>
                    </div>
                  )}
                  {agents.map((item, index) => {
                    const linked = connections.find(
                      (connection) =>
                        connection.id === item.llm.connection_id,
                    );
                    return (
                      <button
                        key={item.id}
                        className={
                          "matrixAgent " +
                          (agent?.id === item.id ? "active" : "")
                        }
                        onClick={() => setAgent(item)}
                      >
                        <span className="agentIndex">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <span className="agentSignal">
                          <i />
                        </span>
                        <span className="agentMeta">
                          <b>{item.name}</b>
                          <small>
                            {item.role} / {linked?.name || item.llm.provider_id}
                          </small>
                        </span>
                        <span className="agentModel">{item.llm.model}</span>
                        <em>{item.state}</em>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="intelligenceCore">
                <div className="coreBackdrop" />
                <div className="orbit orbitOne">
                  <span />
                  <span />
                  <span />
                </div>
                <div className="orbit orbitTwo">
                  <span />
                  <span />
                </div>
                <div className="orbit orbitThree" />
                <div className="coreHalo">
                  <div className="coreSphere">
                    <Zap size={34} />
                    <span>AGENT</span>
                    <b>MAN</b>
                    <small>{online ? "CORE ACTIVE" : "CORE STANDBY"}</small>
                  </div>
                </div>

                {agents.slice(0, 6).map((item, index) => (
                  <button
                    key={item.id}
                    className={`orbitalAgent orbitalAgent${index + 1} ${
                      agent?.id === item.id ? "selected" : ""
                    }`}
                    onClick={() => setAgent(item)}
                    title={item.name}
                  >
                    <span><Bot size={14} /></span>
                    <b>{item.name}</b>
                    <small>{item.role}</small>
                  </button>
                ))}

                <div className="coreCaption">
                  <CircleDot size={13} />
                  <span>
                    {agent
                      ? `${agent.name.toUpperCase()} / ${providerLabel}`
                      : "SELECT AN AGENT"}
                  </span>
                </div>
              </div>

              <div className="hudPanel missionPanel">
                <PanelLabel icon={<Activity />} label="MISSION CONTROL" />
                <div className="missionStatus">
                  <span className={busy ? "statusPulse busy" : "statusPulse"} />
                  <div>
                    <small>CURRENT STATE</small>
                    <strong>{busy ? "EXECUTING" : run?.status?.toUpperCase() || "READY"}</strong>
                  </div>
                </div>

                <div className="missionReadout">
                  <span>SELECTED AGENT</span>
                  <b>{agent?.name || "—"}</b>
                  <span>ROLE</span>
                  <b>{agent?.role || "—"}</b>
                  <span>MODEL</span>
                  <b>{agent?.llm.model || "—"}</b>
                  <span>UPLINK</span>
                  <b>{providerLabel}</b>
                </div>

                <div className="permissionReadout">
                  <button
                    className={allowTerminal ? "permissionChip active" : "permissionChip"}
                    onClick={() => setAllowTerminal((value) => !value)}
                  >
                    <TerminalSquare size={13} />
                    EXEC
                  </button>
                  <button
                    className={allowNetwork ? "permissionChip active" : "permissionChip"}
                    onClick={() => setAllowNetwork((value) => !value)}
                    title="Allow public internet access for this run"
                  >
                    <Globe2 size={13} />
                    NET
                  </button>
                  <button
                    className={allowDelete ? "permissionChip danger active" : "permissionChip danger"}
                    onClick={() => setAllowDelete((value) => !value)}
                  >
                    <Wrench size={13} />
                    FILE DEL
                  </button>
                  <button
                    className="permissionChip danger"
                    onClick={() => void deleteSelectedAgent()}
                    disabled={!agent || busy}
                    title="Delete selected agent"
                  >
                    <Trash2 size={13} />
                    AGENT DEL
                  </button>
                </div>
              </div>
            </section>

            <section className="hudCommandPanel">
              <div className="commandHeader">
                <div>
                  <span className="hudEyebrow">DIRECTIVE / SINGLE AGENT</span>
                  <h3>{agent ? `Task ${agent.name}` : "Awaiting agent selection"}</h3>
                </div>
                <div className="commandStatus">
                  <i className={busy ? "busy" : ""} />
                  {busy ? "PROCESSING" : "AWAITING DIRECTIVE"}
                </div>
              </div>

              <form className="commandComposer" onSubmit={execute}>
                <span className="commandPrompt">&gt;</span>
                <textarea
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder="Issue a directive to the selected agent..."
                />
                <button disabled={!agent || !prompt.trim() || busy}>
                  <Zap size={16} />
                  {busy ? "EXECUTING" : "EXECUTE"}
                </button>
              </form>

              <div className="commandOutput">
                <div className="outputRail">
                  <span />
                  <small>OUTPUT</small>
                </div>
                <div className="outputBody">
                  {run?.text ||
                    "Agent Man is standing by. Select an agent and issue a directive."}
                </div>
              </div>

              {run && run.steps.length > 0 && (
                <div className="trace hudTrace">
                  <h4>EXECUTION TRACE / {run.status.toUpperCase()}</h4>
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
            </section>
          </div>
        )}
      </section>
    </div>
  );
}

function RailButton({
  active,
  label,
  icon,
  onClick,
}: {
  active: boolean;
  label: string;
  icon: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      className={active ? "railButton active" : "railButton"}
      onClick={onClick}
      title={label}
    >
      <span>{icon}</span>
      <small>{label}</small>
    </button>
  );
}

function Telemetry({
  icon,
  label,
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: string | number;
  detail: string;
}) {
  return (
    <article className="telemetryCell">
      <div className="telemetryIcon">{icon}</div>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
        <span>{detail}</span>
      </div>
      <i />
    </article>
  );
}

function PanelLabel({
  icon,
  label,
}: {
  icon: ReactNode;
  label: string;
}) {
  return (
    <div className="panelLabel">
      <span>{icon}</span>
      <b>{label}</b>
      <i />
    </div>
  );
}
