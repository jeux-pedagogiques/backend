"""Router for module sheet import and text extraction."""

import io
from datetime import datetime
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.services.auth_service import get_current_user
from app.models.user import User
from app.models.module_analysis import ModuleAnalysis


router = APIRouter(prefix="/api/modules", tags=["modules"])


class TextImportRequest(BaseModel):
    """Schema for direct text import."""
    content: str
    title: str | None = None


class ModuleImportResponse(BaseModel):
    """Response after a module fiche has been imported."""
    title: str
    content: str
    source: str  # "file_upload", "direct_input", "paste"
    file_name: str | None = None


def _extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF bytes using pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    text_parts = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text_parts.append(page_text)
    return "\n\n".join(text_parts)


def _extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX bytes using python-docx."""
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    text_parts = []
    for para in doc.paragraphs:
        if para.text.strip():
            text_parts.append(para.text)
    return "\n\n".join(text_parts)


def _extract_text_from_txt(file_bytes: bytes) -> str:
    """Extract text from plain text file bytes."""
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return file_bytes.decode("latin-1")


# Allowed MIME types and their extractors
ALLOWED_TYPES = {
    "application/pdf": _extract_text_from_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": _extract_text_from_docx,
    "text/plain": _extract_text_from_txt,
}

# Allowed file extensions as fallback
ALLOWED_EXTENSIONS = {
    ".pdf": _extract_text_from_pdf,
    ".docx": _extract_text_from_docx,
    ".txt": _extract_text_from_txt,
}


@router.post("/import/file", response_model=ModuleImportResponse)
async def import_from_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Import a module fiche from a file upload (PDF, DOCX, TXT)."""

    # Determine the extractor based on content type or file extension
    extractor = ALLOWED_TYPES.get(file.content_type)

    if not extractor and file.filename:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        extractor = ALLOWED_EXTENSIONS.get(ext)

    if not extractor:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {file.content_type}. Accepted formats: PDF, DOCX, TXT.",
        )

    file_bytes = await file.read()

    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty.",
        )

    try:
        content = extractor(file_bytes)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to extract text from file: {str(e)}",
        )

    if not content.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No text content could be extracted from the uploaded file.",
        )

    # Derive a title from the filename
    title = file.filename.rsplit(".", 1)[0] if file.filename else "Fiche Module Importée"

    return ModuleImportResponse(
        title=title,
        content=content,
        source="file_upload",
        file_name=file.filename,
    )


@router.post("/import/text", response_model=ModuleImportResponse)
def import_from_text(
    data: TextImportRequest,
    current_user: User = Depends(get_current_user),
):
    """Import a module fiche from direct text input or paste."""

    if not data.content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le contenu ne peut pas être vide.",
        )

    return ModuleImportResponse(
        title=data.title or "Fiche Module",
        content=data.content,
        source="direct_input",
        file_name=None,
    )


# ============ AI ANALYSIS ============

class AnalyzeRequest(BaseModel):
    """Schema for requesting AI analysis of module content."""
    content: str
    title: str | None = None


class LearningOutcome(BaseModel):
    id: int
    description: str
    bloom_level: str
    bloom_justification: str


class AnalysisResponse(BaseModel):
    """Response from AI analysis of module content."""
    module_title: str
    learning_outcomes: list[LearningOutcome]
    key_concepts: list[str]
    keywords: list[str]
    central_notions: list[str] = []
    estimated_duration: str | None = None
    target_audience: str | None = None
    module_summary: str | None = None


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_module(
    data: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
):
    """Analyze module content using Gemini AI to extract learning outcomes, Bloom levels, etc."""
    from app.services.gemini_service import analyze_module_content

    if not data.content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le contenu à analyser ne peut pas être vide.",
        )

    try:
        result = await analyze_module_content(data.content)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Erreur lors de l'analyse IA : {str(e)}",
        )

    # Use provided title or AI-detected title
    title = data.title or result.get("module_title", "Fiche Module")

    return AnalysisResponse(
        module_title=title,
        learning_outcomes=[
            LearningOutcome(**lo) for lo in result.get("learning_outcomes", [])
        ],
        key_concepts=result.get("key_concepts", []),
        keywords=result.get("keywords", []),
        central_notions=result.get("central_notions", []),
        estimated_duration=result.get("estimated_duration"),
        target_audience=result.get("target_audience"),
        module_summary=result.get("module_summary"),
    )


# ============ ANALYSIS HISTORY ============

class SaveAnalysisRequest(BaseModel):
    """Request body to save an analysis result to history."""
    module_title: str
    original_content: str | None = None
    learning_outcomes: list[LearningOutcome]
    key_concepts: list[str]
    keywords: list[str]
    central_notions: list[str] = []
    estimated_duration: str | None = None
    target_audience: str | None = None
    module_summary: str | None = None


class SavedAnalysisResponse(BaseModel):
    """Schema of a saved module analysis history item."""
    id: int
    user_id: int
    module_title: str
    module_summary: str | None = None
    original_content: str | None = None
    learning_outcomes: list[LearningOutcome]
    key_concepts: list[str]
    keywords: list[str]
    central_notions: list[str] = []
    estimated_duration: str | None = None
    target_audience: str | None = None
    created_at: datetime


@router.post("/history", response_model=SavedAnalysisResponse)
async def save_analysis_history(
    data: SaveAnalysisRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Save a validated module analysis result to the user's history."""
    # Convert learning outcomes from Pydantic models to dicts for JSON column storage
    outcomes_dict = [lo.model_dump() for lo in data.learning_outcomes]

    history_entry = ModuleAnalysis(
        user_id=current_user.id,
        module_title=data.module_title,
        module_summary=data.module_summary,
        original_content=data.original_content,
        learning_outcomes=outcomes_dict,
        key_concepts=data.key_concepts,
        keywords=data.keywords,
        central_notions=data.central_notions,
        estimated_duration=data.estimated_duration,
        target_audience=data.target_audience,
    )

    session.add(history_entry)
    session.commit()
    session.refresh(history_entry)

    return SavedAnalysisResponse(
        id=history_entry.id,
        user_id=history_entry.user_id,
        module_title=history_entry.module_title,
        module_summary=history_entry.module_summary,
        original_content=history_entry.original_content,
        learning_outcomes=[LearningOutcome(**lo) for lo in history_entry.learning_outcomes],
        key_concepts=history_entry.key_concepts,
        keywords=history_entry.keywords,
        central_notions=history_entry.central_notions,
        estimated_duration=history_entry.estimated_duration,
        target_audience=history_entry.target_audience,
        created_at=history_entry.created_at,
    )


@router.get("/history", response_model=list[SavedAnalysisResponse])
async def list_analysis_history(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Get the module analysis history for the current user."""
    statement = (
        select(ModuleAnalysis)
        .where(ModuleAnalysis.user_id == current_user.id)
        .order_by(ModuleAnalysis.created_at.desc())
    )
    results = session.exec(statement).all()

    response = []
    for entry in results:
        # Deserialize JSON lists/dicts to Pydantic models
        lo_list = [LearningOutcome(**lo) for lo in entry.learning_outcomes]
        response.append(
            SavedAnalysisResponse(
                id=entry.id,
                user_id=entry.user_id,
                module_title=entry.module_title,
                module_summary=entry.module_summary,
                original_content=entry.original_content,
                learning_outcomes=lo_list,
                key_concepts=entry.key_concepts,
                keywords=entry.keywords,
                central_notions=entry.central_notions,
                estimated_duration=entry.estimated_duration,
                target_audience=entry.target_audience,
                created_at=entry.created_at,
            )
        )
    return response


@router.delete("/history/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_analysis_history(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Delete a module analysis entry from the user's history."""
    entry = session.get(ModuleAnalysis, analysis_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Module analysis history item not found.",
        )

    if entry.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this history item.",
        )

    session.delete(entry)
    session.commit()
