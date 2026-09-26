import {
  FormEvent,
  ReactNode,
  useEffect,
  useMemo,
  useState,
} from "react";
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
  FileText,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  Trash2,
  Volume2,
  VolumeX,
  Wrench,
  Zap,
} from "lucide-react";

import HudModal from "../../components/HudModal";
import MultiAgentWorkspace from "../agents/MultiAgentWorkspace";
import OrchestrationPage from "../agents/OrchestrationPage";
import VoiceControl from "../audio/VoiceControl";
import { useAgentVoice } from "../audio/useAgentVoice";
import { useWakeWord } from "../audio/useWakeWord";
import AIConnections from "../settings/AIConnections";
import LLMLogsPage from "../settings/LLMLogsPage";
import SettingsPage from "../settings/SettingsPage";
import ToolsPage from "../tools/ToolsPage";
import {
  api,
  Agent,
  AIConnection,
  MainAgentConfig,
  MainAgentReply,
  Project,
  Tool,
} from "../../services/api";

type View =
  | "dashboard"
  | "orchestration"
  | "multi-agent"
  | "tools"
  | "connections"
  | "logs"
  | "settings";

type Notice = {
  title: string;
  message: string;
  tone?: "default" | "danger";
};

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
  logs: {
    label: "LLM Logs",
    eyebrow: "SYSTEM / MODEL ACTIVITY",
    description: "Inspect model requests, responses, latency, and failures.",
  },
  settings: {
    label: "Settings",
    eyebrow: "SYSTEM / CONFIGURATION",
    description: "Configure Agent Man executive behavior and runtime preferences.",
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
  const [run, setRun] = useState<MainAgentReply | null>(null);
  const [mainConfig, setMainConfig] = useState<MainAgentConfig | null>(null);
  const [online, setOnline] = useState(false);
  const [allowTerminal, setAllowTerminal] = useState(false);
  const [allowDelete, setAllowDelete] = useState(false);
  const [allowNetwork, setAllowNetwork] = useState(false);
  const [busy, setBusy] = useState(false);

  const [projectDialog, setProjectDialog] = useState(false);
  const [projectName, setProjectName] = useState("Agent Man Dev");
  const [workspacePath, setWorkspacePath] = useState(
    "D:\\AgentMan\\projects\\demo",
  );

  const [agentDialog, setAgentDialog] = useState(false);
  const [agentName, setAgentName] = useState("Developer");
  const [agentRole, setAgentRole] = useState("Developer");
  const [agentConnectionId, setAgentConnectionId] = useState("");
  const [agentModel, setAgentModel] = useState("");
  const [agentDetectedModels, setAgentDetectedModels] = useState<string[]>([]);
  const [detectingAgentModels, setDetectingAgentModels] = useState(false);

  const [deleteDialog, setDeleteDialog] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [voiceOpen, setVoiceOpen] = useState(false);

  const voice = useAgentVoice();
  const wake = useWakeWord({
    enabled: voice.settings.enabled && voice.settings.wakeEnabled,
    wakePhrase: voice.settings.wakePhrase,
    language: voice.settings.wakeLanguage,
    onWake: async () => {
      await voice.speakAsync("Listening.", true);
    },
    onCommand: (command) => {
      void runDirective(command);
    },
  });

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
        const [loadedAgents, executiveConfig] = await Promise.all([
          api.agents(currentProject.id),
          api.mainAgentConfig(currentProject.id),
        ]);
        setMainConfig(executiveConfig);
        setAgents(loadedAgents);
        setAgent((current) =>
          loadedAgents.find((item) => item.id === current?.id) ||
          loadedAgents[0] ||
          null,
        );
      } else {
        setAgents([]);
        setAgent(null);
        setMainConfig(null);
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

  useEffect(() => {
    if (
      run?.status === "completed" &&
      run.text &&
      voice.settings.enabled &&
      voice.settings.autoSpeak
    ) {
      voice.speak(run.text);
    }
  }, [run?.status, run?.text]);

  function openProjectDialog() {
    setProjectName("Agent Man Dev");
    setWorkspacePath("D:\\AgentMan\\projects\\demo");
    setProjectDialog(true);
  }

  async function createProject(event: FormEvent) {
    event.preventDefault();
    if (!projectName.trim() || !workspacePath.trim()) return;

    setBusy(true);
    try {
      await api.createProject({
        name: projectName.trim(),
        workspace_path: workspacePath.trim(),
      });
      setProjectDialog(false);
      await load();
    } catch (error) {
      setNotice({
        title: "Project creation failed",
        message: error instanceof Error ? error.message : String(error),
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  function openAgentDialog() {
    if (!project) return;

    if (connections.length === 0) {
      setView("connections");
      setNotice({
        title: "AI uplink required",
        message:
          "Create at least one AI connection before deploying an agent.",
      });
      return;
    }

    const connection = connections[0];
    setAgentName("Developer");
    setAgentRole("Developer");
    setAgentConnectionId(connection.id);
    setAgentModel(connection.default_model || "");
    setAgentDetectedModels([]);
    setAgentDialog(true);
  }

  function chooseAgentConnection(connectionId: string) {
    const connection = connections.find((item) => item.id === connectionId);
    setAgentConnectionId(connectionId);
    setAgentDetectedModels([]);
    setAgentModel(connection?.default_model || "");
  }

  async function detectAgentModels() {
    if (!agentConnectionId) return;
    setDetectingAgentModels(true);
    try {
      const result = await api.connectionModels(agentConnectionId);
      setAgentDetectedModels(result.models);
      if (result.models.length > 0 && !result.models.includes(agentModel)) {
        const connection = connections.find(
          (item) => item.id === agentConnectionId,
        );
        const preferred =
          connection?.default_model &&
          result.models.includes(connection.default_model)
            ? connection.default_model
            : result.models[0];
        setAgentModel(preferred);
      }
      if (result.models.length === 0) {
        setNotice({
          title: "No models detected",
          message:
            "The selected AI connection responded but did not return any discoverable models. You can still enter the model identifier manually.",
        });
      }
    } catch (error) {
      setAgentDetectedModels([]);
      setNotice({
        title: "Model detection failed",
        message: error instanceof Error ? error.message : String(error),
        tone: "danger",
      });
    } finally {
      setDetectingAgentModels(false);
    }
  }

  async function createAgent(event: FormEvent) {
    event.preventDefault();
    if (!project) return;

    const connection = connections.find(
      (item) => item.id === agentConnectionId,
    );
    if (!connection) {
      setNotice({
        title: "Invalid AI uplink",
        message: "Select a valid AI connection for this agent.",
        tone: "danger",
      });
      return;
    }

    if (!agentName.trim() || !agentRole.trim() || !agentModel.trim()) {
      setNotice({
        title: "Agent configuration incomplete",
        message: "Name, role, connection and model are required.",
      });
      return;
    }

    setBusy(true);
    try {
      await api.createAgent({
        project_id: project.id,
        name: agentName.trim(),
        role: agentRole.trim(),
        llm: {
          provider_id: connection.provider_id,
          connection_id: connection.id,
          model: agentModel.trim(),
          endpoint: connection.endpoint,
          temperature: 0.2,
          cloud_fallback_allowed: false,
        },
      });
      setAgentDialog(false);
      await load();
    } catch (error) {
      setNotice({
        title: "Agent deployment failed",
        message: error instanceof Error ? error.message : String(error),
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  async function runDirective(directive: string) {
    const command = directive.trim();
    if (!command || !project) return;

    if (!mainConfig) {
      setView("settings");
      setPrompt(command);
      setNotice({
        title: "Executive model required",
        message:
          "Configure Agent Man under Settings. Model discovery is available there for the selected AI connection.",
      });
      await voice.speakAsync(
        "Configure my executive model in Settings first.",
        true,
      );
      return;
    }

    if (busy) {
      await voice.speakAsync(
        "A mission is already running. I will be ready when it completes.",
        true,
      );
      return;
    }

    setView("dashboard");
    setPrompt(command);
    voice.stop();
    setBusy(true);
    setRun(null);

    try {
      const result = await api.chatMainAgent(
        project.id,
        command,
        allowTerminal,
        allowDelete,
        allowNetwork,
      );
      setRun(result);
    } catch (error) {
      setRun({
        status: "error",
        text: error instanceof Error ? error.message : String(error),
        steps: [],
      });
    } finally {
      setBusy(false);
    }
  }

  async function execute(event: FormEvent) {
    event.preventDefault();
    await runDirective(prompt);
  }

  async function confirmDeleteAgent() {
    if (!agent) return;

    setBusy(true);
    try {
      await api.deleteAgent(agent.id);
      setDeleteDialog(false);
      setAgent(null);
      setRun(null);
      await load();
      setNotice({
        title: "Agent removed",
        message: "The selected agent was deleted from this project.",
      });
    } catch (error) {
      setDeleteDialog(false);
      setNotice({
        title: "Agent deletion blocked",
        message: error instanceof Error ? error.message : String(error),
        tone: "danger",
      });
    } finally {
      setBusy(false);
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
          <RailButton
            active={view === "logs"}
            label="Logs"
            icon={<FileText />}
            onClick={() => setView("logs")}
          />
          <RailButton
            active={view === "settings"}
            label="Settings"
            icon={<Settings2 />}
            onClick={() => setView("settings")}
          />
        </nav>

        <div className="railFooter">
          <button
            className="railQuick"
            onClick={openProjectDialog}
            title="New project"
          >
            <Plus />
          </button>
          <button
            className="railQuick"
            onClick={openAgentDialog}
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

          <div className="topControls">
            <button
              className={
                voice.settings.enabled
                  ? "voiceCoreButton active"
                  : "voiceCoreButton"
              }
              onClick={() => setVoiceOpen(true)}
              title="Voice Core"
            >
              {voice.settings.enabled ? (
                <Volume2 size={15} />
              ) : (
                <VolumeX size={15} />
              )}
              <span>
                {wake.state === "listening"
                  ? "LISTEN"
                  : voice.settings.wakeEnabled
                    ? "WAKE"
                    : "VOICE"}
              </span>
              <i
                className={
                  voice.speaking
                    ? "speaking"
                    : wake.state === "listening"
                      ? "listening"
                      : wake.state === "standby"
                        ? "armed"
                        : ""
                }
              />
            </button>

            <div
              className={
                online ? "runtimeBadge online" : "runtimeBadge offline"
              }
            >
              <Radio size={14} />
              <span>{online ? "RUNTIME ONLINE" : "RUNTIME OFFLINE"}</span>
              <b>{online ? "LIVE" : "DOWN"}</b>
            </div>
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
            <code>
              {project?.workspace_path ||
                "Create a project to initialize the workspace."}
            </code>
          </div>
        </div>

        {view === "connections" ? (
          <AIConnections
            connections={connections}
            onChanged={reloadConnections}
          />
        ) : view === "logs" ? (
          <LLMLogsPage project={project} />
        ) : view === "settings" ? (
          <SettingsPage
            project={project}
            connections={connections}
            mainConfig={mainConfig}
            onConfigured={setMainConfig}
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
                label="Workers"
                value={agents.length}
                detail={
                  agents.length ? "READY FOR DELEGATION" : "NONE CONFIGURED"
                }
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

                <div className="executiveAgentCard">
                  <div className="executiveAgentIdentity">
                    <span className="executiveCoreGlyph">
                      <Sparkles size={18} />
                    </span>
                    <div>
                      <small>PRIMARY / EXECUTIVE</small>
                      <strong>AGENT MAN</strong>
                      <span>
                        {mainConfig
                          ? "Executive core online"
                          : "Executive setup required"}
                      </span>
                    </div>
                  </div>

                  <div className="executiveManagedNote">
                    <Settings2 size={13} />
                    Executive configuration is managed in Settings
                  </div>
                </div>

                <div className="workerDivider">
                  <span>WORKER AGENTS</span>
                  <i />
                </div>

                <div className="agentMatrixList">
                  {agents.length === 0 && (
                    <div className="hudEmpty">
                      <Bot />
                      <strong>NO WORKERS ONLINE</strong>
                      <span>Create an AI connection and deploy a worker agent.</span>
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
                            {item.role} /{" "}
                            {linked?.name || item.llm.provider_id}
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
                    <span>
                      <Bot size={14} />
                    </span>
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
                  <span
                    className={busy ? "statusPulse busy" : "statusPulse"}
                  />
                  <div>
                    <small>CURRENT STATE</small>
                    <strong>
                      {busy
                        ? "EXECUTING"
                        : run?.status?.toUpperCase() || "READY"}
                    </strong>
                  </div>
                </div>

                <div className="missionReadout">
                  <span>PRIMARY AGENT</span>
                  <b>AGENT MAN</b>
                  <span>EXECUTIVE STATUS</span>
                  <b>{mainConfig ? "ONLINE" : "SETUP REQUIRED"}</b>
                  <span>INSPECTED WORKER</span>
                  <b>{agent?.name || "—"}</b>
                  <span>WORKER STATE</span>
                  <b>{agent?.state || "—"}</b>
                </div>

                <div className="permissionReadout">
                  <button
                    className={
                      allowTerminal
                        ? "permissionChip active"
                        : "permissionChip"
                    }
                    onClick={() =>
                      setAllowTerminal((value) => !value)
                    }
                  >
                    <TerminalSquare size={13} />
                    EXEC
                  </button>
                  <button
                    className={
                      allowNetwork
                        ? "permissionChip active"
                        : "permissionChip"
                    }
                    onClick={() =>
                      setAllowNetwork((value) => !value)
                    }
                    title="Allow public internet access for this run"
                  >
                    <Globe2 size={13} />
                    NET
                  </button>
                  <button
                    className={
                      allowDelete
                        ? "permissionChip danger active"
                        : "permissionChip danger"
                    }
                    onClick={() =>
                      setAllowDelete((value) => !value)
                    }
                  >
                    <Wrench size={13} />
                    FILE DEL
                  </button>
                  <button
                    className="permissionChip danger"
                    onClick={() => setDeleteDialog(true)}
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
                  <span className="hudEyebrow">
                    DIRECTIVE / AGENT MAN EXECUTIVE
                  </span>
                  <h3>
                    Talk to Agent Man
                  </h3>
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
                  placeholder="Tell Agent Man what you want accomplished..."
                />
                <button disabled={!project || !prompt.trim() || busy}>
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
                    (mainConfig
                      ? "Agent Man is standing by. Give me the objective; I will choose and coordinate the workers."
                      : "Configure Agent Man's executive model to begin.")}
                </div>
              </div>

              {run && run.steps.length > 0 && (
                <div className="trace hudTrace">
                  <h4>
                    EXECUTION TRACE / {run.status.toUpperCase()}
                  </h4>
                  {run.steps.map((step, index) => (
                    <div className="traceRow" key={index}>
                      <b>{String(step.tool || step.type || "runtime")}</b>
                      <span>{String(step.status || "")}</span>
                      <code>
                        {JSON.stringify(
                          step.arguments ||
                            step.result ||
                            step.message ||
                            {},
                          null,
                          2,
                        )}
                      </code>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </section>

      <HudModal
        open={projectDialog}
        onClose={() => setProjectDialog(false)}
        title="Initialize Project"
        eyebrow="COMMAND / NEW SANDBOX"
        footer={
          <>
            <button
              className="secondaryButton"
              onClick={() => setProjectDialog(false)}
            >
              Cancel
            </button>
            <button
              className="primaryButton"
              form="project-create-form"
              type="submit"
              disabled={busy}
            >
              <Plus size={14} />
              Create project
            </button>
          </>
        }
      >
        <form
          id="project-create-form"
          className="hudDialogForm"
          onSubmit={createProject}
        >
          <label>
            Project name
            <input
              value={projectName}
              onChange={(event) => setProjectName(event.target.value)}
              autoFocus
            />
          </label>
          <label>
            Windows workspace path
            <input
              value={workspacePath}
              onChange={(event) => setWorkspacePath(event.target.value)}
            />
          </label>
          <p className="dialogHint">
            This directory becomes the project sandbox boundary used by
            Agent Man tools.
          </p>
        </form>
      </HudModal>

      <HudModal
        open={agentDialog}
        onClose={() => setAgentDialog(false)}
        title="Deploy Agent"
        eyebrow="COMMAND / AGENT CONFIGURATION"
        footer={
          <>
            <button
              className="secondaryButton"
              onClick={() => setAgentDialog(false)}
            >
              Cancel
            </button>
            <button
              className="primaryButton"
              form="agent-create-form"
              type="submit"
              disabled={busy}
            >
              <Bot size={14} />
              Deploy agent
            </button>
          </>
        }
      >
        <form
          id="agent-create-form"
          className="hudDialogForm"
          onSubmit={createAgent}
        >
          <div className="dialogGrid">
            <label>
              Agent name
              <input
                value={agentName}
                onChange={(event) => setAgentName(event.target.value)}
                autoFocus
              />
            </label>
            <label>
              Role
              <input
                value={agentRole}
                onChange={(event) => setAgentRole(event.target.value)}
              />
            </label>
          </div>
          <label>
            AI connection
            <select
              value={agentConnectionId}
              onChange={(event) =>
                chooseAgentConnection(event.target.value)
              }
            >
              {connections.map((connection) => (
                <option value={connection.id} key={connection.id}>
                  {connection.name} · {connection.provider_id}
                </option>
              ))}
            </select>
          </label>
          <div className="dialogModelDetect">
            <button
              type="button"
              className="secondaryButton"
              onClick={() => void detectAgentModels()}
              disabled={!agentConnectionId || detectingAgentModels}
            >
              <Search size={14} />
              {detectingAgentModels ? "Detecting..." : "Detect Models"}
            </button>
            <span>Query the selected connection for its available models.</span>
          </div>

          {agentDetectedModels.length > 0 ? (
            <label>
              Model
              <select
                value={agentModel}
                onChange={(event) => setAgentModel(event.target.value)}
              >
                {agentDetectedModels.map((model) => (
                  <option value={model} key={model}>
                    {model}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label>
              Model
              <input
                value={agentModel}
                onChange={(event) => setAgentModel(event.target.value)}
                placeholder="Detect models or enter a model identifier"
              />
            </label>
          )}
          <p className="dialogHint">
            Tools and risk permissions can be changed later in Capability
            Matrix.
          </p>
        </form>
      </HudModal>

      <HudModal
        open={deleteDialog}
        onClose={() => setDeleteDialog(false)}
        title="Delete Agent"
        eyebrow="SECURITY / DESTRUCTIVE ACTION"
        tone="danger"
        footer={
          <>
            <button
              className="secondaryButton"
              onClick={() => setDeleteDialog(false)}
            >
              Keep agent
            </button>
            <button
              className="primaryButton dangerAction"
              onClick={() => void confirmDeleteAgent()}
              disabled={busy}
            >
              <Trash2 size={14} />
              Delete agent
            </button>
          </>
        }
      >
        <div className="dialogWarning">
          <ShieldAlert size={22} />
          <div>
            <strong>{agent?.name || "Selected agent"}</strong>
            <p>
              Agent Man will block deletion if this agent is still referenced
              by workflow stages, workflow history, or multi-agent history.
            </p>
          </div>
        </div>
      </HudModal>

      <HudModal
        open={Boolean(notice)}
        onClose={() => setNotice(null)}
        title={notice?.title || "System message"}
        eyebrow={
          notice?.tone === "danger"
            ? "SYSTEM / ATTENTION"
            : "SYSTEM / MESSAGE"
        }
        tone={notice?.tone}
        footer={
          <button
            className="primaryButton"
            onClick={() => setNotice(null)}
          >
            Acknowledge
          </button>
        }
      >
        <p className="systemMessage">{notice?.message}</p>
      </HudModal>

      <VoiceControl
        open={voiceOpen}
        onClose={() => setVoiceOpen(false)}
        settings={voice.settings}
        voices={voice.voices}
        selectedVoice={voice.selectedVoice}
        speaking={voice.speaking}
        wakeSupported={wake.supported}
        wakeState={wake.state}
        lastHeard={wake.lastHeard}
        onUpdate={voice.update}
        onTest={voice.testVoice}
        onStop={voice.stop}
        onReset={voice.resetSignature}
        onListenNow={() => void wake.listenNow()}
      />
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
