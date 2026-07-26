import logging
import random
from datetime import datetime
import socketio
from sqlmodel import Session, select
from app.database import engine
from app.models.quiz_session import QuizSession, QuizParticipant, QuizAttempt
from app.models.cas_etude import CasEtude, EquipeCasEtude, RoleAssignment, DecisionEquipe
from app.models.mindmap import MindMap, MindMapNode

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


