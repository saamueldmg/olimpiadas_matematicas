from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required
from services.quiz_service import QuizService
from services.team_service import TeamService
from firebase_admin import firestore  # ← AGREGAR ESTE IMPORT
from utils.decorators import handle_errors

quiz_bp = Blueprint('quiz', __name__, url_prefix='/quiz')


def get_services():
    """Helper para obtener instancias de servicios"""
    db = firestore.client()  # ← CREAR INSTANCIA DE DB
    return QuizService(), TeamService(db)  # ← PASAR db A TeamService


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
    return render_template('countdown.html')


@quiz_bp.route('/quiz')
@login_required
@handle_errors
def quiz_question():
    quiz_service, _ = get_services()

    if quiz_service.is_quiz_finished():
        return redirect(url_for('quiz.quiz_finished'))

    question = quiz_service.get_current_question()
    if not question:
        flash('Error al cargar la pregunta', 'error')
        return redirect(url_for('quiz.dashboard'))

    current_index = session.get('current_question_index', 0)
    total_questions = len(session.get('quiz_question_ids', []))
    teams = session.get('quiz_teams', [])
    scores = session.get('quiz_scores', {})

    return render_template('quiz.html',
                           question=question,
                           current_index=current_index,
                           total_questions=total_questions,
                           teams=teams,
                           scores=scores)


@quiz_bp.route('/submit-answer', methods=['POST'])
@login_required
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
@handle_errors
def assign_point():
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


@quiz_bp.route('/quiz-finished')
@login_required
@handle_errors
def quiz_finished():
    quiz_service, _ = get_services()
    results = quiz_service.get_quiz_results()
    quiz_service.clear_quiz_session()

    return render_template('quiz_finished.html', results=results)


@quiz_bp.route('/scoreboard')
@handle_errors
def scoreboard():
    _, team_service = get_services()
    teams = team_service.get_all_teams()

    # Ordenar por puntos
    teams_sorted = sorted(teams, key=lambda x: x.get('score', 0), reverse=True)

    return render_template('scoreboard.html', teams=teams_sorted)
