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
  BrainCircuit,
  Clock3,
  Cpu,
  GitBranch,
  Globe2,
  Home,
  Mic,
  Network,
  Plug,
  Plus,
  Radio,
  Search,
  Server,
  FileText,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Volume2,
  VolumeX,
  WandSparkles,
  Wrench,
  Zap,
} from "lucide-react";

import HudModal from "../../components/HudModal";
import CommandConsole, {
  CommandConsoleLine,
} from "./CommandConsole";
import MultiAgentWorkspace from "../agents/MultiAgentWorkspace";
import BackgroundPage from "../agents/BackgroundPage";
import ExtensionsPage from "../extensions/ExtensionsPage";
import OrchestrationPage from "../agents/OrchestrationPage";
import VoiceControl from "../audio/VoiceControl";
import {
  requestAgentSpeech,
  useAgentVoice,
} from "../audio/useAgentVoice";
import { useWakeWord } from "../audio/useWakeWord";
import AIConnections from "../settings/AIConnections";
import LLMLogsPage from "../settings/LLMLogsPage";
import SettingsPage from "../settings/SettingsPage";
import ToolsPage from "../tools/ToolsPage";
import {
  api,
  Agent,
  AIConnection,
  BackgroundJob,
  EffectiveToolAccess,
  LLMLog,
  MainAgentConfig,
  MainAgentReply,
  Project,
  ReinforcementSummary,
  RuntimeEvent,
  Tool,
} from "../../services/api";

type View =
  | "background"
  | "dashboard"
  | "orchestration"
  | "multi-agent"
  | "tools"
  | "connections"
  | "extensions"
  | "logs"
  | "settings";

type Notice = {
  title: string;
  message: string;
  tone?: "default" | "danger";
  approvalJobId?: string;
  approvalPermission?: string;
};

type LiveResponse = {
  id: string;
  agentId: string;
  name: string;
  text: string;
  status: string;
};

type LiveActivity = {
  id: string;
  agentName: string;
  phase: string;
  status: string;
  label: string;
  message: string;
  timestamp: string;
};

type LiveModelCall = {
  id: string;
  actorName: string;
  actorRole: string;
  providerId: string;
  model: string;
  status: "running" | "streaming" | "success" | "error";
  durationMs: number | null;
  timestamp: string;
  error: string;
};

function safeMonitorDetail(value: unknown) {
  const text = String(value || "")
    .replace(
      /("(?:api[_-]?key|password|secret|token)"\s*:\s*)"[^"]*"/gi,
      '$1"[redacted]"',
    )
    .replace(
      /\b(?:sk|key|token)-[A-Za-z0-9._-]{12,}\b/g,
      "[redacted]",
    )
    .replace(/\s+/g, " ")
    .trim();

  return text.slice(0, 900);
}

function approvalActionLabel(
  tool: string,
  permission: string,
) {
  if (
    permission === "terminal.execute" ||
    ["run_command", "run_tests", "run_build", "lint"].includes(tool)
  ) {
    return "run a terminal command";
  }
  if (permission === "network.internet") {
    return "use network access";
  }
  if (permission === "hardware.serial") {
    return "access connected hardware";
  }
  if (permission === "project.files.delete") {
    return "perform a destructive project action";
  }
  return tool
    ? "use " + tool.replaceAll("_", " ")
    : "continue the task";
}

function runtimeSpeechAnnouncement(
  runtimeEvent: RuntimeEvent,
): string | null {
  const name = String(
    runtimeEvent.agent_name || "Worker",
  );

  // Narration policy:
  // 1. Speak once when delegation begins.
  // 2. Stay silent during worker progress, approvals, resume, tools,
  //    verification, and next-step updates.
  // 3. Speak the final result or terminal error once.
  if (
    runtimeEvent.type === "executive.activity" &&
    runtimeEvent.phase === "delegation" &&
    runtimeEvent.status === "connecting"
  ) {
    return String(
      runtimeEvent.message ||
        "Connecting with " + name + ".",
    );
  }

  if (runtimeEvent.type === "background_job.completed") {
    const result = String(
      runtimeEvent.result_text || "",
    ).trim();
    return result
      ? name + " finished the task. " + result
      : name + " finished the assigned task.";
  }

  if (runtimeEvent.type === "background_job.error") {
    const error = String(
      runtimeEvent.error || "",
    ).trim();
    return error
      ? name + " could not complete the task. " + error
      : name + " could not complete the assigned task.";
  }

  return null;
}

function consoleLineFromEvent(
  runtimeEvent: RuntimeEvent,
): CommandConsoleLine | null {
  if (runtimeEvent.type === "agent.response.delta") {
    return null;
  }

  const timestamp = String(
    runtimeEvent.timestamp || "",
  );
  const status = String(
    runtimeEvent.status ||
      runtimeEvent.state ||
      "info",
  );

  if (runtimeEvent.type === "runtime.console") {
    return {
      id: runtimeEvent.id,
      timestamp,
      source: String(
        runtimeEvent.source ||
          runtimeEvent.agent_name ||
          "runtime",
      ),
      status,
      message: String(runtimeEvent.message || ""),
    };
  }

  if (
    runtimeEvent.type.startsWith("background_job.")
  ) {
    const phase = String(
      runtimeEvent.current_phase ||
        runtimeEvent.status ||
        status,
    );
    const action = String(
      runtimeEvent.current_action ||
        runtimeEvent.message ||
        runtimeEvent.task ||
        runtimeEvent.type,
    );
    const tool = String(
      runtimeEvent.current_tool || "",
    );
    const detail = safeMonitorDetail(
      runtimeEvent.current_detail || "",
    );

    return {
      id: runtimeEvent.id,
      timestamp,
      source: String(
        runtimeEvent.agent_name ||
          "background worker",
      ),
      status: phase,
      message:
        action +
        (tool ? " · tool: " + tool : "") +
        (detail ? " · " + detail : ""),
    };
  }

  if (runtimeEvent.type === "executive.activity") {
    return {
      id: runtimeEvent.id,
      timestamp,
      source:
        "Agent Man / " +
        String(
          runtimeEvent.label ||
            runtimeEvent.phase ||
            "executive",
        ),
      status,
      message: String(
        runtimeEvent.message || runtimeEvent.type,
      ),
    };
  }

  if (runtimeEvent.type === "agent.state.changed") {
    return {
      id: runtimeEvent.id,
      timestamp,
      source: String(
        runtimeEvent.agent_name ||
          runtimeEvent.agent_id ||
          "worker",
      ),
      status,
      message:
        "State → " +
        String(runtimeEvent.state || "unknown"),
    };
  }

  if (runtimeEvent.type === "agent.delegated") {
    return {
      id: runtimeEvent.id,
      timestamp,
      source: String(
        runtimeEvent.agent_name || "worker",
      ),
      status: "assigned",
      message:
        "Delegated: " +
        String(runtimeEvent.task || ""),
    };
  }

  if (
    runtimeEvent.type === "agent.self_correction"
  ) {
    return {
      id: runtimeEvent.id,
      timestamp,
      source: String(
        runtimeEvent.agent_name || "agent",
      ),
      status,
      message:
        "Self-correction: " +
        String(
          runtimeEvent.failed_tool ||
            runtimeEvent.recovery_tool ||
            "replanning",
        ),
    };
  }

  if (
    runtimeEvent.type === "tool.executed" ||
    runtimeEvent.type === "multi_agent.tool.executed"
  ) {
    return {
      id: runtimeEvent.id,
      timestamp,
      source: String(
        runtimeEvent.tool || "tool",
      ),
      status,
      message:
        String(
          runtimeEvent.agent_name ||
            runtimeEvent.agent_id ||
            "agent",
        ) +
        " / " +
        String(runtimeEvent.status || "completed"),
    };
  }

  if (
    runtimeEvent.type === "agent.response.completed" ||
    runtimeEvent.type === "agent.response.error"
  ) {
    return {
      id: runtimeEvent.id,
      timestamp,
      source: String(
        runtimeEvent.agent_name || "LLM",
      ),
      status:
        runtimeEvent.type === "agent.response.error"
          ? "error"
          : "success",
      message:
        runtimeEvent.type === "agent.response.error"
          ? String(runtimeEvent.error || "Model call failed")
          : "Model response completed" +
            (typeof runtimeEvent.duration_ms === "number"
              ? " in " +
                runtimeEvent.duration_ms +
                " ms"
              : ""),
    };
  }

  return null;
}


const VIEW_META: Record<
  View,
  { label: string; eyebrow: string; description: string }
> = {
  background: {
    label: "Background Activity",
    eyebrow: "WORKSPACE / BACKGROUND",
    description: "Monitor agent jobs, running processes, and output.",
  },
  dashboard: {
    label: "Overview",
    eyebrow: "WORKSPACE / OVERVIEW",
    description: "Monitor agents, tasks, tools, and runtime activity from one place.",
  },
  orchestration: {
    label: "Workflows",
    eyebrow: "WORKSPACE / WORKFLOWS",
    description: "Deterministic stage handoffs with success and failure routing.",
  },
  "multi-agent": {
    label: "Agents",
    eyebrow: "WORKSPACE / AGENTS",
    description: "Shared task context with independent peer reasoning.",
  },
  tools: {
    label: "Tools & Permissions",
    eyebrow: "WORKSPACE / TOOLS",
    description: "Control which runtime capabilities each agent can access.",
  },
  connections: {
    label: "AI Connections",
    eyebrow: "WORKSPACE / CONNECTIONS",
    description: "Configure local and cloud model connections.",
  },
  extensions: {
    label: "Extensions",
    eyebrow: "WORKSPACE / EXTENSIONS",
    description: "Build reusable SKILL.md packages and governed connectors.",
  },
  logs: {
    label: "LLM Logs",
    eyebrow: "WORKSPACE / MODEL ACTIVITY",
    description: "Inspect model requests, responses, latency, and failures.",
  },
  settings: {
    label: "Settings",
    eyebrow: "WORKSPACE / SETTINGS",
    description: "Configure Agent Man executive behavior and runtime preferences.",
  },
};

const AGENT_CONTEXT_TEMPLATES = {
  Developer:
    "You are the implementation specialist. Inspect the existing codebase before changing it, implement requested features and fixes, keep changes scoped to the objective, use assigned development tools, and validate your work with relevant tests/builds before reporting completion.",
  Tester:
    "You are the validation and quality specialist. Reproduce reported issues, inspect the implementation, run relevant tests and builds, identify regressions and edge cases, and only confirm completion when the requested behavior is verified with evidence.",
} as const;

export default function Dashboard() {
  const [view, setView] = useState<View>("dashboard");
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [connections, setConnections] = useState<AIConnection[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [executiveAccess, setExecutiveAccess] =
    useState<EffectiveToolAccess | null>(null);
  const [agent, setAgent] = useState<Agent | null>(null);
  const [prompt, setPrompt] = useState("");
  const [lastDirective, setLastDirective] = useState("");
  const [run, setRun] = useState<MainAgentReply | null>(null);
  const [liveResponses, setLiveResponses] = useState<LiveResponse[]>([]);
  const [liveActivities, setLiveActivities] = useState<LiveActivity[]>([]);
  const [liveModelCalls, setLiveModelCalls] =
    useState<LiveModelCall[]>([]);
  const [serverLogs, setServerLogs] = useState<LLMLog[]>([]);
  const [backgroundJobs, setBackgroundJobs] =
    useState<BackgroundJob[]>([]);
  const [reinforcement, setReinforcement] =
    useState<ReinforcementSummary | null>(null);
  const [feedbackSent, setFeedbackSent] =
    useState<-1 | 1 | null>(null);
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [consoleLines, setConsoleLines] =
    useState<CommandConsoleLine[]>([]);
  const [streamConnected, setStreamConnected] = useState(false);
  const [mainConfig, setMainConfig] = useState<MainAgentConfig | null>(null);
  const [online, setOnline] = useState(false);
  const [allowDelete, setAllowDelete] = useState(false);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [processingStartedAt, setProcessingStartedAt] =
    useState<number | null>(null);
  const [processingSeconds, setProcessingSeconds] = useState(0);

  const [projectDialog, setProjectDialog] = useState(false);
  const [projectName, setProjectName] = useState("Agent Man Dev");
  const [workspacePath, setWorkspacePath] = useState(
    "D:\\AgentMan\\projects\\demo",
  );

  const [agentDialog, setAgentDialog] = useState(false);
  const [agentName, setAgentName] = useState("Developer");
  const [agentRole, setAgentRole] = useState("Developer");
  const [agentContext, setAgentContext] = useState<string>(
    AGENT_CONTEXT_TEMPLATES.Developer,
  );
  const [agentConnectionId, setAgentConnectionId] = useState("");
  const [agentModel, setAgentModel] = useState("");
  const [agentDetectedModels, setAgentDetectedModels] = useState<string[]>([]);
  const [detectingAgentModels, setDetectingAgentModels] = useState(false);

  const [agentContextDialog, setAgentContextDialog] = useState(false);
  const [editingAgentContext, setEditingAgentContext] = useState("");
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
    onCommand: (command) => runDirective(command),
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
        const [
          loadedAgents,
          executiveConfig,
          effectiveAccess,
          recentServerLogs,
          recentBackgroundJobs,
          reinforcementSummary,
        ] = await Promise.all([
          api.agents(currentProject.id),
          api.mainAgentConfig(currentProject.id),
          api.effectiveMainAgentTools(currentProject.id),
          api.llmLogs(currentProject.id, 12),
          api.backgroundJobs(currentProject.id),
          api.reinforcementSummary(currentProject.id),
        ]);
        setMainConfig(executiveConfig);
        setExecutiveAccess(effectiveAccess);
        setServerLogs(recentServerLogs);
        setBackgroundJobs(recentBackgroundJobs);
        setReinforcement(reinforcementSummary);
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
        setExecutiveAccess(null);
        setServerLogs([]);
        setBackgroundJobs([]);
        setReinforcement(null);
      }
    } catch {
      setOnline(false);
    }
  }

  async function reloadConnections() {
    setConnections(await api.aiConnections());
  }

  async function refreshExecutiveAccess(
    projectId?: string,
  ) {
    const id = projectId || project?.id;
    if (!id) {
      setExecutiveAccess(null);
      return;
    }

    try {
      setExecutiveAccess(
        await api.effectiveMainAgentTools(id),
      );
    } catch {
      setExecutiveAccess(null);
    }
  }

  async function refreshServerLogs(
    projectId?: string,
  ) {
    const id = projectId || project?.id;
    if (!id) {
      setServerLogs([]);
      return;
    }

    try {
      setServerLogs(await api.llmLogs(id, 12));
    } catch {
      // Keep the last known server log snapshot.
    }
  }

  async function refreshReinforcement(
    projectId?: string,
  ) {
    const id = projectId || project?.id;
    if (!id) {
      setReinforcement(null);
      return;
    }
    try {
      setReinforcement(
        await api.reinforcementSummary(id),
      );
    } catch {
      // Keep the previous learning snapshot.
    }
  }

  async function refreshWorkers(projectId?: string) {
    const id = projectId || project?.id;
    if (!id) return;

    try {
      const loadedAgents = await api.agents(id);
      setAgents(loadedAgents);
      setAgent((current) =>
        current
          ? loadedAgents.find((item) => item.id === current.id) || current
          : loadedAgents[0] || null,
      );
    } catch {
      // Keep the last known worker state if a polling request fails.
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (view === "dashboard" && project?.id) {
      void refreshExecutiveAccess(project.id);
    }
  }, [view, project?.id]);

  useEffect(() => {
    setLiveResponses([]);
    setLiveActivities([]);
    setLiveModelCalls([]);
    setConsoleLines([]);
    setStreamConnected(false);
    if (!project) return;

    const stream = new EventSource(
      api.runtimeEventsUrl(project.id),
    );
    stream.onopen = () => setStreamConnected(true);
    stream.onerror = () => setStreamConnected(false);

    stream.onmessage = (event) => {
      let runtimeEvent: RuntimeEvent;

      try {
        runtimeEvent = JSON.parse(event.data) as RuntimeEvent;
      } catch {
        return;
      }

      const consoleLine =
        consoleLineFromEvent(runtimeEvent);
      if (consoleLine) {
        setConsoleLines((current) =>
          [...current, consoleLine].slice(-300),
        );
      }

      const speech =
        runtimeSpeechAnnouncement(runtimeEvent);
      if (speech) {
        requestAgentSpeech(speech);
      }

      if (runtimeEvent.type === "agent.delegated") {
        setConsoleOpen(true);
      }

      if (
        runtimeEvent.type ===
        "background_job.approval_required"
      ) {
        const workerName = String(
          runtimeEvent.agent_name || "Worker",
        );
        const tool = String(runtimeEvent.tool || "");
        const permission = String(
          runtimeEvent.permission || "",
        );
        const action = approvalActionLabel(
          tool,
          permission,
        );
        const message =
          workerName +
          " is waiting for approval to " +
          action +
          ". Approve it to continue the same background task.";

        setConsoleOpen(true);
        setView("dashboard");
        setNotice({
          title: "Agent Man needs your approval",
          message,
          approvalJobId: String(runtimeEvent.job_id || ""),
          approvalPermission: permission,
        });
        setRun((current) => ({
          status: "waiting_approval",
          text: message,
          steps: current?.steps || [],
        }));
      }

      if (
        [
          "background_job.resumed",
          "background_job.started",
          "background_job.completed",
          "background_job.error",
        ].includes(runtimeEvent.type) &&
        runtimeEvent.job_id
      ) {
        const changedJobId = String(runtimeEvent.job_id);
        setNotice((current) =>
          current?.approvalJobId === changedJobId
            ? null
            : current,
        );
        if (runtimeEvent.type === "background_job.resumed") {
          setRun((current) => ({
            status: "background",
            text: String(
              runtimeEvent.message ||
                "Approval received. Worker is resuming.",
            ),
            steps: current?.steps || [],
          }));
        }
      }

      if (
        runtimeEvent.type ===
        "reinforcement.reward.recorded"
      ) {
        void refreshReinforcement(project.id);
      }

      if (
        runtimeEvent.type === "ui.command_console"
      ) {
        const action = String(
          runtimeEvent.action || "toggle",
        );
        setConsoleOpen((current) =>
          action === "open"
            ? true
            : action === "close"
              ? false
              : !current,
        );
        return;
      }

      if (
        runtimeEvent.type.startsWith(
          "background_job.",
        ) &&
        runtimeEvent.job_id
      ) {
        const jobId = String(runtimeEvent.job_id);
        setBackgroundJobs((current) => {
          const existing = current.find(
            (item) => item.id === jobId,
          );
          const next: BackgroundJob = {
            id: jobId,
            project_id: String(
              runtimeEvent.project_id ||
                existing?.project_id ||
                project.id,
            ),
            agent_id: String(
              runtimeEvent.agent_id ||
                existing?.agent_id ||
                "",
            ),
            agent_name: String(
              runtimeEvent.agent_name ||
                existing?.agent_name ||
                "Worker",
            ),
            agent_role: String(
              runtimeEvent.agent_role ||
                existing?.agent_role ||
                "Worker",
            ),
            task: String(
              runtimeEvent.task ||
                existing?.task ||
                "",
            ),
            status: String(
              runtimeEvent.status ||
                existing?.status ||
                "queued",
            ),
            created_at:
              existing?.created_at ||
              String(runtimeEvent.timestamp || ""),
            started_at:
              runtimeEvent.type ===
              "background_job.started"
                ? String(
                    runtimeEvent.timestamp || "",
                  )
                : existing?.started_at || null,
            completed_at:
              runtimeEvent.type ===
                "background_job.completed" ||
              runtimeEvent.type ===
                "background_job.error"
                ? String(
                    runtimeEvent.timestamp || "",
                  )
                : existing?.completed_at || null,
            result_text: String(
              runtimeEvent.result_text ||
                existing?.result_text ||
                "",
            ),
            step_count:
              typeof runtimeEvent.step_count ===
              "number"
                ? runtimeEvent.step_count
                : existing?.step_count || 0,
            error: String(
              runtimeEvent.error ||
                existing?.error ||
                "",
            ),
            current_phase: String(
              runtimeEvent.current_phase ||
                existing?.current_phase ||
                runtimeEvent.status ||
                "queued",
            ),
            current_action: String(
              runtimeEvent.current_action ||
                runtimeEvent.message ||
                existing?.current_action ||
                "",
            ),
            current_tool: String(
              runtimeEvent.current_tool ||
                existing?.current_tool ||
                "",
            ),
            current_detail: String(
              runtimeEvent.current_detail ||
                existing?.current_detail ||
                "",
            ),
            current_next_step: String(
              runtimeEvent.current_next_step ||
                existing?.current_next_step ||
                "",
            ),
            updated_at: String(
              runtimeEvent.updated_at ||
                runtimeEvent.timestamp ||
                existing?.updated_at ||
                "",
            ),
          };
          return (
            existing
              ? current.map((item) =>
                  item.id === jobId ? next : item,
                )
              : [next, ...current]
          ).slice(0, 40);
        });
        return;
      }

      if (
        runtimeEvent.type === "executive.activity" &&
        typeof runtimeEvent.id === "string"
      ) {
        const activity: LiveActivity = {
          id: runtimeEvent.id,
          agentName: String(
            runtimeEvent.agent_name || "Agent Man",
          ),
          phase: String(runtimeEvent.phase || "runtime"),
          status: String(runtimeEvent.status || "working"),
          label: String(runtimeEvent.label || "runtime"),
          message: String(
            runtimeEvent.message || "Working...",
          ),
          timestamp: String(runtimeEvent.timestamp || ""),
        };
        setLiveActivities((current) =>
          [...current, activity].slice(-40),
        );
        return;
      }

      if (
        runtimeEvent.type.startsWith("agent.response.") &&
        typeof runtimeEvent.response_id === "string"
      ) {
        const responseId = runtimeEvent.response_id;
        const responseStatus =
          runtimeEvent.type === "agent.response.started"
            ? "running"
            : runtimeEvent.type === "agent.response.delta"
              ? "streaming"
              : runtimeEvent.type === "agent.response.error"
                ? "error"
                : "success";

        const modelCall: LiveModelCall = {
          id: responseId,
          actorName: String(
            runtimeEvent.agent_name || "Agent",
          ),
          actorRole: String(
            runtimeEvent.agent_role || "Unknown",
          ),
          providerId: String(
            runtimeEvent.provider_id || "provider",
          ),
          model: String(
            runtimeEvent.model || "model",
          ),
          status: responseStatus,
          durationMs:
            typeof runtimeEvent.duration_ms === "number"
              ? runtimeEvent.duration_ms
              : null,
          timestamp: String(
            runtimeEvent.timestamp || "",
          ),
          error: String(runtimeEvent.error || ""),
        };

        setLiveModelCalls((current) => {
          const found = current.some(
            (item) => item.id === responseId,
          );
          return (
            found
              ? current.map((item) =>
                  item.id === responseId
                    ? { ...item, ...modelCall }
                    : item,
                )
              : [...current, modelCall]
          ).slice(-12);
        });

        const response: LiveResponse = {
          id: responseId,
          agentId: String(runtimeEvent.agent_id || ""),
          name: String(runtimeEvent.agent_name || "Agent"),
          text: typeof runtimeEvent.text === "string" ? runtimeEvent.text : "",
          status: runtimeEvent.type.split(".").pop() || "started",
        };
        setLiveResponses((current) => {
          const found = current.some((item) => item.id === responseId);
          return (found
            ? current.map((item) => item.id === responseId ? response : item)
            : [...current, response]).slice(-20);
        });
        return;
      }

      if (runtimeEvent.type === "agent.configuration.updated") {
        void refreshWorkers(project.id);
        return;
      }

      if (
        runtimeEvent.type === "agent.state.changed" &&
        runtimeEvent.agent_id &&
        runtimeEvent.state
      ) {
        setAgents((current) =>
          current.map((item) =>
            item.id === runtimeEvent.agent_id
              ? { ...item, state: runtimeEvent.state as string }
              : item,
          ),
        );
        setAgent((current) =>
          current && current.id === runtimeEvent.agent_id
            ? { ...current, state: runtimeEvent.state as string }
            : current,
        );
        return;
      }

      if (
        runtimeEvent.type === "agent.delegated" &&
        runtimeEvent.agent_id
      ) {
        setAgents((current) =>
          current.map((item) =>
            item.id === runtimeEvent.agent_id
              ? { ...item, state: "assigned" }
              : item,
          ),
        );
        setAgent((current) =>
          current && current.id === runtimeEvent.agent_id
            ? { ...current, state: "assigned" }
            : current,
        );
        return;
      }

      if (
        runtimeEvent.type === "agent.deleted" &&
        runtimeEvent.agent_id
      ) {
        setAgents((current) =>
          current.filter(
            (item) => item.id !== runtimeEvent.agent_id,
          ),
        );
        setAgent((current) =>
          current?.id === runtimeEvent.agent_id
            ? null
            : current,
        );
      }
    };

    return () => {
      stream.close();
    };
  }, [project?.id]);

  useEffect(() => {
    if (wake.state === "listening" && wake.liveTranscript) {
      setPrompt(wake.liveTranscript);
    }
  }, [wake.state, wake.liveTranscript]);

  useEffect(() => {
    if (processingStartedAt === null) {
      setProcessingSeconds(0);
      return;
    }

    const update = () => {
      setProcessingSeconds(
        Math.max(
          0,
          Math.floor((Date.now() - processingStartedAt) / 1000),
        ),
      );
    };
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [processingStartedAt]);

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
    setAgentContext(AGENT_CONTEXT_TEMPLATES.Developer);
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

    if (
      !agentName.trim() ||
      !agentRole.trim() ||
      !agentContext.trim() ||
      !agentModel.trim()
    ) {
      setNotice({
        title: "Agent configuration incomplete",
        message:
          "Name, role, context, connection and model are required.",
      });
      return;
    }

    setBusy(true);
    try {
      await api.createAgent({
        project_id: project.id,
        name: agentName.trim(),
        role: agentRole.trim(),
        context: agentContext.trim(),
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

  function openAgentContextDialog() {
    if (!agent) return;
    setEditingAgentContext(agent.context || "");
    setAgentContextDialog(true);
  }

  async function saveAgentContext(event: FormEvent) {
    event.preventDefault();
    if (!agent || !editingAgentContext.trim()) {
      setNotice({
        title: "Agent context required",
        message:
          "Describe what this agent is responsible for before saving.",
      });
      return;
    }

    setBusy(true);
    try {
      const updated = await api.updateAgent(agent.id, {
        context: editingAgentContext.trim(),
      });
      setAgent(updated);
      setAgents((current) =>
        current.map((item) =>
          item.id === updated.id ? updated : item,
        ),
      );
      setAgentContextDialog(false);
      setNotice({
        title: "Agent context updated",
        message:
          updated.name +
          " will use the new context on its next task.",
      });
    } catch (error) {
      setNotice({
        title: "Context update failed",
        message:
          error instanceof Error
            ? error.message
            : String(error),
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
    setLastDirective(command);
    setPrompt("");
    voice.stop();
    setBusy(true);
    setProcessingStartedAt(Date.now());
    setRun(null);
    setFeedbackSent(null);
    setLiveResponses([]);
    setLiveActivities([]);
    setLiveModelCalls([]);

    let result: MainAgentReply | null = null;

    try {
      result = await api.chatMainAgent(
        project.id,
        command,
        false,
        allowDelete,
        false,
        false,
      );
      setRun(result);
    } catch (error) {
      setRun({
        status: "error",
        text: error instanceof Error ? error.message : String(error),
        steps: [],
      });
    } finally {
      await refreshWorkers(project.id);
      await refreshServerLogs(project.id);
      setLiveModelCalls([]);
      setBusy(false);
      setProcessingStartedAt(null);
    }

    if (
      result &&
      result.status === "completed" &&
      result.text &&
      voice.settings.enabled &&
      voice.settings.autoSpeak
    ) {
      await voice.queueSpeakAsync(result.text);
    }
  }

  async function submitReinforcementFeedback(
    value: -1 | 1,
  ) {
    if (!project || !run || feedbackSent !== null) {
      return;
    }

    const recentJob =
      backgroundJobs.length > 0
        ? backgroundJobs[0]
        : null;

    try {
      await api.reinforcementFeedback(project.id, {
        value,
        agent_id: recentJob?.agent_id || null,
        agent_name:
          recentJob?.agent_name || "Agent Man",
        tool_name:
          recentJob?.current_tool || null,
        task:
          recentJob?.task || lastDirective,
        note:
          value > 0
            ? "User confirmed this result was useful."
            : "User indicated this result needs improvement.",
        reference_id: recentJob?.id || null,
      });
      setFeedbackSent(value);
      await refreshReinforcement(project.id);
      setNotice({
        title:
          value > 0
            ? "Feedback learned"
            : "Correction recorded",
        message:
          value > 0
            ? "Agent Man will treat this outcome as positive evidence."
            : "Agent Man will reduce confidence in this approach and use the feedback on future choices.",
      });
    } catch (error) {
      setNotice({
        title: "Feedback could not be saved",
        message:
          error instanceof Error
            ? error.message
            : String(error),
        tone: "danger",
      });
    }
  }

  async function approveWaitingJob(jobId: string) {
    if (!project || !jobId || approvalBusy) {
      return;
    }

    setApprovalBusy(true);
    try {
      const resumed = await api.approveBackgroundJob(
        project.id,
        jobId,
      );
      setBackgroundJobs((current) =>
        current.map((item) =>
          item.id === resumed.id ? resumed : item,
        ),
      );
      setRun((current) => ({
        status: "background",
        text:
          resumed.agent_name +
          " received approval and is resuming the task.",
        steps: current?.steps || [],
      }));
      setNotice(null);
      setAllowDelete(false);
    } catch (error) {
      setNotice({
        title: "Approval could not continue the worker",
        message:
          error instanceof Error
            ? error.message
            : String(error),
        tone: "danger",
      });
    } finally {
      setApprovalBusy(false);
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

  const globallyEnabledTools =
    tools.filter((tool) => tool.enabled).length;
  const activeTools = executiveAccess?.count ?? 0;
  const executiveGateCounts = {
    exec:
      executiveAccess?.tools.filter(
        (tool) => tool.approval_gate === "exec",
      ).length ?? 0,
    net:
      executiveAccess?.tools.filter(
        (tool) => tool.approval_gate === "net",
      ).length ?? 0,
    hw:
      executiveAccess?.tools.filter(
        (tool) => tool.approval_gate === "hw",
      ).length ?? 0,
    delete:
      executiveAccess?.tools.filter(
        (tool) => tool.approval_gate === "delete",
      ).length ?? 0,
  };
  const automaticToolCount =
    executiveAccess?.tools.filter(
      (tool) => tool.approval_gate !== "delete",
    ).length ?? 0;

  const providerLabel = useMemo(() => {
    if (!agent) return "NO AGENT";
    return (
      connections.find(
        (connection) => connection.id === agent.llm.connection_id,
      )?.name || agent.llm.provider_id
    );
  }, [agent, connections]);

  const activeBackgroundJobs =
    backgroundJobs.filter((item) =>
      ["queued", "running"].includes(item.status),
    );
  const activeBackgroundJob =
    activeBackgroundJobs.length > 0
      ? activeBackgroundJobs[0]
      : null;
  const waitingApprovalJob =
    backgroundJobs.find(
      (item) => item.status === "waiting_approval",
    ) || null;
  const completedBackgroundJobs =
    backgroundJobs.filter(
      (item) => item.status === "completed",
    ).length;

  const activeWorkerStates = new Set([
    "assigned",
    "working",
    "validating",
    "verifying",
    "waiting_approval",
    "waiting_capability",
  ]);
  const activeWorker =
    agents.find((item) => activeWorkerStates.has(item.state)) || null;
  const activeWorkerDisplayState =
    activeWorker?.state === "assigned"
      ? "CONNECTING"
      : activeWorker?.state.toUpperCase() || "—";
  const activeWorkerMessage = activeWorker
    ? activeWorker.state === "assigned"
      ? "Connecting with " + activeWorker.name + "..."
      : activeWorker.name +
        " is " +
        activeWorker.state.replaceAll("_", " ") +
        "..."
    : "";

  const interactionPhase =
    voice.speaking
      ? "speaking"
      : busy || wake.state === "processing"
        ? "processing"
        : wake.state === "listening"
          ? "listening"
          : wake.state === "waking"
            ? "waking"
            : wake.state === "error"
              ? "error"
              : wake.state === "off"
                ? "off"
                : voice.settings.wakeEnabled
                  ? "standby"
                  : "ready";

  const interactionLabel =
    interactionPhase === "speaking"
      ? "SPEAKING"
      : interactionPhase === "processing"
        ? "PROCESSING"
        : interactionPhase === "listening"
          ? "LISTENING"
          : interactionPhase === "waking"
            ? "WAKING"
            : interactionPhase === "error"
              ? "MIC ERROR"
              : interactionPhase === "off"
                ? "MIC OFF"
                : interactionPhase === "standby"
                  ? "WAKE READY"
                  : "READY";

  const latestLiveResponse =
    [...liveResponses]
      .reverse()
      .find((item) => Boolean(item.text)) || null;
  const latestLiveActivity =
    liveActivities.length > 0
      ? liveActivities[liveActivities.length - 1]
      : null;
  const liveOutputText =
    latestLiveResponse?.text ||
    latestLiveActivity?.message ||
    "";
  const liveOutputAgent =
    latestLiveResponse?.name ||
    latestLiveActivity?.agentName ||
    "Agent Man";
  const liveOutputStatus =
    latestLiveResponse?.status ||
    latestLiveActivity?.status ||
    "working";
  const streamActive =
    busy &&
    Boolean(
      liveOutputText ||
        liveResponses.length ||
        liveActivities.length,
    );

  const serverLogRows = [
    ...[...liveModelCalls]
      .reverse()
      .map((item) => ({
        id: "live:" + item.id,
        actorName: item.actorName,
        actorRole: item.actorRole,
        providerId: item.providerId,
        model: item.model,
        status: item.status,
        durationMs: item.durationMs,
        timestamp: item.timestamp,
        error: item.error,
        live: true,
      })),
    ...serverLogs.map((item) => ({
      id: "saved:" + item.id,
      actorName: item.actor_name,
      actorRole: item.actor_role,
      providerId: item.provider_id,
      model: item.model,
      status: item.status,
      durationMs: item.duration_ms,
      timestamp: item.created_at,
      error: item.error_text,
      live: false,
    })),
  ].slice(0, 10);

    const meta = VIEW_META[view];

  return (
    <div className="jarvisShell">

      <aside className="commandRail">
        <button
          className="coreMark"
          onClick={() => setView("dashboard")}
          title="Agent Man"
        >
          <span className="coreMarkRing">
            <Sparkles size={18} />
          </span>
          <span className="coreMarkLabel">
            <strong>Agent Man</strong>
            <small>Workspace</small>
          </span>
        </button>

        <nav className="railNav">
          <RailButton
            active={view === "background"}
            label="Background"
            icon={<Activity />}
            onClick={() => setView("background")}
          />
          <RailButton
            active={view === "dashboard"}
            label="Overview"
            icon={<Home />}
            onClick={() => setView("dashboard")}
          />
          <RailButton
            active={view === "orchestration"}
            label="Workflows"
            icon={<GitBranch />}
            onClick={() => setView("orchestration")}
          />
          <RailButton
            active={view === "multi-agent"}
            label="Agents"
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
            label="Connections"
            icon={<Plug />}
            onClick={() => setView("connections")}
          />
          <RailButton
            active={view === "extensions"}
            label="Extensions"
            icon={<WandSparkles />}
            onClick={() => setView("extensions")}
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
              <small>AGENT MAN / LOCAL AGENT RUNTIME</small>
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
                {interactionPhase === "processing"
                  ? "PROCESS"
                  : interactionPhase === "listening"
                    ? "LISTEN"
                    : interactionPhase === "speaking"
                      ? "SPEAK"
                      : voice.settings.wakeEnabled
                        ? "WAKE"
                        : "VOICE"}
              </span>
              <i className={interactionPhase} />
            </button>

            <button
              className={
                consoleOpen
                  ? "consoleCoreButton active"
                  : "consoleCoreButton"
              }
              onClick={() =>
                setConsoleOpen((current) => !current)
              }
              title="Command Console"
            >
              <TerminalSquare size={14} />
              <span>CONSOLE</span>
              <b>{activeBackgroundJobs.length}</b>
            </button>

            <div
              className={
                online ? "runtimeBadge online" : "runtimeBadge offline"
              }
            >
              <Radio size={14} />
              <span>{online ? "Online" : "Offline"}</span>
              <b>{online ? "Live" : "Down"}</b>
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
            <small>ACTIVE PROJECT</small>
            <strong>{project?.name || "UNASSIGNED"}</strong>
            <code>
              {project?.workspace_path ||
                "Create a project to initialize the workspace."}
            </code>
          </div>
        </div>

        {view === "background" ? (
          <BackgroundPage project={project} />
        ) : view === "connections" ? (
          <AIConnections
            connections={connections}
            onChanged={reloadConnections}
          />
        ) : view === "extensions" ? (
          <ExtensionsPage
            project={project}
            agents={agents}
          />
        ) : view === "logs" ? (
          <LLMLogsPage project={project} />
        ) : view === "settings" ? (
          <SettingsPage
            agents={agents}
            onAgentSaved={(saved) => setAgents((current) =>
              current.some((agent) => agent.id === saved.id)
                ? current.map((agent) => agent.id === saved.id ? saved : agent)
                : [...current, saved],
            )}
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
          <ToolsPage
            project={project}
            agents={agents}
          />
        ) : (
          <div className="commandDeck">
            <section className="telemetryStrip">
              <Telemetry
                icon={<Bot />}
                label="Workers"
                value={agents.length}
                detail={
                  activeBackgroundJobs.length
                    ? activeBackgroundJobs.length +
                      " BACKGROUND ACTIVE"
                    : agents.length
                      ? "READY FOR DELEGATION"
                      : "NONE CONFIGURED"
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
                detail={`${globallyEnabledTools} RUNTIME ENABLED`}
              />
              <Telemetry
                icon={<BrainCircuit />}
                label="Learning"
                value={
                  reinforcement
                    ? reinforcement.overall.average_reward.toFixed(2)
                    : "0.00"
                }
                detail={
                  reinforcement
                    ? reinforcement.events + " REWARD EVENTS"
                    : "NO FEEDBACK YET"
                }
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
                <PanelLabel icon={<Boxes />} label="AGENTS" />

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
                  <span>WORKERS</span>
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
                          "matrixAgent state-" +
                          item.state +
                          " " +
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
                        <em>
                          {item.state === "assigned"
                            ? "connecting"
                            : item.state}
                        </em>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="executiveOverview">
                <div className="executiveOverviewHeader">
                  <div className="executiveAvatar">
                    <Sparkles size={20} />
                  </div>
                  <div>
                    <small>EXECUTIVE AGENT</small>
                    <h2>Agent Man</h2>
                    <p>
                      Coordinates requests, delegates work, and reports live progress.
                    </p>
                  </div>
                  <span
                    className={
                      online
                        ? "professionalStatus online"
                        : "professionalStatus offline"
                    }
                  >
                    {online ? "Online" : "Offline"}
                  </span>
                </div>

                <div className="executiveSummaryGrid">
                  <div>
                    <span>Current state</span>
                    <strong>{interactionLabel}</strong>
                  </div>
                  <div>
                    <span>Background jobs</span>
                    <strong>{activeBackgroundJobs.length}</strong>
                  </div>
                  <div>
                    <span>Available tools</span>
                    <strong>{activeTools}</strong>
                  </div>
                  <div>
                    <span>Workers</span>
                    <strong>{agents.length}</strong>
                  </div>
                </div>

                <div className="currentWorkCard">
                  <div className="currentWorkHeader">
                    <div>
                      <small>CURRENT PROCESS</small>
                      <strong>
                        {activeBackgroundJob
                          ? activeBackgroundJob.agent_name
                          : busy
                            ? "Agent Man"
                            : "No active task"}
                      </strong>
                    </div>
                    <span>
                      {activeBackgroundJob
                        ? activeBackgroundJob.current_phase || activeBackgroundJob.status
                        : busy
                          ? "Working"
                          : "Ready"}
                    </span>
                  </div>
                  <p>
                    {activeBackgroundJob
                      ? activeBackgroundJob.current_action ||
                        activeBackgroundJob.task
                      : busy
                        ? liveOutputText || "Processing your request."
                        : "Agent Man is ready for your next instruction."}
                  </p>
                </div>

                <div className="selectedWorkerCard">
                  <div className="selectedWorkerTitle">
                    <span>SELECTED WORKER</span>
                    {agent && (
                      <button
                        type="button"
                        onClick={openAgentContextDialog}
                      >
                        Edit context
                      </button>
                    )}
                  </div>
                  {agent ? (
                    <>
                      <div className="selectedWorkerIdentity">
                        <div className="workerAvatar">
                          <Bot size={17} />
                        </div>
                        <div>
                          <strong>{agent.name}</strong>
                          <span>{agent.role}</span>
                        </div>
                        <em className={"workerState state-" + agent.state}>
                          {agent.state === "assigned"
                            ? "connecting"
                            : agent.state}
                        </em>
                      </div>
                      <div className="selectedWorkerMeta">
                        <div>
                          <span>Provider</span>
                          <strong>{providerLabel}</strong>
                        </div>
                        <div>
                          <span>Model</span>
                          <strong>{agent.llm.model}</strong>
                        </div>
                      </div>
                    </>
                  ) : (
                    <div className="professionalEmpty">
                      Select a worker to view its configuration and status.
                    </div>
                  )}
                </div>
              </div>

              <div className="hudPanel missionPanel">
                <PanelLabel icon={<Activity />} label="RUNTIME STATUS" />
                <div className="missionStatus">
                  <span
                    className={
                      "statusPulse phase-" + interactionPhase
                    }
                  />
                  <div>
                    <small>CURRENT STATE</small>
                    <strong>{interactionLabel}</strong>
                  </div>
                </div>

                <div className="missionReadout">
                  <span>PRIMARY AGENT</span>
                  <b>AGENT MAN</b>
                  <span>EXECUTIVE STATUS</span>
                  <b>{mainConfig ? "ONLINE" : "SETUP REQUIRED"}</b>
                  <span>EXECUTIVE TOOLS</span>
                  <b>
                    {executiveAccess
                      ? executiveAccess.count +
                        " EFFECTIVE / " +
                        globallyEnabledTools +
                        " ENABLED"
                      : "VERIFYING..."}
                  </b>
                  <span>AUTO-AUTHORIZED TOOLS</span>
                  <b>{automaticToolCount} READY IMMEDIATELY</b>
                  <span>ACTIVE WORKER</span>
                  <b>
                    {activeWorker
                      ? activeWorker.name
                      : busy
                        ? "Agent Man direct"
                        : "—"}
                  </b>
                  <span>WORKER STATE</span>
                  <b>
                    {activeWorker
                      ? activeWorkerDisplayState
                      : busy
                        ? "EXECUTIVE WORKING"
                        : "—"}
                  </b>
                  <span>BACKGROUND JOBS</span>
                  <b>
                    {activeBackgroundJobs.length
                      ? activeBackgroundJobs.length +
                        " ACTIVE / " +
                        completedBackgroundJobs +
                        " COMPLETE"
                      : completedBackgroundJobs
                        ? completedBackgroundJobs +
                          " COMPLETE"
                        : "NONE"}
                  </b>
                  <span>EXECUTIVE CHANNEL</span>
                  <b>
                    {busy
                      ? "RESPONDING"
                      : "AVAILABLE"}
                  </b>
                  <span>CURRENT PROCESS</span>
                  <b>
                    {activeBackgroundJob
                      ? activeBackgroundJob.agent_name +
                        ": " +
                        (activeBackgroundJob.current_action ||
                          activeBackgroundJob.current_phase)
                      : "—"}
                  </b>
                </div>

                <div className="missionGateLegend">
                  <span>
                    Assigned Executive tools are available immediately.
                  </span>
                  <span>
                    Only destructive actions require separate approval.
                  </span>
                </div>

                <div className="permissionReadout">
                  <div
                    className={
                      "permissionChip " +
                      (executiveGateCounts.exec > 0
                        ? "available active"
                        : "")
                    }
                    title={
                      executiveGateCounts.exec +
                      " assigned Executive terminal tools are automatically authorized"
                    }
                  >
                    <TerminalSquare size={13} />
                    <span>
                      EXEC
                      <small>
                        {executiveGateCounts.exec} TOOL
                        {executiveGateCounts.exec === 1 ? "" : "S"} · AUTO
                      </small>
                    </span>
                  </div>
                  <div
                    className={
                      "permissionChip " +
                      (executiveGateCounts.net > 0
                        ? "available active"
                        : "")
                    }
                    title={
                      executiveGateCounts.net +
                      " assigned Executive network tools are automatically authorized"
                    }
                  >
                    <Globe2 size={13} />
                    <span>
                      NET
                      <small>
                        {executiveGateCounts.net} TOOL
                        {executiveGateCounts.net === 1 ? "" : "S"} · AUTO
                      </small>
                    </span>
                  </div>
                  <div
                    className={
                      "permissionChip " +
                      (executiveGateCounts.hw > 0
                        ? "available active"
                        : "")
                    }
                    title={
                      executiveGateCounts.hw +
                      " assigned Executive hardware tools are automatically authorized"
                    }
                  >
                    <Cpu size={13} />
                    <span>
                      HW
                      <small>
                        {executiveGateCounts.hw} TOOL
                        {executiveGateCounts.hw === 1 ? "" : "S"} · AUTO
                      </small>
                    </span>
                  </div>
                  <button
                    className={
                      "permissionChip danger " +
                      (executiveGateCounts.delete > 0
                        ? "available "
                        : "") +
                      (allowDelete ? "active" : "")
                    }
                    onClick={() => {
                      const shouldApproveWaitingJob =
                        !allowDelete &&
                        waitingApprovalJob?.current_detail ===
                          "project.files.delete";
                      setAllowDelete((value) => !value);
                      if (shouldApproveWaitingJob) {
                        void approveWaitingJob(
                          waitingApprovalJob.id,
                        );
                      }
                    }}
                    disabled={
                      busy ||
                      approvalBusy ||
                      executiveGateCounts.delete === 0
                    }
                    title={
                      executiveGateCounts.delete +
                      " assigned Executive tools require project.files.delete approval"
                    }
                  >
                    <Wrench size={13} />
                    <span>
                      FILE DEL
                      <small>
                        {executiveGateCounts.delete} TOOL
                        {executiveGateCounts.delete === 1 ? "" : "S"} ·{" "}
                        {allowDelete ? "ARMED" : "ASK"}
                      </small>
                    </span>
                  </button>
                  <button
                    className="permissionChip available"
                    onClick={openAgentContextDialog}
                    disabled={!agent || busy}
                    title="Edit selected worker agent context"
                  >
                    <Settings2 size={13} />
                    <span>
                      AGENT CTX
                      <small>ROLE INSTRUCTIONS</small>
                    </span>
                  </button>
                  <button
                    className="permissionChip danger"
                    onClick={() => setDeleteDialog(true)}
                    disabled={!agent || busy}
                    title="Delete selected worker agent"
                  >
                    <Trash2 size={13} />
                    <span>
                      AGENT DEL
                      <small>WORKER MANAGEMENT</small>
                    </span>
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
                <div className={"commandStatus phase-" + interactionPhase}>
                  <i />
                  {interactionLabel}
                  {interactionPhase === "processing" &&
                    " · " + processingSeconds + "s"}
                </div>
              </div>

              <div className="directiveWorkspace">
                <div className="directiveMain">
              {(voice.settings.wakeEnabled ||
                interactionPhase === "processing" ||
                interactionPhase === "speaking") && (
                <div
                  className={
                    "interactionMonitor phase-" + interactionPhase
                  }
                >
                  <div className="interactionMonitorIcon">
                    {interactionPhase === "listening" ? (
                      <Mic size={16} />
                    ) : (
                      <Sparkles size={16} />
                    )}
                  </div>
                  <div className="interactionMonitorBody">
                    <small>{interactionLabel}</small>
                    <strong>
                      {interactionPhase === "listening"
                        ? wake.liveTranscript ||
                          "Listening for your command..."
                        : interactionPhase === "processing"
                          ? activeWorker
                            ? activeWorkerMessage
                            : "Agent Man is processing: " +
                              (wake.finalTranscript || prompt)
                          : interactionPhase === "speaking"
                            ? "Agent Man is speaking the result."
                            : interactionPhase === "off"
                              ? wake.errorMessage ||
                                "Microphone is off. Use Listen Now or re-enable Wake Mode."
                              : wake.errorMessage ||
                                "Say “" +
                                  voice.settings.wakePhrase +
                                  "” to begin."}
                    </strong>
                  </div>
                  {(interactionPhase === "listening" ||
                    interactionPhase === "processing") && (
                    <div
                      className={
                        "interactionBars " + interactionPhase
                      }
                      aria-hidden="true"
                    >
                      {Array.from({ length: 8 }).map((_, index) => (
                        <i key={index} />
                      ))}
                    </div>
                  )}
                </div>
              )}

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

              <div className={"commandOutput " + (streamActive ? "streaming" : "")}>
                <div className="outputRail">
                  <span />
                  <small>{streamActive ? "Live" : "OUTPUT"}</small>
                </div>
                <div className="outputBody">
                  <div className="outputStreamHeader">
                    <span
                      className={
                        "streamState " +
                        (streamActive ? "active" : "idle")
                      }
                    >
                      {streamActive
                        ? streamConnected
                          ? "LIVE STREAM"
                          : "RECONNECTING"
                        : run
                          ? "FINAL"
                          : "STANDBY"}
                    </span>
                    <b>
                      {streamActive
                        ? liveOutputAgent
                        : "Agent Man"}
                    </b>
                    {streamActive && (
                      <small>{liveOutputStatus}</small>
                    )}
                  </div>

                  <div
                    className="outputText"
                    role="log"
                    aria-live="polite"
                    aria-atomic="false"
                  >
                    {run?.text ||
                      (busy && liveOutputText) ||
                      (busy
                        ? "Agent Man is working on the directive..."
                        : mainConfig
                          ? "Agent Man is standing by. Give me the objective; I will choose and coordinate the workers."
                          : "Configure Agent Man's executive model to begin.")}
                    {streamActive && (
                      <span
                        className="streamCursor"
                        aria-hidden="true"
                      />
                    )}
                  </div>

                  {run && !busy && (
                    <div className="reinforcementFeedback">
                      <span>Was this outcome useful?</span>
                      <button
                        type="button"
                        className={
                          feedbackSent === 1
                            ? "positive active"
                            : "positive"
                        }
                        onClick={() =>
                          void submitReinforcementFeedback(1)
                        }
                        disabled={feedbackSent !== null}
                        title="Positive reinforcement"
                      >
                        <ThumbsUp size={15} />
                        Helpful
                      </button>
                      <button
                        type="button"
                        className={
                          feedbackSent === -1
                            ? "negative active"
                            : "negative"
                        }
                        onClick={() =>
                          void submitReinforcementFeedback(-1)
                        }
                        disabled={feedbackSent !== null}
                        title="Negative reinforcement"
                      >
                        <ThumbsDown size={15} />
                        Needs work
                      </button>
                    </div>
                  )}

                  {busy && liveActivities.length > 0 && (
                    <div className="liveActivityFeed">
                      {liveActivities
                        .slice(-6)
                        .map((item) => (
                          <div
                            className={
                              "liveActivityRow status-" +
                              item.status
                            }
                            key={item.id}
                          >
                            <span>{item.phase}</span>
                            <b>{item.label}</b>
                            <small>{item.message}</small>
                          </div>
                        ))}
                    </div>
                  )}
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
                </div>

                <aside className="aiServerLogPanel">
                  <header>
                    <div>
                      <span className="hudEyebrow">
                        AI SERVER / LIVE
                      </span>
                      <h4>Model Traffic</h4>
                    </div>
                    <Server size={15} />
                  </header>

                  <div className="aiServerStatus">
                    <i
                      className={
                        streamConnected ? "online" : ""
                      }
                    />
                    <span>
                      {streamConnected
                        ? "EVENT STREAM CONNECTED"
                        : "EVENT STREAM OFFLINE"}
                    </span>
                  </div>

                  <div
                    className="aiServerLogList"
                    role="log"
                    aria-live="polite"
                  >
                    {serverLogRows.length === 0 && (
                      <div className="aiServerLogEmpty">
                        No model calls yet.
                      </div>
                    )}

                    {serverLogRows.map((item) => (
                      <div
                        className={
                          "aiServerLogRow status-" +
                          item.status
                        }
                        key={item.id}
                      >
                        <div className="aiServerLogTop">
                          <b>{item.actorName}</b>
                          <span>{item.status}</span>
                        </div>
                        <small>
                          {item.providerId} / {item.model}
                        </small>
                        <div className="aiServerLogMeta">
                          <span>
                            <Clock3 size={10} />
                            {item.durationMs === null
                              ? item.live
                                ? "Live"
                                : "—"
                              : item.durationMs < 1000
                                ? item.durationMs + " ms"
                                : (
                                    item.durationMs / 1000
                                  ).toFixed(2) + " s"}
                          </span>
                          <time>
                            {item.timestamp
                              ? new Date(
                                  item.timestamp,
                                ).toLocaleTimeString()
                              : "—"}
                          </time>
                        </div>
                        {item.error && (
                          <em>{item.error}</em>
                        )}
                      </div>
                    ))}
                  </div>

                  <button
                    className="aiServerLogOpen"
                    type="button"
                    onClick={() => setView("logs")}
                  >
                    Open full LLM logs
                  </button>
                </aside>
              </div>
            </section>
          </div>
        )}
      </section>

      <CommandConsole
        open={consoleOpen}
        lines={consoleLines}
        onClose={() => setConsoleOpen(false)}
        onClear={() => setConsoleLines([])}
      />

      <HudModal
        open={projectDialog}
        onClose={() => setProjectDialog(false)}
        title="Initialize Project"
        eyebrow="PROJECT / NEW"
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
        eyebrow="AGENT / CONFIGURATION"
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

          <label className="agentContextField">
            Agent context
            <textarea
              value={agentContext}
              onChange={(event) =>
                setAgentContext(event.target.value)
              }
              maxLength={8000}
              rows={7}
              placeholder="Describe this agent's responsibilities, scope, constraints, and what good completion looks like."
            />
          </label>
          <div className="agentContextTemplates">
            <span>STARTING TEMPLATES</span>
            <button
              className="secondaryButton"
              type="button"
              onClick={() => {
                setAgentRole("Developer");
                setAgentContext(
                  AGENT_CONTEXT_TEMPLATES.Developer,
                );
              }}
            >
              Developer
            </button>
            <button
              className="secondaryButton"
              type="button"
              onClick={() => {
                setAgentRole("Tester");
                setAgentContext(
                  AGENT_CONTEXT_TEMPLATES.Tester,
                );
              }}
            >
              Tester
            </button>
          </div>
          <p className="dialogHint">
            Context tells the agent what it is responsible for. Tool access is
            still controlled separately in Capability Matrix.
          </p>

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
        open={agentContextDialog}
        onClose={() => setAgentContextDialog(false)}
        title="Agent Context"
        eyebrow="AGENT / CONTEXT"
        footer={
          <>
            <button
              className="secondaryButton"
              onClick={() => setAgentContextDialog(false)}
            >
              Cancel
            </button>
            <button
              className="primaryButton"
              form="agent-context-form"
              type="submit"
              disabled={busy || !editingAgentContext.trim()}
            >
              <Settings2 size={14} />
              Save context
            </button>
          </>
        }
      >
        <form
          id="agent-context-form"
          className="hudDialogForm"
          onSubmit={saveAgentContext}
        >
          <div className="agentContextIdentity">
            <small>SELECTED WORKER</small>
            <strong>{agent?.name || "No agent selected"}</strong>
            <span>{agent?.role || "—"}</span>
          </div>
          <label className="agentContextField">
            Agent context
            <textarea
              value={editingAgentContext}
              onChange={(event) =>
                setEditingAgentContext(event.target.value)
              }
              maxLength={8000}
              rows={9}
              placeholder="Describe this agent's responsibilities, scope, constraints, and completion criteria."
              autoFocus
            />
          </label>
          <p className="dialogHint">
            The Executive sees a summary of this context when choosing a
            worker, and the worker receives the full context on every task.
            Context does not grant tools or permissions.
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
          notice?.approvalJobId ? (
            <>
              <button
                className="secondaryButton"
                onClick={() => setNotice(null)}
                disabled={approvalBusy}
              >
                Not now
              </button>
              <button
                className="primaryButton"
                onClick={() =>
                  void approveWaitingJob(
                    notice.approvalJobId || "",
                  )
                }
                disabled={approvalBusy}
              >
                <ShieldCheck size={14} />
                {approvalBusy
                  ? "Continuing..."
                  : "Approve & Continue"}
              </button>
            </>
          ) : (
            <button
              className="primaryButton"
              onClick={() => setNotice(null)}
            >
              Acknowledge
            </button>
          )
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
        elevenConfig={voice.elevenConfig}
        elevenVoices={voice.elevenVoices}
        selectedElevenVoice={voice.selectedElevenVoice}
        elevenLoading={voice.elevenLoading}
        elevenStatus={voice.elevenStatus}
        audioStatus={voice.audioStatus}
        wakeSupported={wake.supported}
        wakeState={wake.state}
        lastHeard={wake.lastHeard}
        liveTranscript={wake.liveTranscript}
        finalTranscript={wake.finalTranscript}
        errorMessage={wake.errorMessage}
        onUpdate={voice.update}
        onTest={voice.testVoice}
        onStop={voice.stop}
        onReset={voice.resetSignature}
        onListenNow={() => void wake.listenNow()}
        onRefreshElevenVoices={voice.refreshElevenVoices}
        onSaveElevenLabs={voice.saveElevenLabs}
        onTestElevenLabs={voice.testElevenLabs}
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
