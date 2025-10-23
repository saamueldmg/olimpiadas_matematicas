from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, get_flashed_messages
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import random
import os
import json
# --- CORRECCIÓN IMPORTACIÓN FieldPath ---
# Ya no necesitamos FieldPath, usamos '__name__' en la consulta
from google.cloud.firestore_v1 import Increment
# from google.cloud.firestore import FieldPath  # <-- Ya no se necesita
from whitenoise import WhiteNoise
import firebase_admin
from firebase_admin import credentials, firestore, storage

# --- CONFIGURACIÓN DE LA APLICACIÓN ---
app = Flask(__name__)
STATIC_ROOT = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), 'static')
app.wsgi_app = WhiteNoise(app.wsgi_app, root=STATIC_ROOT, prefix="static/")
app.secret_key = 'una-clave-super-secreta-y-dificil'
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor, inicia sesión para acceder."
login_manager.login_message_category = "error"

# --- INICIALIZACIÓN DE FIREBASE ---
try:
    if not firebase_admin._apps:
        STORAGE_BUCKET = 'olympic-math.appspot.com'

        # Lee las credenciales desde el archivo local
        if os.path.exists("serviceAccountKey.json"):
            cred = credentials.Certificate("serviceAccountKey.json")
            firebase_admin.initialize_app(
                cred, {'storageBucket': STORAGE_BUCKET})
        else:
            raise Exception(
                "No se encontraron las credenciales de Firebase. Asegúrate de tener serviceAccountKey.json.")
except Exception as e:
    print(f"Error crítico al inicializar Firebase: {e}")

db = firestore.client()
teams_collection = db.collection('teams')
questions_collection = db.collection('questions')
brackets_collection = db.collection('brackets')


# --- MODELO DE USUARIO Y LOGIN ---
class User(UserMixin):
    def __init__(self, id):
        self.id = id

    def get_id(self):
        return str(self.id)


users = {"admin": {"password": generate_password_hash("bosco@tech%")}}


@login_manager.user_loader
def load_user(user_id):
    return User(user_id) if user_id in users else None


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if not username or not password:
            flash("Por favor, ingresa usuario y contraseña.", "error")
            return render_template('login.html')

        user = users.get(username)
        if user and check_password_hash(user['password'], password):
            login_user(User(username))
            session.permanent = False  # Cierra sesión al cerrar navegador
            return redirect(url_for('dashboard'))

        flash("Usuario o contraseña incorrectos", "error")
        return render_template('login.html')

    # Limpia mensajes viejos al cargar la pág. de login
    get_flashed_messages()
    return render_template('login.html')


@app.route('/')
def index():
    # Esta ruta ahora también cierra sesión si el usuario ya estaba logueado
    if current_user.is_authenticated:
        logout_user()
        session.clear()

    return redirect(url_for('login'))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    flash("Has cerrado sesión exitosamente.", "success")
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    # Verificar si los equipos ya fueron creados
    teams_exist = teams_collection.limit(1).get()
    setup_needed = not bool(teams_exist)
    return render_template('dashboard.html', setup_needed=setup_needed)


# --- GESTIÓN DE PREGUNTAS ---

@app.route('/add-question', methods=['GET', 'POST'])
@login_required
def add_question():
    if request.method == 'POST':
        try:
            file = request.files.get('question_image')
            if not file or file.filename == '':
                flash("No se seleccionó ningún archivo de imagen", "error")
                return redirect(url_for('add_question'))

            filename = secure_filename(file.filename)
            bucket = storage.bucket()
            blob = bucket.blob(f"question_images/{filename}")

            file.seek(0)
            blob.upload_from_file(file, content_type=file.content_type)
            blob.make_public()
            public_url = blob.public_url

            new_question = {
                'level': request.form.get('level'),
                'question_image': public_url,
                'options': {
                    'a': request.form.get('option_a'),
                    'b': request.form.get('option_b'),
                    'c': request.form.get('option_c'),
                    'd': request.form.get('option_d')
                },
                'correct': request.form.get('correct_answer')
            }
            questions_collection.add(new_question)
            flash("¡Pregunta añadida exitosamente!", "success")
            return redirect(url_for('add_question'))
        except Exception as e:
            flash(f"Error al añadir la pregunta: {e}", "error")
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
        image_url = question_doc.to_dict().get('question_image')

        if image_url:
            try:
                # Extrae el path del archivo desde la URL pública
                file_path_in_bucket = image_url.split(
                    f"/{storage.bucket().name}/")[1].split('?')[0]
                blob = storage.bucket().blob(file_path_in_bucket)
                if blob.exists():
                    blob.delete()
            except Exception as e:
                print(
                    f"Error al borrar la imagen de Storage (puede que ya no exista): {e}")

        question_ref.delete()
        flash("Pregunta eliminada correctamente.", "success")
    return redirect(url_for('manage_questions'))


# --- GESTIÓN DE EQUIPOS (Firestore) ---

@app.route('/manage-teams')
@login_required
def manage_teams():
    teams_ref = teams_collection.stream()
    teams_n1_list = []
    teams_n2_list = []

    for doc in teams_ref:
        team_data = doc.to_dict()
        team_entry = {'id': doc.id, **team_data}
        if team_data.get('level') == 'Nivel I':
            teams_n1_list.append(team_entry)
        elif team_data.get('level') == 'Nivel II':
            teams_n2_list.append(team_entry)

    return render_template('manage_teams.html', teams_n1=teams_n1_list, teams_n2=teams_n2_list)


@app.route('/delete-team/<team_id>', methods=['POST'])
@login_required
def delete_team(team_id):
    try:
        teams_collection.document(team_id).delete()
        flash("Equipo eliminado exitosamente.", "success")
    except Exception as e:
        flash(f"Error al eliminar el equipo: {e}", "error")
    return redirect(url_for('manage_teams'))


@app.route('/update-team-name/<team_id>', methods=['POST'])
@login_required
def update_team_name(team_id):
    new_name = request.form.get('new_name')
    if new_name:
        try:
            teams_collection.document(team_id).update({'name': new_name})
            flash("Nombre del equipo actualizado.", "success")
        except Exception as e:
            flash(f"Error al actualizar el nombre: {e}", "error")
    else:
        flash("El nuevo nombre no puede estar vacío.", "error")
    return redirect(url_for('manage_teams'))


@app.route('/setup-teams')
@login_required
def setup_teams():
    # Lista de colegios (basada en la foto de Excel)
    colegios = {
        "Nivel I": [
            "COLEGIO TECNICA INDUSTRIAL CARLOS SARMIENTO LORA", "COLEGIO TECNICA OCCIDENTE", "COLEGIO MARIA ANTONIA RUIZ",
            "COLEGIO MODERNA DE TULUA", "COLEGIO ALFONSO LOPEZ PUMAREJO", "COLEGIO CORAZON DEL VALLE",
            "COLEGIO GIMNASIO DEL PACIFICO", "COLEGIO JUAN MARIA CESPEDES", "COLEGIO AGUACLARA", "COLEGIO JULIA RESTREPO",
            "COLEGIO TECNICA SAN JUAN DE BARRAGAN", "COLEGIO JULIO CESAR ZULUAGA", "COLEGIO MONTELORO", "COLEGIO SAN RAFAEL",
            "COLEGIO TECNICA LA MARINA", "COLEGIO JOVITA SANTACOLOMA",
            "COLEGIO CAMPESTRE SAN JUAN DE LA LOMA", "COLEGIO NAZARETH", "COLEGIO SALESIANOS SAN JUAN BOSCO"
        ],
        "Nivel II": [
            "COLEGIO TECNICA INDUSTRIAL CARLOS SARMIENTO LORA", "COLEGIO TECNICA OCCIDENTE", "COLEGIO MARIA ANTONIA RUIZ",
            "COLEGIO MODERNA DE TULUA", "COLEGIO ALFONSO LOPEZ PUMAREJO", "COLEGIO CORAZON DEL VALLE",
            "COLEGIO GIMNASIO DEL PACIFICO", "COLEGIO JUAN MARIA CESPEDES", "COLEGIO AGUACLARA", "COLEGIO JULIA RESTREPO",
            "COLEGIO TECNICA SAN JUAN DE BARRAGAN", "COLEGIO ALTO DEL ROCIO", "COLEGIO JULIO CESAR ZULUAGA", "COLEGIO MONTELORO",
            "COLEGIO SAN RAFAEL", "COLEGIO TECNICA LA MARINA", "COLEGIO JOVITA SANTACOLOMA", "COLEGIO LA MORALIA",
            "COLEGIO CAMPESTRE SAN JUAN DE LA LOMA", "COLEGIO NAZARETH", "COLEGIO SALESIANOS SAN JUAN BOSCO"
        ]
    }

    try:
        batch = db.batch()

        # Borrar equipos existentes para evitar duplicados
        docs = teams_collection.stream()
        for doc in docs:
            batch.delete(doc.reference)

        # Crear equipos Nivel I
        for colegio in colegios["Nivel I"]:
            team_name = f"{colegio} (Nivel I)"
            team_ref = teams_collection.document()
            batch.set(team_ref, {'name': team_name,
                      'score': 0, 'level': 'Nivel I'})

        # Crear equipos Nivel II
        for colegio in colegios["Nivel II"]:
            team_name = f"{colegio} (Nivel II)"
            team_ref = teams_collection.document()
            batch.set(team_ref, {'name': team_name,
                      'score': 0, 'level': 'Nivel II'})

        batch.commit()
        flash("¡Éxito! Todos los colegios han sido registrados en la base de datos.", "success")
    except Exception as e:
        flash(f"Error al poblar los equipos: {e}", "error")

    return redirect(url_for('dashboard'))


# --- GESTIÓN DE PUNTUACIONES ---

@app.route('/scoreboard')
@login_required
def show_scoreboard():
    teams_ref = teams_collection.stream()
    scores_n1_list = []
    scores_n2_list = []

    print("--- Cargando Scoreboard ---")  # DEBUG
    count = 0  # DEBUG
    for doc in teams_ref:
        count += 1  # DEBUG
        team_data = doc.to_dict()
        print(f"Documento {doc.id}: {team_data}")  # DEBUG
        if team_data.get('name'):
            score_entry = {'name': team_data.get(
                'name'), 'score': team_data.get('score', 0)}
            if team_data.get('level') == 'Nivel I':
                print(f"  -> Añadiendo a Nivel I: {score_entry}")  # DEBUG
                scores_n1_list.append(score_entry)
            elif team_data.get('level') == 'Nivel II':
                print(f"  -> Añadiendo a Nivel II: {score_entry}")  # DEBUG
                scores_n2_list.append(score_entry)
            else:
                # DEBUG
                print(f"  -> Nivel no reconocido: {team_data.get('level')}")
        else:
            print(f"  -> Equipo sin nombre: {doc.id}")  # DEBUG

    print(f"Total documentos leídos: {count}")  # DEBUG
    scores_n1_list.sort(key=lambda x: x.get('score', 0), reverse=True)
    scores_n2_list.sort(key=lambda x: x.get('score', 0), reverse=True)

    print(f"Lista Nivel I final: {scores_n1_list}")  # DEBUG
    print(f"Lista Nivel II final: {scores_n2_list}")  # DEBUG
    print("--- Fin Carga Scoreboard ---")  # DEBUG

    return render_template('scoreboard.html', scores_n1=scores_n1_list, scores_n2=scores_n2_list)


@app.route('/reset-points', methods=['POST'])
@login_required
def reset_points():
    try:
        batch = db.batch()
        teams_ref = teams_collection.stream()
        for doc in teams_ref:
            batch.update(doc.reference, {'score': 0})
        batch.commit()
        flash("Puntajes de todos los equipos reiniciados a 0.", "success")
    except Exception as e:
        flash(f"Error al reiniciar los puntajes: {e}", "error")
    return redirect(url_for('show_scoreboard'))


# --- RUTAS DEL QUIZ ---

@app.route('/select-level', methods=['GET', 'POST'])
@login_required
def select_level():
    session.pop('quiz_pool', None)
    session.pop('current_question_index', None)
    session.pop('quiz_scores', None)
    session.pop('current_question', None)
    session.pop('quiz_level', None)
    session.pop('quiz_teams', None)

    # Cargar equipos (método robusto sin índices)
    teams_ref = teams_collection.stream()
    teams_n1_list = []
    teams_n2_list = []
    for doc in teams_ref:
        team_data = doc.to_dict()
        if team_data.get('level') == 'Nivel I':
            teams_n1_list.append(team_data.get('name'))
        elif team_data.get('level') == 'Nivel II':
            teams_n2_list.append(team_data.get('name'))

    if not teams_n1_list and not teams_n2_list:
        flash("No hay equipos creados. Ve al Dashboard y ejecuta el 'Setup de Equipos'.", "error")
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        team1 = request.form.get('team1')
        team2 = request.form.get('team2')
        level = request.form.get('level')  # "Nivel I", "Nivel II", "Nivel III"

        if not team1 or not team2 or not level:
            flash("Faltó seleccionar equipos o el nivel.", "error")
            return redirect(url_for('select_level'))

        if team1 == team2:
            flash("¡Error! No puedes seleccionar el mismo equipo dos veces.", "error")
            return redirect(url_for('select_level'))

        session['quiz_level'] = level
        session['quiz_teams'] = [team1, team2]
        return redirect(url_for('start_quiz'))

    return render_template('select_level.html', teams_n1=teams_n1_list, teams_n2=teams_n2_list)


@app.route('/start-quiz')
@login_required
def start_quiz():
    level = session.get('quiz_level')  # "Nivel I", "Nivel II", etc.
    if not level:
        flash("No se ha seleccionado ningún nivel.", "error")
        return redirect(url_for('select_level'))

    # Mapear el nombre amigable ("Nivel I") al nombre de la BD ("nivel1")
    level_map = {
        "Nivel I": "nivel1",
        "Nivel II": "nivel2",
        "Nivel III": "nivel3"
    }
    firestore_level = level_map.get(level)  # ej: 'nivel1'

    if not firestore_level:
        flash("Nivel no válido seleccionado.", "error")
        return redirect(url_for('select_level'))

    # 1. Obtener TODOS los IDs de las preguntas del nivel (1 viaje ligero)
    quiz_ids_docs = questions_collection.where(
        'level', '==', firestore_level).select([]).stream()
    all_question_ids = [doc.id for doc in quiz_ids_docs]

    if len(all_question_ids) < 3:
        flash(
            f"No hay suficientes preguntas para el {level}. Se necesitan al menos 3.", "error")
        return redirect(url_for('select_level'))

    # 2. Seleccionar 10 IDs (o el total disponible) al azar (rápido, en memoria)
    questions_to_pick = min(len(all_question_ids), 10)
    random_selected_ids = random.sample(all_question_ids, questions_to_pick)

    # 3. Cargar los datos completos de los 10 IDs en UN solo viaje (MUCHO MÁS RÁPIDO)
    quiz_pool_docs = []
    if random_selected_ids:  # Asegurarse de que la lista no esté vacía
        quiz_pool_docs = questions_collection.where(
            '__name__', 'in', random_selected_ids  # <--- ¡ARREGLADO! Usando __name__
        ).stream()

    quiz_pool = [{'id': doc.id, **doc.to_dict()} for doc in quiz_pool_docs]

    # 4. Barajar el pool final (porque 'in' no garantiza orden)
    random.shuffle(quiz_pool)

    session['quiz_pool'] = quiz_pool
    session['current_question_index'] = 0

    # Inicializa los puntajes del quiz con los equipos seleccionados
    selected_teams = session.get('quiz_teams', [])
    session['quiz_scores'] = {team: 0 for team in selected_teams}

    return redirect(url_for('countdown'))


@app.route('/countdown')
@login_required
def countdown():
    teams = session.get('quiz_teams', ['Equipo 1', 'Equipo 2'])
    return render_template('countdown.html', teams=teams)


@app.route('/quiz-question')
@login_required
def quiz_question():
    if 'quiz_pool' not in session or 'current_question_index' not in session:
        return redirect(url_for('select_level'))

    index = session.get('current_question_index', 0)
    quiz_pool = session.get('quiz_pool', [])

    # Lógica de fin del quiz
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
    teams_in_quiz = session.get('quiz_scores', {})

    if is_correct:
        # Pasa a la pantalla de asignar 1 o 2 puntos
        return render_template('assign_point.html', teams=teams_in_quiz)
    else:
        # Si es incorrecta, simplemente avanza a la siguiente pregunta
        session['current_question_index'] = session.get(
            'current_question_index', 0) + 1
        return redirect(url_for('quiz_question'))


@app.route('/assign-point-to-team', methods=['POST'])
@login_required
def assign_point_to_team():
    team = request.form.get('team')
    points_str = request.form.get('points')  # '1' o '2'

    try:
        points_to_add = int(points_str)
        if points_to_add not in [1, 2]:
            raise ValueError("Puntaje inválido")
    except (ValueError, TypeError):
        points_to_add = 0  # No sumar nada si hay un error
        flash("Error al procesar los puntos.", "error")

    # Asignar punto en la sesión
    if team in session['quiz_scores']:
        session['quiz_scores'][team] += points_to_add
        session.modified = True

        # Incrementar punto en Firestore (para el scoreboard general)
        docs = teams_collection.where('name', '==', team).stream()
        for doc in docs:
            teams_collection.document(doc.id).update(
                {'score': Increment(points_to_add)})
            break

    # Avanzar a la siguiente pregunta
    session['current_question_index'] = session.get(
        'current_question_index', 0) + 1

    return redirect(url_for('quiz_question'))


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

    # Lógica de ganador
    message = "¡Ha habido un empate!"
    winner = "Empate"  # Default
    if scores:
        max_score = -1
        # Manejar el caso de que todos tengan 0
        if any(s > 0 for s in scores.values()):
            max_score = max(scores.values())

        winners = [team for team, score in scores.items() if score ==
                   max_score]

        if len(winners) == 1 and max_score > 0:
            winner = winners[0]
            message = f"¡El equipo {winner} ha ganado esta ronda!"
        elif len(winners) > 1:
            message = "¡Ha habido un empate!"
        else:
            message = "¡Ronda finalizada sin puntos!"

    return render_template('quiz_finished.html', scores=scores, message=message, winner=winner)


# --- GESTIÓN DE BRACKETS (FINALES) ---

@app.route('/brackets')
@login_required
def brackets():
    try:
        bracket_n1_doc = brackets_collection.document('nivel1').get()
        bracket_n2_doc = brackets_collection.document('nivel2').get()

        bracket_n1 = bracket_n1_doc.to_dict() if bracket_n1_doc.exists else None
        bracket_n2 = bracket_n2_doc.to_dict() if bracket_n2_doc.exists else None

        return render_template('brackets.html', bracket_n1=bracket_n1, bracket_n2=bracket_n2)
    except Exception as e:
        print(f"Error al cargar brackets: {e}")
        flash("Error al cargar los datos desde Firestore.", "error")
        return render_template('brackets.html', bracket_n1=None, bracket_n2=None, error=True)


@app.route('/manage-brackets', methods=['GET', 'POST'])
@login_required
def manage_brackets():
    if request.method == 'POST':
        try:
            level = request.form.get('level')  # 'nivel1' o 'nivel2'

            # Recoger los 6 equipos del formulario
            teams_list = [
                request.form.get(f'{level}_team_1'), request.form.get(
                    f'{level}_team_2'),
                request.form.get(f'{level}_team_3'), request.form.get(
                    f'{level}_team_4'),
                request.form.get(f'{level}_team_5'), request.form.get(
                    f'{level}_team_6')
            ]

            # Validar que no haya equipos duplicados
            if len(teams_list) != len(set(teams_list)):
                flash("Error: No puedes seleccionar el mismo equipo dos veces.", "error")
                return redirect(url_for('manage_brackets'))

            # Estructura del bracket de 6 equipos
            # Ronda 1 (Cuartos): 2 partidos
            # Ronda 2 (Semis): 2 partidos
            # Ronda 3 (Final): 1 partido

            bracket_data = {
                'category': f"Nivel { 'I' if level == 'nivel1' else 'II' }",
                'rounds': [
                    {  # Ronda 1: Cuartos de Final
                        "name": "Cuartos de Final",
                        "matches": [
                            {"match_id": "qf_1",
                                "team1": teams_list[2], "team2": teams_list[3], "winner": None},
                            {"match_id": "qf_2",
                                "team1": teams_list[4], "team2": teams_list[5], "winner": None}
                        ]
                    },
                    {  # Ronda 2: Semifinales
                        "name": "Semifinales",
                        "matches": [
                            # Preclasificado 1
                            {"match_id": "sf_1",
                                "team1": teams_list[0], "team2": "Ganador QF 1", "winner": None},
                            # Preclasificado 2
                            {"match_id": "sf_2",
                                "team1": teams_list[1], "team2": "Ganador QF 2", "winner": None}
                        ]
                    },
                    {  # Ronda 3: Final
                        "name": "Final",
                        "matches": [
                            {"match_id": "f_1", "team1": "Ganador SF 1",
                                "team2": "Ganador SF 2", "winner": None}
                        ]
                    }
                ]
            }

            brackets_collection.document(level).set(bracket_data)
            flash(
                f"Bracket para {level} generado/actualizado exitosamente.", "success")
            return redirect(url_for('brackets'))

        except Exception as e:
            flash(f"Error al generar el bracket: {e}", "error")
            return redirect(url_for('manage_brackets'))

    # Método GET (Cargar la página)
    # Cargar equipos (método robusto sin índices)
    teams_ref = teams_collection.stream()
    teams_n1_list = []
    teams_n2_list = []
    for doc in teams_ref:
        team_data = doc.to_dict()
        if team_data.get('level') == 'Nivel I':
            teams_n1_list.append(team_data.get('name'))
        elif team_data.get('level') == 'Nivel II':
            teams_n2_list.append(team_data.get('name'))

    return render_template('manage_brackets.html', teams_n1=teams_n1_list, teams_n2=teams_n2_list)


@app.route('/advance-winner', methods=['POST'])
@login_required
def advance_winner():
    try:
        level = request.form.get('level')  # 'nivel1' o 'nivel2'
        round_index = int(request.form.get('round_index'))
        match_index = int(request.form.get('match_index'))
        winner_name = request.form.get('winner')

        # 1. Obtener el bracket actual
        bracket_ref = brackets_collection.document(level)
        bracket_doc = bracket_ref.get()
        if not bracket_doc.exists:
            raise Exception("El bracket no existe.")

        bracket_data = bracket_doc.to_dict()

        # 2. Actualizar el ganador del partido actual
        bracket_data['rounds'][round_index]['matches'][match_index]['winner'] = winner_name

        # 3. Lógica para avanzar al ganador a la siguiente ronda

        current_match_id = bracket_data['rounds'][round_index]['matches'][match_index]['match_id']

        # --- Avanzar de Cuartos a Semis ---
        if current_match_id == 'qf_1':
            # Poner al ganador en el team2 de la semi 1
            bracket_data['rounds'][1]['matches'][0]['team2'] = winner_name
        elif current_match_id == 'qf_2':
            # Poner al ganador en el team2 de la semi 2
            bracket_data['rounds'][1]['matches'][1]['team2'] = winner_name

        # --- Avanzar de Semis a Final ---
        elif current_match_id == 'sf_1':
            # Poner al ganador en el team1 de la final
            bracket_data['rounds'][2]['matches'][0]['team1'] = winner_name
        elif current_match_id == 'sf_2':
            # Poner al ganador en el team2 de la final
            bracket_data['rounds'][2]['matches'][0]['team2'] = winner_name

        # 4. Guardar los datos actualizados
        bracket_ref.set(bracket_data)
        flash(f"Ganador '{winner_name}' avanzado en el bracket.", "success")

    except Exception as e:
        print(f"Error al avanzar ganador: {e}")
        flash(f"Error al procesar el ganador: {e}", "error")

    return redirect(url_for('brackets'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
