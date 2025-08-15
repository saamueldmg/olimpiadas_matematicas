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

# --- Rutas de la Aplicación ---

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

# --- Rutas del Módulo de Preguntas ---

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

# --- Nuevas rutas para Administrar Preguntas ---

@app.route('/manage-questions')
@login_required
def manage_questions():
    """Muestra la lista de preguntas para cada nivel."""
    return render_template('manage_questions.html', 
                           nivel1=QUIZ_NIVEL1, 
                           nivel2=QUIZ_NIVEL2, 
                           nivel3=QUIZ_NIVEL3)

@app.route('/delete-question/<level>/<int:index>', methods=['POST'])
@login_required
def delete_question(level, index):
    """Elimina una pregunta y su archivo de imagen."""
    question_list = []
    if level == 'nivel1':
        question_list = QUIZ_NIVEL1
    elif level == 'nivel2':
        question_list = QUIZ_NIVEL2
    elif level == 'nivel3':
        question_list = QUIZ_NIVEL3

    if 0 <= index < len(question_list):
        question_to_delete = question_list[index]
        # Elimina el archivo de imagen del sistema
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], question_to_delete['question_image'])
        if os.path.exists(image_path):
            os.remove(image_path)
        
        # Elimina la pregunta de la lista
        del question_list[index]
    
    return redirect(url_for('manage_questions'))

# --- Rutas de Gestión de Equipos ---

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
    scores = session.get('team_scores', {})
    return render_template('scoreboard.html', scores=scores)

# --- Rutas del Quiz ---

@app.route('/select-level')
@login_required
def select_level():
    return render_template('select_level.html')

@app.route('/start-quiz/<level>')
@login_required
def start_quiz(level):
    session['quiz_level'] = level
    quiz_pool = {
        'nivel1': QUIZ_NIVEL1,
        'nivel2': QUIZ_NIVEL2,
        'nivel3': QUIZ_NIVEL3,
    }.get(level, [])
    random.shuffle(quiz_pool)
    session['quiz_pool'] = quiz_pool
    session['current_question_index'] = 0
    session['team_scores'] = {team: 0 for team in session.get('team_scores', {})}
    return redirect(url_for('quiz_question'))

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
    return render_template('assign_point.html', 
                           is_correct=is_correct, 
                           correct_answer=question['correct'],
                           user_answer=user_answer)

@app.route('/assign-point-to-team', methods=['POST'])
@login_required
def assign_point_to_team():
    team = request.form.get('team')
    if team in session['team_scores']:
        session['team_scores'][team] += 1
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
    scores = session.get('team_scores', {})
    if len(scores) < 2:
      winner = "No hay suficientes equipos"
      message = "No se puede determinar un ganador."
    else:
      rojo_score = scores.get("Rojo", 0)
      verde_score = scores.get("Verde", 0)
      if rojo_score > verde_score:
          winner = "Equipo Rojo"
          message = f"¡El {winner} ha ganado!"
      elif verde_score > rojo_score:
          winner = "Equipo Verde"
          message = f"¡El {winner} ha ganado!"
      else:
          winner = "Empate"
          message = "¡Ha habido un empate!"
    return render_template('quiz_finished.html', scores=scores, winner=winner, message=message)

if __name__ == '__main__':
    app.run(debug=True)
