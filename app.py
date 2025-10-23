from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, get_flashed_messages
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import random
import os
import json
# Import only necessary components
from google.cloud.firestore_v1 import Increment
# from google.cloud.firestore import FieldPath # No longer needed
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
    else:
        flash("Error: La pregunta que intentas eliminar no existe.", "error")
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
        if team_data:  # Asegurarse de que el documento no esté vacío
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
    if new_name and new_name.strip():  # Validar que no esté vacío o solo espacios
        try:
            teams_collection.document(team_id).update(
                {'name': new_name.strip()})
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
            team_ref = teams_collection.document()  # Genera ID automático
            batch.set(team_ref, {'name': team_name,
                      'score': 0, 'level': 'Nivel I'})

        # Crear equipos Nivel II
        for colegio in colegios["Nivel II"]:
            team_name = f"{colegio} (Nivel II)"
            team_ref = teams_collection.document()  # Genera ID automático
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
    # print("--- Cargando Scoreboard ---") # DEBUG - REMOVIDO
    scores_n1 = []
    scores_n2 = []

    try:
        teams_ref = teams_collection.stream()
        for doc in teams_ref:
            team_data = doc.to_dict()
            # print(f"Leyendo equipo: {team_data}") # DEBUG - REMOVIDO
            if team_data:
                # Añadir ID para posible uso futuro, asegurarse que name existe
                team_entry = {'id': doc.id, 'name': team_data.get(
                    'name', 'Nombre Desconocido'), 'score': team_data.get('score', 0)}
                if team_data.get('level') == 'Nivel I':
                    scores_n1.append(team_entry)
                elif team_data.get('level') == 'Nivel II':
                    scores_n2.append(team_entry)
            # else: # No imprimir si el doc está vacío, es normal si se borró mal
                # print(f"Documento vacío encontrado con ID: {doc.id}") # DEBUG - REMOVIDO

        # Ordenar en Python
        scores_n1.sort(key=lambda x: x.get('score', 0), reverse=True)
        scores_n2.sort(key=lambda x: x.get('score', 0), reverse=True)

        # print(f"Equipos Nivel I ordenados: {scores_n1}") # DEBUG - REMOVIDO
        # print(f"Equipos Nivel II ordenados: {scores_n2}") # DEBUG - REMOVIDO

    except Exception as e:
        print(f"Error al cargar equipos para scoreboard: {e}")
        flash("Error al cargar las puntuaciones.", "error")
        # Devolver listas vacías en caso de error para que la plantilla no falle
        scores_n1 = []
        scores_n2 = []

    # print("--- Fin Carga Scoreboard ---") # DEBUG - REMOVIDO
    return render_template('scoreboard.html', scores_n1=scores_n1, scores_n2=scores_n2)


@app.route('/reset-points', methods=['POST'])
@login_required
def reset_points():
    try:
        batch = db.batch()
        teams_ref = teams_collection.stream()
        count = 0
        for doc in teams_ref:
            batch.update(doc.reference, {'score': 0})
            count += 1

        if count > 0:
            batch.commit()
            flash("Puntajes de todos los equipos reiniciados a 0.", "success")
        else:
            flash("No se encontraron equipos para reiniciar puntos.", "warning")

    except Exception as e:
        flash(f"Error al reiniciar los puntajes: {e}", "error")
    return redirect(url_for('show_scoreboard'))


# --- RUTAS DEL QUIZ ---

@app.route('/select-level', methods=['GET', 'POST'])
@login_required
def select_level():
    # --- Limpieza Forzada de Sesión ---
    keys_to_clear = ['quiz_pool', 'current_question_index',
                     'quiz_scores', 'current_question', 'quiz_level', 'quiz_teams']
    for key in keys_to_clear:
        session.pop(key, None)
    # ----------------------------------

    # Cargar equipos (método robusto sin índices)
    teams_ref = teams_collection.stream()
    teams_n1_list = []
    teams_n2_list = []
    for doc in teams_ref:
        team_data = doc.to_dict()
        if team_data:  # Asegurarse que el doc no está vacío
            team_name = team_data.get('name')
            if team_name:  # Asegurarse que el nombre existe
                if team_data.get('level') == 'Nivel I':
                    teams_n1_list.append(team_name)
                elif team_data.get('level') == 'Nivel II':
                    teams_n2_list.append(team_name)

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

    # Ordenar alfabéticamente para desplegables
    teams_n1_list.sort()
    teams_n2_list.sort()
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

    try:
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
        random_selected_ids = random.sample(
            all_question_ids, questions_to_pick)

        # 3. Cargar los datos completos de los 10 IDs en UN solo viaje (MUCHO MÁS RÁPIDO)
        quiz_pool_docs = []
        if random_selected_ids:  # Asegurarse de que la lista no esté vacía
            # Usar __name__ en lugar de FieldPath para compatibilidad
            quiz_pool_docs = questions_collection.where(
                '__name__', 'in', random_selected_ids
            ).stream()

        # Verificar existencia y contenido
        quiz_pool = [{'id': doc.id, **doc.to_dict()}
                     for doc in quiz_pool_docs if doc.exists and doc.to_dict()]

        # Verificar si se cargaron preguntas
        if not quiz_pool:
            flash(
                f"Error: No se pudieron cargar los detalles de las preguntas seleccionadas para {level}.", "error")
            return redirect(url_for('select_level'))

        # 4. Barajar el pool final (porque 'in' no garantiza orden)
        random.shuffle(quiz_pool)

        session['quiz_pool'] = quiz_pool
        session['current_question_index'] = 0

        # Inicializa los puntajes del quiz con los equipos seleccionados
        selected_teams = session.get('quiz_teams', [])
        session['quiz_scores'] = {team: 0 for team in selected_teams}

        return redirect(url_for('countdown'))

    except Exception as e:
        print(f"Error detallado en start_quiz: {e}")
        flash(f"Ocurrió un error inesperado al iniciar el quiz: {e}", "error")
        return redirect(url_for('select_level'))


@app.route('/countdown')
@login_required
def countdown():
    teams = session.get('quiz_teams', ['Equipo 1', 'Equipo 2'])
    return render_template('countdown.html', teams=teams)


@app.route('/quiz-question')
@login_required
def quiz_question():
    if 'quiz_pool' not in session or 'current_question_index' not in session:
        flash("La sesión del quiz no es válida o ha expirado.", "error")
        return redirect(url_for('select_level'))

    index = session.get('current_question_index', 0)
    quiz_pool = session.get('quiz_pool', [])

    # Lógica de fin del quiz
    if not quiz_pool or index >= len(quiz_pool):
        return redirect(url_for('quiz_finished'))

    # --- Verificación Extra ---
    if index < 0 or index >= len(quiz_pool) or \
       not isinstance(quiz_pool[index], dict) or 'question_image' not in quiz_pool[index]:
        flash(
            f"Error: La pregunta {index+1} cargada desde la sesión no es válida. Reiniciando selección.", "error")
        # Limpiar sesión por si acaso
        keys_to_clear = ['quiz_pool', 'current_question_index',
                         'quiz_scores', 'current_question', 'quiz_level', 'quiz_teams']
        for key in keys_to_clear:
            session.pop(key, None)
        return redirect(url_for('select_level'))
    # --------------------------

    question = quiz_pool[index]
    session['current_question'] = question

    return render_template('quiz.html', question=question, question_number=index + 1)


@app.route('/submit-answer', methods=['POST'])
@login_required
def submit_answer():
    user_answer = request.form.get('answer')
    question = session.get('current_question')
    if not question:
        flash("No hay una pregunta activa en la sesión.", "error")
        return redirect(url_for('select_level'))

    is_correct = user_answer == question.get('correct')
    # Obtener solo los nombres
    teams_in_quiz = list(session.get('quiz_scores', {}).keys())

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

    # Validar si los equipos existen en la sesión
    if 'quiz_scores' not in session or team not in session['quiz_scores']:
        flash("Error: El equipo seleccionado no es válido para esta ronda.", "error")
        return redirect(url_for('select_level'))  # Redirigir a un lugar seguro

    try:
        points_to_add = int(points_str)
        if points_to_add not in [1, 2]:
            raise ValueError("Puntaje inválido")
    except (ValueError, TypeError):
        points_to_add = 0  # No sumar nada si hay un error
        flash("Error al procesar los puntos. Se asignaron 0 puntos.", "error")

    # Asignar punto en la sesión
    session['quiz_scores'][team] += points_to_add
    session.modified = True

    # Incrementar punto en Firestore (para el scoreboard general)
    try:
        docs = teams_collection.where('name', '==', team).limit(1).stream()
        team_doc_ref = next(docs, None)  # Obtener la referencia al documento
        if team_doc_ref:
            teams_collection.document(team_doc_ref.id).update(
                {'score': Increment(points_to_add)})
        else:
            print(
                f"Advertencia: No se encontró el equipo '{team}' en Firestore para actualizar score general.")

    except Exception as e:
        print(f"Error al actualizar score en Firestore para '{team}': {e}")
        # No mostrar flash al usuario por errores internos del scoreboard

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
        # Manejar el caso de que todos tengan 0 o puntajes negativos
        valid_scores = [
            s for s in scores.values() if isinstance(s, (int, float))]
        if valid_scores:
            max_score = max(valid_scores) if max(valid_scores) > 0 else 0
        else:
            max_score = 0

        winners = [team for team, score in scores.items() if score ==
                   max_score]

        if len(winners) == 1 and max_score > 0:
            winner = winners[0]
            message = f"¡El equipo {winner} ha ganado esta ronda!"
        elif max_score == 0 and len(scores) > 0:
            message = "¡Ronda finalizada sin puntos!"
        elif len(winners) > 1:
            message = "¡Ha habido un empate!"

    return render_template('quiz_finished.html', scores=scores, message=message, winner=winner)


# --- GESTIÓN DE BRACKETS (FINALES - 8 EQUIPOS) ---

@app.route('/brackets')
@login_required
def brackets():
    bracket_n1 = None
    bracket_n2 = None
    error_flag = False
    try:
        bracket_n1_doc = brackets_collection.document('nivel1').get()
        bracket_n2_doc = brackets_collection.document('nivel2').get()

        if bracket_n1_doc.exists:
            bracket_n1 = bracket_n1_doc.to_dict()
        if bracket_n2_doc.exists:
            bracket_n2 = bracket_n2_doc.to_dict()

    except Exception as e:
        # --- MEJOR LOG DE ERROR ---
        print(f"Error detallado al cargar brackets: {e}", flush=True)
        flash("Error al cargar los datos desde Firestore.", "error")
        error_flag = True  # Pasa la bandera de error a la plantilla

    return render_template('brackets.html', bracket_n1=bracket_n1, bracket_n2=bracket_n2, error=error_flag)


@app.route('/manage-brackets', methods=['GET', 'POST'])
@login_required
def manage_brackets():
    if request.method == 'POST':
        try:
            level = request.form.get('level')  # 'nivel1' o 'nivel2'

            # Recoger los 8 equipos del formulario
            teams_list = [request.form.get(
                f'{level}_team_{i+1}') for i in range(8)]

            # Validar que se seleccionaron 8 equipos y no hay vacíos
            if not all(teams_list):
                flash(
                    "Error: Debes seleccionar los 8 equipos para generar el bracket.", "error")
                return redirect(url_for('manage_brackets'))

            # Validar que no haya equipos duplicados
            if len(teams_list) != len(set(teams_list)):
                flash("Error: No puedes seleccionar el mismo equipo dos veces.", "error")
                return redirect(url_for('manage_brackets'))

            # Mezclar aleatoriamente para los enfrentamientos iniciales
            random.shuffle(teams_list)

            # Estructura del bracket de 8 equipos (Cuartos, Semis, Final)
            bracket_data = {
                'category': f"Nivel { 'I' if level == 'nivel1' else 'II' } Final",
                'rounds': [
                    {  # Ronda 1: Cuartos de Final (4 partidos)
                        "name": "Cuartos de Final",
                        "matches": [
                            {"match_id": "qf_1",
                                "team1": teams_list[0], "team2": teams_list[1], "winner": None},
                            {"match_id": "qf_2",
                                "team1": teams_list[2], "team2": teams_list[3], "winner": None},
                            {"match_id": "qf_3",
                                "team1": teams_list[4], "team2": teams_list[5], "winner": None},
                            {"match_id": "qf_4",
                                "team1": teams_list[6], "team2": teams_list[7], "winner": None}
                        ]
                    },
                    {  # Ronda 2: Semifinales (2 partidos)
                        "name": "Semifinales",
                        "matches": [
                            {"match_id": "sf_1", "team1": "Ganador QF 1",
                                "team2": "Ganador QF 2", "winner": None},
                            {"match_id": "sf_2", "team1": "Ganador QF 3",
                                "team2": "Ganador QF 4", "winner": None}
                        ]
                    },
                    {  # Ronda 3: Final (1 partido)
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
                f"Bracket de 8 equipos para {level} generado/actualizado exitosamente.", "success")
            # Redirigir a ver los brackets
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
        if team_data:  # Asegurarse que el doc no está vacío
            team_name = team_data.get('name')
            if team_name:  # Asegurarse que el nombre existe
                if team_data.get('level') == 'Nivel I':
                    teams_n1_list.append(team_name)
                elif team_data.get('level') == 'Nivel II':
                    teams_n2_list.append(team_name)

    # Ordenar alfabéticamente para los desplegables
    teams_n1_list.sort()
    teams_n2_list.sort()

    return render_template('manage_brackets.html', teams_n1=teams_n1_list, teams_n2=teams_n2_list)


@app.route('/advance-winner', methods=['POST'])
@login_required
def advance_winner():
    try:
        level = request.form.get('level')  # 'nivel1' o 'nivel2'
        round_index = int(request.form.get('round_index'))
        match_index = int(request.form.get('match_index'))
        winner_name = request.form.get('winner')

        # Validar entrada
        if not level or round_index is None or match_index is None or not winner_name:
            raise ValueError("Faltan datos para avanzar al ganador.")

        # 1. Obtener el bracket actual
        bracket_ref = brackets_collection.document(level)
        bracket_doc = bracket_ref.get()
        if not bracket_doc.exists:
            raise Exception("El bracket no existe.")

        bracket_data = bracket_doc.to_dict()

        # --- Validación extra: Asegurar que los índices son válidos ---
        if not isinstance(bracket_data.get('rounds'), list) or \
           round_index >= len(bracket_data['rounds']) or \
           not isinstance(bracket_data['rounds'][round_index].get('matches'), list) or \
           match_index >= len(bracket_data['rounds'][round_index]['matches']):
            raise IndexError(
                "Índice de ronda o partido fuera de rango o estructura de datos inválida.")
        # -----------------------------------------------------------

        # 2. Actualizar el ganador del partido actual
        current_match = bracket_data['rounds'][round_index]['matches'][match_index]

        # --- Validación: Asegurar que el ganador sea uno de los participantes ---
        if winner_name != current_match.get('team1') and winner_name != current_match.get('team2'):
            # Evitar asignar si los equipos aún son placeholders como "Ganador QF 1"
            if not str(current_match.get('team1')).startswith("Ganador") and \
               not str(current_match.get('team2')).startswith("Ganador"):
                raise ValueError(
                    f"El ganador '{winner_name}' no es uno de los participantes ({current_match.get('team1')} vs {current_match.get('team2')}).")
            # Permitir si los equipos aún no están definidos (placeholders) - esto no debería ocurrir con el select
            elif str(current_match.get('team1')).startswith("Ganador") or \
                    str(current_match.get('team2')).startswith("Ganador"):
                print(
                    f"Advertencia: Intentando asignar ganador '{winner_name}' a un partido con placeholders.")
                # No hacer nada si los equipos no están definidos aún
                flash(
                    "Espera a que los equipos de esta ronda estén definidos.", "warning")
                return redirect(url_for('brackets'))

        current_match['winner'] = winner_name

        # 3. Lógica para avanzar al ganador a la siguiente ronda (8 EQUIPOS)
        current_match_id = current_match.get('match_id')

        # --- Avanzar de Cuartos (índice 0) a Semis (índice 1) ---
        if round_index == 0:  # Si estamos en Cuartos
            next_round_index = 1
            if next_round_index < len(bracket_data['rounds']) and isinstance(bracket_data['rounds'][next_round_index].get('matches'), list):
                if current_match_id == 'qf_1':  # Ganador QF 1 va a SF 1, Team 1
                    if len(bracket_data['rounds'][next_round_index]['matches']) > 0:
                        bracket_data['rounds'][next_round_index]['matches'][0]['team1'] = winner_name
                elif current_match_id == 'qf_2':  # Ganador QF 2 va a SF 1, Team 2
                    if len(bracket_data['rounds'][next_round_index]['matches']) > 0:
                        bracket_data['rounds'][next_round_index]['matches'][0]['team2'] = winner_name
                elif current_match_id == 'qf_3':  # Ganador QF 3 va a SF 2, Team 1
                    if len(bracket_data['rounds'][next_round_index]['matches']) > 1:
                        bracket_data['rounds'][next_round_index]['matches'][1]['team1'] = winner_name
                elif current_match_id == 'qf_4':  # Ganador QF 4 va a SF 2, Team 2
                    if len(bracket_data['rounds'][next_round_index]['matches']) > 1:
                        bracket_data['rounds'][next_round_index]['matches'][1]['team2'] = winner_name

        # --- Avanzar de Semis (índice 1) a Final (índice 2) ---
        elif round_index == 1:  # Si estamos en Semis
            next_round_index = 2
            if next_round_index < len(bracket_data['rounds']) and \
               isinstance(bracket_data['rounds'][next_round_index].get('matches'), list) and \
               len(bracket_data['rounds'][next_round_index]['matches']) > 0:
                if current_match_id == 'sf_1':  # Ganador SF 1 va a Final, Team 1
                    bracket_data['rounds'][next_round_index]['matches'][0]['team1'] = winner_name
                elif current_match_id == 'sf_2':  # Ganador SF 2 va a Final, Team 2
                    bracket_data['rounds'][next_round_index]['matches'][0]['team2'] = winner_name

        # 4. Guardar los datos actualizados
        bracket_ref.set(bracket_data)
        flash(f"Ganador '{winner_name}' avanzado en el bracket.", "success")

    except (ValueError, IndexError, Exception) as e:
        # Imprime el error completo en la consola para depuración
        import traceback
        print(f"Error detallado al avanzar ganador: {traceback.format_exc()}")
        flash(f"Error al procesar el ganador: {e}", "error")

    return redirect(url_for('brackets'))


if __name__ == '__main__':
    # Cambia debug=False para producción si usas un servidor WSGI como Gunicorn/Waitress
    # Para Render, ellos manejan el servidor de producción, así que debug=True está bien para desarrollo local.
    # Render define esta variable
    is_production = os.environ.get('RENDER', False)
    app.run(host='0.0.0.0', port=int(os.environ.get(
        'PORT', 5000)), debug=not is_production)
