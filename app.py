from flask import Flask, render_template, request, redirect, url_for, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import random
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import Increment
from flask import Flask, render_template, request, redirect, url_for, session
from whitenoise import WhiteNoise

# --- CONFIGURACIÓN DE LA APLICACIÓN ---
app = Flask(__name__)
# <--- 2. AÑADE ESTA LÍNEA
app.wsgi_app = WhiteNoise(app.wsgi_app, root='static/')
app.secret_key = 'una-clave-super-secreta-y-dificil'
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

UPLOAD_FOLDER = 'static/images'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- INICIALIZACIÓN DE FIREBASE (MODIFICADA PARA PRODUCCIÓN) ---
try:
    if not firebase_admin._apps:
        # Opción 1: Busca el archivo de credenciales (ideal para desarrollo local)
        if os.path.exists("serviceAccountKey.json"):
            cred = credentials.Certificate("serviceAccountKey.json")
        # Opción 2: Si no lo encuentra, busca las credenciales en una variable de entorno (para el servidor de Render)
        else:
            firebase_credentials_str = os.environ.get('FIREBASE_CREDENTIALS')
            if firebase_credentials_str:
                firebase_credentials_json = json.loads(
                    firebase_credentials_str)
                cred = credentials.Certificate(firebase_credentials_json)
            else:
                raise Exception(
                    "No se encontraron las credenciales de Firebase en el archivo o en las variables de entorno.")

        firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Error crítico al inicializar Firebase: {e}")

db = firestore.client()
teams_collection = db.collection('teams')
questions_collection = db.collection('questions')


# --- MODELO DE USUARIO Y LOGIN ---
class User(UserMixin):
    def __init__(self, id):
        self.id = id


users = {"admin": {"password": generate_password_hash("password")}}


@login_manager.user_loader
def load_user(user_id):
    return User(user_id) if user_id in users else None


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
    return redirect(url_for('login'))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('login'))


# --- PANEL DE CONTROL ---
@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


# --- GESTIÓN DE PREGUNTAS ---
@app.route('/add-question', methods=['GET', 'POST'])
@login_required
def add_question():
    if request.method == 'POST':
        file = request.files.get('question_image')
        if not file or file.filename == '':
            return "No se seleccionó ningún archivo de imagen", 400

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        new_question = {
            'level': request.form.get('level'),
            'question_image': filename,
            'options': {
                'a': request.form.get('option_a'),
                'b': request.form.get('option_b'),
                'c': request.form.get('option_c'),
                'd': request.form.get('option_d')
            },
            'correct': request.form.get('correct_answer')
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
    return render_template('manage_questions.html', nivel1=questions['nivel1'], nivel2=questions['nivel2'], nivel3=questions['nivel3'])


@app.route('/delete-question/<question_id>', methods=['POST'])
@login_required
def delete_question(question_id):
    question_ref = questions_collection.document(question_id)
    question_doc = question_ref.get()
    if question_doc.exists:
        image_filename = question_doc.to_dict().get('question_image')
        if image_filename:
            image_path = os.path.join(
                app.config['UPLOAD_FOLDER'], image_filename)
            if os.path.exists(image_path):
                os.remove(image_path)
        question_ref.delete()
    return redirect(url_for('manage_questions'))


# --- GESTIÓN DE EQUIPOS ---
@app.route('/manage-teams')
@login_required
def manage_teams():
    teams_ref = teams_collection.stream()
    teams_list = [{'id': doc.id, **doc.to_dict()} for doc in teams_ref]
    return render_template('manage_teams.html', teams=teams_list)


@app.route('/add-team', methods=['POST'])
@login_required
def add_team():
    team_name = request.form.get('team_name')
    if team_name:
        teams_collection.add({'name': team_name, 'score': 0})
    return redirect(url_for('manage_teams'))


@app.route('/delete-team/<team_id>', methods=['POST'])
@login_required
def delete_team(team_id):
    teams_collection.document(team_id).delete()
    return redirect(url_for('manage_teams'))


@app.route('/update-team-name/<team_id>', methods=['POST'])
@login_required
def update_team_name(team_id):
    new_name = request.form.get('new_name')
    if new_name:
        teams_collection.document(team_id).update({'name': new_name})
    return redirect(url_for('manage_teams'))


# --- TABLA DE PUNTUACIONES ---
@app.route('/scoreboard')
@login_required
def show_scoreboard():
    teams_ref = teams_collection.order_by(
        'score', direction=firestore.Query.DESCENDING).stream()
    scores_list = [{'name': doc.to_dict()['name'], 'score': doc.to_dict().get(
        'score', 0)} for doc in teams_ref]
    return render_template('scoreboard.html', scores=scores_list)


@app.route('/reset-points', methods=['POST'])
@login_required
def reset_points():
    teams_ref = teams_collection.stream()
    for doc in teams_ref:
        teams_collection.document(doc.id).update({'score': 0})
    return redirect(url_for('show_scoreboard'))


# --- LÓGICA DEL CONCURSO (QUIZ) ---
@app.route('/select-level', methods=['GET', 'POST'])
@login_required
def select_level():
    session.pop('quiz_pool', None)
    session.pop('current_question_index', None)
    session.pop('quiz_scores', None)
    session.pop('current_question', None)

    teams_docs = list(teams_collection.stream())
    teams_list = [doc.to_dict()['name'] for doc in teams_docs]

    if len(teams_list) < 2:
        return render_template('select_level.html', error="Necesitas crear al menos 2 equipos para poder jugar.")

    if request.method == 'POST':
        team1 = request.form.get('team1')
        team2 = request.form.get('team2')

        if team1 == team2:
            return render_template('select_level.html', teams=teams_list, error="¡Error! No puedes seleccionar el mismo equipo dos veces.")

        session['quiz_level'] = request.form.get('level')
        session['quiz_teams'] = [team1, team2]
        return redirect(url_for('start_quiz'))

    return render_template('select_level.html', teams=teams_list)


@app.route('/start-quiz')
@login_required
def start_quiz():
    level = session.get('quiz_level')
    if not level:
        return redirect(url_for('select_level'))

    quiz_pool_docs = questions_collection.where('level', '==', level).stream()
    quiz_pool = [doc.to_dict() for doc in quiz_pool_docs]

    if len(quiz_pool) < 10:
        teams_docs = list(teams_collection.stream())
        teams_list = [doc.to_dict()['name'] for doc in teams_docs]
        return render_template('select_level.html',
                               teams=teams_list,
                               error=f"No hay suficientes preguntas para el {level}. Se necesitan al menos 10.")

    random.shuffle(quiz_pool)
    session['quiz_pool'] = quiz_pool[:10]

    session['current_question_index'] = 0
    session['quiz_scores'] = {
        team: 0 for team in session.get('quiz_teams', [])}
    return redirect(url_for('countdown'))


@app.route('/countdown')
@login_required
def countdown():
    # Obtiene los nombres de los equipos de la sesión para pasarlos a la plantilla
    teams = session.get('quiz_teams', ['Equipo 1', 'Equipo 2'])
    return render_template('countdown.html', teams=teams)


@app.route('/quiz-question')
@login_required
def quiz_question():
    if 'quiz_pool' not in session or 'current_question_index' not in session:
        return redirect(url_for('select_level'))

    index = session.get('current_question_index', 0)
    quiz_pool = session.get('quiz_pool', [])

    if not quiz_pool or index >= len(quiz_pool):
        return redirect(url_for('quiz_finished'))

    question = quiz_pool[index]
    session['current_question'] = question
    return render_template('quiz.html', question=question, question_number=index + 1)


@app.route('/submit-answer', methods=['POST'])
@login_required
def submit_answer():
    user_answer = request.form.get('answer')
    question = session.get('current_question')

    if not question:
        return redirect(url_for('select_level'))

    is_correct = user_answer == question.get('correct')

    if is_correct:
        return render_template('assign_point.html', teams=session.get('quiz_teams', []))
    else:
        session['current_question_index'] = session.get(
            'current_question_index', 0) + 1
        session.modified = True
        return redirect(url_for('quiz_question'))


@app.route('/assign-point-to-team', methods=['POST'])
@login_required
def assign_point_to_team():
    team = request.form.get('team')
    points_to_add = int(request.form.get('points', 0))

    if team in session.get('quiz_scores', {}):
        session['quiz_scores'][team] += points_to_add

        if points_to_add > 0:
            docs = teams_collection.where('name', '==', team).stream()
            for doc in docs:
                teams_collection.document(doc.id).update(
                    {'score': Increment(points_to_add)})

    session['current_question_index'] = session.get(
        'current_question_index', 0) + 1
    session.modified = True
    return redirect(url_for('quiz_question'))

# --- RUTA PARA SALTAR PREGUNTA (USADA POR EL CRONÓMETRO) ---


@app.route('/skip-question')
@login_required
def skip_question():
    session['current_question_index'] = session.get(
        'current_question_index', 0) + 1
    session.modified = True
    return redirect(url_for('quiz_question'))


@app.route('/quiz-finished')
@login_required
def quiz_finished():
    scores = session.get('quiz_scores', {})
    winner = "Empate"
    message = "¡Ha habido un empate!"
    if scores:
        max_score = max(scores.values())
        winners = [team for team, score in scores.items() if score ==
                   max_score]
        if len(winners) == 1:
            winner = winners[0]
            message = f"¡El equipo {winner} ha ganado!"

    session.pop('quiz_pool', None)
    session.pop('current_question_index', None)
    session.pop('quiz_scores', None)
    session.pop('current_question', None)

    return render_template('quiz_finished.html', scores=scores, winner=winner, message=message)


# --- INICIO DE LA APLICACIÓN ---
if __name__ == '__main__':
    app.run(debug=True)
