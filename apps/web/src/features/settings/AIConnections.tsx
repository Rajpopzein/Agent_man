import { FormEvent, useEffect, useMemo, useState } from "react";
import { Cloud, Cpu, Plug, RefreshCw, Trash2 } from "lucide-react";

import HudModal from "../../components/HudModal";
import {
  api,
  AIConnection,
  AIConnectionTest,
  AIProvider,
} from "../../services/api";

type Props = {
  connections: AIConnection[];
  onChanged: () => Promise<void>;
};

export default function AIConnections({ connections, onChanged }: Props) {
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [providerId, setProviderId] = useState("lmstudio");
  const [name, setName] = useState("Local LM Studio");
  const [endpoint, setEndpoint] = useState("http://localhost:1234/v1");
  const [apiKey, setApiKey] = useState("");
  const [defaultModel, setDefaultModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [tests, setTests] = useState<Record<string, AIConnectionTest>>({});
  const [connectionToDelete, setConnectionToDelete] =
    useState<AIConnection | null>(null);

  useEffect(() => {
    api.aiProviders().then(setProviders).catch((error) => setStatus(String(error)));
  }, []);

  const selectedProvider = useMemo(
    () => providers.find((provider) => provider.id === providerId),
    [providers, providerId],
  );

  function chooseProvider(id: string) {
    setProviderId(id);
    const provider = providers.find((item) => item.id === id);
    setEndpoint(provider?.default_endpoint || "");
    if (provider?.id === "lmstudio") setName("Local LM Studio");
    if (provider?.id === "ollama") setName("Local Ollama");
    if (provider?.id === "gemini") setName("Gemini");
    if (provider?.id === "openai") setName("OpenAI");
    if (provider?.id === "openai-compatible") setName("Custom AI");
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setStatus("");
    try {
      await api.createAIConnection({
        name,
        provider_id: providerId,
        endpoint: endpoint || undefined,
        default_model: defaultModel || undefined,
        api_key: apiKey || undefined,
      });
      setApiKey("");
      setDefaultModel("");
      setStatus("Connection saved.");
      await onChanged();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function test(connection: AIConnection) {
    setStatus("Testing " + connection.name + "...");
    try {
      const result = await api.testAIConnection(connection.id);
      setTests((current) => ({ ...current, [connection.id]: result }));
      setStatus(
        "Connected to " +
          connection.name +
          ". Found " +
          result.models.length +
          " model(s).",
      );
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function selectModel(connection: AIConnection, model: string) {
    await api.updateAIConnection(connection.id, { default_model: model });
    setStatus(model + " is now the default model for " + connection.name + ".");
    await onChanged();
  }

  async function removeConfirmed() {
    if (!connectionToDelete) return;
    try {
      await api.deleteAIConnection(connectionToDelete.id);
      setStatus("Connection deleted.");
      setConnectionToDelete(null);
      await onChanged();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <section className="connectionsPage">
      <div className="sectionHeading">
        <div>
          <h2>AI Connections</h2>
          <p>
            Configure providers once, discover their models, then assign a
            different connection to each agent.
          </p>
        </div>
        <span className="connectionCount">{connections.length} saved</span>
      </div>

      <div className="connectionLayout">
        <div className="panel connectionForm">
          <h3>Add connection</h3>
          <form onSubmit={create}>
            <label>
              Provider
              <select
                value={providerId}
                onChange={(event) => chooseProvider(event.target.value)}
              >
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.label}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Connection name
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
            </label>

            <label>
              Endpoint
              <input
                value={endpoint}
                onChange={(event) => setEndpoint(event.target.value)}
                placeholder="Provider API endpoint"
                required={!selectedProvider?.default_endpoint}
              />
            </label>

            <label>
              API key
              <input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={
                  selectedProvider?.requires_api_key
                    ? "Required - protected with Windows DPAPI"
                    : "Optional"
                }
                required={selectedProvider?.requires_api_key}
              />
            </label>

            <label>
              Default model
              <input
                value={defaultModel}
                onChange={(event) => setDefaultModel(event.target.value)}
                placeholder="Optional - discover after saving"
              />
            </label>

            <button className="primaryButton" disabled={busy}>
              <Plug size={16} />
              {busy ? "Saving..." : "Save connection"}
            </button>
          </form>

          <p className="securityNote">
            Cloud API keys are not stored in agent records or prompts. On
            Windows they are encrypted with DPAPI for the current Windows user.
          </p>
        </div>

        <div className="connectionsList">
          {connections.length === 0 && (
            <div className="panel emptyConnection">
              <Plug />
              <h3>No AI connections yet</h3>
              <p>Add LM Studio, Ollama, Gemini, OpenAI, or a custom endpoint.</p>
            </div>
          )}

          {connections.map((connection) => {
            const result = tests[connection.id];
            const provider = providers.find(
              (item) => item.id === connection.provider_id,
            );
            return (
              <div className="panel connectionCard" key={connection.id}>
                <div className="connectionTop">
                  <div className="providerIcon">
                    {provider?.local ? <Cpu /> : <Cloud />}
                  </div>
                  <div>
                    <h3>{connection.name}</h3>
                    <p>
                      {provider?.label || connection.provider_id}
                      {connection.has_secret ? " · protected key" : ""}
                    </p>
                  </div>
                  <button
                    className="iconButton danger"
                    onClick={() => setConnectionToDelete(connection)}
                    title="Delete connection"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>

                <div className="connectionMeta">
                  <span>Endpoint</span>
                  <code>{connection.endpoint || "default"}</code>
                  <span>Default model</span>
                  <b>{connection.default_model || "Not selected"}</b>
                </div>

                <button
                  className="testButton"
                  onClick={() => void test(connection)}
                >
                  <RefreshCw size={15} /> Test & discover models
                </button>

                {result && (
                  <div className="modelList">
                    {result.models.length === 0 ? (
                      <p className="muted">Connected, but no models were returned.</p>
                    ) : (
                      result.models.map((model) => (
                        <button
                          key={model}
                          className={
                            model === connection.default_model
                              ? "modelChip selectedModel"
                              : "modelChip"
                          }
                          onClick={() => void selectModel(connection, model)}
                        >
                          {model}
                        </button>
                      ))
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {status && <div className="connectionStatus">{status}</div>}

      <HudModal
        open={Boolean(connectionToDelete)}
        onClose={() => setConnectionToDelete(null)}
        title="Delete AI Connection"
        eyebrow="UPLINK / DESTRUCTIVE ACTION"
        tone="danger"
        footer={
          <>
            <button
              className="secondaryButton"
              onClick={() => setConnectionToDelete(null)}
            >
              Keep connection
            </button>
            <button
              className="primaryButton dangerAction"
              onClick={() => void removeConfirmed()}
            >
              <Trash2 size={14} />
              Delete connection
            </button>
          </>
        }
      >
        <p className="systemMessage">
          Remove {connectionToDelete?.name || "this AI connection"} from
          Agent Man? Agents that still reference this connection may need to be
          reconfigured before they can run again.
        </p>
      </HudModal>
    </section>
  );
}
