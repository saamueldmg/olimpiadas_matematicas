"""
Servicio para gestión de quizzes
Olimpiadas Matemáticas - Tuluá
"""
from flask import session
from firebase_admin import firestore
import time
import random


class QuizService:
    """Servicio para operaciones de quiz"""

    def __init__(self, question_service, team_service):
        self.question_service = question_service
        self.team_service = team_service
        self.db = firestore.client()
        self._rng = random.SystemRandom()

    def _get_available_questions(self, level):
        """Obtener preguntas disponibles (NO usadas) del ciclo vigente"""
        tracking_ref = self.db.collection('question_tracking').document(level)
        tracking_doc = tracking_ref.get()

        all_questions = self.question_service.get_questions_by_level(level)
        all_question_ids = [q['id'] for q in all_questions]

        if not all_question_ids:
            return []

        used_ids = tracking_doc.to_dict().get(
            'used_questions', []) if tracking_doc.exists else []
        used_set = set(used_ids)

        available_ids = [
            qid for qid in all_question_ids if qid not in used_set]
        return available_ids

    def _mark_questions_as_used(self, level, question_ids):
        """Marcar preguntas como usadas"""
        tracking_ref = self.db.collection('question_tracking').document(level)
        tracking_doc = tracking_ref.get()

        used_ids = tracking_doc.to_dict().get(
            'used_questions', []) if tracking_doc.exists else []
        seen = set(used_ids)
        for qid in question_ids:
            if qid not in seen:
                used_ids.append(qid)
                seen.add(qid)

        tracking_ref.set({'used_questions': used_ids})

    def initialize_quiz(self, level, team1, team2, questions_count=10):
        """Inicializa sesión con doble aleatoriedad + fill garantizado"""
        try:
            level_map = {
                "Nivel I": "nivel1",
                "Nivel II": "nivel2",
                "Nivel III": "nivel3"
            }
            firestore_level = level_map.get(level)
            if not firestore_level:
                return False, "Nivel no válido", None

            K = questions_count

            all_questions = self.question_service.get_questions_by_level(
                firestore_level)
            all_question_ids = [q['id'] for q in all_questions]
            if not all_question_ids:
                return False, f"No hay preguntas disponibles para {level}", None

            if len(all_question_ids) < K:
                return False, f"No se puede completar {K} sin repetir (total={len(all_question_ids)}).", None

            available_ids = self._get_available_questions(firestore_level)

            tracking_ref = self.db.collection(
                'question_tracking').document(firestore_level)
            tracking_doc = tracking_ref.get()
            used_ids_cycle = tracking_doc.to_dict().get(
                'used_questions', []) if tracking_doc.exists else []

            if len(available_ids) >= K:
                selected_ids = self._rng.sample(available_ids, K)
                self._mark_questions_as_used(firestore_level, selected_ids)
            else:
                restante = available_ids[:]
                self._rng.shuffle(restante)
                faltan = K - len(restante)

                tracking_ref.set({'used_questions': []})

                avoid_set = set(restante)
                prefer_pool = [qid for qid in all_question_ids
                               if qid not in avoid_set and qid not in set(used_ids_cycle)]

                fill_ids = []
                if len(prefer_pool) >= faltan:
                    fill_ids = self._rng.sample(prefer_pool, faltan)
                else:
                    if prefer_pool:
                        self._rng.shuffle(prefer_pool)
                        take = min(len(prefer_pool), faltan)
                        fill_ids.extend(prefer_pool[:take])

                    faltan2 = faltan - len(fill_ids)
                    fallback_pool = [qid for qid in all_question_ids
                                     if qid not in avoid_set and qid not in set(fill_ids)]
                    fill_ids.extend(self._rng.sample(fallback_pool, faltan2))

                selected_ids = restante + fill_ids
                tracking_ref.set({'used_questions': fill_ids})

            self._rng.shuffle(selected_ids)

            session['quiz_level'] = level
            session['quiz_teams'] = [team1, team2]
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
        question_ids = session.get('quiz_question_ids', [])
        index = session.get('current_question_index', 0)

        if index >= len(question_ids):
            return None

        question_id = question_ids[index]
        return self.question_service.get_question_by_id(question_id)

    def start_question_timer(self):
        """Inicia el temporizador para la pregunta actual"""
        if 'question_start_time' not in session or session['question_start_time'] is None:
            session['question_start_time'] = time.time()
            session.modified = True

    def get_remaining_time(self, max_time=300):
        """Calcula el tiempo restante en segundos"""
        start_time = session.get('question_start_time')
        if not start_time:
            return max_time

        elapsed = time.time() - start_time
        remaining = max(0, max_time - int(elapsed))
        return remaining

    def check_answer(self, user_answer):
        """Verifica si la respuesta es correcta"""
        question = self.get_current_question()
        if not question:
            return False, None
        correct_answer = question.get('correct')
        is_correct = (user_answer == correct_answer)
        return is_correct, correct_answer

    def assign_points(self, team_name, points):
        """Asigna puntos a un equipo"""
        if 'quiz_scores' not in session or team_name not in session['quiz_scores']:
            return False
        session['quiz_scores'][team_name] += points
        session.modified = True
        self.team_service.update_team_score(team_name, points)
        return True

    def next_question(self):
        """Avanza a la siguiente pregunta"""
        session['current_question_index'] = session.get(
            'current_question_index', 0) + 1
        session['question_start_time'] = None
        session.modified = True

    def is_quiz_finished(self):
        """Verifica si el quiz ha terminado"""
        question_ids = session.get('quiz_question_ids', [])
        index = session.get('current_question_index', 0)
        return index >= len(question_ids)

    def get_quiz_results(self):
        """Obtener resultados finales del quiz"""
        scores = session.get('quiz_scores', {})
        teams = session.get('quiz_teams', [])
        if not scores or not teams:
            return {}, None, "No hay resultados disponibles"

        team1, team2 = teams[0], teams[1]
        score1 = scores.get(team1, 0)
        score2 = scores.get(team2, 0)

        if score1 == score2:
            winner = "Empate"
            message = f"¡Empate! Ambos equipos terminaron con {score1} puntos"
        elif score1 > score2:
            winner = team1
            message = f"¡{team1} es el ganador con {score1} puntos!"
        else:
            winner = team2
            message = f"¡{team2} es el ganador con {score2} puntos!"

        return scores, winner, message

    def break_tie(self, winner_team):
        """Romper empate asignando +1 punto al equipo ganador"""
        try:
            # Asignar punto adicional
            success = self.team_service.update_team_score(winner_team, 1)

            if success:
                # Actualizar scores en sesión si aún existe
                if 'quiz_scores' in session and winner_team in session['quiz_scores']:
                    session['quiz_scores'][winner_team] += 1
                    session.modified = True

                return True, f"{winner_team} gana el duelo por desempate! (+1 punto)"
            else:
                return False, "Error al asignar punto de desempate"
        except Exception as e:
            return False, f"❌ Error: {str(e)}"

    def clear_quiz_session(self):
        """Limpia la sesión del quiz"""
        keys_to_clear = [
            'quiz_level', 'quiz_teams', 'quiz_question_ids',
            'current_question_index', 'quiz_scores', 'question_start_time'
        ]
        for key in keys_to_clear:
            session.pop(key, None)
        session.modified = True
