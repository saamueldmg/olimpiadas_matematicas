from flask import Flask, render_template, request, redirect, url_for, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import random
import os
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import Increment

# --- 1. CONFIGURACIÓN DE LA APLICACIÓN ---
app = Flask(__name__)
app.secret_key = 'una-clave-super-secreta-cambiala-por-algo-seguro'
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

UPLOAD_FOLDER = 'static/images'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- 2. INICIALIZACIÓN DE FIREBASE ---
try:
    if not firebase_admin._apps:
        # Asegúrate de que tu archivo 'serviceAccountKey.json' esté en la misma carpeta
        cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Error crítico al inicializar Firebase: {e}")
    # En un entorno de producción, podrías querer manejar esto de forma más robusta

db = firestore.client()
teams_collection = db.collection('teams')
questions_collection = db.collection('questions')

# --- 3. MODELO DE USUARIO Y AUTENTICACIÓN ---


class User(UserMixin):
    def __init__(self, id):
        self.id = id

    def get_id(self):
        return str(self.id)


# En una aplicación real, esto vendría de una base de datos de usuarios
users = {"admin": {"password": generate_password_hash("password")}}


@login_manager.user_loader
def load_user(user_id):
    if user_id in users:
        return User(user_id)
    return None

# --- 4. RUTAS DE AUTENTICACIÓN Y NAVEGACIÓN PRINCIPAL ---


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
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

# --- 5. RUTAS PARA GESTIONAR PREGUNTAS ---


@app.route('/add-question', methods=['GET', 'POST'])
@login_required
def add_question():
    if request.method == 'POST':
        level = request.form.get('level')
        correct_answer = request.form.get('correct_answer')
        options = {
            'a': request.form.get('option_a'), 'b': request.form.get('option_b'),
            'c': request.form.get('option_c'), 'd': request.form.get('option_d')
        }
        file = request.files.get('question_image')
        if file and file.filename:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            new_question = {
                'question_image': filename, 'options': options,
                'correct': correct_answer, 'level': level
            }
            questions_collection.add(new_question)
        return redirect(url_for('add_question'))
    return render_template('add_question.html')


@app.route('/manage-questions')
@login_required
def manage_questions():
    questions_ref = questions_collection.stream()
    questions = {'nivel1': [], 'nivel2': [], 'nivel3': []}
    for doc in questions_ref:
        question_data = doc.to_dict()
        level = question_data.get('level')
        if level in questions:
            questions[level].append({'id': doc.id, **question_data})
    return render_template('manage_questions.html', **questions)


@app.route('/delete-question/<question_id>', methods=['POST'])
@login_required
def delete_question(question_id):
    question_ref = questions_collection.document(question_id)
    question_doc = question_ref.get()
    if question_doc.exists:
        question_data = question_doc.to_dict()
        image_name = question_data.get('question_image')
        if image_name:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_name)
            if os.path.exists(image_path):
                os.remove(image_path)
        question_ref.delete()
    return redirect(url_for('manage_questions'))

# --- 6. RUTAS PARA GESTIONAR EQUIPOS ---


@app.route('/manage-teams')
@login_required
def manage_teams():
    teams_ref = teams_collection.stream()
    teams_list = []
    for doc in teams_ref:
        team_data = doc.to_dict()
        team_data['id'] = doc.id
        teams_list.append(team_data)
    return render_template('manage_teams.html', teams=teams_list)


@app.route('/add-team', methods=['POST'])
@login_required
def add_team():
    team_name = request.form.get('team_name')
    if team_name:
        teams_collection.add({'name': team_name, 'score': 0})
    return redirect(url_for('manage_teams'))


@app.route('/update-team-name/<team_id>', methods=['POST'])
@login_required
def update_team_name(team_id):
    new_name = request.form.get('new_team_name')
    if new_name:
        teams_collection.document(team_id).update({'name': new_name})
    return redirect(url_for('manage_teams'))


@app.route('/delete-team/<team_id>', methods=['POST'])
@login_required
def delete_team(team_id):
    teams_collection.document(team_id).delete()
    return redirect(url_for('manage_teams'))

# --- 7. RUTAS DEL MARCADOR Y EL JUEGO ---


@app.route('/scoreboard')
@login_required
def show_scoreboard():
    teams_ref = teams_collection.stream()
    scores = {doc.to_dict()['name']: doc.to_dict().get('score', 0)
              for doc in teams_ref}
    return render_template('scoreboard.html', scores=scores)


@app.route('/reset-points', methods=['POST'])
@login_required
def reset_points():
    for doc in teams_collection.stream():
        teams_collection.document(doc.id).update({'score': 0})
    return redirect(url_for('show_scoreboard'))


@app.route('/select-level', methods=['GET', 'POST'])
@login_required
def select_level():
    teams = [doc.to_dict()['name'] for doc in teams_collection.stream()]
    if request.method == 'POST':
        session['quiz_level'] = request.form.get('level')
        session['quiz_teams'] = [request.form.get(
            'team1'), request.form.get('team2')]
        return redirect(url_for('start_quiz'))
    return render_template('select_level.html', teams=teams)


@app.route('/start-quiz')
@login_required
def start_quiz():
    level = session.get('quiz_level')
    quiz_pool = [doc.to_dict() for doc in questions_collection.where(
        'level', '==', level).stream()]
    random.shuffle(quiz_pool)
    session['quiz_pool'] = quiz_pool
    session['current_question_index'] = 0
    session['quiz_scores'] = {
        team: 0 for team in session.get('quiz_teams', [])}
    return redirect(url_for('countdown'))


@app.route('/countdown')
@login_required
def countdown():
    return render_template('countdown.html')


@app.route('/quiz-question')
@login_required
def quiz_question():
    index = session.get('current_question_index', 0)
    quiz_pool = session.get('quiz_pool', [])
    if index >= len(quiz_pool):
        return redirect(url_for('quiz_finished'))
    session['current_question'] = quiz_pool[index]
    return render_template('quiz.html', question=quiz_pool[index], question_number=index + 1)


@app.route('/submit-answer', methods=['POST'])
@login_required
def submit_answer():
    user_answer = request.form.get('answer')
    question = session.get('current_question', {})
    is_correct = user_answer == question.get('correct')
    return render_template('assign_point.html', is_correct=is_correct, old_question=not is_correct, teams=session.get('quiz_scores', {}))


@app.route('/assign-point-to-team', methods=['POST'])
@login_required
def assign_point_to_team():
    team = request.form.get('team')
    old_question_flag = request.form.get('old_question_flag') == 'False'

    quiz_scores = session.get('quiz_scores', {})
    if team in quiz_scores:
        quiz_scores[team] += 1
        docs = teams_collection.where('name', '==', team).limit(1).stream()
        for doc in docs:
            teams_collection.document(doc.id).update({'score': Increment(1)})
    session['quiz_scores'] = quiz_scores

    if any(score >= 3 for score in quiz_scores.values()):
        return redirect(url_for('quiz_finished'))

    if old_question_flag:
        session['current_question_index'] = session.get(
            'current_question_index', 0) + 1
    return redirect(url_for('quiz_question'))


@app.route('/skip-question')
@login_required
def skip_question():
    session['current_question_index'] = session.get(
        'current_question_index', 0) + 1
    return redirect(url_for('quiz_question'))


@app.route('/quiz-finished')
@login_required
def quiz_finished():
    scores = session.get('quiz_scores', {})
    winner, message = "Empate", "¡Ha habido un empate!"
    if scores:
        max_score = -1
        winners = []
        for team, score in scores.items():
            if score > max_score:
                max_score = score
                winners = [team]
            elif score == max_score:
                winners.append(team)
        if len(winners) == 1:
            winner = winners[0]
            message = f"¡El equipo {winner} ha ganado!"
    return render_template('quiz_finished.html', scores=scores, winner=winner, message=message)


# --- 8. INICIO DE LA APLICACIÓN ---
if __name__ == '__main__':
    app.run(debug=True)
# Nota: En producción, establece debug=False y usa un servidor adecuado
