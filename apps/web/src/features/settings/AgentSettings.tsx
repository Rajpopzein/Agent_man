import { FormEvent, useState } from "react";
import { Plus, Save, Users } from "lucide-react";
import { Agent, AIConnection, api } from "../../services/api";

type Props = {
  projectId: string;
  agents: Agent[];
  connections: AIConnection[];
  onSaved: (agent: Agent) => void;
};

export default function AgentSettings(props: Props) {
  const [selectedId, setSelectedId] = useState("");
  const [creating, setCreating] = useState(false);
  const selected = props.agents.find((agent) => agent.id === selectedId);

  return (
    <section className="panel executiveSettings">
      <div className="settingsPanelHeader">
        <div className="settingsGlyph"><Users size={19} /></div>
        <div>
          <small>PROJECT AGENTS</small>
          <h3>Configure agents</h3>
          <p>Add an agent or edit its role, instructions, connection, and model.</p>
        </div>
      </div>
      <label className="settingsField">
        Agent to configure
        <select value={creating ? "" : selectedId} onChange={(event) => {
          setSelectedId(event.target.value);
          setCreating(false);
        }}>
          <option value="">Select an agent</option>
          {props.agents.map((agent) => (
            <option key={agent.id} value={agent.id}>{agent.name} · {agent.role}</option>
          ))}
        </select>
      </label>
      <button type="button" className="secondaryButton" onClick={() => {
        setSelectedId("");
        setCreating(true);
      }}><Plus size={14} />Add agent</button>
      {props.agents.length === 0 && !creating && <p className="muted">No agents yet. Add an agent to get started.</p>}
      {(creating || selected) && (
        <AgentEditor key={selected?.id || "new"} {...props} agent={creating ? undefined : selected}
          onSaved={(agent) => {
            props.onSaved(agent);
            setSelectedId(agent.id);
            setCreating(false);
          }} />
      )}
    </section>
  );
}

function AgentEditor({ projectId, agent, connections, onSaved }: Props & { agent?: Agent }) {
  const [name, setName] = useState(agent?.name || "");
  const [role, setRole] = useState(agent?.role || "");
  const [context, setContext] = useState(agent?.context || "");
  const [connectionId, setConnectionId] = useState(agent?.llm.connection_id || connections[0]?.id || "");
  const [model, setModel] = useState(agent?.llm.model || connections[0]?.default_model || "");
  const [models, setModels] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const connection = connections.find((item) => item.id === connectionId);

  async function detectModels() {
    setBusy(true);
    setStatus("");
    try {
      const result = await api.connectionModels(connectionId);
      setModels(result.models);
      setStatus(result.models.length ? `Detected ${result.models.length} models. Choose a suggestion or enter a model manually.` : "No models discovered. Enter a model manually.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || !connection || !name.trim() || !role.trim() || !model.trim() || !context.trim()) return;
    setBusy(true);
    setStatus("");
    try {
      const payload = {
        name: name.trim(), role: role.trim(), context: context.trim(),
        llm: {
          ...agent?.llm,
          connection_id: connection.id,
          provider_id: connection.provider_id,
          endpoint: connection.endpoint,
          model: model.trim(),
        },
      };
      const saved = agent
        ? await api.updateAgent(agent.id, payload)
        : await api.createAgent({ ...payload, project_id: projectId });
      onSaved(saved);
      setStatus("Agent configuration saved.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save}>
      <fieldset disabled={busy} style={{ border: 0, padding: 0, margin: "20px 0 0", minWidth: 0 }}>
        <legend>{agent ? `Edit ${agent.name}` : "New agent"}</legend>
        <label className="settingsField">Name
          <input required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="settingsField">Role
          <input required maxLength={120} value={role} placeholder="Developer, Tester, Researcher…" onChange={(event) => setRole(event.target.value)} />
        </label>
        <label className="settingsField">Agent context / instructions
          <textarea required maxLength={8000} rows={6} value={context} placeholder="Describe this agent’s responsibilities and how it should work." onChange={(event) => setContext(event.target.value)} />
        </label>
        <label className="settingsField">AI connection
          <select required value={connectionId} onChange={(event) => {
            const id = event.target.value;
            setConnectionId(id);
            setModel(connections.find((item) => item.id === id)?.default_model || "");
            setModels([]);
            setStatus("");
          }}>
            <option value="">Select AI connection</option>
            {connectionId && !connection && <option value={connectionId}>Unavailable connection — select another</option>}
            {connections.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.provider_id}</option>)}
          </select>
        </label>
        {connections.length === 0 && <p className="settingsWarning">Add an AI connection under AI Uplink first.</p>}
        <div className="modelDetectRow">
          <button type="button" className="secondaryButton" disabled={!connection} onClick={() => void detectModels()}>Detect Models</button>
        </div>
        <label className="settingsField">Agent model
          <input required maxLength={160} list="agent-settings-models" value={model} placeholder="Enter a model identifier" onChange={(event) => setModel(event.target.value)} />
          <datalist id="agent-settings-models">{models.map((item) => <option key={item} value={item} />)}</datalist>
        </label>
        <button className="primaryButton settingsSaveButton" disabled={!connection || !name.trim() || !role.trim() || !context.trim() || !model.trim()}>
          <Save size={15} />{busy ? "Working..." : agent ? "Save Agent" : "Create Agent"}
        </button>
      </fieldset>
      {status && <div className="connectionStatus" role="status">{status}</div>}
    </form>
  );
}
