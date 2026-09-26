import { FormEvent, useEffect, useState } from "react";
import {
  ArrowDown,
  BrainCircuit,
  GitBranch,
  Globe2,
  Play,
  Plus,
  RotateCcw,
  Save,
  ShieldCheck,
  Trash2,
} from "lucide-react";

import {
  api,
  Agent,
  Project,
  Workflow,
  WorkflowRun,
} from "../../services/api";

type Props = {
  project: Project | null;
  agents: Agent[];
};

type DraftNode = {
  key: string;
  name: string;
  agent_id: string;
  instructions: string;
  on_success_key: string | null;
  on_failure_key: string | null;
  max_retries: number;
};

export default function OrchestrationPage({ project, agents }: Props) {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [active, setActive] = useState<Workflow | null>(null);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [activeRun, setActiveRun] = useState<WorkflowRun | null>(null);
  const [name, setName] = useState("Development pipeline");
  const [description, setDescription] = useState(
    "Architect → Developer → Tester with explicit success/failure routing.",
  );
  const [nodes, setNodes] = useState<DraftNode[]>([]);
  const [objective, setObjective] = useState("");
  const [allowTerminal, setAllowTerminal] = useState(false);
  const [allowDelete, setAllowDelete] = useState(false);
  const [allowNetwork, setAllowNetwork] = useState(false);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  async function loadWorkflows() {
    if (!project) {
      setWorkflows([]);
      setActive(null);
      return;
    }
    const loaded = await api.workflows(project.id);
    setWorkflows(loaded);
    if (active) {
      const refreshed = loaded.find((item) => item.id === active.id);
      if (refreshed) setActive(refreshed);
    } else if (loaded[0]) {
      setActive(loaded[0]);
    }
  }

  async function loadRuns(workflow: Workflow | null) {
    if (!workflow) {
      setRuns([]);
      setActiveRun(null);
      return;
    }
    const loaded = await api.workflowRuns(workflow.id);
    setRuns(loaded);
    if (activeRun) {
      const refreshed = loaded.find((item) => item.id === activeRun.id);
      if (refreshed) setActiveRun(refreshed);
    } else if (loaded[0]) {
      setActiveRun(loaded[0]);
    }
  }

  useEffect(() => {
    void loadWorkflows();
  }, [project?.id]);

  useEffect(() => {
    void loadRuns(active);
  }, [active?.id]);

  function addStage() {
    if (agents.length === 0) return;
    const key = "stage-" + String(nodes.length + 1);
    setNodes((current) => {
      const next = current.map((node, index) =>
        index === current.length - 1 && node.on_success_key === null
          ? { ...node, on_success_key: key }
          : node,
      );
      return [
        ...next,
        {
          key,
          name: "Stage " + String(current.length + 1),
          agent_id: agents[0].id,
          instructions: "",
          on_success_key: null,
          on_failure_key: null,
          max_retries: 0,
        },
      ];
    });
  }

  function updateStage(
    key: string,
    patch: Partial<DraftNode>,
  ) {
    setNodes((current) =>
      current.map((node) =>
        node.key === key ? { ...node, ...patch } : node,
      ),
    );
  }

  function removeStage(key: string) {
    setNodes((current) =>
      current
        .filter((node) => node.key !== key)
        .map((node) => ({
          ...node,
          on_success_key:
            node.on_success_key === key ? null : node.on_success_key,
          on_failure_key:
            node.on_failure_key === key ? null : node.on_failure_key,
        })),
    );
  }

  async function saveWorkflow(event: FormEvent) {
    event.preventDefault();
    if (!project || nodes.length === 0) return;
    setBusy(true);
    setStatus("Saving workflow...");
    try {
      const created = await api.createWorkflow({
        project_id: project.id,
        name,
        description,
        nodes,
      });
      setStatus("Workflow saved.");
      setActive(created);
      await loadWorkflows();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function runWorkflow() {
    if (!active || !objective.trim()) return;
    setBusy(true);
    setStatus("Executing workflow...");
    try {
      const run = await api.runWorkflow(
        active.id,
        objective.trim(),
        allowTerminal,
        allowDelete,
        allowNetwork,
      );
      setActiveRun(run);
      setStatus("Run finished with status: " + run.status);
      await loadRuns(active);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function resume() {
    if (!activeRun) return;
    setBusy(true);
    setStatus("Resuming workflow...");
    try {
      const run = await api.resumeWorkflowRun(
        activeRun.id,
        activeRun.input_prompt,
        allowTerminal,
        allowDelete,
        allowNetwork,
      );
      setActiveRun(run);
      setStatus("Run status: " + run.status);
      await loadRuns(active);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  if (!project) {
    return (
      <section className="panel orchestrationEmpty">
        <GitBranch />
        <h3>Create a project first</h3>
        <p className="muted">
          Workflows are scoped to one project and its agents.
        </p>
      </section>
    );
  }

  return (
    <section className="orchestrationPage">
      <div className="sectionHeading">
        <div>
          <h2>Orchestration</h2>
          <p>
            Build deterministic agent handoffs. The runtime follows explicit
            success/failure edges; it does not act as a coordinator agent.
          </p>
        </div>
        <span className="connectionCount">{workflows.length} workflows</span>
      </div>

      <div className="orchestrationLayout">
        <form className="panel workflowBuilder" onSubmit={saveWorkflow}>
          <h3>Workflow builder</h3>

          <label>
            Name
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>

          <label>
            Description
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>

          <div className="builderHeader">
            <span>Stages</span>
            <button
              type="button"
              className="secondaryButton"
              onClick={addStage}
              disabled={agents.length === 0}
            >
              <Plus size={14} /> Add stage
            </button>
          </div>

          {nodes.length === 0 && (
            <p className="muted">
              Add a stage, assign an agent, then connect success/failure routes.
            </p>
          )}

          <div className="draftStages">
            {nodes.map((node, index) => (
              <div className="draftStage" key={node.key}>
                <div className="draftStageTop">
                  <span className="stageNumber">{index + 1}</span>
                  <input
                    value={node.name}
                    onChange={(event) =>
                      updateStage(node.key, { name: event.target.value })
                    }
                  />
                  <button
                    type="button"
                    className="iconButton danger"
                    onClick={() => removeStage(node.key)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>

                <label>
                  Agent
                  <select
                    value={node.agent_id}
                    onChange={(event) =>
                      updateStage(node.key, { agent_id: event.target.value })
                    }
                  >
                    {agents.map((agent) => (
                      <option value={agent.id} key={agent.id}>
                        {agent.name} · {agent.role}
                      </option>
                    ))}
                  </select>
                </label>

                <label>
                  Stage instructions / acceptance criteria
                  <textarea
                    value={node.instructions}
                    onChange={(event) =>
                      updateStage(node.key, {
                        instructions: event.target.value,
                      })
                    }
                    placeholder="Example: implement the approved architecture and run the build."
                  />
                </label>

                <div className="edgeGrid">
                  <label>
                    Success →
                    <select
                      value={node.on_success_key || ""}
                      onChange={(event) =>
                        updateStage(node.key, {
                          on_success_key: event.target.value || null,
                        })
                      }
                    >
                      <option value="">Complete workflow</option>
                      {nodes
                        .filter((target) => target.key !== node.key)
                        .map((target) => (
                          <option value={target.key} key={target.key}>
                            {target.name}
                          </option>
                        ))}
                    </select>
                  </label>

                  <label>
                    Failure →
                    <select
                      value={node.on_failure_key || ""}
                      onChange={(event) =>
                        updateStage(node.key, {
                          on_failure_key: event.target.value || null,
                        })
                      }
                    >
                      <option value="">Fail workflow</option>
                      {nodes
                        .filter((target) => target.key !== node.key)
                        .map((target) => (
                          <option value={target.key} key={target.key}>
                            {target.name}
                          </option>
                        ))}
                    </select>
                  </label>
                </div>

                <label className="retryField">
                  Execution retries
                  <input
                    type="number"
                    min={0}
                    max={5}
                    value={node.max_retries}
                    onChange={(event) =>
                      updateStage(node.key, {
                        max_retries: Number(event.target.value),
                      })
                    }
                  />
                </label>
              </div>
            ))}
          </div>

          <button
            className="primaryButton"
            disabled={busy || nodes.length === 0}
          >
            <Save size={15} /> Save workflow
          </button>
        </form>

        <div className="orchestrationRight">
          <div className="panel workflowList">
            <h3>Saved workflows</h3>
            {workflows.length === 0 && (
              <p className="muted">No workflows saved yet.</p>
            )}
            {workflows.map((workflow) => (
              <button
                key={workflow.id}
                className={
                  "workflowListRow " +
                  (active?.id === workflow.id ? "selectedWorkflow" : "")
                }
                onClick={() => setActive(workflow)}
              >
                <span>
                  <b>{workflow.name}</b>
                  <small>{workflow.nodes.length} stages</small>
                </span>
                <GitBranch size={15} />
              </button>
            ))}
          </div>

          {active && (
            <div className="panel workflowCanvas">
              <div className="workflowCanvasHeader">
                <div>
                  <h3>{active.name}</h3>
                  <p className="muted">{active.description}</p>
                </div>
                <ShieldCheck size={20} />
              </div>

              <div className="workflowGraph">
                {active.nodes.map((node, index) => (
                  <div className="graphStageWrap" key={node.id}>
                    <div className="graphStage">
                      <BrainCircuit size={18} />
                      <span>
                        <b>{node.name}</b>
                        <small>{node.agent_name} · {node.role}</small>
                      </span>
                      <div className="edgeSummary">
                        <em>✓ {node.on_success_key || "complete"}</em>
                        <em>✕ {node.on_failure_key || "fail"}</em>
                      </div>
                    </div>
                    {index < active.nodes.length - 1 && (
                      <ArrowDown className="graphArrow" size={18} />
                    )}
                  </div>
                ))}
              </div>

              <div className="runComposer">
                <textarea
                  value={objective}
                  onChange={(event) => setObjective(event.target.value)}
                  placeholder="Give this workflow its objective..."
                />
                <div className="runApprovals">
                  <label className="approval">
                    <input
                      type="checkbox"
                      checked={allowTerminal}
                      onChange={(event) =>
                        setAllowTerminal(event.target.checked)
                      }
                    />
                    Allow execute tools
                  </label>
                  <label className="approval">
                    <input
                      type="checkbox"
                      checked={allowNetwork}
                      onChange={(event) =>
                        setAllowNetwork(event.target.checked)
                      }
                    />
                    <Globe2 size={14} />
                    Allow public internet
                  </label>
                  <label className="approval">
                    <input
                      type="checkbox"
                      checked={allowDelete}
                      onChange={(event) =>
                        setAllowDelete(event.target.checked)
                      }
                    />
                    Allow destructive deletion
                  </label>
                </div>
                <button
                  className="primaryButton"
                  onClick={() => void runWorkflow()}
                  disabled={busy || !objective.trim()}
                >
                  <Play size={15} /> Run workflow
                </button>
              </div>
            </div>
          )}

          {active && (
            <div className="panel workflowRuns">
              <h3>Runs</h3>
              <div className="runHistory">
                {runs.map((run) => (
                  <button
                    key={run.id}
                    className={
                      "runHistoryRow " +
                      (activeRun?.id === run.id ? "selectedRun" : "")
                    }
                    onClick={() => setActiveRun(run)}
                  >
                    <span>
                      <b>{run.status}</b>
                      <small>{run.step_count} steps</small>
                    </span>
                    <RotateCcw size={14} />
                  </button>
                ))}
              </div>

              {activeRun && (
                <div className="runDetail">
                  <div className="runStatusLine">
                    <b>{activeRun.status}</b>
                    <span>{activeRun.step_count} transitions</span>
                  </div>
                  {activeRun.steps.map((step) => (
                    <article
                      className={"workflowStep " + (step.outcome || "")}
                      key={step.id}
                    >
                      <header>
                        <b>{step.node_name}</b>
                        <span>
                          {step.agent_name} · {step.outcome || step.status}
                        </span>
                      </header>
                      <p>{step.output_text}</p>
                    </article>
                  ))}

                  {activeRun.status === "waiting_approval" && (
                    <button
                      className="primaryButton"
                      onClick={() => void resume()}
                      disabled={busy}
                    >
                      <Play size={15} /> Resume with approvals
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {status && <div className="connectionStatus">{status}</div>}
    </section>
  );
}
