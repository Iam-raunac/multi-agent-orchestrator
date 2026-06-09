from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.api.deps import get_db
from app.db.models import Job, JobStatus
from app.schemas.job import JobSummary, JobDetail
from app.schemas.events import HumanApprovalResponse
from app.graph.builder import compile_graph
from app.graph.checkpointer import get_checkpointer

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobSummary])
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    status_filter: JobStatus | None = Query(None, alias="status"),
    limit: int = Query(50, le=100),
):
    """List jobs with optional status filter."""
    query = select(Job).order_by(desc(Job.created_at)).limit(limit)
    if status_filter:
        query = query.where(Job.status == status_filter)

    result = await db.execute(query)
    jobs = result.scalars().all()
    return [JobSummary.model_validate(j) for j in jobs]


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get full details of one job."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobDetail.model_validate(job)


@router.post("/{job_id}/approve")
async def approve_job(
    job_id: str,
    decision: HumanApprovalResponse,
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused pipeline with human approval decision."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.AWAITING_REVIEW:
        raise HTTPException(status_code=400, detail="Job is not awaiting review")

    # Resume the paused graph with human decision injected into state
    async with get_checkpointer() as checkpointer:
        graph = compile_graph(checkpointer)
        config = {"configurable": {"thread_id": job_id}}

        await graph.aupdate_state(
            config,
            {"human_approved": decision.decision == "approve"},
        )

        async for _ in graph.astream(None, config=config):
            pass

    job.status = JobStatus.APPROVED if decision.decision == "approve" else JobStatus.FAILED
    await db.commit()

    return {"status": "ok", "decision": decision.decision}