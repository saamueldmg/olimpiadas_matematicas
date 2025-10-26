from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from flask_login import login_required
from firebase_admin import firestore

from services.quiz_service import QuizService
from services.team_service import TeamService
from services.question_service import QuestionService
from utils.decorators import handle_errors, require_quiz_session

quiz_bp = Blueprint('quiz', __name__)


def get_services():
    db = firestore.client()
    question_service = QuestionService(db)
    team_service = TeamService(db)
    quiz_service = QuizService(question_service, team_service)
    return quiz_service, team_service


@quiz_bp.route('/dashboard')
@login_required
@handle_errors
def dashboard():
    return render_template('dashboard.html')


@quiz_bp.route('/select-level', methods=['GET', 'POST'])
@login_required
@handle_errors
def select_level():
    quiz_service, team_service = get_services()

    if request.method == 'POST':
        team1 = request.form.get('team1')
        team2 = request.form.get('team2')
        level = request.form.get('level')

        if not team1 or not team2 or not level:
            flash('Debes seleccionar ambos equipos y un nivel', 'error')
            return redirect(url_for('quiz.select_level'))

        if team1 == team2:
            flash('No puedes seleccionar el mismo equipo dos veces', 'error')
            return redirect(url_for('quiz.select_level'))

        success, message, questions = quiz_service.initialize_quiz(
            level, team1, team2)

        if not success:
            flash(message, 'error')
            return redirect(url_for('quiz.select_level'))

        return redirect(url_for('quiz.countdown'))

    teams = team_service.get_all_teams()
    teams_n1 = [t['name'] for t in teams if t.get('level') == 'Nivel I']
    teams_n2 = [t['name'] for t in teams if t.get('level') == 'Nivel II']

    return render_template('select_level.html',
                           teams_n1=teams_n1,
                           teams_n2=teams_n2)


@quiz_bp.route('/countdown')
@login_required
@require_quiz_session
@handle_errors
def countdown():
    teams = session.get('quiz_teams', [])
    return render_template('countdown.html', teams=teams)


@quiz_bp.route('/quiz-question')
@login_required
@require_quiz_session
@handle_errors
def quiz_question():
    quiz_service, _ = get_services()

    if quiz_service.is_quiz_finished():
        return redirect(url_for('quiz.quiz_finished'))

    question = quiz_service.get_current_question()

    if not question:
        flash('Error al cargar pregunta', 'error')
        return redirect(url_for('quiz.dashboard'))

    quiz_service.start_question_timer()
    remaining_time = quiz_service.get_remaining_time()

    question_number = session.get('current_question_index', 0) + 1
    total_questions = len(session.get('quiz_question_ids', []))

    return render_template('quiz.html',
                           question=question,
                           question_number=question_number,
                           total_questions=total_questions,
                           time_remaining=remaining_time)


@quiz_bp.route('/submit-answer', methods=['POST'])
@login_required
@require_quiz_session
@handle_errors
def submit_answer():
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
@require_quiz_session
@handle_errors
def assign_point():
    quiz_service, _ = get_services()

    team = request.form.get('team')
    points = request.form.get('points', '1')

    if not team:
        flash('Debes seleccionar un equipo', 'error')
        return redirect(url_for('quiz.quiz_question'))

    try:
        points = int(points)
    except ValueError:
        points = 1

    quiz_service.assign_points(team, points)
    quiz_service.next_question()

    return redirect(url_for('quiz.quiz_question'))


@quiz_bp.route('/skip-question', methods=['POST'])
@login_required
@require_quiz_session
@handle_errors
def skip_question():
    quiz_service, _ = get_services()
    quiz_service.next_question()
    return redirect(url_for('quiz.quiz_question'))


@quiz_bp.route('/quiz-finished')
@login_required
@handle_errors
def quiz_finished():
    quiz_service, _ = get_services()
    scores, winner, message = quiz_service.get_quiz_results()

    # Obtener el orden original de los equipos
    teams_order = session.get('quiz_teams', [])

    quiz_service.clear_quiz_session()

    return render_template('quiz_finished.html',
                           scores=scores,
                           winner=winner,
                           message=message,
                           teams_order=teams_order)  # ← Pasar el orden original


@quiz_bp.route('/break-tie', methods=['POST'])
@login_required
@handle_errors
def break_tie():
    """Asignar punto de desempate al equipo ganador"""
    quiz_service, _ = get_services()

    winner_team = request.form.get('winner_team')

    if not winner_team:
        flash('❌ Error: No se especificó el equipo ganador', 'error')
        return redirect(url_for('quiz.dashboard'))

    # Romper empate usando el servicio
    success, message = quiz_service.break_tie(winner_team)
    flash(message, 'success' if success else 'error')

    # Redirigir al scoreboard
    return redirect(url_for('quiz.scoreboard'))


@quiz_bp.route('/scoreboard')
@login_required
@handle_errors
def scoreboard():
    _, team_service = get_services()
    teams = team_service.get_all_teams(use_cache=False)

    nivel1 = [t for t in teams if t.get('level') == 'Nivel I']
    nivel2 = [t for t in teams if t.get('level') == 'Nivel II']

    # Ordenar por total_score (prioridad) o score como fallback
    nivel1.sort(key=lambda x: x.get(
        'total_score', x.get('score', 0)), reverse=True)
    nivel2.sort(key=lambda x: x.get(
        'total_score', x.get('score', 0)), reverse=True)

    return render_template('scoreboard.html',
                           scores_n1=nivel1,
                           scores_n2=nivel2)
