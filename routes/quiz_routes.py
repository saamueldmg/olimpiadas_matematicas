from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_required
from services.quiz_service import QuizService
from services.team_service import TeamService
from firebase_admin import firestore
from utils.decorators import handle_errors

quiz_bp = Blueprint('quiz', __name__, url_prefix='/quiz')


def get_services():
    db = firestore.client()
    return QuizService(), TeamService(db)


def sort_teams_for_scoreboard(teams):
    return sorted(
        teams,
        key=lambda x: x.get('total_score', x.get('score', 0)),
        reverse=True
    )


def normalize_public_level(level_slug):
    """
    Convierte el slug público de URL al nivel interno usado en Firestore.
    """
    mapping = {
        'nivel1': 'nivel1',
        'nivel2': 'nivel2',
        'nivel3': 'nivel3',
    }

    if not level_slug:
        return None

    return mapping.get(str(level_slug).strip().lower())


def get_public_level_label(level_slug):
    labels = {
        'nivel1': 'Nivel I',
        'nivel2': 'Nivel II',
        'nivel3': 'Nivel III',
    }

    return labels.get(level_slug, level_slug)


@quiz_bp.route('/dashboard')
@login_required
@handle_errors
def dashboard():
    _, team_service = get_services()
    teams = team_service.get_all_teams()
    needs_team_setup = len(teams) == 0

    return render_template(
        'dashboard.html',
        needs_team_setup=needs_team_setup
    )


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

        success, message, _ = quiz_service.initialize_quiz(
            level=level,
            team1=team1,
            team2=team2,
            round_type=round_type
        )

        if not success:
            flash(message, 'error')
            return redirect(url_for('quiz.select_level'))

        return redirect(url_for('quiz.countdown'))

    teams = team_service.get_all_teams()
    teams_n1 = [t['name'] for t in teams if t.get('level') == 'Nivel I']
    teams_n2 = [t['name'] for t in teams if t.get('level') == 'Nivel II']
    teams_n3 = [t['name'] for t in teams if t.get('level') == 'Nivel III']

    return render_template(
        'select_level.html',
        teams_n1=teams_n1,
        teams_n2=teams_n2,
        teams_n3=teams_n3
    )


@quiz_bp.route('/reset-question-tracking', methods=['POST'])
@login_required
@handle_errors
def reset_question_tracking():
    quiz_service, _ = get_services()

    level = request.form.get('level')
    round_type = request.form.get('round')

    success, message = quiz_service.reset_used_questions_tracking(
        level=level if level else None,
        round_type=round_type if round_type else None
    )

    flash(message, 'success' if success else 'error')
    return redirect(url_for('quiz.select_level'))


@quiz_bp.route('/countdown')
@login_required
@handle_errors
def countdown():
    """
    Countdown privado/simple para admin.
    El countdown bonito se ve en /quiz/versus/<nivel>.
    """
    quiz_service, _ = get_services()

    if 'quiz_teams' not in session or 'quiz_level' not in session:
        flash('Debes seleccionar equipos y nivel primero', 'error')
        return redirect(url_for('quiz.select_level'))

    teams = session.get('quiz_teams', ['Equipo 1', 'Equipo 2'])
    level = session.get('quiz_level', 'Nivel I')
    round_type = session.get('quiz_round', 'octavos')

    quiz_service.start_countdown(duration=12)

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
    quiz_service, _ = get_services()

    if 'quiz_question_ids' not in session:
        flash('Debes iniciar un enfrentamiento primero', 'error')
        return redirect(url_for('quiz.select_level'))

    if quiz_service.is_quiz_finished():
        return redirect(url_for('quiz.quiz_finished'))

    question = quiz_service.get_current_question()
    if not question:
        flash('Error al cargar la pregunta actual', 'error')
        return redirect(url_for('quiz.dashboard'))

    current_index = session.get('current_question_index', 0)
    total_questions = len(session.get('quiz_question_ids', []))
    teams = session.get('quiz_teams', [])
    scores = session.get('quiz_scores', {})

    public_state = quiz_service.get_public_quiz_state(
        level=session.get('quiz_firestore_level')
    )
    public_question = public_state.get('question') or {}

    public_selected_answer = public_question.get('selected_answer')
    admin_validation_result = public_question.get('admin_validation_result')
    argument_validation_required = public_question.get('argument_validation_required', False)
    show_correct_answer = public_question.get('show_correct_answer', False)
    validated_team_name = public_question.get('validated_team_name')
    question_timer = public_state.get('question_timer') or {}

    if public_selected_answer and admin_validation_result == 'correct' and argument_validation_required:
        return redirect(url_for('quiz.assign_point'))

    return render_template(
        'quiz.html',
        question=question,
        question_number=current_index + 1,
        current_index=current_index,
        total_questions=total_questions,
        teams=teams,
        scores=scores,
        public_selected_answer=public_selected_answer,
        admin_validation_result=admin_validation_result,
        argument_validation_required=argument_validation_required,
        show_correct_answer=show_correct_answer,
        validated_team_name=validated_team_name,
        question_timer=question_timer
    )


@quiz_bp.route('/assign-point', methods=['GET', 'POST'])
@login_required
@handle_errors
def assign_point():
    """
    Pantalla exclusiva de admin para asignar puntos
    cuando la respuesta pública ya fue validada automáticamente como correcta.
    """
    quiz_service, _ = get_services()

    if 'quiz_question_ids' not in session:
        flash('Debes iniciar un enfrentamiento primero', 'error')
        return redirect(url_for('quiz.select_level'))

    public_state = quiz_service.get_public_quiz_state(
        level=session.get('quiz_firestore_level')
    )
    public_question = public_state.get('question') or {}

    if public_question.get('admin_validation_result') != 'correct':
        flash('Solo puedes entrar a asignación si la respuesta fue correcta.', 'error')
        return redirect(url_for('quiz.quiz_question'))

    if not public_question.get('argument_validation_required', False):
        flash('No hay una asignación pendiente en este momento.', 'error')
        return redirect(url_for('quiz.quiz_question'))

    if request.method == 'POST':
        team_name = request.form.get('team')
        points_raw = request.form.get('points')

        if not team_name:
            flash('Debes seleccionar el equipo correcto.', 'error')
            return redirect(url_for('quiz.assign_point'))

        if points_raw not in ('1', '2'):
            flash('Debes seleccionar la puntuación (1 o 2 puntos).', 'error')
            return redirect(url_for('quiz.assign_point'))

        points_value = int(points_raw)
        argument_valid = points_value == 2

        success, message = quiz_service.resolve_correct_answer_assignment(
            team_name=team_name,
            argument_valid=argument_valid
        )

        flash(message, 'success' if success else 'error')
        return redirect(url_for('quiz.quiz_question'))

    question = quiz_service.get_current_question()
    if not question:
        flash('No se pudo cargar la pregunta actual', 'error')
        return redirect(url_for('quiz.quiz_question'))

    current_index = session.get('current_question_index', 0)
    total_questions = len(session.get('quiz_question_ids', []))
    teams = session.get('quiz_teams', [])
    scores = session.get('quiz_scores', {})
    public_selected_answer = public_question.get('selected_answer')
    question_timer = public_state.get('question_timer') or {}

    return render_template(
        'assign_point.html',
        question=question,
        question_number=current_index + 1,
        total_questions=total_questions,
        teams=teams,
        scores=scores,
        public_selected_answer=public_selected_answer,
        question_timer=question_timer
    )


# ============================================================
# Pantallas públicas por nivel
# ============================================================

@quiz_bp.route('/versus')
@handle_errors
def versus():
    """
    Pantalla pública general.
    Muestra un panel con los enfrentamientos activos por nivel.
    """
    quiz_service, _ = get_services()
    all_states = quiz_service.get_all_public_quiz_states()

    cards = []

    for level_key in ['nivel1', 'nivel2', 'nivel3']:
        state = all_states.get(level_key) or {}
        status = state.get('status', 'idle')
        teams = state.get('teams', []) or []

        cards.append({
            'level_key': level_key,
            'level_label': get_public_level_label(level_key),
            'status': status,
            'teams': teams,
            'has_active_match': status not in (None, '', 'idle'),
            'url': url_for('quiz.versus_level', level_slug=level_key)
        })

    return render_template(
        'versus_hub.html',
        cards=cards
    )


@quiz_bp.route('/versus/state')
@handle_errors
def versus_state():
    """
    Estado general de todos los niveles.
    Lo usa versus_hub.html.
    """
    quiz_service, _ = get_services()
    return jsonify(quiz_service.get_all_public_quiz_states())


@quiz_bp.route('/versus/<level_slug>')
@handle_errors
def versus_level(level_slug):
    """
    Pantalla pública específica por nivel.
    """
    quiz_service, _ = get_services()

    normalized_level = normalize_public_level(level_slug)
    if not normalized_level:
        flash('Nivel público no válido.', 'error')
        return redirect(url_for('quiz.versus'))

    public_state = quiz_service.get_public_quiz_state(level=normalized_level)
    status = public_state.get('status') if public_state else 'idle'
    has_active_match = bool(public_state) and status not in (None, '', 'idle')

    if status == 'countdown':
        return render_template(
            'contador_versus.html',
            match_state=public_state,
            has_active_match=has_active_match,
            level_slug=normalized_level
        )

    return render_template(
        'versus.html',
        match_state=public_state,
        has_active_match=has_active_match,
        level_slug=normalized_level
    )


@quiz_bp.route('/versus/<level_slug>/state')
@handle_errors
def versus_level_state(level_slug):
    """
    Estado público específico por nivel.
    Lo usan versus.html y contador_versus.html.
    """
    quiz_service, _ = get_services()

    normalized_level = normalize_public_level(level_slug)
    if not normalized_level:
        return jsonify({}), 404

    public_state = quiz_service.get_public_quiz_state(level=normalized_level)
    return jsonify(public_state or {})


@quiz_bp.route('/submit-public-answer/<level_slug>', methods=['POST'])
@handle_errors
def submit_public_answer(level_slug):
    """
    El público envía respuesta para un nivel específico.
    """
    quiz_service, _ = get_services()

    normalized_level = normalize_public_level(level_slug)
    if not normalized_level:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'message': 'Nivel no válido.'
            }), 400

        flash('Nivel no válido.', 'error')
        return redirect(url_for('quiz.versus'))

    answer = request.form.get('answer')
    success, message = quiz_service.submit_public_answer(
        answer,
        level=normalized_level
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': success,
            'message': message
        }), 200 if success else 400

    flash(message, 'success' if success else 'error')
    return redirect(url_for('quiz.versus_level', level_slug=normalized_level))


# ============================================================
# Rutas admin / control del quiz
# ============================================================

@quiz_bp.route('/validate-answer', methods=['POST'])
@login_required
@handle_errors
def validate_answer():
    flash('La validación ahora es automática cuando el público envía la respuesta.', 'info')
    return redirect(url_for('quiz.quiz_question'))


@quiz_bp.route('/skip-question', methods=['POST'])
@login_required
@handle_errors
def skip_question():
    quiz_service, _ = get_services()
    quiz_service.next_question()
    flash('Pregunta omitida', 'success')
    return redirect(url_for('quiz.quiz_question'))


@quiz_bp.route('/finish-match', methods=['POST'])
@login_required
@handle_errors
def finish_match():
    quiz_service, _ = get_services()

    success = quiz_service.finish_match()
    if success:
        flash('El enfrentamiento fue finalizado manualmente', 'success')
    else:
        flash('No se pudo finalizar el enfrentamiento', 'error')

    return redirect(url_for('quiz.quiz_finished'))


@quiz_bp.route('/next-question', methods=['POST'])
@login_required
@handle_errors
def next_question():
    quiz_service, _ = get_services()

    success = quiz_service.next_question()
    if not success:
        flash('No se pudo avanzar a la siguiente pregunta', 'error')

    return redirect(url_for('quiz.quiz_question'))


@quiz_bp.route('/quiz-finished')
@login_required
@handle_errors
def quiz_finished():
    quiz_service, _ = get_services()
    results = quiz_service.get_quiz_results()

    if isinstance(results, list):
        scores = session.get('quiz_scores', {})
        teams = session.get('quiz_teams', [])

        if scores:
            max_score = max(scores.values())
            winners = [team for team, score in scores.items() if score == max_score]

            if len(winners) > 1:
                winner = 'Empate'
                message = f'¡Empate! {" y ".join(winners)} tienen {max_score} puntos'
            else:
                winner = winners[0]
                message = f'¡{winner} gana con {max_score} puntos!'
        else:
            winner = 'Ninguno'
            message = 'No se registraron puntos'

        teams_order = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    else:
        winner = results.get('winner', 'Desconocido')
        message = results.get('message', 'Quiz finalizado')
        scores = results.get('scores', {})
        teams_order = results.get('teams_order', list(scores.keys()))

    rendered_scores = scores
    rendered_winner = winner
    rendered_message = message
    rendered_teams_order = teams_order
    rendered_results = results

    quiz_service.clear_quiz_session()

    return render_template(
        'quiz_finished.html',
        winner=rendered_winner,
        message=rendered_message,
        scores=rendered_scores,
        teams_order=rendered_teams_order,
        results=rendered_results
    )


@quiz_bp.route('/break-tie', methods=['POST'])
@login_required
@handle_errors
def break_tie():
    _, team_service = get_services()
    winner_team = request.form.get('winner_team')

    if not winner_team:
        flash('Debes seleccionar un equipo ganador', 'error')
        return redirect(url_for('quiz.quiz_finished'))

    success = team_service.update_team_score(winner_team, 1)

    if success:
        flash(f'¡{winner_team} gana el desempate! +1 punto agregado', 'success')
    else:
        flash('Error al actualizar el puntaje', 'error')

    return redirect(url_for('quiz.scoreboard'))


@quiz_bp.route('/scoreboard')
@handle_errors
def scoreboard():
    _, team_service = get_services()
    teams = team_service.get_all_teams()

    teams_n1 = [t for t in teams if t.get('level') == 'Nivel I']
    teams_n2 = [t for t in teams if t.get('level') == 'Nivel II']
    teams_n3 = [t for t in teams if t.get('level') == 'Nivel III']

    teams_n1_sorted = sort_teams_for_scoreboard(teams_n1)
    teams_n2_sorted = sort_teams_for_scoreboard(teams_n2)
    teams_n3_sorted = sort_teams_for_scoreboard(teams_n3)

    return render_template(
        'scoreboard.html',
        scores_n1=teams_n1_sorted,
        scores_n2=teams_n2_sorted,
        scores_n3=teams_n3_sorted,
        teams=teams
    )