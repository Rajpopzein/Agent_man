const BASE = "http://localhost:8765";

export type Agent = {
  id: string;
  project_id: string;
  name: string;
  role: string;
  context: string;
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

export type ElevenLabsVoiceConfig = {
  provider_id: "elevenlabs";
  voice_id: string;
  model_id: string;
  output_format: string;
  has_secret: boolean;
};

export type ElevenLabsVoice = {
  voice_id: string;
  name: string;
  category: string;
  description: string;
  preview_url: string | null;
  labels: Record<string, string>;
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

export type Tool = {
  name: string;
  description: string;
  category: string;
  risk: string;
  version: string;
  builtin: boolean;
  enabled: boolean;
};

export type AgentTool = {
  name: string;
  description: string;
  category: string;
  risk: string;
  version: string;
  globally_enabled: boolean;
  assigned: boolean;
};

export type EffectiveToolAccess = {
  project_id: string;
  count: number;
  tools: Array<{
    name: string;
    category: string;
    risk: string;
    description: string;
    approval_gate: "exec" | "net" | "hw" | "delete" | null;
    permission: string | null;
  }>;
};

export type WorkflowNode = {
  id: string;
  key: string;
  name: string;
  agent_id: string;
  agent_name: string;
  role: string;
  instructions: string;
  position: number;
  on_success_key: string | null;
  on_failure_key: string | null;
  max_retries: number;
};

export type Workflow = {
  id: string;
  project_id: string;
  name: string;
  description: string;
  start_node_id: string | null;
  created_at: string;
  nodes: WorkflowNode[];
};

export type WorkflowRunStep = {
  id: string;
  node_id: string;
  node_name: string;
  agent_id: string;
  agent_name: string;
  attempt: number;
  status: string;
  outcome: string | null;
  output_text: string;
  created_at: string;
};

export type WorkflowRun = {
  id: string;
  workflow_id: string;
  project_id: string;
  status: string;
  current_node_id: string | null;
  input_prompt: string;
  last_output: string;
  step_count: number;
  created_at: string;
  completed_at: string | null;
  steps: WorkflowRunStep[];
};

export type MainAgentConfig = {
  project_id: string;
  connection_id: string;
  provider_id: string;
  model: string;
  endpoint: string | null;
  context_limit: number | null;
  temperature: number;
};

export type MainAgentMessage = {
  id: string;
  role: string;
  content: string;
  created_at: string;
};

export type MainAgentReply = {
  status: string;
  text: string;
  steps: Array<Record<string, unknown>>;
};

export type RuntimeEvent = {
  id: string;
  sequence: number;
  type: string;
  timestamp: string;
  project_id?: string;
  agent_id?: string;
  agent_name?: string;
  agent_role?: string;
  state?: string;
  [key: string]: unknown;
};

export type LLMLog = {
  id: string;
  project_id: string | null;
  actor_id: string | null;
  actor_name: string;
  actor_role: string;
  provider_id: string;
  model: string;
  endpoint: string | null;
  status: string;
  duration_ms: number;
  request_json: string;
  response_text: string;
  error_text: string;
  created_at: string;
};

function legacyApprovalMetadata(
  toolName: string,
): {
  approval_gate: "exec" | "net" | "hw" | "delete" | null;
  permission: string | null;
} {
  if (toolName === "delete_path") {
    return {
      approval_gate: "delete",
      permission: "project.files.delete",
    };
  }

  if (
    [
      "run_command",
      "git_commit",
      "run_tests",
      "run_build",
      "lint",
      "start_process",
      "stop_process",
    ].includes(toolName)
  ) {
    return {
      approval_gate: "exec",
      permission: "terminal.execute",
    };
  }

  if (toolName === "http_get") {
    return {
      approval_gate: "net",
      permission: "network.internet",
    };
  }

  if (
    [
      "serial_open",
      "serial_read",
      "serial_write",
    ].includes(toolName)
  ) {
    return {
      approval_gate: "hw",
      permission: "hardware.serial",
    };
  }

  return {
    approval_gate: null,
    permission: null,
  };
}


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
  runtimeEventsUrl: (projectId: string) =>
    BASE +
    "/api/events/stream?project_id=" +
    encodeURIComponent(projectId),
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
  updateAgent: (
    agentId: string,
    payload: {
      name?: string;
      role?: string;
      context?: string;
    },
  ) =>
    request<Agent>("/api/agents/" + agentId, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteAgent: (agentId: string) =>
    request<{ deleted: boolean; id: string }>(
      "/api/agents/" + agentId,
      { method: "DELETE" },
    ),
  runAgent: (
    agentId: string,
    prompt: string,
    allowTerminal: boolean,
    endpoint?: string | null,
    allowDelete = false,
    allowNetwork = false,
    allowHardware = false,
  ) =>
    request<AgentRun>("/api/agents/" + agentId + "/execute", {
      method: "POST",
      body: JSON.stringify({
        prompt,
        allow_terminal: allowTerminal,
        allow_delete: allowDelete,
        allow_network: allowNetwork,
        allow_hardware: allowHardware,
        endpoint: endpoint || undefined,
      }),
    }),
  mainAgentConfig: (projectId: string) =>
    request<MainAgentConfig | null>(
      "/api/main-agent/projects/" + projectId + "/config",
    ),
  configureMainAgent: (
    projectId: string,
    payload: {
      connection_id: string;
      model: string;
      context_limit?: number | null;
      temperature?: number;
    },
  ) =>
    request<MainAgentConfig>(
      "/api/main-agent/projects/" + projectId + "/config",
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
    ),
  mainAgentMessages: (projectId: string) =>
    request<MainAgentMessage[]>(
      "/api/main-agent/projects/" + projectId + "/messages",
    ),
  clearMainAgentMessages: (projectId: string) =>
    request<{ cleared: boolean }>(
      "/api/main-agent/projects/" + projectId + "/messages",
      { method: "DELETE" },
    ),
  chatMainAgent: (
    projectId: string,
    message: string,
    allowTerminal: boolean,
    allowDelete: boolean,
    allowNetwork: boolean,
    allowHardware: boolean,
  ) =>
    request<MainAgentReply>(
      "/api/main-agent/projects/" + projectId + "/chat",
      {
        method: "POST",
        body: JSON.stringify({
          message,
          allow_terminal: allowTerminal,
          allow_delete: allowDelete,
          allow_network: allowNetwork,
          allow_hardware: allowHardware,
        }),
      },
    ),
  elevenLabsVoiceConfig: () =>
    request<ElevenLabsVoiceConfig>(
      "/api/voice/elevenlabs/config",
    ),
  configureElevenLabsVoice: (payload: {
    voice_id: string;
    model_id: string;
    output_format: string;
    api_key?: string | null;
    clear_secret?: boolean;
  }) =>
    request<ElevenLabsVoiceConfig>(
      "/api/voice/elevenlabs/config",
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
    ),
  elevenLabsVoices: () =>
    request<ElevenLabsVoice[]>(
      "/api/voice/elevenlabs/voices",
    ),
  testElevenLabsVoice: () =>
    request<{ ok: boolean; voices_visible: number }>(
      "/api/voice/elevenlabs/test",
      { method: "POST" },
    ),
  streamElevenLabsSpeech: async (
    text: string,
    signal?: AbortSignal,
  ) => {
    const response = await fetch(
      BASE + "/api/voice/elevenlabs/speech",
      {
        method: "POST",
        signal,
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ text }),
      },
    );
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(
        payload.detail || response.statusText,
      );
    }
    return response;
  },
  llmLogs: (projectId: string, limit = 200) =>
    request<LLMLog[]>(
      "/api/llm-logs/projects/" + projectId + "?limit=" + limit,
    ),
  clearLLMLogs: (projectId: string) =>
    request<{ cleared: boolean; count: number }>(
      "/api/llm-logs/projects/" + projectId,
      { method: "DELETE" },
    ),
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
  connectionModels: (connectionId: string) =>
    request<{ models: string[] }>(
      "/api/ai/connections/" + connectionId + "/models",
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
  runMultiAgentTask: (
    taskId: string,
    allowTerminal: boolean,
    allowDelete = false,
    extendRounds = 0,
    allowNetwork = false,
    allowHardware = false,
  ) =>
    request<MultiAgentTask>(
      "/api/multi-agent/tasks/" + taskId + "/run",
      {
        method: "POST",
        body: JSON.stringify({
          allow_terminal: allowTerminal,
          allow_delete: allowDelete,
          allow_network: allowNetwork,
          allow_hardware: allowHardware,
          extend_rounds: extendRounds,
        }),
      },
    ),
  multiAgentTask: (taskId: string) =>
    request<MultiAgentTask>("/api/multi-agent/tasks/" + taskId),
  tools: () => request<Tool[]>("/api/tools"),
  setToolEnabled: (toolName: string, enabled: boolean) =>
    request<Tool>("/api/tools/" + toolName, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }),
  mainAgentTools: (projectId: string) =>
    request<AgentTool[]>(
      "/api/tools/main-agent/" + projectId,
    ),
  effectiveMainAgentTools: (projectId: string) =>
    request<EffectiveToolAccess>(
      "/api/tools/main-agent/" + projectId + "/effective",
    ),
  setMainAgentTool: (
    projectId: string,
    toolName: string,
    enabled: boolean,
  ) =>
    request<AgentTool>(
      "/api/tools/main-agent/" + projectId + "/" + toolName,
      {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      },
    ),
  setMainAgentToolAssignments: async (
    projectId: string,
    toolNames: string[],
  ) => {
    try {
      return await request<EffectiveToolAccess>(
        "/api/tools/main-agent/" + projectId + "/bulk/set",
        {
          method: "PUT",
          body: JSON.stringify({ tool_names: toolNames }),
        },
      );
    } catch (error) {
      if (
        !(error instanceof Error) ||
        !/not found/i.test(error.message)
      ) {
        throw error;
      }

      const requested = new Set(toolNames);
      const current = await request<AgentTool[]>(
        "/api/tools/main-agent/" + projectId,
      );

      for (const tool of current) {
        const shouldAssign =
          tool.globally_enabled && requested.has(tool.name);
        if (tool.assigned === shouldAssign) continue;

        await request<AgentTool>(
          "/api/tools/main-agent/" +
            projectId +
            "/" +
            tool.name,
          {
            method: "PUT",
            body: JSON.stringify({
              enabled: shouldAssign,
            }),
          },
        );
      }

      const updated = await request<AgentTool[]>(
        "/api/tools/main-agent/" + projectId,
      );
      const effectiveTools = updated
        .filter(
          (tool) =>
            tool.globally_enabled && tool.assigned,
        )
        .map((tool) => ({
          name: tool.name,
          category: tool.category,
          risk: tool.risk,
          description: tool.description,
          ...legacyApprovalMetadata(tool.name),
        }));

      return {
        project_id: projectId,
        count: effectiveTools.length,
        tools: effectiveTools,
      };
    }
  },
  grantAllMainAgentTools: (projectId: string) =>
    request<{ updated: number; assigned: string[] }>(
      "/api/tools/main-agent/" + projectId + "/bulk/grant-all",
      { method: "PUT" },
    ),
  revokeAllMainAgentTools: (projectId: string) =>
    request<{ updated: number; assigned: string[] }>(
      "/api/tools/main-agent/" + projectId + "/bulk/revoke-all",
      { method: "PUT" },
    ),
  agentTools: (agentId: string) =>
    request<AgentTool[]>("/api/tools/agents/" + agentId),
  setAgentTool: (
    agentId: string,
    toolName: string,
    enabled: boolean,
  ) =>
    request<AgentTool>(
      "/api/tools/agents/" + agentId + "/" + toolName,
      {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      },
    ),
  workflows: (projectId: string) =>
    request<Workflow[]>(
      "/api/orchestration/projects/" + projectId + "/workflows",
    ),
  createWorkflow: (payload: {
    project_id: string;
    name: string;
    description: string;
    nodes: Array<{
      key: string;
      name: string;
      agent_id: string;
      instructions: string;
      on_success_key?: string | null;
      on_failure_key?: string | null;
      max_retries: number;
    }>;
  }) =>
    request<Workflow>("/api/orchestration/workflows", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  workflowRuns: (workflowId: string) =>
    request<WorkflowRun[]>(
      "/api/orchestration/workflows/" + workflowId + "/runs",
    ),
  runWorkflow: (
    workflowId: string,
    inputPrompt: string,
    allowTerminal: boolean,
    allowDelete: boolean,
    allowNetwork: boolean,
    allowHardware: boolean,
  ) =>
    request<WorkflowRun>(
      "/api/orchestration/workflows/" + workflowId + "/runs",
      {
        method: "POST",
        body: JSON.stringify({
          input_prompt: inputPrompt,
          allow_terminal: allowTerminal,
          allow_delete: allowDelete,
          allow_network: allowNetwork,
          allow_hardware: allowHardware,
        }),
      },
    ),
  resumeWorkflowRun: (
    runId: string,
    inputPrompt: string,
    allowTerminal: boolean,
    allowDelete: boolean,
    allowNetwork: boolean,
    allowHardware: boolean,
  ) =>
    request<WorkflowRun>(
      "/api/orchestration/runs/" + runId + "/resume",
      {
        method: "POST",
        body: JSON.stringify({
          input_prompt: inputPrompt,
          allow_terminal: allowTerminal,
          allow_delete: allowDelete,
          allow_network: allowNetwork,
          allow_hardware: allowHardware,
        }),
      },
    ),
};
