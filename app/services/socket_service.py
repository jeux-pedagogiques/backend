import logging
import random
from datetime import datetime
import socketio
from sqlmodel import Session, select
from app.database import engine
from app.models.quiz_session import QuizSession, QuizParticipant, QuizAttempt
from app.models.cas_etude import CasEtude, EquipeCasEtude, RoleAssignment, DecisionEquipe
from app.models.mindmap import MindMap, MindMapNode
from app.models.debat import Debat, ParticipantDebat, PriseDeParole, NoteObservateur
from app.models.negociation import Negociation, GroupeNegociation, AssignationPersonnage, AccordFinal

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
                plist = [{"id": p.id, "pseudo": p.pseudo, "score_total": p.score_total, "is_active": p.is_active, "socket_id": p.socket_id} for p in participants]
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


# In-memory store for debate turn management (server-side chrono)
# debat_id -> { "participant_id": str, "pseudo": str, "camp": str, "start": datetime, "duree_max": int }
active_interventions = {}

# debat_id -> socket sid of the professor who launched it (for live-only observer notes)
debat_prof_sids = {}


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
        plist = [{"id": p.id, "pseudo": p.pseudo, "score_total": p.score_total, "is_active": p.is_active, "socket_id": p.socket_id} for p in participants]
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


# ==========================================
# CAS D'ÉTUDE GAMIFIÉE EVENTS
# ==========================================

@sio.on("cas:launch")
async def on_cas_launch(sid, data):
    """
    Professor launches a Case Study session.
    Distributes scenario to room and sends ASSYMETRIC ROLE INFO exclusively to each participant sid.
    """
    session_id = data.get("session_id")
    session_code = data.get("session_code")
    cas_etude_id = data.get("cas_etude_id")
    equipes_data = data.get("equipes", [])  # list of {"nom_equipe": "...", "participants": [{"id": "sid_or_uid", "pseudo": "..."}]}

    if not cas_etude_id or not session_code:
        return {"status": "error", "message": "Missing cas_etude_id or session_code"}

    with Session(engine) as db:
        cas = db.get(CasEtude, cas_etude_id)
        if not cas:
            return {"status": "error", "message": "Cas d'étude not found"}

        roles_list = cas.roles or []
        created_equipes = []

        for eq_data in equipes_data:
            nom_equipe = eq_data.get("nom_equipe", "Équipe")
            participants = eq_data.get("participants", [])

            equipe = EquipeCasEtude(
                session_id=session_id or 0,
                cas_etude_id=cas.id,
                nom_equipe=nom_equipe,
                statut="en_analyse"
            )
            db.add(equipe)
            db.commit()
            db.refresh(equipe)

            # Assign roles round-robin to participants in team
            assigned_roles = []
            for idx, part in enumerate(participants):
                part_id = str(part.get("id") or part.get("socket_id") or f"part_{idx}")
                part_pseudo = part.get("pseudo", f"Participant {idx + 1}")
                
                # Pick role
                role_obj = roles_list[idx % len(roles_list)] if roles_list else {"nom_role": "Analyste"}
                role_name = role_obj.get("nom_role", "Analyste")

                assignment = RoleAssignment(
                    equipe_cas_etude_id=equipe.id,
                    participant_id=part_id,
                    nom_role=role_name,
                    participant_pseudo=part_pseudo
                )
                db.add(assignment)
                db.commit()

                # CRITICAL SECURITY REQUIREMENT:
                # Send private role info DIRECTLY to this participant's socket ID only (NO BROADCAST)
                target_sid = part.get("socket_id") or part_id
                role_private_payload = {
                    "equipe_id": equipe.id,
                    "nom_equipe": equipe.nom_equipe,
                    "nom_role": role_name,
                    "objectifs": role_obj.get("objectifs", ""),
                    "infos_privees": role_obj.get("infos_privees", ""),
                    "contraintes_secretes": role_obj.get("contraintes_secretes", "")
                }
                try:
                    await sio.emit("cas:your_role_info", role_private_payload, to=target_sid)
                except Exception as e:
                    logger.warning(f"Could not send role info directly to sid {target_sid}: {e}")

                assigned_roles.append({
                    "participant_id": part_id,
                    "participant_pseudo": part_pseudo,
                    "nom_role": role_name
                })

            created_equipes.append({
                "equipe_id": equipe.id,
                "nom_equipe": equipe.nom_equipe,
                "statut": equipe.statut,
                "members_count": len(participants)
            })

        # Broadcast general scenario context to room (WITHOUT role private data)
        room = f"session_{session_code}"
        await sio.emit("cas:scenario_started", {
            "cas_etude_id": cas.id,
            "titre": cas.titre,
            "contexte_scenario": cas.contexte_scenario,
            "questions_decisions": cas.questions_decisions,
            "format_restitution": cas.format_restitution,
            "equipes": created_equipes
        }, room=room)

        return {"status": "success", "equipes": created_equipes}


@sio.on("cas:start_restitution")
async def on_cas_start_restitution(sid, data):
    """Professor transitions a team or all teams to restitution phase."""
    equipe_id = data.get("equipe_id")
    session_code = data.get("session_code")

    with Session(engine) as db:
        if equipe_id:
            eq = db.get(EquipeCasEtude, equipe_id)
            if eq:
                eq.statut = "restitution_faite"
                db.add(eq)
                db.commit()

        room = f"session_{session_code}" if session_code else None
        payload = {
            "equipe_id": equipe_id,
            "statut": "restitution_faite"
        }
        if room:
            await sio.emit("cas:phase_restitution", payload, room=room)
        else:
            await sio.emit("cas:phase_restitution", payload)

        return {"status": "success"}


@sio.on("cas:submit_decision")
async def on_cas_submit_decision(sid, data):
    """Student team submits a decision for a question."""
    equipe_id = data.get("equipe_id")
    question_id = str(data.get("question_id", ""))
    decision_texte = data.get("decision_texte", "")
    justification_texte = data.get("justification_texte", "")
    session_code = data.get("session_code")

    if not equipe_id or not question_id:
        return {"status": "error", "message": "Missing equipe_id or question_id"}

    with Session(engine) as db:
        decision = DecisionEquipe(
            equipe_cas_etude_id=equipe_id,
            question_id=question_id,
            decision_texte=decision_texte,
            justification_texte=justification_texte
        )
        db.add(decision)
        db.commit()
        db.refresh(decision)

        # Notify submitting student/team
        await sio.emit("cas:decision_saved", {
            "id": decision.id,
            "equipe_id": equipe_id,
            "question_id": question_id,
            "status": "saved"
        }, to=sid)

        # Notify professor/room of decision progress
        if session_code:
            room = f"session_{session_code}"
            await sio.emit("cas:team_decision_updated", {
                "equipe_id": equipe_id,
                "question_id": question_id,
                "decision_texte": decision_texte,
                "justification_texte": justification_texte
            }, room=room)

        return {"status": "success", "decision_id": decision.id}


@sio.on("cas:view_role_info")
async def on_cas_view_role_info(sid, data):
    """
    Student requests their role private info.
    Server fetches role assignment and returns ONLY that participant's private info to their sid.
    """
    participant_id = str(data.get("participant_id") or sid)

    with Session(engine) as db:
        assignment = db.exec(
            select(RoleAssignment).where(RoleAssignment.participant_id == participant_id)
        ).first()

        if not assignment:
            # Fallback check by socket sid
            assignment = db.exec(
                select(RoleAssignment).where(RoleAssignment.participant_id == sid)
            ).first()

        if not assignment:
            await sio.emit("cas:role_info", {"error": "Aucun rôle attribué trouvé."}, to=sid)
            return {"status": "error", "message": "Role assignment not found"}

        equipe = db.get(EquipeCasEtude, assignment.equipe_cas_etude_id)
        if not equipe:
            await sio.emit("cas:role_info", {"error": "Équipe non trouvée."}, to=sid)
            return {"status": "error", "message": "Team not found"}

        cas = db.get(CasEtude, equipe.cas_etude_id)
        if not cas:
            await sio.emit("cas:role_info", {"error": "Cas d'étude non trouvé."}, to=sid)
            return {"status": "error", "message": "Case study not found"}

        roles_list = cas.roles or []
        target_role = None
        for r in roles_list:
            if r.get("nom_role") == assignment.nom_role:
                target_role = r
                break

        if not target_role and roles_list:
            target_role = roles_list[0]

        role_payload = {
            "equipe_id": equipe.id,
            "nom_equipe": equipe.nom_equipe,
            "nom_role": assignment.nom_role,
            "objectifs": target_role.get("objectifs", "") if target_role else "",
            "infos_privees": target_role.get("infos_privees", "") if target_role else "",
            "contraintes_secretes": target_role.get("contraintes_secretes", "") if target_role else ""
        }

        # Send ONLY to requesting student's sid
        await sio.emit("cas:role_info", role_payload, to=sid)
        return {"status": "success", "role_info": role_payload}


# ==========================================
# MIND MAP COLLABORATIF EVENTS
# ==========================================

@sio.on("mindmap:launch")
async def on_mindmap_launch(sid, data):
    """
    Professor launches a Mind Map session.
    Broadcasts concept_central and branches_suggerees to session room.
    """
    session_code = data.get("session_code")
    mindmap_id = data.get("mindmap_id")

    if not mindmap_id or not session_code:
        return {"status": "error", "message": "Missing mindmap_id or session_code"}

    with Session(engine) as db:
        mindmap = db.get(MindMap, mindmap_id)
        if not mindmap:
            return {"status": "error", "message": "Mind Map not found"}

        # Fetch existing nodes if any
        nodes = db.exec(select(MindMapNode).where(MindMapNode.mindmap_id == mindmap.id)).all()
        nodes_data = [
            {
                "id": n.id,
                "parent_node_id": n.parent_node_id,
                "titre": n.titre,
                "equipe_id": n.equipe_id,
                "cree_par_participant_id": n.cree_par_participant_id,
                "ordre": n.ordre
            }
            for n in nodes
        ]

        payload = {
            "mindmap_id": mindmap.id,
            "concept_central": mindmap.concept_central,
            "branches_suggerees": mindmap.branches_suggerees,
            "nodes": nodes_data
        }

        room = f"session_{session_code}"
        await sio.emit("mindmap:started", payload, room=room)
        return {"status": "success", "mindmap": payload}


@sio.on("mindmap:add_node")
async def on_mindmap_add_node(sid, data):
    """
    Student or team adds a new node to the Mind Map.
    Saves in DB and broadcasts 'mindmap:node_added' in real time to the team/room.
    """
    mindmap_id = data.get("mindmap_id")
    equipe_id = data.get("equipe_id", 0)
    parent_node_id = data.get("parent_node_id")  # Can be None for top-level branch
    titre = data.get("titre")
    participant_id = str(data.get("participant_id") or sid)
    session_code = data.get("session_code")

    if not mindmap_id or not titre:
        return {"status": "error", "message": "Missing mindmap_id or titre"}

    with Session(engine) as db:
        node = MindMapNode(
            mindmap_id=mindmap_id,
            equipe_id=equipe_id,
            parent_node_id=parent_node_id,
            titre=titre,
            cree_par_participant_id=participant_id
        )
        db.add(node)
        db.commit()
        db.refresh(node)

        payload = {
            "id": node.id,
            "mindmap_id": node.mindmap_id,
            "equipe_id": node.equipe_id,
            "parent_node_id": node.parent_node_id,
            "titre": node.titre,
            "cree_par_participant_id": node.cree_par_participant_id,
            "created_at": node.created_at.isoformat() if node.created_at else None
        }

        room = f"session_{session_code}" if session_code else f"team_{equipe_id}"
        await sio.emit("mindmap:node_added", payload, room=room)
        return {"status": "success", "node": payload}


@sio.on("mindmap:remove_node")
async def on_mindmap_remove_node(sid, data):
    """
    Deletes a node and recursively all its child nodes.
    Broadcasts 'mindmap:node_removed' to room.
    """
    node_id = data.get("node_id")
    session_code = data.get("session_code")
    equipe_id = data.get("equipe_id", 0)

    if not node_id:
        return {"status": "error", "message": "Missing node_id"}

    with Session(engine) as db:
        def get_all_child_ids(parent_id: int) -> list[int]:
            children = db.exec(select(MindMapNode).where(MindMapNode.parent_node_id == parent_id)).all()
            ids = [parent_id]
            for child in children:
                ids.extend(get_all_child_ids(child.id))
            return ids

        target_node = db.get(MindMapNode, node_id)
        if not target_node:
            return {"status": "error", "message": "Node not found"}

        ids_to_delete = get_all_child_ids(node_id)
        for n_id in ids_to_delete:
            n = db.get(MindMapNode, n_id)
            if n:
                db.delete(n)
        db.commit()

        payload = {
            "node_id": node_id,
            "deleted_node_ids": ids_to_delete
        }

        room = f"session_{session_code}" if session_code else f"team_{equipe_id}"
        await sio.emit("mindmap:node_removed", payload, room=room)
        return {"status": "success", "deleted_ids": ids_to_delete}


@sio.on("mindmap:move_node")
async def on_mindmap_move_node(sid, data):
    """
    Reorganizes a node by attaching it to a new parent_node_id.
    Broadcasts 'mindmap:node_moved' in real time to room.
    """
    node_id = data.get("node_id")
    new_parent_node_id = data.get("new_parent_node_id")
    session_code = data.get("session_code")
    equipe_id = data.get("equipe_id", 0)

    if not node_id:
        return {"status": "error", "message": "Missing node_id"}

    with Session(engine) as db:
        node = db.get(MindMapNode, node_id)
        if not node:
            return {"status": "error", "message": "Node not found"}

        node.parent_node_id = new_parent_node_id
        db.add(node)
        db.commit()
        db.refresh(node)

        payload = {
            "node_id": node.id,
            "new_parent_node_id": node.parent_node_id
        }

        room = f"session_{session_code}" if session_code else f"team_{equipe_id}"
        await sio.emit("mindmap:node_moved", payload, room=room)
        return {"status": "success", "node": payload}


# ==========================================
# DÉBAT STRUCTURÉ EVENTS
# ==========================================


def _assign_debat_camp_role(index: int) -> tuple[str, str]:
    """Assign a camp + role to a participant by index.

    Index 0 -> modérateur (neutre)
    Index 1 -> observateur-rapporteur (neutre)
    Reste   -> avocat (camp pour) / avocat_du_diable (camp contre) en alternance.
    """
    if index == 0:
        return "neutre", "moderateur"
    if index == 1:
        return "neutre", "observateur_rapporteur"
    if index % 2 == 0:
        return "pour", "avocat"
    return "contre", "avocat_du_diable"


@sio.on("debat:launch")
async def on_debat_launch(sid, data):
    """
    Professor launches a Debate.
    Distributes the problematique + initial arguments to the room and assigns
    a camp + role to every participant (private role info sent per socket).
    """
    debat_id = data.get("debat_id")
    session_code = data.get("session_code")
    session_id = data.get("session_id", 0)
    participants = data.get("participants", [])  # [{id, pseudo, socket_id?}]

    if not debat_id:
        return {"status": "error", "message": "Missing debat_id"}

    with Session(engine) as db:
        debat = db.get(Debat, debat_id)
        if not debat:
            return {"status": "error", "message": "Débat introuvable."}

        # Resolve the hosting session id from the room code when not provided
        if not session_id and session_code:
            quiz_session = db.exec(
                select(QuizSession).where(
                    QuizSession.code_session == session_code,
                    QuizSession.statut != "terminee",
                )
            ).first()
            session_id = quiz_session.id if quiz_session else 0

        debat.statut = "en_cours"
        db.add(debat)

        roles_defs = debat.roles or []
        created = []
        for idx, part in enumerate(participants):
            part_id = str(part.get("id") or part.get("socket_id") or f"part_{idx}")
            part_pseudo = part.get("pseudo", f"Participant {idx + 1}")

            camp, role = _assign_debat_camp_role(idx)

            participant = ParticipantDebat(
                session_id=session_id,
                debat_id=debat.id,
                participant_id=part_id,
                pseudo=part_pseudo,
                camp=camp,
                role=role,
            )
            db.add(participant)
            db.commit()
            db.refresh(participant)

            role_meta = next(
                (r for r in roles_defs if r.get("nom_role") == role), {}
            )

            # Private role info -> only this participant's socket (NO broadcast)
            role_private_payload = {
                "debat_id": debat.id,
                "participant_id": participant.id,
                "camp": camp,
                "role": role,
                "role_description": role_meta.get("description", ""),
                "missions": role_meta.get("missions", []),
            }
            target_sid = part.get("socket_id") or part_id
            try:
                await sio.emit("debat:your_role", role_private_payload, to=target_sid)
            except Exception as e:
                logger.warning(f"Could not send debat role info directly to sid {target_sid}: {e}")

            created.append({
                "participant_id": participant.id,
                "client_id": part_id,
                "participant_pseudo": part_pseudo,
                "camp": camp,
                "role": role,
            })

        # Remember the prof sid for live-only observer notes
        debat_prof_sids[debat.id] = sid

        room = f"session_{session_code}" if session_code else None
        payload = {
            "debat_id": debat.id,
            "session_id": session_id,
            "problematique": debat.problematique,
            "camp_pour": debat.camp_pour,
            "camp_contre": debat.camp_contre,
            "roles": debat.roles,
            "questions_relance": debat.questions_relance,
            "duree_intervention_secondes": data.get("duree_intervention_secondes", 120),
            "participants": created,
        }
        if room:
            await sio.emit("debat:launched", payload, room=room)
        else:
            await sio.emit("debat:launched", payload)

        logger.info(f"Debate {debat.id} launched in session {session_code or session_id}")
        return {"status": "success", "session_id": session_id, "participants": created}


@sio.on("debat:start_intervention")
async def on_debat_start_intervention(sid, data):
    """
    Start the speaking turn (server-side chrono) for the given participant.
    Any still-open turn is finalized automatically (one speaker at a time).
    """
    debat_id = data.get("debat_id")
    participant_id = str(data.get("participant_id", ""))
    pseudo = data.get("pseudo", "Participant")
    camp = data.get("camp", "neutre")
    duree_max = int(data.get("duree_max", 120))
    session_code = data.get("session_code")

    if not debat_id:
        return {"status": "error", "message": "Missing debat_id"}

    now = datetime.utcnow()

    with Session(engine) as db:
        debat = db.get(Debat, debat_id)
        if not debat or debat.statut != "en_cours":
            return {"status": "error", "message": "Débat introuvable ou non lancé."}

        # Auto-finalize a still-open intervention (strict turn management)
        if debat_id in active_interventions:
            active_interventions.pop(debat_id)
            open_prise = db.exec(
                select(PriseDeParole).where(
                    PriseDeParole.debat_id == debat_id,
                    PriseDeParole.timestamp_fin.is_(None),
                ).order_by(PriseDeParole.timestamp_debut.desc())
            ).first()
            if open_prise:
                open_prise.timestamp_fin = now
                open_prise.duree_secondes = max(
                    0, int((now - open_prise.timestamp_debut).total_seconds())
                )
                db.add(open_prise)

        prise = PriseDeParole(
            debat_id=debat_id,
            participant_id=participant_id,
            pseudo=pseudo,
            camp=camp,
            timestamp_debut=now,
        )
        db.add(prise)
        db.commit()
        db.refresh(prise)

        active_interventions[debat_id] = {
            "participant_id": participant_id,
            "pseudo": pseudo,
            "camp": camp,
            "start": now,
            "duree_max": duree_max,
        }

        room = f"session_{session_code}" if session_code else None
        payload = {
            "debat_id": debat_id,
            "intervention_id": prise.id,
            "participant_id": participant_id,
            "pseudo": pseudo,
            "camp": camp,
            "duree_max": duree_max,
            "start_timestamp": now.isoformat(),
        }
        if room:
            await sio.emit("debat:intervention_started", payload, room=room)
        else:
            await sio.emit("debat:intervention_started", payload)

        return {"status": "success", "intervention_id": prise.id}


@sio.on("debat:end_intervention")
async def on_debat_end_intervention(sid, data):
    """
    Stop the speaking turn, record the real server-side duration and save the
    spoken argument text (if provided).
    """
    debat_id = data.get("debat_id")
    contenu = (data.get("contenu") or "").strip()
    session_code = data.get("session_code")

    if not debat_id:
        return {"status": "error", "message": "Missing debat_id"}

    now = datetime.utcnow()
    active = active_interventions.pop(debat_id, None)

    with Session(engine) as db:
        prise = db.exec(
            select(PriseDeParole).where(
                PriseDeParole.debat_id == debat_id,
                PriseDeParole.timestamp_fin.is_(None),
            ).order_by(PriseDeParole.timestamp_debut.desc())
        ).first()

        if not prise:
            return {"status": "error", "message": "Aucune intervention en cours pour ce débat."}

        if active:
            duree = max(0, int((now - active["start"]).total_seconds()))
        else:
            duree = max(0, int((now - prise.timestamp_debut).total_seconds()))

        prise.timestamp_fin = now
        prise.duree_secondes = duree
        if contenu:
            prise.contenu = contenu
        db.add(prise)
        db.commit()
        db.refresh(prise)

        room = f"session_{session_code}" if session_code else None
        payload = {
            "debat_id": debat_id,
            "intervention_id": prise.id,
            "participant_id": prise.participant_id,
            "pseudo": prise.pseudo,
            "camp": prise.camp,
            "duree_secondes": prise.duree_secondes,
            "contenu": prise.contenu,
        }
        if room:
            await sio.emit("debat:intervention_ended", payload, room=room)
        else:
            await sio.emit("debat:intervention_ended", payload)

        return {"status": "success", "intervention_id": prise.id, "duree_secondes": prise.duree_secondes}


@sio.on("debat:add_observer_note")
async def on_debat_add_observer_note(sid, data):
    """
    Observer writes a note.
    Live: emitted privately ONLY to the professor's socket.
    Final: available to everyone via GET /api/debat/{session_id}/notes.
    """
    debat_id = data.get("debat_id")
    participant_id = str(data.get("participant_id") or sid)
    pseudo = data.get("pseudo", "Observateur")
    note_texte = (data.get("note_texte") or "").strip()

    if not debat_id:
        return {"status": "error", "message": "Missing debat_id"}
    if not note_texte:
        return {"status": "error", "message": "Note vide."}

    with Session(engine) as db:
        debat = db.get(Debat, debat_id)
        if not debat:
            return {"status": "error", "message": "Débat introuvable."}

        note = NoteObservateur(
            debat_id=debat_id,
            participant_id=participant_id,
            pseudo=pseudo,
            note_texte=note_texte,
            timestamp=datetime.utcnow(),
        )
        db.add(note)
        db.commit()
        db.refresh(note)

        payload = {
            "debat_id": debat_id,
            "note_id": note.id,
            "participant_id": note.participant_id,
            "pseudo": note.pseudo,
            "note_texte": note.note_texte,
            "timestamp": note.timestamp.isoformat() if note.timestamp else None,
        }

        # Live: only the professor sees the note (private emit)
        prof_sid = debat_prof_sids.get(debat_id)
        if prof_sid:
            try:
                await sio.emit("debat:observer_note", payload, to=prof_sid)
            except Exception as e:
                logger.warning(f"Could not emit observer note to prof {prof_sid}: {e}")

        return {"status": "success", "note_id": note.id}


@sio.on("debat:end")
async def on_debat_end(sid, data):
    """
    End the debate: finalize the current turn, generate the automatic AI
    synthesis from the PriseDeParole history and broadcast it to the room.
    """
    debat_id = data.get("debat_id")
    session_code = data.get("session_code")

    if not debat_id:
        return {"status": "error", "message": "Missing debat_id"}

    # Finalize any still-open intervention
    active_interventions.pop(debat_id, None)

    with Session(engine) as db:
        debat = db.get(Debat, debat_id)
        if not debat:
            return {"status": "error", "message": "Débat introuvable."}

        interventions = db.exec(
            select(PriseDeParole)
            .where(PriseDeParole.debat_id == debat.id)
            .order_by(PriseDeParole.timestamp_debut)
        ).all()
        notes = db.exec(
            select(NoteObservateur)
            .where(NoteObservateur.debat_id == debat.id)
            .order_by(NoteObservateur.timestamp)
        ).all()

        from app.services.debat_service import generate_debat_synthese

        try:
            debat.synthese = await generate_debat_synthese(
                problematique=debat.problematique,
                interventions=[
                    {
                        "pseudo": i.pseudo,
                        "camp": i.camp,
                        "contenu": i.contenu,
                        "duree_secondes": i.duree_secondes,
                    }
                    for i in interventions
                ],
                notes=[n.note_texte for n in notes],
            )
        except RuntimeError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            logger.error(f"Failed to generate debate synthesis: {e}")
            return {"status": "error", "message": f"Erreur lors de la génération de la synthèse : {e}"}

        debat.statut = "terminee"
        db.add(debat)
        db.commit()
        db.refresh(debat)

        room = f"session_{session_code}" if session_code else None
        payload = {
            "debat_id": debat.id,
            "synthese": debat.synthese,
            "nb_interventions": len(interventions),
            "nb_notes": len(notes),
        }
        if room:
            await sio.emit("debat:synthese", payload, room=room)
        else:
            await sio.emit("debat:synthese", payload)

        logger.info(f"Debate {debat.id} ended, synthesis generated")
        return {"status": "success", "synthese": debat.synthese}


# ==========================================
# SIMULATION DE NÉGOCIATION EVENTS
# ==========================================

@sio.on("negociation:launch")
async def on_negociation_launch(sid, data):
    """
    Launch a Negotiation Simulation session.
    Partitions participants into small groups/pairs, assigns character roles,
    and sends targeted private character cards to each student (not broadcasted).
    """
    negociation_id = data.get("negociation_id")
    session_code = data.get("session_code")

    if not negociation_id or not session_code:
        return {"status": "error", "message": "Missing negociation_id or session_code"}

    with Session(engine) as db:
        negociation = db.get(Negociation, negociation_id)
        if not negociation:
            return {"status": "error", "message": "Negotiation scenario not found"}

        session_obj = db.exec(
            select(QuizSession).where(QuizSession.code_session == session_code)
        ).first()
        if not session_obj:
            return {"status": "error", "message": "Live session not found"}

        # Fetch active room participants
        participants = db.exec(
            select(QuizParticipant).where(
                QuizParticipant.session_id == session_obj.id,
                QuizParticipant.is_active == True
            )
        ).all()

        if not participants:
            return {"status": "error", "message": "Aucun participant actif dans la session"}

        personnages = negociation.personnages or []
        if not personnages:
            return {"status": "error", "message": "Aucun personnage défini dans le scénario"}

        nb_per_group = len(personnages)
        shuffled_participants = list(participants)
        random.shuffle(shuffled_participants)

        # Partition into groups
        groupes_created = []
        assignments_map = {}  # socket_id -> private character payload

        group_count = 0
        for i in range(0, len(shuffled_participants), nb_per_group):
            group_count += 1
            group_members = shuffled_participants[i:i + nb_per_group]
            nom_groupe = f"Groupe Négociation #{group_count}"

            groupe = GroupeNegociation(
                session_id=session_obj.id,
                negociation_id=negociation.id,
                nom_groupe=nom_groupe,
                statut="en_cours"
            )
            db.add(groupe)
            db.commit()
            db.refresh(groupe)

            group_assignments = []
            for idx, p in enumerate(group_members):
                perso = personnages[idx % len(personnages)]
                assignation = AssignationPersonnage(
                    groupe_negociation_id=groupe.id,
                    participant_id=str(p.id),
                    nom_personnage=perso.get("nom_personnage", f"Rôle {idx+1}"),
                    participant_pseudo=p.pseudo
                )
                db.add(assignation)

                # Store targeted private payload for this participant
                if p.socket_id:
                    assignments_map[p.socket_id] = {
                        "groupe_id": groupe.id,
                        "nom_groupe": groupe.nom_groupe,
                        "nom_personnage": perso.get("nom_personnage"),
                        "role_description": perso.get("role_description"),
                        "objectifs_secrets": perso.get("objectifs_secrets"),
                        "arguments_cles": perso.get("arguments_cles", []),
                        "lignes_rouges_et_compromis": perso.get("lignes_rouges_et_compromis")
                    }

                group_assignments.append({
                    "participant_id": p.id,
                    "pseudo": p.pseudo,
                    "nom_personnage": perso.get("nom_personnage")
                })

            db.commit()
            groupes_created.append({
                "groupe_id": groupe.id,
                "nom_groupe": groupe.nom_groupe,
                "membres": group_assignments
            })

        room = f"session_{session_code}"

        # 1. Broadcast PUBLIC scenario context to room
        public_payload = {
            "negociation_id": negociation.id,
            "titre": negociation.titre,
            "contexte_scenario": negociation.contexte_scenario,
            "points_passage": negociation.points_passage or [],
            "groupes": groupes_created
        }
        await sio.emit("negociation:launched", public_payload, room=room)

        # 2. Emit TARGETED PRIVATE character cards directly to each participant socket
        for target_sid, private_card in assignments_map.items():
            try:
                await sio.emit("negociation:your_character", private_card, to=target_sid)
            except Exception as e:
                logger.warning(f"Could not send targeted character card to {target_sid}: {e}")

        logger.info(f"Negotiation {negociation.id} launched for session {session_code} with {len(groupes_created)} groups")
        return {"status": "success", "groupes": groupes_created}


@sio.on("negociation:passage_point")
async def on_negociation_passage_point(sid, data):
    """
    Broadcast a milestone passage point notification according to server timer or professor trigger.
    """
    session_code = data.get("session_code")
    etape = data.get("etape")
    titre = data.get("titre")
    instruction = data.get("instruction")

    if not session_code:
        return {"status": "error", "message": "Missing session_code"}

    room = f"session_{session_code}"
    payload = {
        "etape": etape,
        "titre": titre,
        "instruction": instruction,
        "timestamp": datetime.utcnow().isoformat()
    }
    await sio.emit("negociation:milestone", payload, room=room)
    logger.info(f"Negotiation milestone step {etape} broadcast to session {session_code}")
    return {"status": "success"}


@sio.on("negociation:submit_accord")
async def on_negociation_submit_accord(sid, data):
    """
    Submit final agreement summary for a negotiation group.
    """
    groupe_id = data.get("groupe_negociation_id")
    resume_accord = data.get("resume_accord")
    participant_redacteur_id = data.get("participant_redacteur_id")
    statut_accord = data.get("statut_accord", "conclu")
    session_code = data.get("session_code")

    if not groupe_id or not resume_accord:
        return {"status": "error", "message": "Missing groupe_negociation_id or resume_accord"}

    with Session(engine) as db:
        groupe = db.get(GroupeNegociation, groupe_id)
        if not groupe:
            return {"status": "error", "message": "Groupe de négociation non trouvé"}

        # Upsert final agreement
        existing_accord = db.exec(
            select(AccordFinal).where(AccordFinal.groupe_negociation_id == groupe_id)
        ).first()

        if existing_accord:
            existing_accord.resume_accord = resume_accord
            existing_accord.participant_redacteur_id = str(participant_redacteur_id)
            existing_accord.statut_accord = statut_accord
            db.add(existing_accord)
            accord = existing_accord
        else:
            accord = AccordFinal(
                groupe_negociation_id=groupe_id,
                resume_accord=resume_accord,
                participant_redacteur_id=str(participant_redacteur_id),
                statut_accord=statut_accord
            )
            db.add(accord)

        groupe.statut = statut_accord
        db.add(groupe)
        db.commit()
        db.refresh(accord)

        room = f"session_{session_code}" if session_code else None
        payload = {
            "groupe_id": groupe.id,
            "nom_groupe": groupe.nom_groupe,
            "resume_accord": accord.resume_accord,
            "statut_accord": accord.statut_accord,
            "participant_redacteur_id": accord.participant_redacteur_id
        }

        if room:
            await sio.emit("negociation:accord_submitted", payload, room=room)
        else:
            await sio.emit("negociation:accord_submitted", payload)

        logger.info(f"Negotiation agreement submitted for group {groupe_id}")
        return {"status": "success", "accord_id": accord.id}


@sio.on("negociation:end")
async def on_negociation_end(sid, data):
    """
    Conclude negotiation session and generate debriefing reflection payload.
    """
    session_code = data.get("session_code")
    negociation_id = data.get("negociation_id")

    if not session_code or not negociation_id:
        return {"status": "error", "message": "Missing session_code or negociation_id"}

    with Session(engine) as db:
        negociation = db.get(Negociation, negociation_id)
        session_obj = db.exec(
            select(QuizSession).where(QuizSession.code_session == session_code)
        ).first()

        groupes = db.exec(
            select(GroupeNegociation).where(GroupeNegociation.session_id == session_obj.id)
        ).all() if session_obj else []

        accords_list = []
        for g in groupes:
            accord = db.exec(
                select(AccordFinal).where(AccordFinal.groupe_negociation_id == g.id)
            ).first()
            accords_list.append({
                "nom_groupe": g.nom_groupe,
                "statut": g.statut,
                "resume_accord": accord.resume_accord if accord else "Pas d'accord formalisé"
            })

        room = f"session_{session_code}"
        payload = {
            "negociation_id": negociation_id,
            "criteres_debriefing": negociation.criteres_debriefing if negociation else [],
            "accords_groupes": accords_list
        }
        await sio.emit("negociation:debriefing", payload, room=room)
        logger.info(f"Negotiation session {session_code} ended, debriefing broadcast")
        return {"status": "success", "debriefing": payload}



