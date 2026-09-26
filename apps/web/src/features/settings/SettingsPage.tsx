import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  BrainCircuit,
  CheckCircle2,
  Cpu,
  RefreshCw,
  Save,
  Settings2,
  Sparkles,
} from "lucide-react";

import {
  api,
  AIConnection,
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

  useEffect(() => {
    const connection =
      connections.find((item) => item.id === mainConfig?.connection_id) ||
      connections[0] ||
      null;

    setConnectionId(connection?.id || "");
    setModel(mainConfig?.model || connection?.default_model || "");
    setDetectedModels([]);
  }, [project?.id, mainConfig?.connection_id, mainConfig?.model, connections]);

  const selectedConnection = useMemo(
    () => connections.find((item) => item.id === connectionId) || null,
    [connections, connectionId],
  );

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
            Configure Agent Man itself here. Command Core is execution-only;
            executive model selection and discovery live in Settings.
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
                This is the model you talk to. It decides when to reply,
                delegate to workers, start peer collaboration, or run a saved
                workflow.
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
    </section>
  );
}
