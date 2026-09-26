import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  BrainCircuit,
  CheckCircle2,
  Cpu,
  Power,
  RefreshCw,
  Save,
  Settings2,
  Sparkles,
  Wrench,
} from "lucide-react";

import {
  api,
  AgentTool,
  AIConnection,
  EffectiveToolAccess,
  MainAgentConfig,
  Project,
} from "../../services/api";

type Props = {
  project: Project | null;
  connections: AIConnection[];
  mainConfig: MainAgentConfig | null;
  onConfigured: (config: MainAgentConfig) => void;
};

export default function SettingsPage({
  project,
  connections,
  mainConfig,
  onConfigured,
}: Props) {
  const [connectionId, setConnectionId] = useState("");
  const [model, setModel] = useState("");
  const [detectedModels, setDetectedModels] = useState<string[]>([]);
  const [detecting, setDetecting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState("");
  const [executiveTools, setExecutiveTools] = useState<AgentTool[]>([]);
  const [effectiveTools, setEffectiveTools] =
    useState<EffectiveToolAccess | null>(null);
  const [toolStatus, setToolStatus] = useState("");
  const [verifyingTools, setVerifyingTools] = useState(false);

  useEffect(() => {
    const connection =
      connections.find((item) => item.id === mainConfig?.connection_id) ||
      connections[0] ||
      null;

    setConnectionId(connection?.id || "");
    setModel(mainConfig?.model || connection?.default_model || "");
    setDetectedModels([]);
  }, [project?.id, mainConfig?.connection_id, mainConfig?.model, connections]);

  useEffect(() => {
    if (!project) {
      setExecutiveTools([]);
      setEffectiveTools(null);
      return;
    }
    void loadExecutiveTools(project.id);
    void verifyExecutiveTools(project.id, false);
  }, [project?.id]);

  async function loadExecutiveTools(projectId: string) {
    try {
      setExecutiveTools(await api.mainAgentTools(projectId));
    } catch (error) {
      setToolStatus(
        error instanceof Error ? error.message : String(error),
      );
    }
  }

  async function verifyExecutiveTools(
    projectId: string,
    announce = true,
  ) {
    setVerifyingTools(true);
    try {
      const effective = await api.effectiveMainAgentTools(projectId);
      setEffectiveTools(effective);
      if (announce) {
        setToolStatus(
          effective.count > 0
            ? "Runtime verified: Agent Man receives " +
                effective.count +
                " effective tools."
            : "Runtime verified: Agent Man currently receives 0 effective tools.",
        );
      }
      return effective;
    } catch (error) {
      setEffectiveTools(null);
      if (announce) {
        setToolStatus(
          "Unable to verify Executive runtime access: " +
            (error instanceof Error ? error.message : String(error)),
        );
      }
      return null;
    } finally {
      setVerifyingTools(false);
    }
  }

  const selectedConnection = useMemo(
    () => connections.find((item) => item.id === connectionId) || null,
    [connections, connectionId],
  );

  const groupedTools = useMemo(() => {
    const groups: Record<string, AgentTool[]> = {};
    for (const tool of executiveTools) {
      if (!groups[tool.category]) groups[tool.category] = [];
      groups[tool.category].push(tool);
    }
    return groups;
  }, [executiveTools]);

  const assignedToolCount = executiveTools.filter(
    (tool) => tool.globally_enabled && tool.assigned,
  ).length;

  function selectConnection(id: string) {
    const connection = connections.find((item) => item.id === id);
    setConnectionId(id);
    setModel(connection?.default_model || "");
    setDetectedModels([]);
    setStatus("");
  }

  async function detectModels() {
    if (!connectionId) return;

    setDetecting(true);
    setStatus("Detecting models from selected AI connection...");
    try {
      const result = await api.connectionModels(connectionId);
      setDetectedModels(result.models);

      if (result.models.length === 0) {
        setStatus(
          "Connection responded successfully, but it returned no discoverable models.",
        );
        return;
      }

      if (!model || !result.models.includes(model)) {
        const preferred =
          selectedConnection?.default_model &&
          result.models.includes(selectedConnection.default_model)
            ? selectedConnection.default_model
            : result.models[0];
        setModel(preferred);
      }

      setStatus(
        "Detected " +
          result.models.length +
          " model" +
          (result.models.length === 1 ? "" : "s") +
          ".",
      );
    } catch (error) {
      setDetectedModels([]);
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setDetecting(false);
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!project || !connectionId || !model.trim()) return;

    setSaving(true);
    setStatus("Saving Agent Man executive configuration...");
    try {
      const configured = await api.configureMainAgent(project.id, {
        connection_id: connectionId,
        model: model.trim(),
        temperature: 0.2,
      });
      onConfigured(configured);
      setStatus("Agent Man executive configuration saved.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  }

  async function toggleExecutiveTool(tool: AgentTool) {
    if (!project || !tool.globally_enabled) return;

    setToolStatus("Updating " + tool.name + "...");
    try {
      const updated = await api.setMainAgentTool(
        project.id,
        tool.name,
        !tool.assigned,
      );
      setExecutiveTools((current) =>
        current.map((item) =>
          item.name === updated.name ? updated : item,
        ),
      );
      await verifyExecutiveTools(project.id, false);
      setToolStatus(
        updated.name +
          (updated.assigned
            ? " now has Executive access."
            : " Executive access removed."),
      );
    } catch (error) {
      setToolStatus(
        "Unable to update Executive tool access: " +
          (error instanceof Error ? error.message : String(error)),
      );
    }
  }

  async function grantAllExecutiveTools() {
    if (!project) return;

    setToolStatus("Granting all enabled runtime tools to Agent Man...");
    try {
      const result = await api.grantAllMainAgentTools(project.id);
      await loadExecutiveTools(project.id);
      const effective = await verifyExecutiveTools(
        project.id,
        false,
      );
      setToolStatus(
        "Granted " +
          result.updated +
          " enabled runtime tools to Agent Man Executive. Runtime now exposes " +
          (effective?.count ?? 0) +
          " tools.",
      );
    } catch (error) {
      setToolStatus(
        "Unable to grant Executive tool access: " +
          (error instanceof Error ? error.message : String(error)),
      );
    }
  }

  async function revokeAllExecutiveTools() {
    if (!project) return;

    setToolStatus("Removing Executive tool assignments...");
    try {
      const result = await api.revokeAllMainAgentTools(project.id);
      await loadExecutiveTools(project.id);
      await verifyExecutiveTools(project.id, false);
      setToolStatus(
        "Removed " +
          result.updated +
          " Executive tool assignments.",
      );
    } catch (error) {
      setToolStatus(
        "Unable to remove Executive tool access: " +
          (error instanceof Error ? error.message : String(error)),
      );
    }
  }

  async function repairExecutiveTools() {
    if (!project) return;

    setToolStatus("Repairing Executive runtime tool access...");
    try {
      await api.grantAllMainAgentTools(project.id);
      await loadExecutiveTools(project.id);
      const effective = await verifyExecutiveTools(project.id, false);
      setToolStatus(
        effective && effective.count > 0
          ? "Executive tool access repaired. Runtime confirms " +
              effective.count +
              " effective tools."
          : "Repair completed, but runtime still reports 0 effective tools.",
      );
    } catch (error) {
      setToolStatus(
        "Unable to repair Executive tool access: " +
          (error instanceof Error ? error.message : String(error)),
      );
    }
  }

  if (!project) {
    return (
      <section className="panel settingsEmpty">
        <Settings2 size={24} />
        <h3>No project selected</h3>
        <p className="muted">
          Create or select a project before configuring Agent Man.
        </p>
      </section>
    );
  }

  return (
    <section className="settingsPage">
      <div className="sectionHeading">
        <div>
          <h2>Settings</h2>
          <p>
            Configure Agent Man itself here: executive model, model discovery,
            and the exact runtime tools exposed to the Executive.
          </p>
        </div>
        <span className="connectionCount">
          {mainConfig ? "EXECUTIVE ONLINE" : "SETUP REQUIRED"}
        </span>
      </div>

      <div className="settingsGrid">
        <form className="panel executiveSettings" onSubmit={save}>
          <div className="settingsPanelHeader">
            <div className="settingsGlyph">
              <Sparkles size={19} />
            </div>
            <div>
              <small>PRIMARY AGENT</small>
              <h3>Agent Man Executive</h3>
              <p>
                This is the model you talk to. It can use the tools assigned
                below directly, delegate to workers, start peer collaboration,
                or run a saved workflow.
              </p>
            </div>
          </div>

          <label className="settingsField">
            AI connection
            <select
              value={connectionId}
              onChange={(event) => selectConnection(event.target.value)}
            >
              <option value="">Select AI connection</option>
              {connections.map((connection) => (
                <option value={connection.id} key={connection.id}>
                  {connection.name} · {connection.provider_id}
                </option>
              ))}
            </select>
          </label>

          {selectedConnection && (
            <div className="connectionSummary">
              <span>
                <small>PROVIDER</small>
                <b>{selectedConnection.provider_id}</b>
              </span>
              <span>
                <small>ENDPOINT</small>
                <code>{selectedConnection.endpoint || "provider default"}</code>
              </span>
              <span>
                <small>DEFAULT MODEL</small>
                <b>{selectedConnection.default_model || "not set"}</b>
              </span>
            </div>
          )}

          <div className="modelDetectRow">
            <button
              type="button"
              className="secondaryButton"
              onClick={() => void detectModels()}
              disabled={!connectionId || detecting}
            >
              <RefreshCw
                size={14}
                className={detecting ? "spinIcon" : ""}
              />
              {detecting ? "Detecting..." : "Detect Models"}
            </button>

            <span>
              Queries the selected connection directly and loads the models it
              currently exposes.
            </span>
          </div>

          {detectedModels.length > 0 ? (
            <label className="settingsField">
              Executive model
              <select
                value={model}
                onChange={(event) => setModel(event.target.value)}
              >
                {detectedModels.map((item) => (
                  <option value={item} key={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label className="settingsField">
              Executive model
              <input
                value={model}
                onChange={(event) => setModel(event.target.value)}
                placeholder="Detect models or enter a model identifier manually"
              />
            </label>
          )}

          <button
            className="primaryButton settingsSaveButton"
            disabled={saving || !connectionId || !model.trim()}
          >
            <Save size={15} />
            {saving ? "Saving..." : "Save Executive Model"}
          </button>

          {status && <div className="connectionStatus">{status}</div>}
        </form>

        <aside className="panel settingsStatusPanel">
          <div className="settingsStatusIcon">
            {mainConfig ? (
              <CheckCircle2 size={24} />
            ) : (
              <BrainCircuit size={24} />
            )}
          </div>

          <small>EXECUTIVE STATUS</small>
          <h3>{mainConfig ? "Configured" : "Not configured"}</h3>

          <div className="settingsStatusReadout">
            <span>Project</span>
            <b>{project.name}</b>
            <span>Provider</span>
            <b>{mainConfig?.provider_id || "—"}</b>
            <span>Model</span>
            <b>{mainConfig?.model || "—"}</b>
            <span>Connection</span>
            <b>
              {connections.find(
                (item) => item.id === mainConfig?.connection_id,
              )?.name || "—"}
            </b>
            <span>Tools</span>
            <b>{assignedToolCount} assigned</b>
          </div>

          {connections.length === 0 && (
            <div className="settingsWarning">
              <Cpu size={16} />
              <span>
                No AI connections are available. Add one under AI Uplink
                first.
              </span>
            </div>
          )}
        </aside>
      </div>

      <section className="panel executiveToolSettings">
        <div className="executiveToolSettingsHeader">
          <div>
            <Wrench size={18} />
            <span>
              <small>EXECUTIVE CAPABILITIES</small>
              <h3>Tool Access</h3>
              <p>
                Only tools marked Assigned are included in Agent Man's system
                prompt and accepted by the runtime. A tool must also have
                Runtime ON in the Tools page.
              </p>
            </span>
          </div>
          <div className="executiveToolHeaderActions">
            <strong>
              {assignedToolCount}/{executiveTools.length} assigned
            </strong>
            <button
              type="button"
              className="secondaryButton"
              onClick={() => void verifyExecutiveTools(project.id)}
              disabled={verifyingTools}
            >
              <RefreshCw
                size={13}
                className={verifyingTools ? "spinIcon" : ""}
              />
              {verifyingTools ? "Verifying..." : "Verify runtime"}
            </button>
            <button
              type="button"
              className="secondaryButton"
              onClick={() => void repairExecutiveTools()}
              disabled={executiveTools.length === 0}
            >
              Repair access
            </button>
            <button
              type="button"
              className="secondaryButton"
              onClick={() => void grantAllExecutiveTools()}
              disabled={executiveTools.length === 0}
            >
              Grant all enabled
            </button>
            <button
              type="button"
              className="secondaryButton dangerAction"
              onClick={() => void revokeAllExecutiveTools()}
              disabled={assignedToolCount === 0}
            >
              Remove all
            </button>
          </div>
        </div>

        <div
          className={
            "executiveRuntimeAccess " +
            (effectiveTools?.count ? "verified" : "empty")
          }
        >
          <div>
            <small>EFFECTIVE RUNTIME ACCESS</small>
            <strong>
              {effectiveTools
                ? effectiveTools.count + " tools visible to Executive LLM"
                : "Not verified"}
            </strong>
          </div>
          <p>
            {effectiveTools && effectiveTools.count > 0
              ? effectiveTools.tools.map((tool) => tool.name).join(", ")
              : "Use Verify runtime. If this says 0, Repair access will restore all globally enabled tools."}
          </p>
        </div>

        <div className="executiveToolGroups">
          {Object.entries(groupedTools).map(([category, tools]) => (
            <div className="executiveToolGroup" key={category}>
              <h4>{category}</h4>
              <div className="executiveToolList">
                {tools.map((tool) => (
                  <button
                    type="button"
                    key={tool.name}
                    className={
                      tool.assigned && tool.globally_enabled
                        ? "executiveToolChip assigned"
                        : "executiveToolChip"
                    }
                    disabled={!tool.globally_enabled}
                    onClick={() => void toggleExecutiveTool(tool)}
                    title={
                      tool.globally_enabled
                        ? tool.description
                        : "Enable Runtime access for this tool in Tools first."
                    }
                    aria-pressed={tool.assigned}
                  >
                    <span
                      className={
                        tool.assigned
                          ? "executiveToolCheckbox checked"
                          : "executiveToolCheckbox"
                      }
                    >
                      {tool.assigned ? "✓" : ""}
                    </span>
                    <span>
                      <b>{tool.name}</b>
                      <small>{tool.risk}</small>
                    </span>
                    <em>
                      {!tool.globally_enabled
                        ? "RUNTIME OFF"
                        : tool.assigned
                          ? "ACCESS ON"
                          : "ACCESS OFF"}
                    </em>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        {toolStatus && (
          <div className="connectionStatus">{toolStatus}</div>
        )}
      </section>
    </section>
  );
}
