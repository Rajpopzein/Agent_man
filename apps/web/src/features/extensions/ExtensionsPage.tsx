import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Bot,
  Link2,
  Plus,
  Save,
  Trash2,
  WandSparkles,
} from "lucide-react";

import {
  api,
  Agent,
  Connector,
  Project,
  Skill,
} from "../../services/api";

type Props = {
  project: Project | null;
  agents: Agent[];
};

const DEFAULT_SKILL = `# Purpose
Describe what this skill helps the agent accomplish.

## When to use
- Define the situations where this skill applies.

## Instructions
1. Follow the project conventions.
2. Work in small verifiable steps.
3. Validate before reporting completion.

## Output
Explain what changed and how it was verified.
`;

export default function ExtensionsPage({
  project,
  agents,
}: Props) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [selectedSkillId, setSelectedSkillId] = useState("");
  const [skillName, setSkillName] = useState("Frontend Design");
  const [skillSlug, setSkillSlug] = useState("frontend-design");
  const [skillDescription, setSkillDescription] = useState(
    "Reusable frontend design and implementation guidance.",
  );
  const [skillContent, setSkillContent] = useState(DEFAULT_SKILL);
  const [targetAgentId, setTargetAgentId] = useState("");
  const [assignedSkillIds, setAssignedSkillIds] =
    useState<Set<string>>(new Set());

  const [connectorName, setConnectorName] = useState("");
  const [connectorKind, setConnectorKind] = useState("generic-http");
  const [connectorBaseUrl, setConnectorBaseUrl] = useState("");
  const [connectorApiKey, setConnectorApiKey] = useState("");
  const [status, setStatus] = useState("");

  async function load() {
    if (!project) {
      setSkills([]);
      setConnectors([]);
      return;
    }
    const [loadedSkills, loadedConnectors] = await Promise.all([
      api.skills(project.id),
      api.connectors(project.id),
    ]);
    setSkills(loadedSkills);
    setConnectors(loadedConnectors);
  }

  async function loadAgentSkills(agentId: string) {
    if (!agentId) {
      setAssignedSkillIds(new Set());
      return;
    }
    const rows = await api.agentSkills(agentId);
    setAssignedSkillIds(new Set(rows.map((item) => item.id)));
  }

  useEffect(() => {
    void load();
  }, [project?.id]);

  useEffect(() => {
    if (!targetAgentId && agents.length > 0) {
      setTargetAgentId(agents[0].id);
      void loadAgentSkills(agents[0].id);
    } else if (
      targetAgentId &&
      !agents.some((agent) => agent.id === targetAgentId)
    ) {
      setTargetAgentId(agents[0]?.id || "");
    }
  }, [agents, targetAgentId]);

  const selectedSkill = useMemo(
    () => skills.find((item) => item.id === selectedSkillId) || null,
    [skills, selectedSkillId],
  );

  function selectSkill(skill: Skill) {
    setSelectedSkillId(skill.id);
    setSkillName(skill.name);
    setSkillSlug(skill.slug);
    setSkillDescription(skill.description);
    setSkillContent(skill.content);
  }

  function newSkill() {
    setSelectedSkillId("");
    setSkillName("Frontend Design");
    setSkillSlug("frontend-design");
    setSkillDescription(
      "Reusable frontend design and implementation guidance.",
    );
    setSkillContent(DEFAULT_SKILL);
  }

  async function saveSkill(event: FormEvent) {
    event.preventDefault();
    if (!project) return;
    try {
      if (selectedSkill) {
        await api.updateSkill(selectedSkill.id, {
          name: skillName.trim(),
          slug: skillSlug.trim(),
          description: skillDescription.trim(),
          content: skillContent.trim(),
        });
        setStatus("SKILL.md updated.");
      } else {
        const created = await api.createSkill(project.id, {
          name: skillName.trim(),
          slug: skillSlug.trim(),
          description: skillDescription.trim(),
          content: skillContent.trim(),
        });
        setSelectedSkillId(created.id);
        setStatus("SKILL.md created.");
      }
      await load();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function removeSkill() {
    if (!selectedSkill) return;
    try {
      await api.deleteSkill(selectedSkill.id);
      newSkill();
      await load();
      if (targetAgentId) {
        await loadAgentSkills(targetAgentId);
      }
      setStatus("Skill removed.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function toggleSkillAssignment(skillId: string) {
    if (!targetAgentId) return;
    try {
      if (assignedSkillIds.has(skillId)) {
        await api.unassignSkill(targetAgentId, skillId);
      } else {
        await api.assignSkill(targetAgentId, skillId);
      }
      await loadAgentSkills(targetAgentId);
      setStatus("Agent skill assignment updated.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  function useGrowwTemplate() {
    setConnectorName("Groww");
    setConnectorKind("groww");
    setConnectorBaseUrl("");
    setConnectorApiKey("");
    setStatus(
      "Groww template selected. Add only the documented API/auth details you intend to use.",
    );
  }

  async function createConnector(event: FormEvent) {
    event.preventDefault();
    if (!project || !connectorName.trim()) return;
    try {
      await api.createConnector(project.id, {
        name: connectorName.trim(),
        kind: connectorKind.trim(),
        base_url: connectorBaseUrl.trim(),
        api_key: connectorApiKey.trim() || undefined,
        config: {},
      });
      setConnectorName("");
      setConnectorKind("generic-http");
      setConnectorBaseUrl("");
      setConnectorApiKey("");
      await load();
      setStatus("Connector definition created.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function removeConnector(connectorId: string) {
    try {
      await api.deleteConnector(connectorId);
      await load();
      setStatus("Connector removed.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  if (!project) {
    return (
      <section className="panel extensionsEmpty">
        <WandSparkles size={24} />
        <h3>No project selected</h3>
        <p className="muted">
          Create or select a project before adding skills or connectors.
        </p>
      </section>
    );
  }

  return (
    <section className="extensionsPage">
      <div className="sectionHeading">
        <div>
          <h2>Extensions</h2>
          <p>
            Build reusable SKILL.md instructions and governed external connectors.
          </p>
        </div>
        <span className="connectionCount">
          {skills.length} skills · {connectors.length} connectors
        </span>
      </div>

      {status && <div className="panel extensionStatus">{status}</div>}

      <div className="extensionsGrid">
        <section className="panel skillStudio">
          <div className="extensionPanelHeader">
            <div>
              <small>AGENT CAPABILITY</small>
              <h3>SKILL.md Studio</h3>
              <p>
                Reusable instructions are injected into assigned workers on every task.
              </p>
            </div>
            <button className="secondaryButton" type="button" onClick={newSkill}>
              <Plus size={14} />
              New skill
            </button>
          </div>

          <div className="skillPicker">
            {skills.map((skill) => (
              <button
                type="button"
                key={skill.id}
                className={selectedSkillId === skill.id ? "active" : ""}
                onClick={() => selectSkill(skill)}
              >
                <strong>{skill.name}</strong>
                <small>{skill.slug}/SKILL.md</small>
              </button>
            ))}
          </div>

          <form className="skillEditor" onSubmit={saveSkill}>
            <div className="extensionTwoCol">
              <label>
                Skill name
                <input
                  value={skillName}
                  onChange={(event) => setSkillName(event.target.value)}
                />
              </label>
              <label>
                Slug
                <input
                  value={skillSlug}
                  onChange={(event) => setSkillSlug(event.target.value)}
                />
              </label>
            </div>
            <label>
              Description
              <input
                value={skillDescription}
                onChange={(event) =>
                  setSkillDescription(event.target.value)
                }
              />
            </label>
            <label>
              SKILL.md
              <textarea
                className="skillMarkdownEditor"
                value={skillContent}
                onChange={(event) => setSkillContent(event.target.value)}
              />
            </label>
            <div className="extensionActions">
              <button className="primaryButton">
                <Save size={14} />
                Save SKILL.md
              </button>
              {selectedSkill && (
                <button
                  className="secondaryButton danger"
                  type="button"
                  onClick={() => void removeSkill()}
                >
                  <Trash2 size={14} />
                  Delete
                </button>
              )}
            </div>
          </form>

          <div className="skillAssignment">
            <div>
              <Bot size={16} />
              <strong>Assign skills to worker</strong>
            </div>
            <select
              value={targetAgentId}
              onChange={(event) => {
                setTargetAgentId(event.target.value);
                void loadAgentSkills(event.target.value);
              }}
            >
              <option value="">Select worker</option>
              {agents.map((agent) => (
                <option value={agent.id} key={agent.id}>
                  {agent.name} · {agent.role}
                </option>
              ))}
            </select>
            <div className="skillAssignmentList">
              {skills.map((skill) => (
                <label key={skill.id}>
                  <input
                    type="checkbox"
                    checked={assignedSkillIds.has(skill.id)}
                    onChange={() => void toggleSkillAssignment(skill.id)}
                    disabled={!targetAgentId}
                  />
                  <span>
                    <b>{skill.name}</b>
                    <small>{skill.description || skill.slug}</small>
                  </span>
                </label>
              ))}
            </div>
          </div>
        </section>

        <section className="panel connectorStudio">
          <div className="extensionPanelHeader">
            <div>
              <small>EXTERNAL CAPABILITY</small>
              <h3>Connectors</h3>
              <p>
                Store connector metadata and credentials separately from agent prompts.
              </p>
            </div>
            <button
              className="secondaryButton"
              type="button"
              onClick={useGrowwTemplate}
            >
              <WandSparkles size={14} />
              Groww template
            </button>
          </div>

          <form className="connectorForm" onSubmit={createConnector}>
            <label>
              Name
              <input
                value={connectorName}
                onChange={(event) => setConnectorName(event.target.value)}
                placeholder="Groww"
              />
            </label>
            <label>
              Connector kind
              <select
                value={connectorKind}
                onChange={(event) => setConnectorKind(event.target.value)}
              >
                <option value="generic-http">Generic HTTP API</option>
                <option value="groww">Groww template</option>
              </select>
            </label>
            <label>
              Base URL
              <input
                value={connectorBaseUrl}
                onChange={(event) =>
                  setConnectorBaseUrl(event.target.value)
                }
                placeholder="Use the documented API base URL"
              />
            </label>
            <label>
              API key / token
              <input
                type="password"
                value={connectorApiKey}
                onChange={(event) =>
                  setConnectorApiKey(event.target.value)
                }
                placeholder="Stored using Windows DPAPI"
              />
            </label>
            <button className="primaryButton">
              <Link2 size={14} />
              Create connector
            </button>
          </form>

          <div className="connectorList">
            {connectors.map((connector) => (
              <div className="connectorRow" key={connector.id}>
                <div>
                  <strong>{connector.name}</strong>
                  <small>
                    {connector.kind}
                    {connector.has_secret ? " · credential stored" : ""}
                  </small>
                  <code>
                    {connector.base_url || "No API base URL configured"}
                  </code>
                </div>
                <button
                  className="iconButton"
                  type="button"
                  onClick={() => void removeConnector(connector.id)}
                  title="Delete connector"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            {connectors.length === 0 && (
              <div className="professionalEmpty">
                No connectors configured yet.
              </div>
            )}
          </div>
        </section>
      </div>
    </section>
  );
}
