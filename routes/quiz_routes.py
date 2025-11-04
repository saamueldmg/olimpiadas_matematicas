from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required
from services.quiz_service import QuizService
from services.team_service import TeamService
from firebase_admin import firestore
from utils.decorators import handle_errors

quiz_bp = Blueprint('quiz', __name__, url_prefix='/quiz')


def get_services():
    """Helper para obtener instancias de servicios"""
    db = firestore.client()
    return QuizService(), TeamService(db)


@quiz_bp.route('/dashboard')
@login_required
@handle_errors
def dashboard():
    """Dashboard principal del quiz"""
    _, team_service = get_services()
    teams = team_service.get_all_teams()
    needs_team_setup = len(teams) == 0
    return render_template('dashboard.html', needs_team_setup=needs_team_setup)


@quiz_bp.route('/select-level', methods=['GET', 'POST'])
@login_required
@handle_errors
def select_level():
    """Selección de nivel, equipos y ronda"""
    quiz_service, team_service = get_services()

    if request.method == 'POST':
        team1 = request.form.get('team1')
        team2 = request.form.get('team2')
        level = request.form.get('level')
        round_type = request.form.get('round', 'octavos')

        if not team1 or not team2 or not level:
            flash('Debes seleccionar ambos equipos y un nivel', 'error')
            return redirect(url_for('quiz.select_level'))

        if team1 == team2:
            flash('No puedes seleccionar el mismo equipo dos veces', 'error')
            return redirect(url_for('quiz.select_level'))

        success, message, questions = quiz_service.initialize_quiz(
            level, team1, team2, round_type=round_type)

        if not success:
            flash(message, 'error')
            return redirect(url_for('quiz.select_level'))

        return redirect(url_for('quiz.countdown'))

    teams = team_service.get_all_teams()
    teams_n1 = [t['name'] for t in teams if t.get('level') == 'Nivel I']
    teams_n2 = [t['name'] for t in teams if t.get('level') == 'Nivel II']
    teams_n3 = [t['name'] for t in teams if t.get('level') == 'Nivel III']

    return render_template('select_level.html',
                           teams_n1=teams_n1,
                           teams_n2=teams_n2,
                           teams_n3=teams_n3)


@quiz_bp.route('/countdown')
@login_required
@handle_errors
def countdown():
    """Pantalla de cuenta regresiva antes del quiz"""
    if 'quiz_teams' not in session or 'quiz_level' not in session:
        flash('Debes seleccionar equipos y nivel primero', 'error')
        return redirect(url_for('quiz.select_level'))

    teams = session.get('quiz_teams', ['Equipo 1', 'Equipo 2'])
    level = session.get('quiz_level', 'Nivel I')
    round_type = session.get('quiz_round', 'octavos')

    return render_template(
        'countdown.html',
        teams=teams,
        level=level,
        round=round_type
    )


@quiz_bp.route('/quiz')
@login_required
@handle_errors
def quiz_question():
    """Mostrar pregunta actual del quiz - CORREGIDO"""
    quiz_service, _ = get_services()

    if quiz_service.is_quiz_finished():
        return redirect(url_for('quiz.quiz_finished'))

    question = quiz_service.get_current_question()
    if not question:
        flash('Error al cargar la pregunta', 'error')
        return redirect(url_for('quiz.dashboard'))

    # CORREGIDO: current_index + 1 para mostrar "Pregunta 1 de 10"
    current_index = session.get('current_question_index', 0)
    total_questions = len(session.get('quiz_question_ids', []))
    teams = session.get('quiz_teams', [])
    scores = session.get('quiz_scores', {})

    return render_template('quiz.html',
                           question=question,
                           question_number=current_index + 1,  # ← AGREGADO
                           current_index=current_index,
                           total_questions=total_questions,
                           teams=teams,
                           scores=scores)


@quiz_bp.route('/submit-answer', methods=['POST'])
@login_required
@handle_errors
def submit_answer():
    """Procesar respuesta del usuario"""
    quiz_service, _ = get_services()
    user_answer = request.form.get('answer')

    if not user_answer:
        flash('Debes seleccionar una respuesta', 'error')
        return redirect(url_for('quiz.quiz_question'))

    is_correct, correct_answer = quiz_service.check_answer(user_answer)

    if is_correct:
        teams = session.get('quiz_teams', [])
        return render_template('assign_point.html', teams=teams)
    else:
        quiz_service.next_question()
        return redirect(url_for('quiz.quiz_question'))


@quiz_bp.route('/assign-point', methods=['POST'])
@login_required
@handle_errors
def assign_point():
    """Asignar puntos a un equipo"""
    quiz_service, _ = get_services()
    team = request.form.get('team')
    points = request.form.get('points', 1)

    if not team:
        flash('Debes seleccionar un equipo', 'error')
        return redirect(url_for('quiz.quiz_question'))

    success = quiz_service.assign_points(team, points)

    if not success:
        flash('Error al asignar puntos', 'error')

    quiz_service.next_question()
    return redirect(url_for('quiz.quiz_question'))


@quiz_bp.route('/skip-question', methods=['POST'])
@login_required
@handle_errors
def skip_question():
    """Saltar pregunta sin asignar puntos"""
    quiz_service, _ = get_services()
    quiz_service.next_question()
    return redirect(url_for('quiz.quiz_question'))


@quiz_bp.route('/quiz-finished')
@login_required
@handle_errors
def quiz_finished():
    """Mostrar resultados finales del quiz - MANEJO DE ERRORES"""
    quiz_service, _ = get_services()
    results = quiz_service.get_quiz_results()

    # VALIDAR SI results ES UNA LISTA O DICCIONARIO
    if isinstance(results, list):
        # Si es una lista, convertirla a diccionario
        teams = session.get('quiz_teams', [])
        scores = session.get('quiz_scores', {})

        # Determinar ganador
        if scores:
            max_score = max(scores.values())
            winners = [team for team, score in scores.items()
                       if score == max_score]

            if len(winners) > 1:
                winner = 'Empate'
                message = f'¡Empate! {" y ".join(winners)} tienen {max_score} puntos'
            else:
                winner = winners[0]
                message = f'¡{winner} gana con {max_score} puntos!'
        else:
            winner = 'Ninguno'
            message = 'No se registraron puntos'

        teams_order = sorted(
            scores.keys(), key=lambda x: scores[x], reverse=True)

    else:
        # Si es un diccionario, extraer normalmente
        winner = results.get('winner', 'Desconocido')
        message = results.get('message', 'Quiz finalizado')
        scores = results.get('scores', {})
        teams_order = results.get('teams_order', list(scores.keys()))

    # Limpiar sesión DESPUÉS de obtener los datos
    quiz_service.clear_quiz_session()

    return render_template(
        'quiz_finished.html',
        winner=winner,
        message=message,
        scores=scores,
        teams_order=teams_order,
        results=results
    )


@quiz_bp.route('/break-tie', methods=['POST'])
@login_required
@handle_errors
def break_tie():
    """Resolver empate dando +1 punto al ganador del tie-breaker"""
    quiz_service, team_service = get_services()
    winner_team = request.form.get('winner_team')

    if not winner_team:
        flash('Debes seleccionar un equipo ganador', 'error')
        return redirect(url_for('quiz.quiz_finished'))

    # Asignar +1 punto extra al ganador del desempate
    success = team_service.update_team_score(winner_team, 1)

    if success:
        flash(f'¡{winner_team} gana el desempate! +1 punto agregado', 'success')
    else:
        flash('Error al actualizar el puntaje', 'error')

    return redirect(url_for('quiz.scoreboard'))


@quiz_bp.route('/scoreboard')
@handle_errors
def scoreboard():
    """Tabla de clasificación general - CORREGIDO"""
    _, team_service = get_services()
    teams = team_service.get_all_teams()

    # Separar por niveles
    teams_n1 = [t for t in teams if t.get('level') == 'Nivel I']
    teams_n2 = [t for t in teams if t.get('level') == 'Nivel II']

    # Ordenar por puntos
    teams_n1_sorted = sorted(
        teams_n1, key=lambda x: x.get('score', 0), reverse=True)
    teams_n2_sorted = sorted(
        teams_n2, key=lambda x: x.get('score', 0), reverse=True)

    return render_template(
        'scoreboard.html',
        scores_n1=teams_n1_sorted,  # ← CORREGIDO
        scores_n2=teams_n2_sorted,  # ← CORREGIDO
        teams=teams
    )
