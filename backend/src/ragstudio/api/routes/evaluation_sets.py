from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.evaluation import EvaluationSetOut, EvaluationSetPage
from ragstudio.services.evaluation_importer import EvaluationImporter, EvaluationImportError

router = APIRouter(prefix="/api/evaluation-sets", tags=["evaluation-sets"])


@router.post("/import", response_model=EvaluationSetOut, status_code=201)
async def import_evaluation_set(
    name: str,
    file: UploadFile,
    session: AsyncSession = Depends(get_session),
) -> EvaluationSetOut:
    content = await file.read()
    try:
        return await EvaluationImporter(session).import_file(
            name=name,
            filename=file.filename or "evaluation-set",
            content=content,
        )
    except EvaluationImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=EvaluationSetPage)
async def list_evaluation_sets(
    session: AsyncSession = Depends(get_session),
) -> EvaluationSetPage:
    return await EvaluationImporter(session).list()
