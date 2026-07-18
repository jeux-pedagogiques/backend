"""WebSocket router for custom WebRTC live sessions signaling and database logs."""

import logging
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from sqlmodel import Session, select
from pydantic import BaseModel

from app.database import get_session, engine
from app.services.auth_service import get_current_user
from app.models.user import User
from app.models.live_session import LiveSession, LiveSessionParticipant, ScheduledMeeting

router = APIRouter(prefix="/api/live", tags=["live-sessions"])

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Active rooms map: room_id -> list of dictionaries containing websocket, client_id, and name
# Dict[str, List[Dict[str, any]]]
active_rooms: Dict[str, List[Dict[str, any]]] = {}


class CreateSessionRequest(BaseModel):
    room_id: str
    name: str


@router.post("/session", status_code=201)
def create_session(
    data: CreateSessionRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Create a live session record in the database."""
    # Only professors can create sessions
    if current_user.role != "prof":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seuls les professeurs peuvent créer des séances."
        )

    # Check if room already exists
    existing = session.exec(
        select(LiveSession).where(LiveSession.room_id == data.room_id)
    ).first()
    if existing:
        # Reactivate it if it was inactive
        if not existing.is_active:
            existing.is_active = True
            session.add(existing)
            session.commit()
            session.refresh(existing)
        return {"status": "ok", "id": existing.id}

    db_session = LiveSession(
        room_id=data.room_id,
        name=data.name,
        creator_id=current_user.id,
        is_active=True
    )
    session.add(db_session)
    session.commit()
    session.refresh(db_session)
    return {"status": "created", "id": db_session.id}


@router.post("/session/{room_id}/end")
def end_session(
    room_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Mark a live session as inactive and set left_at for remaining participants."""
    db_session = session.exec(
        select(LiveSession).where(LiveSession.room_id == room_id)
    ).first()
    if not db_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Séance non trouvée."
        )

    # Allow session creator to end it
    if db_session.creator_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Non autorisé à terminer cette séance."
        )

    db_session.is_active = False
    session.add(db_session)

    # Set left_at for all active participants who haven't left yet
    active_participants = session.exec(
        select(LiveSessionParticipant).where(
            LiveSessionParticipant.room_id == room_id,
            LiveSessionParticipant.left_at == None
        )
    ).all()
    for p in active_participants:
        p.left_at = datetime.utcnow()
        session.add(p)

    session.commit()
    return {"status": "ended"}


class ScheduleMeetingRequest(BaseModel):
    title: str
    description: Optional[str] = None
    scheduled_time: datetime
    duration_minutes: int
    room_id: str


@router.post("/schedule", status_code=201)
def schedule_meeting(
    data: ScheduleMeetingRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Schedule a video meeting in the database."""
    if current_user.role != "prof":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seuls les professeurs peuvent planifier des séances."
        )

    # Check if room already used or scheduled
    existing = session.exec(
        select(ScheduledMeeting).where(ScheduledMeeting.room_id == data.room_id)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cet identifiant de séance est déjà réservé."
        )

    meeting = ScheduledMeeting(
        title=data.title,
        description=data.description,
        scheduled_time=data.scheduled_time,
        duration_minutes=data.duration_minutes,
        room_id=data.room_id,
        creator_id=current_user.id
    )
    session.add(meeting)
    session.commit()
    session.refresh(meeting)
    return {"status": "scheduled", "id": meeting.id}


@router.get("/schedule")
def list_scheduled_meetings(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """List scheduled meetings from the database."""
    statement = select(ScheduledMeeting).order_by(ScheduledMeeting.scheduled_time.asc())
    meetings = session.exec(statement).all()
    
    result = []
    for m in meetings:
        creator = session.get(User, m.creator_id)
        creator_name = (
            f"{creator.first_name} {creator.last_name}"
            if creator and creator.first_name and creator.last_name
            else (creator.username if creator else "Professeur")
        )
        result.append({
            "id": m.id,
            "title": m.title,
            "description": m.description,
            "scheduled_time": m.scheduled_time,
            "duration_minutes": m.duration_minutes,
            "room_id": m.room_id,
            "creator_name": creator_name,
            "is_mine": m.creator_id == current_user.id
        })
    return result


@router.delete("/schedule/{meeting_id}")
def delete_scheduled_meeting(
    meeting_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Cancel/Delete a scheduled meeting."""
    meeting = session.get(ScheduledMeeting, meeting_id)
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Séance planifiée non trouvée."
        )

    if meeting.creator_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Non autorisé à annuler cette séance planifiée."
        )

    session.delete(meeting)
    session.commit()
    return {"status": "deleted"}


class LockSessionRequest(BaseModel):
    locked: bool


@router.post("/session/{room_id}/lock")
def lock_session(
    room_id: str,
    data: LockSessionRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Lock or unlock a live session room."""
    db_session = session.exec(
        select(LiveSession).where(LiveSession.room_id == room_id, LiveSession.is_active == True)
    ).first()
    
    if not db_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Séance active non trouvée."
        )

    if db_session.creator_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seul l'organisateur peut verrouiller la séance."
        )

    db_session.is_locked = data.locked
    session.add(db_session)
    session.commit()
    return {"status": "success", "is_locked": db_session.is_locked}


@router.websocket("/ws/{room_id}/{client_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    room_id: str,
    client_id: str,
    name: str = "Invité",
    role: str = "guest",
    user_id: Optional[int] = None
):
    """WebSocket endpoint for WebRTC signaling and participant log tracking."""
    # Open DB session to check room and duplicate name
    with Session(engine) as db:
        # 1. Validate if session is active
        db_session = db.exec(
            select(LiveSession).where(LiveSession.room_id == room_id, LiveSession.is_active == True)
        ).first()
        
        if not db_session:
            scheduled = db.exec(
                select(ScheduledMeeting).where(ScheduledMeeting.room_id == room_id)
            ).first()
            msg = "Cette séance n'est pas active ou a été fermée."
            if scheduled:
                msg = "Cette séance n'a pas encore été démarrée par le professeur."
            
            await websocket.accept()
            await websocket.send_json({
                "type": "error",
                "message": msg
            })
            await websocket.close(code=4002)
            return

        # 2. Check if room is locked (only professors can bypass locks)
        if db_session.is_locked and role != "prof":
            await websocket.accept()
            await websocket.send_json({
                "type": "error",
                "message": "Cette séance est verrouillée par l'organisateur. L'accès est fermé."
            })
            await websocket.close(code=4003)
            return

        # 2. Check if username is already taken in this room
        if room_id in active_rooms:
            reconnecting_client = None
            for client in active_rooms[room_id]:
                if client.get("name", "").strip().lower() == name.strip().lower():
                    if client.get("client_id") == client_id:
                        reconnecting_client = client
                    else:
                        await websocket.accept()
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Le nom '{name}' est déjà utilisé dans cette séance. Veuillez en choisir un autre."
                        })
                        await websocket.close(code=4001)
                        return
            
            if reconnecting_client:
                logger.info(f"Reconnection detected for client {client_id} ({name}). Closing old connection.")
                try:
                    await reconnecting_client["websocket"].close()
                except Exception as e:
                    logger.debug(f"Failed to close old websocket for client {client_id}: {e}")
                active_rooms[room_id] = [c for c in active_rooms[room_id] if c["client_id"] != client_id]

    # Accept the connection if all checks pass
    await websocket.accept()
    logger.info(f"Client {client_id} ({name}) connected to room {room_id} with role {role}")

    # Add client to the room
    if room_id not in active_rooms:
        active_rooms[room_id] = []
    
    # Notify existing peers in the room that a new peer joined
    for client in active_rooms[room_id]:
        try:
            await client["websocket"].send_json({
                "type": "peer-joined",
                "senderId": client_id,
            })
        except Exception as e:
            logger.error(f"Error sending peer-joined to {client['client_id']}: {e}")

    # Save connection
    active_rooms[room_id].append({
        "client_id": client_id,
        "websocket": websocket,
        "name": name
    })

    # Log participant join in the database
    with Session(engine) as db:
        participant = LiveSessionParticipant(
            room_id=room_id,
            user_id=user_id,
            username=name,
            role=role,
            joined_at=datetime.utcnow()
        )
        db.add(participant)
        db.commit()

    try:
        while True:
            # Receive text message from client (expected to be JSON string)
            data = await websocket.receive_json()
            
            # Message format: { "type": "offer/answer/candidate", "targetId": "...", "payload": ... }
            target_id = data.get("targetId")
            
            if target_id:
                # Forward signaling message to the targeted peer
                for client in active_rooms[room_id]:
                    if client["client_id"] == target_id:
                        try:
                            await client["websocket"].send_json({
                                "type": data.get("type"),
                                "senderId": client_id,
                                "payload": data.get("payload")
                             })
                        except Exception as e:
                            logger.error(f"Error forwarding message to {target_id}: {e}")
                        break
            else:
                # Broadcast message to everyone else in the room (if no target specified)
                for client in active_rooms[room_id]:
                    if client["client_id"] != client_id:
                        try:
                            await client["websocket"].send_json({
                                "type": data.get("type"),
                                "senderId": client_id,
                                "payload": data.get("payload")
                            })
                        except Exception as e:
                            logger.error(f"Error broadcasting message to {client['client_id']}: {e}")

    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected from room {room_id}")
        
        # Remove client from active room
        if room_id in active_rooms:
            active_rooms[room_id] = [c for c in active_rooms[room_id] if c["client_id"] != client_id]
            
            # If room is now empty, delete it
            if not active_rooms[room_id]:
                del active_rooms[room_id]
            else:
                # Notify remaining peers that this client left
                for client in active_rooms[room_id]:
                    try:
                        await client["websocket"].send_json({
                            "type": "peer-left",
                            "senderId": client_id
                        })
                    except Exception as e:
                        logger.error(f"Error sending peer-left to {client['client_id']}: {e}")

        # Update participant left time in database
        with Session(engine) as db:
            statement = select(LiveSessionParticipant).where(
                LiveSessionParticipant.room_id == room_id,
                LiveSessionParticipant.username == name,
                LiveSessionParticipant.left_at == None
            )
            p = db.exec(statement).first()
            if p:
                p.left_at = datetime.utcnow()
                db.add(p)
                db.commit()

    except Exception as e:
        logger.error(f"Unexpected error in websocket connection for client {client_id}: {e}")
        # Make sure client is removed
        if room_id in active_rooms:
            active_rooms[room_id] = [c for c in active_rooms[room_id] if c["client_id"] != client_id]
            if not active_rooms[room_id]:
                del active_rooms[room_id]

        # Update participant left time in database
        with Session(engine) as db:
            statement = select(LiveSessionParticipant).where(
                LiveSessionParticipant.room_id == room_id,
                LiveSessionParticipant.username == name,
                LiveSessionParticipant.left_at == None
            )
            p = db.exec(statement).first()
            if p:
                p.left_at = datetime.utcnow()
                db.add(p)
                db.commit()
