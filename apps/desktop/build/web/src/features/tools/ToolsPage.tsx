import { useEffect, useMemo, useState } from "react";
import {
  Code2,
  Cpu,
  FolderSearch,
  GitBranch,
  Globe2,
  Power,
  Save,
  ShieldAlert,
  Sparkles,
  TerminalSquare,
  Wrench,
} from "lucide-react";

import {
  api,
  Agent,
  AgentTool,
  Project,
  Tool,
} from "../../services/api";

type Props = {
  project: Project | null;
  agents: Agent[];
};

function iconFor(category: string) {
  if (category === "filesystem") return <FolderSearch size={17} />;
  if (category === "git") return <GitBranch size={17} />;
  if (category === "development") return <Code2 size={17} />;
  if (category === "terminal") return <TerminalSquare size={17} />;
  if (category === "network") return <Globe2 size={17} />;
  if (category === "hardware") return <Cpu size={17} />;
  return <Wrench size={17} />;
}

const EXECUTIVE_TARGET = "__agent_man_executive__";

export default function ToolsPage({
  project,
  agents,
}: Props) {
  const [tools, setTools] = useState<Tool[]>([]);
  const [targetId, setTargetId] = useState(
    project ? EXECUTIVE_TARGET : agents[0]?.id || "",
  );
  const [targetTools, setTargetTools] = useState<AgentTool[]>([]);
  const [executiveDraft, setExecutiveDraft] =
    useState<Set<string>>(new Set());
  const [executiveEffectiveCount, setExecutiveEffectiveCount] =
    useState<number | null>(null);
  const [executiveSaving, setExecutiveSaving] = useState(false);
  const [status, setStatus] = useState("");

  const configuringExecutive =
    targetId === EXECUTIVE_TARGET;

  async function loadTools() {
    setTools(await api.tools());
  }

  async function loadTargetTools(id: string) {
    if (!id) {
      setTargetTools([]);
      return;
    }

    if (id === EXECUTIVE_TARGET) {
      if (!project) {
        setTargetTools([]);
        return;
      }
      const loaded = await api.mainAgentTools(project.id);
      setTargetTools(loaded);
      setExecutiveDraft(
        new Set(
          loaded
            .filter((tool) => tool.globally_enabled && tool.assigned)
            .map((tool) => tool.name),
        ),
      );
      try {
        const effective = await api.effectiveMainAgentTools(project.id);
        setExecutiveEffectiveCount(effective.count);
      } catch {
        setExecutiveEffectiveCount(null);
      }
      return;
    }

    setTargetTools(await api.agentTools(id));
  }

  useEffect(() => {
    void loadTools();
  }, []);

  useEffect(() => {
    if (targetId === EXECUTIVE_TARGET && project) {
      return;
    }

    if (!agents.some((agent) => agent.id === targetId)) {
      setTargetId(
        project
          ? EXECUTIVE_TARGET
          : agents[0]?.id || "",
      );
    }
  }, [project?.id, agents, targetId]);

  useEffect(() => {
    void loadTargetTools(targetId);
  }, [targetId, project?.id]);

  const grouped = useMemo(() => {
    const result: Record<string, Tool[]> = {};
    for (const tool of tools) {
      if (!result[tool.category]) {
        result[tool.category] = [];
      }
      result[tool.category].push(tool);
    }
    return result;
  }, [tools]);

  const assignmentMap = useMemo(
    () =>
      Object.fromEntries(
        targetTools.map((tool) => [tool.name, tool]),
      ),
    [targetTools],
  );

  const persistedExecutiveNames = useMemo(
    () =>
      new Set(
        targetTools
          .filter((tool) => tool.globally_enabled && tool.assigned)
          .map((tool) => tool.name),
      ),
    [targetTools],
  );

  const executiveDraftChanged = useMemo(() => {
    if (!configuringExecutive) return false;
    if (executiveDraft.size !== persistedExecutiveNames.size) return true;
    for (const name of executiveDraft) {
      if (!persistedExecutiveNames.has(name)) return true;
    }
    return false;
  }, [configuringExecutive, executiveDraft, persistedExecutiveNames]);

  const assignedCount = configuringExecutive
    ? executiveDraft.size
    : targetTools.filter(
        (tool) =>
          tool.globally_enabled && tool.assigned,
      ).length;

  async function toggleGlobal(tool: Tool) {
    try {
      await api.setToolEnabled(
        tool.name,
        !tool.enabled,
      );
      await Promise.all([
        loadTools(),
        loadTargetTools(targetId),
      ]);
      setStatus(
        tool.name +
          " is now " +
          (!tool.enabled ? "enabled" : "disabled") +
          " globally.",
      );
    } catch (error) {
      setStatus(
        error instanceof Error
          ? error.message
          : String(error),
      );
    }
  }

  function selectAllExecutiveTools() {
    setExecutiveDraft(
      new Set(
        targetTools
          .filter((tool) => tool.globally_enabled)
          .map((tool) => tool.name),
      ),
    );
    setStatus("All enabled Executive tools selected. Apply to save.");
  }

  function clearExecutiveTools() {
    setExecutiveDraft(new Set());
    setStatus("Executive tool selection cleared. Apply to save.");
  }

  async function verifyExecutiveAccess() {
    if (!project) return;
    try {
      const effective = await api.effectiveMainAgentTools(project.id);
      setExecutiveEffectiveCount(effective.count);
      setStatus(
        "Runtime confirms " +
          effective.count +
          " effective Executive tools.",
      );
    } catch (error) {
      setStatus(
        "Unable to verify Executive access: " +
          (error instanceof Error ? error.message : String(error)),
      );
    }
  }

  async function applyExecutiveTools() {
    if (!project) return;
    setExecutiveSaving(true);
    setStatus("Saving Executive tool access...");
    try {
      const effective = await api.setMainAgentToolAssignments(
        project.id,
        Array.from(executiveDraft).sort(),
      );
      setExecutiveEffectiveCount(effective.count);
      await loadTargetTools(EXECUTIVE_TARGET);
      setStatus(
        "Saved. Runtime confirms " +
          effective.count +
          " effective Executive tools.",
      );
    } catch (error) {
      setStatus(
        "Unable to save Executive tool access: " +
          (error instanceof Error ? error.message : String(error)),
      );
    } finally {
      setExecutiveSaving(false);
    }
  }

  async function toggleTarget(tool: Tool) {
    if (!targetId) return;

    const current =
      assignmentMap[tool.name]?.assigned ?? false;

    if (configuringExecutive) {
      setExecutiveDraft((draft) => {
        const next = new Set(draft);
        if (next.has(tool.name)) {
          next.delete(tool.name);
        } else {
          next.add(tool.name);
        }
        return next;
      });
      setStatus(
        "Executive selection changed. Press Apply Executive Access to save.",
      );
      return;
    }

    try {
      await api.setAgentTool(
        targetId,
        tool.name,
        !current,
      );

      await loadTargetTools(targetId);
      setStatus(
        tool.name +
          " " +
          (!current ? "assigned to" : "removed from") +
          " the selected worker.",
      );
    } catch (error) {
      setStatus(
        error instanceof Error
          ? error.message
          : String(error),
      );
    }
  }

  return (
    <section className="toolsPage">
      <div className="sectionHeading">
        <div>
          <h2>Tools</h2>
          <p>
            Configure exactly which runtime capabilities Agent Man Executive
            and each worker agent can see and execute.
          </p>
        </div>
        <span className="connectionCount">
          {tools.filter((tool) => tool.enabled).length}/{tools.length} runtime
        </span>
      </div>

      <div className="executiveToolsNotice panel">
        <div>
          <Sparkles size={18} />
          <span>
            <b>
              {configuringExecutive
                ? "Agent Man Executive"
                : "Worker tool assignment"}
            </b>
            <small>
              {configuringExecutive
                ? assignedCount +
                  " globally enabled tools are currently exposed to the Executive model."
                : "Worker agents only receive tools explicitly assigned to them."}
            </small>
          </span>
        </div>
        <div className="executiveToolsActions">
          <strong>
            {assignedCount} selected
            {configuringExecutive &&
              executiveEffectiveCount !== null &&
              " · " + executiveEffectiveCount + " effective"}
          </strong>
          {configuringExecutive && (
            <>
              <button
                className="secondaryButton"
                onClick={() => void verifyExecutiveAccess()}
              >
                Verify runtime
              </button>
              <button
                className="secondaryButton"
                onClick={selectAllExecutiveTools}
              >
                Select all enabled
              </button>
              <button
                className="secondaryButton"
                onClick={clearExecutiveTools}
              >
                Clear
              </button>
              <button
                className="primaryButton"
                onClick={() => void applyExecutiveTools()}
                disabled={executiveSaving || !executiveDraftChanged}
              >
                <Save size={13} />
                {executiveSaving ? "Saving..." : "Apply Executive Access"}
              </button>
            </>
          )}
        </div>
      </div>

      <div className="toolControls panel">
        <label>
          Configure target
          <select
            value={targetId}
            onChange={(event) =>
              setTargetId(event.target.value)
            }
          >
            {project && (
              <option value={EXECUTIVE_TARGET}>
                Agent Man · Executive
              </option>
            )}
            {agents.map((agent) => (
              <option value={agent.id} key={agent.id}>
                {agent.name} · {agent.role}
              </option>
            ))}
            {!project && agents.length === 0 && (
              <option value="">
                No agent target available
              </option>
            )}
          </select>
        </label>

        <div className="toolLegend">
          <span>
            <i className="riskDot read" /> READ auto
          </span>
          <span>
            <i className="riskDot write" /> WRITE policy
          </span>
          <span>
            <i className="riskDot execute" /> EXECUTE approval
          </span>
          <span>
            <i className="riskDot network" /> NETWORK approval
          </span>
          <span>
            <i className="riskDot hardware" /> HARDWARE approval
          </span>
          <span>
            <i className="riskDot destructive" /> DESTRUCTIVE approval
          </span>
        </div>
      </div>

      {Object.entries(grouped).map(
        ([category, categoryTools]) => (
          <section
            className="toolCategory"
            key={category}
          >
            <h3>{category}</h3>
            <div className="toolGrid">
              {categoryTools.map((tool) => {
                const assignment =
                  assignmentMap[tool.name];
                const assigned = configuringExecutive
                  ? executiveDraft.has(tool.name)
                  : Boolean(assignment?.assigned);

                return (
                  <article
                    className="toolCard panel"
                    key={tool.name}
                  >
                    <div className="toolHeader">
                      <div className="toolIcon">
                        {iconFor(category)}
                      </div>
                      <div>
                        <h4>{tool.name}</h4>
                        <small>
                          v{tool.version} · built-in
                        </small>
                      </div>
                      <span
                        className={
                          "riskBadge " + tool.risk
                        }
                      >
                        {tool.risk}
                      </span>
                    </div>

                    <p>{tool.description}</p>

                    <div className="toolActions">
                      <button
                        className={
                          tool.enabled
                            ? "toolToggle on"
                            : "toolToggle"
                        }
                        onClick={() =>
                          void toggleGlobal(tool)
                        }
                      >
                        <Power size={14} />
                        Runtime{" "}
                        {tool.enabled ? "on" : "off"}
                      </button>

                      <button
                        className={
                          assigned && tool.enabled
                            ? "toolToggle assigned"
                            : "toolToggle"
                        }
                        disabled={
                          !targetId || !tool.enabled
                        }
                        onClick={() =>
                          void toggleTarget(tool)
                        }
                      >
                        {tool.risk ===
                        "destructive" ? (
                          <ShieldAlert size={14} />
                        ) : (
                          <Wrench size={14} />
                        )}
                        {assigned
                          ? "Assigned"
                          : "Not assigned"}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        ),
      )}

      {configuringExecutive && executiveDraftChanged && (
        <div className="connectionStatus">
          Unsaved Executive tool selections. Press Apply Executive Access.
        </div>
      )}

      {status && (
        <div className="connectionStatus">
          {status}
        </div>
      )}
    </section>
  );
}
