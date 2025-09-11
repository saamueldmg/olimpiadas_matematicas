from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func  # Importamos func
import os

# Configuración de la aplicación Flask
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configuración de la base de datos SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Modelos de la Base de Datos ---

# Modelo para los equipos


class Equipo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    puntaje = db.Column(db.Integer, default=0)

# Modelo para las preguntas


class Pregunta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    texto = db.Column(db.String(500), nullable=False)
    opcion_a = db.Column(db.String(200), nullable=False)
    opcion_b = db.Column(db.String(200), nullable=False)
    opcion_c = db.Column(db.String(200), nullable=False)
    opcion_d = db.Column(db.String(200), nullable=False)
    respuesta_correcta = db.Column(db.String(1), nullable=False)


# --- Creación inicial de la base de datos ---
# ESTE ES EL CAMBIO: Movemos la creación de la BD aquí
with app.app_context():
    db.create_all()

# --- Rutas de la Aplicación ---

# Ruta principal para registrar equipos


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Limpiar la base de datos de equipos anteriores
        Equipo.query.delete()
        db.session.commit()

        # Crear y guardar los nuevos equipos
        equipo1 = Equipo(nombre=request.form['equipo1'])
        equipo2 = Equipo(nombre=request.form['equipo2'])
        db.session.add(equipo1)
        db.session.add(equipo2)
        db.session.commit()

        # Guardar nombres en la sesión para la cuenta regresiva
        session['teams'] = [equipo1.nombre, equipo2.nombre]

        # Limpiar datos de la sesión anterior
        session.pop('preguntas_ordenadas', None)
        session.pop('pregunta_actual_idx', None)
        session.pop('turno_equipo_id', None)

        return redirect(url_for('countdown'))

    return render_template('index.html')

# Ruta para la pantalla de cuenta regresiva


@app.route('/countdown')
def countdown():
    teams = session.get('teams', ['Equipo 1', 'Equipo 2'])
    return render_template('countdown.html', teams=teams)

# Ruta para mostrar las preguntas del quiz


@app.route('/quiz_question')
def quiz_question():
    # Si no hay un orden de preguntas en la sesión, créalo aleatoriamente
    if 'preguntas_ordenadas' not in session:
        # AQUÍ ESTÁ EL CAMBIO: Ordenamos las preguntas aleatoriamente
        preguntas = Pregunta.query.order_by(func.random()).all()
        session['preguntas_ordenadas'] = [p.id for p in preguntas]
        session['pregunta_actual_idx'] = 0

        # Decidir qué equipo empieza
        equipos = Equipo.query.all()
        if equipos:
            session['turno_equipo_id'] = equipos[0].id

    # Obtener el estado actual del juego desde la sesión
    preguntas_ids = session.get('preguntas_ordenadas', [])
    pregunta_idx = session.get('pregunta_actual_idx', 0)

    # Si se acabaron las preguntas, ir a la pantalla de resultados
    if pregunta_idx >= len(preguntas_ids):
        return redirect(url_for('results'))

    # Obtener la pregunta y equipos actuales
    pregunta_id = preguntas_ids[pregunta_idx]
    pregunta_actual = Pregunta.query.get(pregunta_id)
    equipos = Equipo.query.all()
    equipo_en_turno = Equipo.query.get(session.get('turno_equipo_id'))

    return render_template('quiz.html', pregunta=pregunta_actual, equipos=equipos, equipo_en_turno=equipo_en_turno)

# Ruta para procesar la respuesta de un equipo


@app.route('/submit_answer', methods=['POST'])
def submit_answer():
    pregunta_id = int(request.form['pregunta_id'])
    respuesta_usuario = request.form['respuesta']
    equipo_id = session.get('turno_equipo_id')

    pregunta = Pregunta.query.get(pregunta_id)
    equipo = Equipo.query.get(equipo_id)

    # Verificar si la respuesta es correcta y actualizar puntaje
    if pregunta and equipo and respuesta_usuario == pregunta.respuesta_correcta:
        equipo.puntaje += 10
        db.session.commit()

    # Pasar al siguiente turno
    session['pregunta_actual_idx'] += 1
    equipos = Equipo.query.all()

    # Cambiar el turno al otro equipo
    siguiente_equipo_id = equipos[1].id if equipo_id == equipos[0].id else equipos[0].id
    session['turno_equipo_id'] = siguiente_equipo_id

    return redirect(url_for('quiz_question'))

# Ruta para mostrar los resultados finales


@app.route('/results')
def results():
    equipos = Equipo.query.order_by(Equipo.puntaje.desc()).all()
    ganador = None
    if len(equipos) >= 2 and equipos[0].puntaje > equipos[1].puntaje:
        ganador = equipos[0]
    elif len(equipos) >= 2 and equipos[1].puntaje > equipos[0].puntaje:
        ganador = equipos[1]

    return render_template('results.html', equipos=equipos, ganador=ganador)

# --- Rutas para la gestión de preguntas ---

# Ruta para ver y agregar preguntas


@app.route('/admin_preguntas', methods=['GET', 'POST'])
def admin_preguntas():
    if request.method == 'POST':
        # Crear nueva pregunta desde el formulario
        nueva_pregunta = Pregunta(
            texto=request.form['texto'],
            opcion_a=request.form['opcion_a'],
            opcion_b=request.form['opcion_b'],
            opcion_c=request.form['opcion_c'],
            opcion_d=request.form['opcion_d'],
            respuesta_correcta=request.form['respuesta_correcta']
        )
        db.session.add(nueva_pregunta)
        db.session.commit()
        return redirect(url_for('admin_preguntas'))

    preguntas = Pregunta.query.all()
    return render_template('admin_preguntas.html', preguntas=preguntas)

# Ruta para eliminar una pregunta


@app.route('/eliminar_pregunta/<int:id>')
def eliminar_pregunta(id):
    pregunta_a_eliminar = Pregunta.query.get_or_404(id)
    db.session.delete(pregunta_a_eliminar)
    db.session.commit()
    return redirect(url_for('admin_preguntas'))


if __name__ == '__main__':
    app.run(debug=True)
