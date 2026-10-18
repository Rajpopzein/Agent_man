import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  BrainCircuit,
  CheckCircle2,
  Cpu,
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
  const [toolDraft, setToolDraft] = useState<Set<string>>(new Set());
  const [effectiveTools, setEffectiveTools] =
    useState<EffectiveToolAccess | null>(null);
  const [toolStatus, setToolStatus] = useState("");
  const [toolSaving, setToolSaving] = useState(false);
  const [verifyingTools, setVerifyingTools] = useState(false);

  useEffect(() => {
    const connection =
      connections.find((item) => item.id === mainConfig?.connection_id) ||
      connections[0] ||
      null;

    setConnectionId(connection?.id || "");
    setModel(mainConfig?.model || connection?.default_model || "");
    setDetectedModels([]);
  }, [
    project?.id,
    mainConfig?.connection_id,
    mainConfig?.model,
    connections,
  ]);

  useEffect(() => {
    if (!project) {
      setExecutiveTools([]);
      setToolDraft(new Set());
      setEffectiveTools(null);
      return;
    }

    void loadExecutiveTools(project.id);
    void verifyExecutiveTools(project.id, false);
  }, [project?.id]);

  async function loadExecutiveTools(projectId: string) {
    try {
      const loaded = await api.mainAgentTools(projectId);
      setExecutiveTools(loaded);
      setToolDraft(
        new Set(
          loaded
            .filter((tool) => tool.globally_enabled && tool.assigned)
            .map((tool) => tool.name),
        ),
      );
    } catch (error) {
      setToolStatus(
        "Unable to load Executive tools: " +
          (error instanceof Error ? error.message : String(error)),
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
            ? "Runtime verified: Agent Man currently receives " +
                effective.count +
                " tools."
            : "Runtime verified: Agent Man currently receives 0 tools.",
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

  const persistedToolNames = useMemo(
    () =>
      new Set(
        executiveTools
          .filter((tool) => tool.globally_enabled && tool.assigned)
          .map((tool) => tool.name),
      ),
    [executiveTools],
  );

  const toolDraftChanged = useMemo(() => {
    if (toolDraft.size !== persistedToolNames.size) return true;
    for (const name of toolDraft) {
      if (!persistedToolNames.has(name)) return true;
    }
    return false;
  }, [toolDraft, persistedToolNames]);

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

  function toggleToolDraft(tool: AgentTool) {
    if (!tool.globally_enabled) return;
    setToolDraft((current) => {
      const next = new Set(current);
      if (next.has(tool.name)) {
        next.delete(tool.name);
      } else {
        next.add(tool.name);
      }
      return next;
    });
    setToolStatus("Tool selection changed. Press Apply Tool Access to save.");
  }

  function selectAllEnabledTools() {
    setToolDraft(
      new Set(
        executiveTools
          .filter((tool) => tool.globally_enabled)
          .map((tool) => tool.name),
      ),
    );
    setToolStatus("All runtime-enabled tools selected. Apply to save.");
  }

  function clearToolSelection() {
    setToolDraft(new Set());
    setToolStatus("All Executive tools deselected. Apply to save.");
  }

  async function applyToolAccess() {
    if (!project) return;

    setToolSaving(true);
    setToolStatus("Saving Executive tool access...");
    try {
      const effective = await api.setMainAgentToolAssignments(
        project.id,
        Array.from(toolDraft).sort(),
      );
      setEffectiveTools(effective);
      await loadExecutiveTools(project.id);
      setToolStatus(
        "Saved. Runtime confirms " +
          effective.count +
          " effective tools for Agent Man Executive.",
      );
    } catch (error) {
      setToolStatus(
        "Unable to save Executive tool access: " +
          (error instanceof Error ? error.message : String(error)),
      );
    } finally {
      setToolSaving(false);
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
            Configure Agent Man Executive, discover models, and explicitly
            choose the runtime tools it can use.
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
                This is the model you talk to. Tool access is configured
                separately below and enforced by the runtime.
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
              Query the selected connection and load its currently available
              models.
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
            <span>Effective tools</span>
            <b>{effectiveTools?.count ?? "not verified"}</b>
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
                Select the tools Agent Man should receive, then save the whole
                assignment set in one operation.
              </p>
            </span>
          </div>

          <div className="executiveToolHeaderActions">
            <strong>
              {toolDraft.size}/{executiveTools.length} selected
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
              onClick={selectAllEnabledTools}
            >
              Select all enabled
            </button>
            <button
              type="button"
              className="secondaryButton"
              onClick={clearToolSelection}
            >
              Clear selection
            </button>
            <button
              type="button"
              className="primaryButton"
              onClick={() => void applyToolAccess()}
              disabled={toolSaving || !toolDraftChanged}
            >
              <Save size={13} />
              {toolSaving ? "Saving..." : "Apply Tool Access"}
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
              : "Select tools and press Apply Tool Access. Verify runtime confirms the exact set used by Agent Man."}
          </p>
        </div>

        <div className="executiveToolGroups">
          {Object.entries(groupedTools).map(([category, tools]) => (
            <div className="executiveToolGroup" key={category}>
              <h4>{category}</h4>
              <div className="executiveToolList">
                {tools.map((tool) => {
                  const selected = toolDraft.has(tool.name);
                  return (
                    <button
                      type="button"
                      key={tool.name}
                      className={
                        selected && tool.globally_enabled
                          ? "executiveToolChip assigned"
                          : "executiveToolChip"
                      }
                      disabled={!tool.globally_enabled}
                      onClick={() => toggleToolDraft(tool)}
                      aria-pressed={selected}
                      title={
                        tool.globally_enabled
                          ? tool.description
                          : "Enable Runtime access for this tool in Tools first."
                      }
                    >
                      <span
                        className={
                          selected
                            ? "executiveToolCheckbox checked"
                            : "executiveToolCheckbox"
                        }
                      >
                        {selected ? "✓" : ""}
                      </span>
                      <span>
                        <b>{tool.name}</b>
                        <small>{tool.risk}</small>
                      </span>
                      <em>
                        {!tool.globally_enabled
                          ? "RUNTIME OFF"
                          : selected
                            ? "SELECTED"
                            : "NOT SELECTED"}
                      </em>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {toolDraftChanged && (
          <div className="connectionStatus">
            Unsaved tool access changes. Press Apply Tool Access.
          </div>
        )}
        {toolStatus && (
          <div className="connectionStatus">{toolStatus}</div>
        )}
      </section>
    </section>
  );
}
