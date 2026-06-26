"""
Servicio para gestión de quiz.

Flujo actual:
- El público responde
- El sistema valida automáticamente si la respuesta es correcta o incorrecta
- Si es incorrecta: se revela la respuesta correcta
- Si es correcta: el admin pasa a assign_point.html
- En assign_point.html se define:
  - equipo
  - argumento válido / inválido
- Puntaje:
  - correcta + argumento inválido = 1
  - correcta + argumento válido = 2

Versión actualizada:
- El estado público se guarda por nivel:
    public_state/nivel1
    public_state/nivel2
    public_state/nivel3
"""

from flask import session
from services.question_service import QuestionService
from services.team_service import TeamService
from firebase_admin import firestore
import random
import time


class QuizService:
    PUBLIC_STATE_COLLECTION = 'public_state'
    USED_QUESTIONS_COLLECTION = 'used_questions'

    def __init__(self):
        self.db = firestore.client()
        self.question_service = QuestionService()
        self.team_service = TeamService(self.db)
        self._rng = random.Random()
        self._rng.seed(int(time.time()))

    # ============================================================
    # Flujo principal
    # ============================================================

    def initialize_quiz(self, level, team1, team2, questions_count=10, round_type='octavos'):
        try:
            level_map = {
                "Nivel I": "nivel1",
                "Nivel II": "nivel2",
                "Nivel III": "nivel3"
            }

            firestore_level = level_map.get(level)
            if not firestore_level:
                return False, "Nivel no válido", None

            round_type = self._normalize_round(round_type)

            all_questions = self.question_service.get_questions_by_level_and_round(
                firestore_level,
                round_type
            )

            if not all_questions:
                return False, f"No hay preguntas disponibles para {level} en ronda {round_type}", None

            all_question_ids = [q['id'] for q in all_questions]
            used_question_ids = self._get_used_question_ids(firestore_level, round_type)

            available_question_ids = [
                qid for qid in all_question_ids if qid not in used_question_ids
            ]

            if len(available_question_ids) < questions_count:
                return (
                    False,
                    (
                        f"Solo hay {len(available_question_ids)} preguntas nuevas disponibles "
                        f"para {level} en ronda {round_type}. "
                        f"Se necesitan {questions_count}. "
                        f"Agrega más preguntas o reinicia el tracking de esa ronda."
                    ),
                    None
                )

            selected_ids = self._rng.sample(available_question_ids, questions_count)
            self._rng.shuffle(selected_ids)

            session['quiz_level'] = level
            session['quiz_firestore_level'] = firestore_level
            session['quiz_teams'] = [team1, team2]
            session['quiz_round'] = round_type
            session['quiz_question_ids'] = selected_ids
            session['current_question_index'] = 0
            session['quiz_scores'] = {team1: 0, team2: 0}

            session['question_start_time'] = None
            session['question_timer_started_at'] = None
            session['question_timer_duration'] = 300

            session['countdown_started_at'] = None
            session['countdown_duration'] = 0

            session['show_correct_answer'] = False
            session['last_submitted_answer'] = None
            session['public_selected_answer'] = None
            session['admin_validation_result'] = None
            session['argument_validation_required'] = False
            session['validated_team_name'] = None

            session['match_finished_manually'] = False
            session.modified = True

            self._mark_questions_as_used(firestore_level, round_type, selected_ids)

            self._publish_current_state(
                status='countdown',
                question_override=None,
                level=firestore_level
            )

            return True, "Quiz iniciado correctamente", selected_ids

        except Exception as e:
            return False, f"Error al inicializar quiz: {str(e)}", None

    def start_countdown(self, duration=12):
        try:
            session['countdown_started_at'] = time.time()
            session['countdown_duration'] = int(duration)
            session.modified = True

            self._publish_current_state(
                status='countdown',
                question_override=None,
                level=session.get('quiz_firestore_level')
            )
            return True

        except Exception as e:
            print(f"Error al iniciar countdown: {e}")
            return False

    def get_current_question(self):
        """
        Obtiene la pregunta actual y publica estado público.
        Si la misma pregunta ya está en awaiting_argument_validation o answer_revealed,
        preserva ese estado.
        """
        try:
            question = self._get_current_question_raw()
            if not question:
                return None

            question['display_options'] = self._normalize_options(question.get('options', {}))

            if session.get('question_start_time') is None:
                session['question_start_time'] = time.time()

            if session.get('question_timer_started_at') is None:
                session['question_timer_started_at'] = time.time()
                session['question_timer_duration'] = 300

            session.modified = True

            existing_state = self.get_public_quiz_state(level=session.get('quiz_firestore_level'))
            existing_status = existing_state.get('status')
            existing_question = existing_state.get('question') or {}

            preserve_statuses = {
                'awaiting_argument_validation',
                'answer_revealed'
            }

            if (
                existing_question.get('id') == question.get('id')
                and existing_status in preserve_statuses
            ):
                status_to_publish = existing_status
            else:
                status_to_publish = 'in_progress'

            self._publish_current_state(
                status=status_to_publish,
                question_override=question,
                level=session.get('quiz_firestore_level')
            )

            return question

        except Exception as e:
            print(f"Error al obtener pregunta actual: {e}")
            return None

    def submit_public_answer(self, user_answer, level=None):
        """
        El público responde y el sistema valida automáticamente
        si la respuesta es correcta o incorrecta.
        """
        try:
            public_state = self.get_public_quiz_state(level=level)

            if not public_state or public_state.get('status') != 'in_progress':
                return False, "No hay pregunta en curso"

            if self._is_question_timer_expired(public_state):
                return False, "Se agotó el tiempo de respuesta"

            public_question = public_state.get('question') or {}
            question_id = public_question.get('id')

            if not question_id:
                return False, "No hay pregunta activa"

            if public_question.get('selected_answer'):
                return False, "Ya se registró una respuesta para esta pregunta"

            if not user_answer or user_answer not in ('a', 'b', 'c', 'd'):
                return False, "Respuesta no válida"

            current_question = self.question_service.get_question_by_id(question_id)
            if not current_question:
                return False, "No se pudo cargar la pregunta activa"

            correct_answer = current_question.get('correct')
            is_correct = user_answer == correct_answer

            session['public_selected_answer'] = user_answer
            session['last_submitted_answer'] = user_answer
            session['admin_validation_result'] = 'correct' if is_correct else 'incorrect'
            session['argument_validation_required'] = bool(is_correct)
            session['show_correct_answer'] = not is_correct
            session['validated_team_name'] = None
            session.modified = True

            updated_question = {
                'id': question_id,
                'image': public_question.get('image'),
                'options': public_question.get('options', {}),
                'correct_answer': None,
                'show_correct_answer': False,
                'selected_answer': user_answer,
                'admin_validation_result': 'correct' if is_correct else 'incorrect',
                'argument_validation_required': bool(is_correct),
                'validated_team_name': None
            }

            if is_correct:
                self._public_state_ref(level=level).set({
                    'status': 'awaiting_argument_validation',
                    'question': updated_question,
                    'updated_at': firestore.SERVER_TIMESTAMP
                }, merge=True)

                return True, "Respuesta correcta. Esperando asignación del administrador."

            updated_question['correct_answer'] = correct_answer
            updated_question['show_correct_answer'] = True
            updated_question['argument_validation_required'] = False

            self._public_state_ref(level=level).set({
                'status': 'answer_revealed',
                'question': updated_question,
                'updated_at': firestore.SERVER_TIMESTAMP
            }, merge=True)

            return True, "Respuesta incorrecta. Se revelará la opción correcta."

        except Exception as e:
            print(f"Error en submit_public_answer: {e}")
            return False, f"Error al registrar respuesta pública: {str(e)}"

    def resolve_correct_answer_assignment(self, team_name, argument_valid):
        """
        Completa la asignación de puntos cuando la respuesta ya fue
        validada automáticamente como correcta.
        """
        try:
            current_question = self._get_current_question_raw()
            if not current_question:
                return False, "No hay una pregunta activa"

            public_state = self.get_public_quiz_state(level=session.get('quiz_firestore_level'))
            public_question = public_state.get('question') or {}

            if public_question.get('admin_validation_result') != 'correct':
                return False, "La respuesta no fue marcada como correcta"

            if not public_question.get('argument_validation_required', False):
                return False, "No hay una asignación pendiente para esta respuesta"

            selected_answer = public_question.get('selected_answer')
            if not selected_answer:
                return False, "No hay respuesta seleccionada"

            if not team_name:
                return False, "Debes seleccionar un equipo"

            success_base = self.assign_points(team_name, 1, publish_status=False)
            if not success_base:
                return False, "No se pudo asignar el punto base"

            total_awarded = 1

            if argument_valid:
                success_extra = self.assign_points(team_name, 1, publish_status=False)
                if not success_extra:
                    return False, "No se pudo asignar el punto extra"
                total_awarded = 2

            session['argument_validation_required'] = False
            session['show_correct_answer'] = True
            session['validated_team_name'] = team_name
            session.modified = True

            updated_scores = session.get('quiz_scores', {}).copy()

            updated_question = {
                'id': current_question.get('id'),
                'image': current_question.get('question_image'),
                'options': self._normalize_options(current_question.get('options', {})),
                'correct_answer': current_question.get('correct'),
                'show_correct_answer': True,
                'selected_answer': selected_answer,
                'admin_validation_result': 'correct',
                'argument_validation_required': False,
                'validated_team_name': team_name
            }

            self._public_state_ref(level=session.get('quiz_firestore_level')).set({
                'status': 'answer_revealed',
                'question': updated_question,
                'scores': updated_scores,
                'updated_at': firestore.SERVER_TIMESTAMP
            }, merge=True)

            if total_awarded == 2:
                return True, f"Asignación completada: {team_name} recibe 2 puntos."

            return True, f"Asignación completada: {team_name} recibe 1 punto."

        except Exception as e:
            print(f"Error en resolve_correct_answer_assignment: {e}")
            return False, f"Error al completar la asignación: {str(e)}"

    def assign_points(self, team_name, points=1, publish_status=True):
        try:
            if 'quiz_scores' not in session or team_name not in session['quiz_scores']:
                return False

            points = int(points)
            session['quiz_scores'][team_name] += points
            session.modified = True

            self.team_service.update_team_score(team_name, points)

            if publish_status:
                self._publish_current_state(
                    status='answer_revealed',
                    level=session.get('quiz_firestore_level')
                )

            return True

        except Exception as e:
            print(f"Error al asignar puntos: {e}")
            return False

    def next_question(self):
        try:
            session['current_question_index'] = session.get('current_question_index', 0) + 1
            session['question_start_time'] = None
            session['show_correct_answer'] = False
            session['last_submitted_answer'] = None
            session['public_selected_answer'] = None
            session['admin_validation_result'] = None
            session['argument_validation_required'] = False
            session['validated_team_name'] = None

            session['question_timer_started_at'] = None
            session['question_timer_duration'] = 300

            session.modified = True

            if self.is_quiz_finished():
                self._publish_current_state(
                    status='finished',
                    level=session.get('quiz_firestore_level')
                )
            else:
                next_question = self._get_current_question_raw()
                if next_question:
                    next_question['display_options'] = self._normalize_options(
                        next_question.get('options', {})
                    )

                session['question_timer_started_at'] = time.time()
                session['question_timer_duration'] = 300
                session.modified = True

                self._publish_current_state(
                    status='in_progress',
                    question_override=next_question,
                    level=session.get('quiz_firestore_level')
                )

            return True

        except Exception as e:
            print(f"Error al avanzar pregunta: {e}")
            return False

    def finish_match(self):
        try:
            session['match_finished_manually'] = True
            session.modified = True

            self._publish_current_state(
                status='finished',
                level=session.get('quiz_firestore_level')
            )
            return True

        except Exception as e:
            print(f"Error al finalizar enfrentamiento: {e}")
            return False

    def is_quiz_finished(self):
        try:
            if session.get('match_finished_manually', False):
                return True

            question_ids = session.get('quiz_question_ids', [])
            current_index = session.get('current_question_index', 0)
            return current_index >= len(question_ids)

        except Exception as e:
            print(f"Error al verificar fin de quiz: {e}")
            return True

    def get_quiz_results(self):
        try:
            teams = session.get('quiz_teams', [])
            scores = session.get('quiz_scores', {})

            results = []
            for team in teams:
                results.append({
                    'team': team,
                    'score': scores.get(team, 0)
                })

            results.sort(key=lambda x: x['score'], reverse=True)
            return results

        except Exception as e:
            print(f"Error al obtener resultados: {e}")
            return []

    def clear_quiz_session(self):
        try:
            current_level = session.get('quiz_firestore_level')

            quiz_keys = [
                'quiz_level',
                'quiz_firestore_level',
                'quiz_teams',
                'quiz_round',
                'quiz_question_ids',
                'current_question_index',
                'quiz_scores',
                'question_start_time',
                'show_correct_answer',
                'last_submitted_answer',
                'public_selected_answer',
                'admin_validation_result',
                'argument_validation_required',
                'validated_team_name',
                'countdown_started_at',
                'countdown_duration',
                'question_timer_started_at',
                'question_timer_duration',
                'match_finished_manually'
            ]

            for key in quiz_keys:
                session.pop(key, None)

            session.modified = True
            self._clear_public_state(level=current_level)
            return True

        except Exception as e:
            print(f"Error al limpiar sesión: {e}")
            return False

    # ============================================================
    # Estado público por nivel
    # ============================================================

    def get_public_quiz_state(self, level=None):
        try:
            doc = self._public_state_ref(level=level).get()

            if not doc.exists:
                return self._empty_public_state()

            return doc.to_dict() or self._empty_public_state()

        except Exception as e:
            print(f"Error al obtener estado público del quiz: {e}")
            return self._empty_public_state()

    def get_all_public_quiz_states(self):
        try:
            return {
                'nivel1': self.get_public_quiz_state(level='nivel1'),
                'nivel2': self.get_public_quiz_state(level='nivel2'),
                'nivel3': self.get_public_quiz_state(level='nivel3'),
            }
        except Exception as e:
            print(f"Error al obtener todos los estados públicos: {e}")
            return {
                'nivel1': self._empty_public_state(),
                'nivel2': self._empty_public_state(),
                'nivel3': self._empty_public_state()
            }

    def reset_used_questions_tracking(self, level=None, round_type=None):
        try:
            if level and round_type:
                level_map = {
                    "Nivel I": "nivel1",
                    "Nivel II": "nivel2",
                    "Nivel III": "nivel3"
                }

                firestore_level = level_map.get(level, level)
                round_type = self._normalize_round(round_type)

                doc_id = self._used_questions_doc_id(firestore_level, round_type)
                self.db.collection(self.USED_QUESTIONS_COLLECTION).document(doc_id).delete()

                return True, f"Tracking reiniciado para {level} - {round_type}"

            docs = self.db.collection(self.USED_QUESTIONS_COLLECTION).stream()
            count = 0

            for doc in docs:
                doc.reference.delete()
                count += 1

            return True, f"Tracking global reiniciado correctamente ({count} documentos)"

        except Exception as e:
            return False, f"Error al reiniciar tracking de preguntas: {str(e)}"

    # ============================================================
    # Helpers internos
    # ============================================================

    def _get_current_question_raw(self):
        try:
            question_ids = session.get('quiz_question_ids', [])
            current_index = session.get('current_question_index', 0)

            if current_index >= len(question_ids):
                return None

            question_id = question_ids[current_index]
            question = self.question_service.get_question_by_id(question_id)

            if question and 'id' not in question:
                question['id'] = question_id

            return question

        except Exception as e:
            print(f"Error al obtener pregunta raw: {e}")
            return None

    def _normalize_options(self, options):
        options = options or {}
        return {
            'a': options.get('a', ''),
            'b': options.get('b', ''),
            'c': options.get('c', ''),
            'd': options.get('d', '')
        }

    def _normalize_round(self, round_type):
        mapping = {
            'octavos': 'octavos',
            'quarters': 'cuartos',
            'cuartos': 'cuartos',
            'semis': 'semifinal',
            'semifinal': 'semifinal',
            'final': 'final',
        }

        if not round_type:
            return 'octavos'

        return mapping.get(str(round_type).strip().lower(), str(round_type).strip().lower())

    def _used_questions_doc_id(self, firestore_level, round_type):
        safe_level = str(firestore_level).strip().lower().replace(' ', '_')
        safe_round = str(round_type).strip().lower().replace(' ', '_')
        return f"{safe_level}__{safe_round}"

    def _get_used_question_ids(self, firestore_level, round_type):
        try:
            doc_id = self._used_questions_doc_id(firestore_level, round_type)
            doc_ref = self.db.collection(self.USED_QUESTIONS_COLLECTION).document(doc_id)
            doc = doc_ref.get()

            if not doc.exists:
                return []

            data = doc.to_dict() or {}
            return data.get('question_ids', [])

        except Exception as e:
            print(f"Error al obtener preguntas usadas: {e}")
            return []

    def _mark_questions_as_used(self, firestore_level, round_type, question_ids):
        try:
            doc_id = self._used_questions_doc_id(firestore_level, round_type)
            doc_ref = self.db.collection(self.USED_QUESTIONS_COLLECTION).document(doc_id)

            existing_ids = set(self._get_used_question_ids(firestore_level, round_type))
            existing_ids.update(question_ids)

            doc_ref.set({
                'level': firestore_level,
                'round': round_type,
                'question_ids': list(existing_ids),
                'updated_at': firestore.SERVER_TIMESTAMP
            }, merge=True)

            return True

        except Exception as e:
            print(f"Error al marcar preguntas usadas: {e}")
            return False

    def _get_public_state_doc_name(self, level=None):
        level_value = level or session.get('quiz_firestore_level')

        if not level_value:
            return 'general'

        normalized = str(level_value).strip().lower()

        level_map = {
            'nivel1': 'nivel1',
            'nivel2': 'nivel2',
            'nivel3': 'nivel3',
            'nivel i': 'nivel1',
            'nivel ii': 'nivel2',
            'nivel iii': 'nivel3'
        }

        return level_map.get(normalized, normalized)

    def _public_state_ref(self, level=None):
        doc_name = self._get_public_state_doc_name(level)
        return self.db.collection(self.PUBLIC_STATE_COLLECTION).document(doc_name)

    def _is_question_timer_expired(self, public_state):
        try:
            timer = public_state.get('question_timer') or {}
            started_at = timer.get('started_at')
            duration = int(timer.get('duration', 300))

            if started_at is None:
                return False

            if isinstance(started_at, dict):
                if '_seconds' in started_at:
                    started_seconds = started_at['_seconds']
                elif 'seconds' in started_at:
                    started_seconds = started_at['seconds']
                else:
                    return False
            else:
                started_seconds = float(started_at)

            elapsed = time.time() - started_seconds
            return elapsed >= duration

        except Exception:
            return False

    def _empty_public_state(self):
        return {
            'status': 'idle',
            'level': None,
            'round': None,
            'teams': [],
            'scores': {},
            'current_index': 0,
            'question_number': 0,
            'total_questions': 0,
            'countdown': {
                'started_at': None,
                'duration': 0
            },
            'question_timer': {
                'started_at': None,
                'duration': 300
            },
            'question': None,
            'updated_at': None
        }

    def _build_public_payload(self, status='idle', question_override=None):
        teams = session.get('quiz_teams', [])
        scores = session.get('quiz_scores', {})
        level = session.get('quiz_level')
        round_type = session.get('quiz_round')
        current_index = session.get('current_question_index', 0)
        question_ids = session.get('quiz_question_ids', [])
        total_questions = len(question_ids)

        countdown_started_at = session.get('countdown_started_at')
        countdown_duration = session.get('countdown_duration', 0)

        question_timer_started_at = session.get('question_timer_started_at')
        question_timer_duration = session.get('question_timer_duration', 300)

        if status == 'countdown':
            question = None
        else:
            question = question_override or self._get_current_question_raw()

        existing_state = self.get_public_quiz_state(level=session.get('quiz_firestore_level'))
        existing_question = existing_state.get('question') or {}

        question_payload = None

        if question:
            same_question = existing_question.get('id') == question.get('id')

            if same_question:
                selected_answer = existing_question.get('selected_answer')
                admin_validation_result = existing_question.get('admin_validation_result')
                argument_validation_required = existing_question.get('argument_validation_required', False)
                show_correct_answer = existing_question.get('show_correct_answer', False)
                correct_answer = existing_question.get('correct_answer') if show_correct_answer else None
                validated_team_name = existing_question.get('validated_team_name')

                existing_timer = existing_state.get('question_timer') or {}

                if status == 'in_progress' and not existing_timer.get('started_at'):
                    public_question_timer = {
                        'started_at': question_timer_started_at,
                        'duration': question_timer_duration
                    }
                else:
                    public_question_timer = existing_timer or {
                        'started_at': question_timer_started_at,
                        'duration': question_timer_duration
                    }
            else:
                selected_answer = session.get('public_selected_answer')
                admin_validation_result = session.get('admin_validation_result')
                argument_validation_required = session.get('argument_validation_required', False)
                show_correct_answer = session.get('show_correct_answer', False)
                correct_answer = question.get('correct') if show_correct_answer else None
                validated_team_name = session.get('validated_team_name')

                public_question_timer = {
                    'started_at': question_timer_started_at,
                    'duration': question_timer_duration
                }

            question_payload = {
                'id': question.get('id'),
                'image': question.get('question_image'),
                'options': self._normalize_options(question.get('options', {})),
                'correct_answer': correct_answer,
                'show_correct_answer': show_correct_answer,
                'selected_answer': selected_answer,
                'admin_validation_result': admin_validation_result,
                'argument_validation_required': argument_validation_required,
                'validated_team_name': validated_team_name,
            }
        else:
            public_question_timer = {
                'started_at': question_timer_started_at,
                'duration': question_timer_duration
            }

        payload = {
            'status': status,
            'level': level,
            'round': round_type,
            'teams': teams,
            'scores': scores,
            'current_index': current_index,
            'question_number': (
                current_index + 1
                if total_questions > 0 and current_index < total_questions
                else total_questions
            ),
            'total_questions': total_questions,
            'countdown': {
                'started_at': countdown_started_at,
                'duration': countdown_duration
            },
            'question_timer': public_question_timer,
            'question': question_payload,
            'updated_at': firestore.SERVER_TIMESTAMP
        }

        return payload

    def _publish_current_state(self, status='in_progress', question_override=None, level=None):
        try:
            payload = self._build_public_payload(
                status=status,
                question_override=question_override
            )
            self._public_state_ref(level=level).set(payload, merge=False)
            return True

        except Exception as e:
            print(f"Error al publicar estado actual del quiz: {e}")
            return False

    def _clear_public_state(self, level=None):
        try:
            self._public_state_ref(level=level).set({
                'status': 'idle',
                'level': None,
                'round': None,
                'teams': [],
                'scores': {},
                'current_index': 0,
                'question_number': 0,
                'total_questions': 0,
                'countdown': {
                    'started_at': None,
                    'duration': 0
                },
                'question_timer': {
                    'started_at': None,
                    'duration': 300
                },
                'question': None,
                'updated_at': firestore.SERVER_TIMESTAMP
            }, merge=False)

            return True

        except Exception as e:
            print(f"Error al limpiar estado público del quiz: {e}")
            return False