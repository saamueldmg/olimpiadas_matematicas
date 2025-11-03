"""
Servicio para gestión de quiz
"""
from flask import session
from services.question_service import QuestionService
from services.team_service import TeamService
from firebase_admin import firestore
import random
import time


class QuizService:
    def __init__(self):
        self.db = firestore.client()
        self.question_service = QuestionService()  # ← SIN db (se auto-inicializa)
        self.team_service = TeamService(self.db)  # ← CON db (lo requiere)
        self._rng = random.Random()
        self._rng.seed(int(time.time()))

    def initialize_quiz(self, level, team1, team2, questions_count=10, round_type='octavos'):
        """Inicializa sesión con preguntas filtradas POR RONDA (sin tracking)"""
        try:
            level_map = {
                "Nivel I": "nivel1",
                "Nivel II": "nivel2",
                "Nivel III": "nivel3"
            }
            firestore_level = level_map.get(level)
            if not firestore_level:
                return False, "Nivel no válido", None

            # Obtener preguntas de la ronda específica
            all_questions = self.question_service.get_questions_by_level_and_round(
                firestore_level, round_type
            )

            if not all_questions:
                return False, f"No hay preguntas disponibles para {level} en ronda {round_type}", None

            all_question_ids = [q['id'] for q in all_questions]

            if len(all_question_ids) < questions_count:
                return False, f"Solo hay {len(all_question_ids)} preguntas para esta ronda. Se necesitan {questions_count}.", None

            # Selección aleatoria simple (sin tracking)
            selected_ids = self._rng.sample(all_question_ids, questions_count)
            self._rng.shuffle(selected_ids)

            # Guardar en sesión
            session['quiz_level'] = level
            session['quiz_teams'] = [team1, team2]
            session['quiz_round'] = round_type
            session['quiz_question_ids'] = selected_ids
            session['current_question_index'] = 0
            session['quiz_scores'] = {team1: 0, team2: 0}
            session['question_start_time'] = None
            session.modified = True

            return True, "Quiz iniciado correctamente", selected_ids

        except Exception as e:
            return False, f"Error al inicializar quiz: {str(e)}", None

    def get_current_question(self):
        """Obtiene la pregunta actual del quiz"""
        try:
            question_ids = session.get('quiz_question_ids', [])
            current_index = session.get('current_question_index', 0)

            if current_index >= len(question_ids):
                return None

            question_id = question_ids[current_index]
            question = self.question_service.get_question_by_id(question_id)

            if not question:
                return None

            # Mezclar opciones
            options = question.get('options', {})
            options_list = list(options.items())
            self._rng.shuffle(options_list)
            question['shuffled_options'] = options_list

            # Guardar tiempo de inicio
            if session.get('question_start_time') is None:
                session['question_start_time'] = time.time()
                session.modified = True

            return question

        except Exception as e:
            print(f"Error al obtener pregunta actual: {e}")
            return None

    def check_answer(self, user_answer):
        """Verifica si la respuesta es correcta"""
        try:
            question_ids = session.get('quiz_question_ids', [])
            current_index = session.get('current_question_index', 0)

            if current_index >= len(question_ids):
                return False, None

            question_id = question_ids[current_index]
            question = self.question_service.get_question_by_id(question_id)

            if not question:
                return False, None

            correct_answer = question.get('correct')
            is_correct = user_answer == correct_answer

            return is_correct, correct_answer

        except Exception as e:
            print(f"Error al verificar respuesta: {e}")
            return False, None

    def assign_points(self, team_name, points=1):
        """Asigna puntos a un equipo"""
        try:
            if 'quiz_scores' not in session or team_name not in session['quiz_scores']:
                return False

            points = int(points)
            session['quiz_scores'][team_name] += points
            session.modified = True

            # Actualizar puntos en Firebase
            self.team_service.update_team_score(team_name, points)

            return True
        except Exception as e:
            print(f"Error al asignar puntos: {e}")
            return False

    def next_question(self):
        """Avanza a la siguiente pregunta"""
        try:
            session['current_question_index'] = session.get(
                'current_question_index', 0) + 1
            session['question_start_time'] = None
            session.modified = True
            return True
        except Exception as e:
            print(f"Error al avanzar pregunta: {e}")
            return False

    def is_quiz_finished(self):
        """Verifica si el quiz ha terminado"""
        try:
            question_ids = session.get('quiz_question_ids', [])
            current_index = session.get('current_question_index', 0)
            return current_index >= len(question_ids)
        except Exception as e:
            print(f"Error al verificar fin de quiz: {e}")
            return True

    def get_quiz_results(self):
        """Obtiene los resultados del quiz"""
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
        """Limpia la sesión del quiz"""
        try:
            quiz_keys = [
                'quiz_level',
                'quiz_teams',
                'quiz_round',
                'quiz_question_ids',
                'current_question_index',
                'quiz_scores',
                'question_start_time'
            ]

            for key in quiz_keys:
                session.pop(key, None)

            session.modified = True
            return True
        except Exception as e:
            print(f"Error al limpiar sesión: {e}")
            return False

    def get_elapsed_time(self):
        """Obtiene el tiempo transcurrido de la pregunta actual"""
        try:
            start_time = session.get('question_start_time')
            if start_time is None:
                return 0
            return int(time.time() - start_time)
        except Exception as e:
            print(f"Error al obtener tiempo: {e}")
            return 0
