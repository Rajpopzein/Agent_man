from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.orchestration import execute_workflow_run, workflow_nodes
from app.api.schemas import (
    WorkflowCreate,
    WorkflowNodeView,
    WorkflowRunRequest,
    WorkflowRunStepView,
    WorkflowRunView,
    WorkflowView,
)
from app.persistence.database import get_session
from app.persistence.models import (
    AgentRecord,
    ProjectRecord,
    WorkflowNodeRecord,
    WorkflowRecord,
    WorkflowRunRecord,
    WorkflowRunStepRecord,
)

router = APIRouter(
    prefix="/api/orchestration",
    tags=["orchestration"],
)


@router.post("/workflows", response_model=WorkflowView, status_code=201)
def create_workflow(
    body: WorkflowCreate,
    db: Session = Depends(get_session),
):
    project = db.get(ProjectRecord, body.project_id)
    if project is None:
        raise HTTPException(404, "Project not found")

    keys = [node.key for node in body.nodes]
    if len(keys) != len(set(keys)):
        raise HTTPException(422, "Workflow node keys must be unique")

    for node in body.nodes:
        agent = db.get(AgentRecord, node.agent_id)
        if agent is None:
            raise HTTPException(404, f"Agent not found: {node.agent_id}")
        if agent.project_id != body.project_id:
            raise HTTPException(
                422,
                f"Agent {agent.name} does not belong to this project",
            )
        for target in [node.on_success_key, node.on_failure_key]:
            if target is not None and target not in keys:
                raise HTTPException(
                    422,
                    f"Unknown workflow target: {target}",
                )

    workflow = WorkflowRecord(
        project_id=body.project_id,
        name=body.name,
        description=body.description,
    )
    db.add(workflow)
    db.flush()

    by_key = {}
    for position, node in enumerate(body.nodes):
        record = WorkflowNodeRecord(
            workflow_id=workflow.id,
            key=node.key,
            name=node.name,
            agent_id=node.agent_id,
            instructions=node.instructions,
            position=position,
            max_retries=node.max_retries,
        )
        db.add(record)
        db.flush()
        by_key[node.key] = record

    for node in body.nodes:
        record = by_key[node.key]
        record.on_success_node_id = (
            by_key[node.on_success_key].id
            if node.on_success_key
            else None
        )
        record.on_failure_node_id = (
            by_key[node.on_failure_key].id
            if node.on_failure_key
            else None
        )

    workflow.start_node_id = by_key[body.nodes[0].key].id
    db.commit()
    db.refresh(workflow)
    return workflow_view(workflow, db)


@router.get(
    "/projects/{project_id}/workflows",
    response_model=list[WorkflowView],
)
def list_workflows(
    project_id: str,
    db: Session = Depends(get_session),
):
    rows = db.scalars(
        select(WorkflowRecord)
        .where(WorkflowRecord.project_id == project_id)
        .order_by(WorkflowRecord.created_at.desc())
    ).all()
    return [workflow_view(row, db) for row in rows]


@router.get("/workflows/{workflow_id}", response_model=WorkflowView)
def get_workflow(
    workflow_id: str,
    db: Session = Depends(get_session),
):
    workflow = db.get(WorkflowRecord, workflow_id)
    if workflow is None:
        raise HTTPException(404, "Workflow not found")
    return workflow_view(workflow, db)


@router.post(
    "/workflows/{workflow_id}/runs",
    response_model=WorkflowRunView,
    status_code=201,
)
def create_run(
    workflow_id: str,
    body: WorkflowRunRequest,
    db: Session = Depends(get_session),
):
    workflow = db.get(WorkflowRecord, workflow_id)
    if workflow is None:
        raise HTTPException(404, "Workflow not found")

    run = WorkflowRunRecord(
        workflow_id=workflow.id,
        project_id=workflow.project_id,
        status="created",
        current_node_id=workflow.start_node_id,
        input_prompt=body.input_prompt,
        last_output="",
        step_count=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        execute_workflow_run(
            run=run,
            db=db,
            allow_terminal=body.allow_terminal,
            allow_delete=body.allow_delete,
            allow_network=body.allow_network,
        )
    except Exception as exc:
        run.status = "failed"
        run.last_output = str(exc)
        db.commit()
        raise HTTPException(
            502,
            f"Workflow execution error: {exc}",
        ) from exc

    db.refresh(run)
    return run_view(run, db)


@router.post(
    "/runs/{run_id}/resume",
    response_model=WorkflowRunView,
)
def resume_run(
    run_id: str,
    body: WorkflowRunRequest,
    db: Session = Depends(get_session),
):
    run = db.get(WorkflowRunRecord, run_id)
    if run is None:
        raise HTTPException(404, "Workflow run not found")
    if run.status not in {"waiting_approval", "created", "executing"}:
        raise HTTPException(
            409,
            f"Run cannot be resumed from status {run.status}",
        )

    execute_workflow_run(
        run=run,
        db=db,
        allow_terminal=body.allow_terminal,
        allow_delete=body.allow_delete,
        allow_network=body.allow_network,
        allow_hardware=body.allow_hardware,
    )
    db.refresh(run)
    return run_view(run, db)


@router.get(
    "/workflows/{workflow_id}/runs",
    response_model=list[WorkflowRunView],
)
def workflow_runs(
    workflow_id: str,
    db: Session = Depends(get_session),
):
    rows = db.scalars(
        select(WorkflowRunRecord)
        .where(WorkflowRunRecord.workflow_id == workflow_id)
        .order_by(WorkflowRunRecord.created_at.desc())
    ).all()
    return [run_view(row, db) for row in rows]


def workflow_view(
    workflow: WorkflowRecord,
    db: Session,
) -> WorkflowView:
    nodes = workflow_nodes(workflow.id, db)
    id_to_key = {node.id: node.key for node in nodes}
    views = []
    for node in nodes:
        agent = db.get(AgentRecord, node.agent_id)
        views.append(
            WorkflowNodeView(
                id=node.id,
                key=node.key,
                name=node.name,
                agent_id=node.agent_id,
                agent_name=agent.name if agent else "Missing agent",
                role=agent.role if agent else "unknown",
                instructions=node.instructions,
                position=node.position,
                on_success_key=id_to_key.get(node.on_success_node_id),
                on_failure_key=id_to_key.get(node.on_failure_node_id),
                max_retries=node.max_retries,
            )
        )

    return WorkflowView(
        id=workflow.id,
        project_id=workflow.project_id,
        name=workflow.name,
        description=workflow.description,
        start_node_id=workflow.start_node_id,
        created_at=workflow.created_at,
        nodes=views,
    )


def run_view(
    run: WorkflowRunRecord,
    db: Session,
) -> WorkflowRunView:
    steps = db.scalars(
        select(WorkflowRunStepRecord)
        .where(WorkflowRunStepRecord.run_id == run.id)
        .order_by(WorkflowRunStepRecord.created_at)
    ).all()
    node_by_id = {
        node.id: node
        for node in workflow_nodes(run.workflow_id, db)
    }
    step_views = []
    for step in steps:
        node = node_by_id.get(step.node_id)
        agent = db.get(AgentRecord, step.agent_id)
        step_views.append(
            WorkflowRunStepView(
                id=step.id,
                node_id=step.node_id,
                node_name=node.name if node else "Missing stage",
                agent_id=step.agent_id,
                agent_name=agent.name if agent else "Missing agent",
                attempt=step.attempt,
                status=step.status,
                outcome=step.outcome,
                output_text=step.output_text,
                created_at=step.created_at,
            )
        )

    return WorkflowRunView(
        id=run.id,
        workflow_id=run.workflow_id,
        project_id=run.project_id,
        status=run.status,
        current_node_id=run.current_node_id,
        input_prompt=run.input_prompt,
        last_output=run.last_output,
        step_count=run.step_count,
        created_at=run.created_at,
        completed_at=run.completed_at,
        steps=step_views,
    )
