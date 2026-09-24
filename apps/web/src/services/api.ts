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
};
