import { useEffect, useMemo, useState } from "react";
import {
  Code2,
  FolderSearch,
  GitBranch,
  Globe2,
  Power,
  ShieldAlert,
  TerminalSquare,
  Wrench,
} from "lucide-react";

import { api, Agent, AgentTool, Tool } from "../../services/api";

type Props = {
  agents: Agent[];
};

function iconFor(category: string) {
  if (category === "filesystem") return <FolderSearch size={17} />;
  if (category === "git") return <GitBranch size={17} />;
  if (category === "development") return <Code2 size={17} />;
  if (category === "terminal") return <TerminalSquare size={17} />;
  if (category === "network") return <Globe2 size={17} />;
  return <Wrench size={17} />;
}

export default function ToolsPage({ agents }: Props) {
  const [tools, setTools] = useState<Tool[]>([]);
  const [agentId, setAgentId] = useState(agents[0]?.id || "");
  const [agentTools, setAgentTools] = useState<AgentTool[]>([]);
  const [status, setStatus] = useState("");

  async function loadTools() {
    setTools(await api.tools());
  }

  async function loadAgentTools(id: string) {
    if (!id) {
      setAgentTools([]);
      return;
    }
    setAgentTools(await api.agentTools(id));
  }

  useEffect(() => {
    void loadTools();
  }, []);

  useEffect(() => {
    if (!agents.some((agent) => agent.id === agentId)) {
      setAgentId(agents[0]?.id || "");
    }
  }, [agents, agentId]);

  useEffect(() => {
    void loadAgentTools(agentId);
  }, [agentId]);

  const grouped = useMemo(() => {
    const result: Record<string, Tool[]> = {};
    for (const tool of tools) {
      if (!result[tool.category]) result[tool.category] = [];
      result[tool.category].push(tool);
    }
    return result;
  }, [tools]);

  const assignmentMap = useMemo(
    () =>
      Object.fromEntries(
        agentTools.map((tool) => [tool.name, tool]),
      ),
    [agentTools],
  );

  async function toggleGlobal(tool: Tool) {
    try {
      await api.setToolEnabled(tool.name, !tool.enabled);
      await Promise.all([
        loadTools(),
        loadAgentTools(agentId),
      ]);
      setStatus(
        tool.name +
          " is now " +
          (!tool.enabled ? "enabled" : "disabled") +
          " globally.",
      );
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function toggleAgent(tool: Tool) {
    if (!agentId) return;
    const current = assignmentMap[tool.name]?.assigned ?? false;
    try {
      await api.setAgentTool(agentId, tool.name, !current);
      await loadAgentTools(agentId);
      setStatus(
        tool.name +
          " " +
          (!current ? "assigned to" : "removed from") +
          " the selected agent.",
      );
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <section className="toolsPage">
      <div className="sectionHeading">
        <div>
          <h2>Tools</h2>
          <p>
            Built-in capabilities are registered by the trusted runtime.
            Worker agents only see tools assigned here. Agent Man Executive
            sees every globally enabled runtime tool.
          </p>
        </div>
        <span className="connectionCount">
          {tools.filter((tool) => tool.enabled).length}/{tools.length} enabled
        </span>
      </div>

      <div className="executiveToolsNotice panel">
        <div>
          <Globe2 size={18} />
          <span>
            <b>Agent Man Executive</b>
            <small>
              Automatically receives every globally enabled runtime tool.
              EXECUTE, NETWORK, and destructive operations still require the
              run permissions from Command Core.
            </small>
          </span>
        </div>
        <strong>
          {tools.filter((tool) => tool.enabled).length}/{tools.length} tools
        </strong>
      </div>

      <div className="toolControls panel">
        <label>
          Configure agent
          <select
            value={agentId}
            onChange={(event) => setAgentId(event.target.value)}
          >
            {agents.length === 0 && <option value="">No agents available</option>}
            {agents.map((agent) => (
              <option value={agent.id} key={agent.id}>
                {agent.name} · {agent.role}
              </option>
            ))}
          </select>
        </label>

        <div className="toolLegend">
          <span><i className="riskDot read" /> READ auto</span>
          <span><i className="riskDot write" /> WRITE policy</span>
          <span><i className="riskDot execute" /> EXECUTE approval</span>
          <span><i className="riskDot network" /> NETWORK approval</span>
          <span><i className="riskDot destructive" /> DESTRUCTIVE approval</span>
        </div>
      </div>

      {Object.entries(grouped).map(([category, categoryTools]) => (
        <section className="toolCategory" key={category}>
          <h3>{category}</h3>
          <div className="toolGrid">
            {categoryTools.map((tool) => {
              const assignment = assignmentMap[tool.name];
              const assigned = Boolean(assignment?.assigned);
              return (
                <article className="toolCard panel" key={tool.name}>
                  <div className="toolHeader">
                    <div className="toolIcon">{iconFor(category)}</div>
                    <div>
                      <h4>{tool.name}</h4>
                      <small>v{tool.version} · built-in</small>
                    </div>
                    <span className={"riskBadge " + tool.risk}>
                      {tool.risk}
                    </span>
                  </div>

                  <p>{tool.description}</p>

                  <div className="toolActions">
                    <button
                      className={tool.enabled ? "toolToggle on" : "toolToggle"}
                      onClick={() => void toggleGlobal(tool)}
                    >
                      <Power size={14} />
                      Runtime {tool.enabled ? "on" : "off"}
                    </button>

                    <button
                      className={
                        assigned && tool.enabled
                          ? "toolToggle assigned"
                          : "toolToggle"
                      }
                      disabled={!agentId || !tool.enabled}
                      onClick={() => void toggleAgent(tool)}
                    >
                      {tool.risk === "destructive" ? (
                        <ShieldAlert size={14} />
                      ) : (
                        <Wrench size={14} />
                      )}
                      {assigned ? "Assigned" : "Not assigned"}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      ))}

      {status && <div className="connectionStatus">{status}</div>}
    </section>
  );
}
