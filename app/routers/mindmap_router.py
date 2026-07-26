"""REST Router for Mind Map Collaboratif."""

from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from app.database import get_session
from app.models.user import User
from app.models.module_analysis import ModuleAnalysis
from app.models.mindmap import MindMap, MindMapNode
from app.services.auth_service import get_current_user
from app.services.mindmap_service import generate_mindmap
from app.services.library_service import register_library_item

router = APIRouter(prefix="/api/mindmap", tags=["Mind Map"])


class GenerateMindMapRequest(BaseModel):
    module_id: int
    nb_branches: Optional[int] = 4


@router.post("/generate", response_model=dict)
async def generate_mindmap_endpoint(
    req: GenerateMindMapRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Generate a new Mind Map starting structure using AI based on a module analysis."""
    module = session.get(ModuleAnalysis, req.module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module Analysis not found")

    outcomes = module.learning_outcomes or []
    outcomes_dict = []
    for o in outcomes:
        if isinstance(o, dict):
            outcomes_dict.append({
                "description": o.get("description", str(o)),
                "bloom_level": o.get("bloom_level", "comprendre")
            })
        else:
            outcomes_dict.append({
                "description": getattr(o, "description", str(o)),
                "bloom_level": getattr(o, "bloom_level", "comprendre")
            })

    generated = await generate_mindmap(
        module_title=module.module_title,
        learning_outcomes=outcomes_dict,
        key_concepts=module.key_concepts or [],
        keywords=module.keywords or [],
        nb_branches=req.nb_branches or 4
    )

    mindmap = MindMap(
        module_id=module.id,
        user_id=current_user.id,
        concept_central=generated.get("concept_central", module.module_title),
        branches_suggerees=generated.get("branches_suggerees", [])
    )
    session.add(mindmap)
    session.commit()
    session.refresh(mindmap)

    # Register in global library catalogue
    try:
        register_library_item(
            session=session,
            user_id=current_user.id,
            game_type="mindmap",
            game_id=mindmap.id,
            module_id=module.id,
            titre=f"Mind Map : {mindmap.concept_central}",
            niveaux_bloom=["comprendre", "analyser", "creer"],
            concepts_cles=module.key_concepts or []
        )
        session.commit()
    except Exception as e:
        print(f"Warning: could not register mindmap in library: {e}")

    return {
        "id": mindmap.id,
        "module_id": mindmap.module_id,
        "concept_central": mindmap.concept_central,
        "branches_suggerees": mindmap.branches_suggerees,
        "created_at": mindmap.created_at.isoformat() if mindmap.created_at else None
    }


@router.get("/{id}/export")
def export_mindmap(
    id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Export mind map data tree for image rendering / client export."""
    mindmap = session.get(MindMap, id)
    if not mindmap:
        raise HTTPException(status_code=404, detail="Mind Map not found")

    nodes = session.exec(
        select(MindMapNode).where(MindMapNode.mindmap_id == mindmap.id)
    ).all()

    nodes_list = [
        {
            "id": n.id,
            "parent_node_id": n.parent_node_id,
            "titre": n.titre,
            "equipe_id": n.equipe_id,
            "cree_par_participant_id": n.cree_par_participant_id,
            "created_at": n.created_at.isoformat() if n.created_at else None
        }
        for n in nodes
    ]

    return {
        "mindmap_id": mindmap.id,
        "concept_central": mindmap.concept_central,
        "branches_suggerees": mindmap.branches_suggerees,
        "nodes": nodes_list,
        "total_nodes": len(nodes_list)
    }


@router.get("/{session_id}/completeness")
def evaluate_mindmap_completeness(
    session_id: int,
    mindmap_id: Optional[int] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Evaluate completeness of the Mind Map created by students.
    Calculates:
    - % of suggested branches covered by student nodes
    - Total number of sub-branches added by students
    """
    # Fetch mindmap by mindmap_id if provided or search by session
    if mindmap_id:
        mindmap = session.get(MindMap, mindmap_id)
    else:
        mindmap = session.exec(select(MindMap)).first()

    if not mindmap:
        raise HTTPException(status_code=404, detail="Mind Map not found")

    branches_suggerees = mindmap.branches_suggerees or []
    total_suggested = len(branches_suggerees)

    nodes = session.exec(
        select(MindMapNode).where(MindMapNode.mindmap_id == mindmap.id)
    ).all()

    # Check which suggested branches have at least 1 student node associated or matching title
    covered_count = 0
    branch_coverage = []

    for b in branches_suggerees:
        b_titre = (b.get("titre") or "").lower()
        # Find if any student node title contains or matches branch title
        has_match = any(b_titre in (n.titre or "").lower() or (n.parent_node_id is None) for n in nodes)
        if has_match:
            covered_count += 1
        branch_coverage.append({
            "titre": b.get("titre"),
            "couverte": has_match
        })

    coverage_percent = round((covered_count / total_suggested) * 100) if total_suggested > 0 else 100
    sub_branches_added = len([n for n in nodes if n.parent_node_id is not None])

    return {
        "session_id": session_id,
        "mindmap_id": mindmap.id,
        "concept_central": mindmap.concept_central,
        "total_branches_suggerees": total_suggested,
        "branches_couvertes_count": covered_count,
        "couverture_pourcentage": coverage_percent,
        "nombre_sous_branches_ajoutees": sub_branches_added,
        "total_noeuds_etudiants": len(nodes),
        "branch_coverage_details": branch_coverage
    }


@router.get("/{id}")
def get_mindmap_detail(
    id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get single Mind Map detail."""
    mindmap = session.get(MindMap, id)
    if not mindmap:
        raise HTTPException(status_code=404, detail="Mind Map not found")

    return {
        "id": mindmap.id,
        "module_id": mindmap.module_id,
        "concept_central": mindmap.concept_central,
        "branches_suggerees": mindmap.branches_suggerees,
        "created_at": mindmap.created_at.isoformat() if mindmap.created_at else None
    }
