from flask import Flask, render_template, request, redirect, url_for, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from logic.quiz_data import QUIZ_NIVEL1, QUIZ_NIVEL2, QUIZ_NIVEL3
import random
import os

app = Flask(__name__)
app.secret_key = 'una-clave-super-secreta'
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

UPLOAD_FOLDER = 'static/images'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


class User(UserMixin):
    def __init__(self, id):
        self.id = id

    def get_id(self):
        return str(self.id)


users = {"admin": {"password": generate_password_hash("password")}}


@login_manager.user_loader
def load_user(user_id):
    if user_id in users:
        return User(user_id)
    return None


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = users.get(username)
        if user and check_password_hash(user['password'], password):
            login_user(User(username))
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Usuario o contraseña incorrectos")
    return render_template('login.html')


@app.route('/')
def index():
    if 'team_scores' not in session:
        session['team_scores'] = {}

    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


@app.route('/add-question', methods=['GET', 'POST'])
@login_required
def add_question():
    if request.method == 'POST':
        level = request.form.get('level')
        correct_answer = request.form.get('correct_answer')
        options = {
            'a': request.form.get('option_a'),
            'b': request.form.get('option_b'),
            'c': request.form.get('option_c'),
            'd': request.form.get('option_d')
        }

        if 'question_image' not in request.files:
            return "No se encontró el archivo de imagen"
        file = request.files['question_image']
        if file.filename == '':
            return "No se seleccionó ningún archivo"
        if file:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            new_question = {
                'question_image': filename,
                'options': options,
                'correct': correct_answer
            }

            if level == 'nivel1':
                QUIZ_NIVEL1.append(new_question)
            elif level == 'nivel2':
                QUIZ_NIVEL2.append(new_question)
            elif level == 'nivel3':
                QUIZ_NIVEL3.append(new_question)

            return redirect(url_for('add_question'))

    return render_template('add_question.html')


@app.route('/manage-questions')
@login_required
def manage_questions():
    return render_template('manage_questions.html',
                           nivel1=QUIZ_NIVEL1,
                           nivel2=QUIZ_NIVEL2,
                           nivel3=QUIZ_NIVEL3)


@app.route('/delete-question/<level>/<int:index>', methods=['POST'])
@login_required
def delete_question(level, index):
    question_list = []
    if level == 'nivel1':
        question_list = QUIZ_NIVEL1
    elif level == 'nivel2':
        question_list = QUIZ_NIVEL2
    elif level == 'nivel3':
        question_list = QUIZ_NIVEL3

    if 0 <= index < len(question_list):
        question_to_delete = question_list[index]
        image_path = os.path.join(
            app.config['UPLOAD_FOLDER'], question_to_delete['question_image'])
        if os.path.exists(image_path):
            os.remove(image_path)

        del question_list[index]

    return redirect(url_for('manage_questions'))


@app.route('/manage-teams', methods=['GET', 'POST'])
@login_required
def manage_teams():
    if 'team_scores' not in session:
        session['team_scores'] = {}

    if request.method == 'POST':
        new_team_name = request.form.get('new_team_name')
        if new_team_name and new_team_name not in session['team_scores']:
            session['team_scores'][new_team_name] = 0
            session.modified = True

    return render_template('manage_teams.html', teams=session['team_scores'])


@app.route('/update-team-name', methods=['POST'])
@login_required
def update_team_name():
    old_name = request.form.get('old_name')
    new_name = request.form.get('new_name')

    if old_name in session['team_scores'] and new_name:
        updated_teams = {}
        for team, score in session['team_scores'].items():
            if team == old_name:
                updated_teams[new_name] = score
            else:
                updated_teams[team] = score

        session['team_scores'] = updated_teams
        session.modified = True

    return redirect(url_for('manage_teams'))


@app.route('/delete-team/<team_name>', methods=['POST'])
@login_required
def delete_team(team_name):
    if 'team_scores' in session and team_name in session['team_scores']:
        del session['team_scores'][team_name]
        session.modified = True
    return redirect(url_for('manage_teams'))


@app.route('/scoreboard')
@login_required
def show_scoreboard():
    scores = session.get('quiz_scores', {})
    if not scores:
        scores = session.get('team_scores', {})
    return render_template('scoreboard.html', scores=scores)


@app.route('/reset-points', methods=['POST'])
@login_required
def reset_points():
    if 'quiz_scores' in session:
        session['quiz_scores'] = {team: 0 for team in session['quiz_scores']}
    if 'team_scores' in session:
        session['team_scores'] = {team: 0 for team in session['team_scores']}
    return redirect(url_for('show_scoreboard'))


@app.route('/select-level', methods=['GET', 'POST'])
@login_required
def select_level():
    teams = list(session.get('team_scores', {}).keys())
    if request.method == 'POST':
        level = request.form.get('level')
        team1 = request.form.get('team1')
        team2 = request.form.get('team2')

        session['quiz_level'] = level
        session['quiz_teams'] = [team1, team2]
        return redirect(url_for('start_quiz'))

    return render_template('select_level.html', teams=teams)


@app.route('/start-quiz')
@login_required
def start_quiz():
    level = session.get('quiz_level')
    quiz_pool = {
        'nivel1': QUIZ_NIVEL1,
        'nivel2': QUIZ_NIVEL2,
        'nivel3': QUIZ_NIVEL3,
    }.get(level, [])
    random.shuffle(quiz_pool)
    session['quiz_pool'] = quiz_pool
    session['current_question_index'] = 0

    selected_teams = session.get('quiz_teams', [])
    session['quiz_scores'] = {team: 0 for team in selected_teams}

    return redirect(url_for('countdown'))


@app.route('/countdown')
@login_required
def countdown():
    return render_template('countdown.html')


@app.route('/quiz-question')
@login_required
def quiz_question():
    index = session.get('current_question_index')
    quiz_pool = session.get('quiz_pool')
    if not quiz_pool or index >= len(quiz_pool):
        return redirect(url_for('quiz_finished'))
    question = quiz_pool[index]
    session['current_question'] = question
    return render_template('quiz.html',
                           question=question,
                           question_number=index + 1)


@app.route('/submit-answer', methods=['POST'])
@login_required
def submit_answer():
    user_answer = request.form.get('answer')
    question = session.get('current_question')

    is_correct = user_answer == question['correct']

    teams_in_quiz = session.get('quiz_scores')

    if not is_correct:
        return render_template('assign_point.html',
                               is_correct=False,
                               old_question=True,
                               teams=teams_in_quiz)
    else:
        return render_template('assign_point.html',
                               is_correct=True,
                               old_question=False,
                               teams=teams_in_quiz)


@app.route('/assign-point-to-team', methods=['POST'])
@login_required
def assign_point_to_team():
    team = request.form.get('team')
    old_question_flag = request.form.get('old_question_flag')

    if team in session['quiz_scores']:
        session['quiz_scores'][team] += 1

    for score in session['quiz_scores'].values():
        if score >= 5:
            return redirect(url_for('quiz_finished'))

    if old_question_flag == 'False':
        session['current_question_index'] += 1

    return redirect(url_for('quiz_question'))


@app.route('/skip-question')
@login_required
def skip_question():
    session['current_question_index'] += 1
    return redirect(url_for('quiz_question'))


@app.route('/quiz-finished')
@login_required
def quiz_finished():
    scores = session.get('quiz_scores', {})
    if len(scores) < 2:
        winner = "No hay suficientes equipos"
        message = "No se puede determinar un ganador."
    else:
        max_score = 0
        winner_list = []
        for team, score in scores.items():
            if score > max_score:
                max_score = score
                winner_list = [team]
            elif score == max_score:
                winner_list.append(team)

        if len(winner_list) == 1:
            winner = winner_list[0]
            message = f"¡El equipo {winner} ha ganado!"
        else:
            winner = "Empate"
            message = "¡Ha habido un empate!"

    return render_template('quiz_finished.html', scores=scores, winner=winner, message=message)


if __name__ == '__main__':
    app.run(debug=True)
