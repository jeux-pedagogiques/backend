import logging
import random
from datetime import datetime
import socketio
from sqlmodel import Session, select
from app.database import engine
from app.models.quiz_session import QuizSession, QuizParticipant, QuizAttempt

logger = logging.getLogger(__name__)

# Initialize Socket.io AsyncServer
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
socket_app = socketio.ASGIApp(sio, socketio_path="/socket.io")


@sio.event
async def connect(sid, environ):
    logger.info(f"Client connected: {sid}")


@sio.event
async def disconnect(sid):
    logger.info(f"Client disconnected: {sid}")
    # Handle participant disconnection gracefully
    with Session(engine) as db:
        statement = select(QuizParticipant).where(QuizParticipant.socket_id == sid)
        participant = db.exec(statement).first()
        if participant:
            participant.is_active = False
            db.add(participant)
            db.commit()
            db.refresh(participant)

            # Get session code to notify room
            statement_session = select(QuizSession).where(QuizSession.id == participant.session_id)
            quiz_session = db.exec(statement_session).first()
            if quiz_session:
                room = f"session_{quiz_session.code_session}"
                # Broadcast updated participants list
                statement_participants = select(QuizParticipant).where(QuizParticipant.session_id == quiz_session.id)
                participants = db.exec(statement_participants).all()
                plist = [{"id": p.id, "pseudo": p.pseudo, "score_total": p.score_total, "is_active": p.is_active} for p in participants]
                await sio.emit("session:participants_list", plist, room=room)


# ==========================================
# PROFESSOR EVENTS
# ==========================================

@sio.on("session:create")
async def on_session_create(sid, data):
    """Create a new quiz session."""
    prof_id = data.get("prof_id")
    module_id = data.get("module_id")
    mode = data.get("mode", "formatif")

    if not prof_id:
        return {"status": "error", "message": "Missing prof_id"}

    # Use the provided code_session (from WebRTC room ID) if available,
    # otherwise generate a random 6-digit code
    code_session = data.get("code_session")

    with Session(engine) as db:
        if code_session:
            # Check if a session with this code already exists (reconnect scenario)
            existing = db.exec(
                select(QuizSession).where(
                    QuizSession.code_session == code_session,
                    QuizSession.statut != "terminee"
                )
            ).first()
            if existing:
                # Reuse existing session
                room = f"session_{code_session}"
                await sio.enter_room(sid, room)
                await sio.save_session(sid, {
                    "role": "prof",
                    "session_code": code_session,
                    "session_id": existing.id
                })
                logger.info(f"Professor {prof_id} reconnected to existing session {code_session} (ID: {existing.id})")
                return {
                    "status": "success",
                    "code_session": code_session,
                    "session_id": existing.id,
                    "qr_code_data": f"/live-session?room={code_session}"
                }
        else:
            # Generate a unique 6-digit code session
            code_session = "".join(random.choices("0123456789", k=6))


        quiz_session = QuizSession(
            prof_id=prof_id,
            module_id=module_id,
            code_session=code_session,
            statut="en_attente",
            mode=mode
        )
        db.add(quiz_session)
        db.commit()
        db.refresh(quiz_session)

        # Join the socket room
        room = f"session_{code_session}"
        await sio.enter_room(sid, room)

        # Save session context
        await sio.save_session(sid, {
            "role": "prof",
            "session_code": code_session,
            "session_id": quiz_session.id
        })

        logger.info(f"Professor {prof_id} created session {code_session} (ID: {quiz_session.id})")
        return {
            "status": "success",
            "code_session": code_session,
            "session_id": quiz_session.id,
            "qr_code_data": f"/live-session?room={code_session}" # Client can render this as QR Code
        }


@sio.on("session:select_module")
async def on_session_select_module(sid, data):
    """Associate or dissociate a module to the session."""
    session_id = data.get("session_id")
    module_id = data.get("module_id") # Can be null to skip

    with Session(engine) as db:
        quiz_session = db.get(QuizSession, session_id)
        if not quiz_session:
            return {"status": "error", "message": "Session not found"}

        quiz_session.module_id = module_id
        db.add(quiz_session)
        db.commit()
        db.refresh(quiz_session)

        room = f"session_{quiz_session.code_session}"
        await sio.emit("session:module_updated", {"module_id": module_id}, room=room)
        return {"status": "success", "module_id": module_id}


@sio.on("quiz:launch")
async def on_quiz_launch(sid, data):
    """Launch the quiz for the session."""
    session_id = data.get("session_id")
    quiz_id = data.get("quiz_id")

    with Session(engine) as db:
        quiz_session = db.get(QuizSession, session_id)
        if not quiz_session:
            return {"status": "error", "message": "Session not found"}

        quiz_session.statut = "en_cours"
        db.add(quiz_session)
        db.commit()

        room = f"session_{quiz_session.code_session}"
        await sio.emit("quiz:launched", {"quiz_id": quiz_id}, room=room)
        logger.info(f"Quiz {quiz_id} launched in session {quiz_session.code_session}")
        return {"status": "success"}


# In-memory store for active question correct answers and durations
# session_id -> { "correct": str, "duration_s": int }
active_questions = {}


@sio.on("quiz:next_question")
async def on_quiz_next_question(sid, data):
    session_id = data.get("session_id")
    question_id = data.get("question_id")
    enonce = data.get("enonce")
    options = data.get("options", [])
    bonne_reponse = data.get("bonne_reponse")
    duree_secondes = data.get("duree_secondes", 30)
    qtype = data.get("type", "qcm")

    with Session(engine) as db:
        quiz_session = db.get(QuizSession, session_id)
        if not quiz_session:
            return {"status": "error", "message": "Session not found"}

        quiz_session.current_question_id = question_id
        quiz_session.current_question_start = datetime.utcnow()
        db.add(quiz_session)
        db.commit()

        # Save correct answer and duration in memory
        active_questions[quiz_session.id] = {
            "correct_answer": str(bonne_reponse),
            "duration_s": int(duree_secondes)
        }

        room = f"session_{quiz_session.code_session}"
        # Broadcast the question WITHOUT the correct answer to prevent student cheating
        await sio.emit("quiz:question", {
            "question_id": question_id,
            "enonce": enonce,
            "options": options,
            "type": qtype,
            "duree_secondes": duree_secondes,
            "start_timestamp": quiz_session.current_question_start.isoformat()
        }, room=room)

        logger.info(f"Question {question_id} ({qtype}) sent for session {quiz_session.code_session}")
        return {"status": "success"}


@sio.on("quiz:show_leaderboard")
async def on_quiz_show_leaderboard(sid, data):
    """Calculate and broadcast the leaderboard to the room."""
    session_id = data.get("session_id")

    with Session(engine) as db:
        quiz_session = db.get(QuizSession, session_id)
        if not quiz_session:
            return {"status": "error", "message": "Session not found"}

        statement = select(QuizParticipant).where(QuizParticipant.session_id == session_id).order_by(QuizParticipant.score_total.desc())
        participants = db.exec(statement).all()

        leaderboard = [
            {"pseudo": p.pseudo, "score_total": p.score_total, "is_active": p.is_active}
            for p in participants
        ]

        room = f"session_{quiz_session.code_session}"
        await sio.emit("quiz:leaderboard", leaderboard, room=room)
        return {"status": "success", "leaderboard": leaderboard}


# ==========================================
# STUDENT EVENTS
# ==========================================

@sio.on("session:join")
async def on_session_join(sid, data):
    """Student joins a session using a session code and a pseudo."""
    code_session = data.get("code_session")
    pseudo = data.get("pseudo")

    if not code_session or not pseudo:
        return {"status": "error", "message": "Missing code_session or pseudo"}

    with Session(engine) as db:
        # Find active session
        statement = select(QuizSession).where(
            QuizSession.code_session == code_session,
            QuizSession.statut != "terminee"
        )
        quiz_session = db.exec(statement).first()
        if not quiz_session:
            return {"status": "error", "message": "Séance introuvable ou fermée."}

        # Check for existing participant with this pseudo (for reconnects)
        statement_p = select(QuizParticipant).where(
            QuizParticipant.session_id == quiz_session.id,
            QuizParticipant.pseudo == pseudo
        )
        participant = db.exec(statement_p).first()

        if participant:
            # Reconnection: update socket id and make active
            participant.socket_id = sid
            participant.is_active = True
            db.add(participant)
            db.commit()
            db.refresh(participant)
            logger.info(f"Participant {pseudo} reconnected to session {code_session}")
        else:
            # Join: create new participant record
            participant = QuizParticipant(
                session_id=quiz_session.id,
                pseudo=pseudo,
                socket_id=sid,
                score_total=0,
                is_active=True
            )
            db.add(participant)
            db.commit()
            db.refresh(participant)
            logger.info(f"Participant {pseudo} joined session {code_session}")

        # Place connection in room
        room = f"session_{code_session}"
        await sio.enter_room(sid, room)

        # Save session context
        await sio.save_session(sid, {
            "role": "student",
            "session_code": code_session,
            "session_id": quiz_session.id,
            "participant_id": participant.id
        })

        # Broadcast fresh participants list to all room members
        statement_participants = select(QuizParticipant).where(QuizParticipant.session_id == quiz_session.id)
        participants = db.exec(statement_participants).all()
        plist = [{"id": p.id, "pseudo": p.pseudo, "score_total": p.score_total, "is_active": p.is_active} for p in participants]
        await sio.emit("session:participants_list", plist, room=room)

        return {
            "status": "success",
            "participant_id": participant.id,
            "pseudo": pseudo,
            "mode": quiz_session.mode
        }


@sio.on("quiz:submit_answer")
async def on_quiz_submit_answer(sid, data):
    """Receive and grade student's submitted answer."""
    question_id = data.get("question_id")
    reponse = data.get("reponse")

    # Load session context from Socket.io session store
    sio_session = await sio.get_session(sid)
    if not sio_session or sio_session.get("role") != "student":
        return {"status": "error", "message": "Unauthorized client."}

    session_id = sio_session.get("session_id")
    participant_id = sio_session.get("participant_id")
    session_code = sio_session.get("session_code")

    with Session(engine) as db:
        quiz_session = db.get(QuizSession, session_id)
        participant = db.get(QuizParticipant, participant_id)

        if not quiz_session or not participant:
            return {"status": "error", "message": "Session or participant not found."}

        # Check if the submitted question is the active one
        if quiz_session.current_question_id != question_id:
            return {"status": "error", "message": "Cette question n'est plus active."}

        # Verify if student already submitted an answer for this question
        statement_attempt = select(QuizAttempt).where(
            QuizAttempt.participant_id == participant_id,
            QuizAttempt.question_id == question_id
        )
        existing_attempt = db.exec(statement_attempt).first()
        if existing_attempt:
            return {"status": "error", "message": "Réponse déjà soumise pour cette question."}

        # Compute response time on SERVER side
        current_time = datetime.utcnow()
        temps_reponse_ms = int((current_time - quiz_session.current_question_start).total_seconds() * 1000)

        # Retrieve correct answer and duration from memory store
        active_q = active_questions.get(quiz_session.id, {})
        correct_answer = active_q.get("correct_answer")
        duration_s = active_q.get("duration_s", 30)
        duree_max_ms = duration_s * 1000

        # Grade the answer
        # Perform a case-insensitive, stripped match for safety
        est_correcte = str(reponse).strip().lower() == str(correct_answer).strip().lower()

        # Score calculation logic
        points_obtenus = 0
        if est_correcte:
            if quiz_session.mode == "competitif":
                # Max 1000 points, losing points as time goes on, down to min 500 points
                penalty = int((temps_reponse_ms / duree_max_ms) * 500)
                points_obtenus = max(500, 1000 - penalty)
            else:
                # Formative mode: Flat 1000 points for correct answer
                points_obtenus = 1000

        # Save attempt in DB
        attempt = QuizAttempt(
            participant_id=participant_id,
            question_id=question_id,
            reponse_donnee=reponse,
            est_correcte=est_correcte,
            temps_reponse_ms=temps_reponse_ms,
            points_obtenus=points_obtenus
        )
        db.add(attempt)

        # Update participant total score
        participant.score_total += points_obtenus
        db.add(participant)
        db.commit()
        db.refresh(participant)

        # Notify student of their grade
        await sio.emit("quiz:answer_result", {
            "est_correcte": est_correcte,
            "points_obtenus": points_obtenus,
            "temps_reponse_ms": temps_reponse_ms
        }, room=sid)

        # Broadcast updated participant score to room (for real-time leaderboard widgets)
        room = f"session_{session_code}"
        await sio.emit("participant:score_updated", {
            "participant_id": participant.id,
            "pseudo": participant.pseudo,
            "score_total": participant.score_total
        }, room=room)

        return {"status": "success", "points_obtenus": points_obtenus}
