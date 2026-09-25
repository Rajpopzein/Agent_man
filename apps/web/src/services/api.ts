const BASE = "http://localhost:8765";

export type Agent = {
  id: string;
  project_id: string;
  name: string;
  role: string;
  state: string;
  llm: {
    provider_id: string;
    connection_id: string;
    model: string;
    endpoint?: string | null;
  };
};

export type Project = {
  id: string;
  name: string;
  workspace_path: string;
};

export type AgentRun = {
  agent_id: string;
  status: string;
  text: string;
  steps: Array<Record<string, unknown>>;
};

export type AIProvider = {
  id: string;
  label: string;
  default_endpoint: string | null;
  requires_api_key: boolean;
  local: boolean;
};

export type AIConnection = {
  id: string;
  name: string;
  provider_id: string;
  endpoint: string | null;
  default_model: string | null;
  has_secret: boolean;
};

export type AIConnectionTest = {
  ok: boolean;
  provider_id: string;
  endpoint: string | null;
  models: string[];
};

export type MultiAgentParticipant = {
  agent_id: string;
  agent_name: string;
  role: string;
  position: number;
  status: string;
  last_round: number;
};

export type MultiAgentMessage = {
  id: string;
  agent_id: string | null;
  agent_name: string;
  kind: string;
  round_number: number;
  content: string;
  created_at: string;
};

export type MultiAgentTask = {
  id: string;
  project_id: string;
  title: string;
  prompt: string;
  status: string;
  max_rounds: number;
  current_round: number;
  created_at: string;
  completed_at: string | null;
  participants: MultiAgentParticipant[];
  messages: MultiAgentMessage[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || response.statusText);
  }
  return response.json();
}

export const api = {
  health: () => request("/health"),
  projects: () => request<Project[]>("/api/projects"),
  createProject: (payload: { name: string; workspace_path: string }) =>
    request<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  agents: (projectId: string) =>
    request<Agent[]>("/api/projects/" + projectId + "/agents"),
  createAgent: (payload: unknown) =>
    request<Agent>("/api/agents", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  runAgent: (
    agentId: string,
    prompt: string,
    allowTerminal: boolean,
    endpoint?: string | null,
  ) =>
    request<AgentRun>("/api/agents/" + agentId + "/execute", {
      method: "POST",
      body: JSON.stringify({
        prompt,
        allow_terminal: allowTerminal,
        endpoint: endpoint || undefined,
      }),
    }),
  aiProviders: () => request<AIProvider[]>("/api/ai/providers"),
  aiConnections: () => request<AIConnection[]>("/api/ai/connections"),
  createAIConnection: (payload: {
    name: string;
    provider_id: string;
    endpoint?: string | null;
    default_model?: string | null;
    api_key?: string | null;
  }) =>
    request<AIConnection>("/api/ai/connections", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateAIConnection: (
    connectionId: string,
    payload: {
      name?: string;
      endpoint?: string | null;
      default_model?: string | null;
      api_key?: string | null;
      clear_secret?: boolean;
    },
  ) =>
    request<AIConnection>("/api/ai/connections/" + connectionId, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteAIConnection: (connectionId: string) =>
    request<{ deleted: boolean; id: string }>(
      "/api/ai/connections/" + connectionId,
      { method: "DELETE" },
    ),
  testAIConnection: (connectionId: string) =>
    request<AIConnectionTest>(
      "/api/ai/connections/" + connectionId + "/test",
      { method: "POST" },
    ),
  multiAgentTasks: (projectId: string) =>
    request<MultiAgentTask[]>(
      "/api/multi-agent/projects/" + projectId + "/tasks",
    ),
  createMultiAgentTask: (payload: {
    project_id: string;
    title: string;
    prompt: string;
    agent_ids: string[];
    max_rounds: number;
  }) =>
    request<MultiAgentTask>("/api/multi-agent/tasks", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  runMultiAgentTask: (taskId: string, allowTerminal: boolean) =>
    request<MultiAgentTask>(
      "/api/multi-agent/tasks/" + taskId + "/run",
      {
        method: "POST",
        body: JSON.stringify({ allow_terminal: allowTerminal }),
      },
    ),
  multiAgentTask: (taskId: string) =>
    request<MultiAgentTask>("/api/multi-agent/tasks/" + taskId),
};
