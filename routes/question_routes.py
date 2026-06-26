from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.decorators import handle_errors
from services.question_service import QuestionService
from firebase_admin import storage
from werkzeug.utils import secure_filename
import os
import uuid

question_bp = Blueprint('question', __name__, url_prefix='/questions')


ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}


def get_question_service():
    return QuestionService()


def is_allowed_image(filename):
    ext = os.path.splitext(filename.lower())[1]
    return ext in ALLOWED_IMAGE_EXTENSIONS


def normalize_round_value(round_type):
    """
    Normaliza nombres antiguos o visuales de rondas.
    """
    mapping = {
        'octavos': 'octavos',
        'quarters': 'cuartos',
        'cuartos': 'cuartos',
        'semis': 'semifinal',
        'semifinal': 'semifinal',
        'final': 'final',
    }

    if not round_type:
        return ''

    return mapping.get(str(round_type).strip().lower(), str(round_type).strip().lower())


def upload_question_image_to_storage(file_storage):
    """
    Sube una imagen a Firebase Storage y devuelve su URL pública.
    """
    if not file_storage or not file_storage.filename:
        return False, "No se recibió archivo.", None

    if not is_allowed_image(file_storage.filename):
        return False, "Formato no permitido. Usa PNG, JPG, JPEG o WEBP.", None

    try:
        original_name = secure_filename(file_storage.filename)
        ext = os.path.splitext(original_name)[1].lower()
        unique_name = f"questions/{uuid.uuid4().hex}{ext}"

        bucket = storage.bucket()
        blob = bucket.blob(unique_name)

        file_storage.stream.seek(0)
        blob.upload_from_file(
            file_storage.stream,
            content_type=file_storage.mimetype
        )

        blob.make_public()

        return True, "Imagen subida correctamente.", blob.public_url

    except Exception as e:
        return False, f"Error subiendo imagen: {str(e)}", None


@question_bp.route('/add-question', methods=['GET', 'POST'])
@login_required
@handle_errors
def add_question():
    """
    Agregar pregunta manualmente.
    """
    question_service = get_question_service()

    if request.method == 'POST':
        level = request.form.get('level', '').strip().lower()
        round_type = normalize_round_value(request.form.get('round', ''))

        question_text = request.form.get('question_text', '').strip()
        question_image = request.form.get('question_image_url', '').strip()
        question_image_file = request.files.get('question_image')

        option_a = request.form.get('option_a', '').strip()
        option_b = request.form.get('option_b', '').strip()
        option_c = request.form.get('option_c', '').strip()
        option_d = request.form.get('option_d', '').strip()

        correct = request.form.get('correct', '').strip().lower()
        custom_id = request.form.get('id', '').strip()

        valid_levels = {'nivel1', 'nivel2', 'nivel3'}
        valid_rounds = {'octavos', 'cuartos', 'semifinal', 'final'}
        valid_correct = {'a', 'b', 'c', 'd'}

        if level not in valid_levels:
            flash('Nivel inválido. Usa nivel1, nivel2 o nivel3.', 'error')
            return redirect(url_for('question.add_question'))

        if round_type not in valid_rounds:
            flash('Ronda inválida. Usa octavos, cuartos, semifinal o final.', 'error')
            return redirect(url_for('question.add_question'))

        if correct not in valid_correct:
            flash('La respuesta correcta debe ser a, b, c o d.', 'error')
            return redirect(url_for('question.add_question'))

        if not option_a or not option_b or not option_c or not option_d:
            flash('Debes completar las 4 opciones.', 'error')
            return redirect(url_for('question.add_question'))

        if question_image_file and question_image_file.filename:
            success_upload, upload_message, uploaded_url = upload_question_image_to_storage(question_image_file)

            if not success_upload:
                flash(upload_message, 'error')
                return redirect(url_for('question.add_question'))

            question_image = uploaded_url

        question_data = {
            'level': level,
            'round': round_type,
            'question_text': question_text,
            'question_image': question_image,
            'options': {
                'a': option_a,
                'b': option_b,
                'c': option_c,
                'd': option_d
            },
            'correct': correct
        }

        success, message = question_service.add_question(
            question_data,
            doc_id=custom_id or None
        )

        flash(message, 'success' if success else 'error')
        return redirect(url_for('question.add_question'))

    return render_template('add_question.html')


@question_bp.route('/manage-questions')
@login_required
@handle_errors
def manage_questions():
    """
    Visualizar, editar y eliminar preguntas.
    """
    question_service = get_question_service()
    questions = question_service.get_all_questions()

    for q in questions:
        q['round'] = normalize_round_value(q.get('round', ''))

    questions_n1 = [q for q in questions if q.get('level') == 'nivel1']
    questions_n2 = [q for q in questions if q.get('level') == 'nivel2']
    questions_n3 = [q for q in questions if q.get('level') == 'nivel3']

    return render_template(
        'manage_questions.html',
        questions=questions,
        questions_n1=questions_n1,
        questions_n2=questions_n2,
        questions_n3=questions_n3
    )


@question_bp.route('/edit-question/<question_id>', methods=['GET'])
@login_required
@handle_errors
def edit_question(question_id):
    """
    Abre el formulario para editar una pregunta.
    """
    question_service = get_question_service()
    question = question_service.get_question_by_id(question_id)

    if not question:
        flash('No se encontró la pregunta.', 'error')
        return redirect(url_for('question.manage_questions'))

    question['round'] = normalize_round_value(question.get('round', ''))

    return render_template(
        'edit_question.html',
        question=question
    )


@question_bp.route('/update-question/<question_id>', methods=['POST'])
@login_required
@handle_errors
def update_question(question_id):
    """
    Actualiza una pregunta existente.
    """
    question_service = get_question_service()

    level = request.form.get('level', '').strip().lower()
    round_type = normalize_round_value(request.form.get('round', ''))
    question_text = request.form.get('question_text', '').strip()

    question_image = request.form.get('question_image', '').strip()
    question_image_file = request.files.get('question_image_file')

    option_a = request.form.get('option_a', '').strip()
    option_b = request.form.get('option_b', '').strip()
    option_c = request.form.get('option_c', '').strip()
    option_d = request.form.get('option_d', '').strip()

    correct = request.form.get('correct', '').strip().lower()

    valid_levels = {'nivel1', 'nivel2', 'nivel3'}
    valid_rounds = {'octavos', 'cuartos', 'semifinal', 'final'}
    valid_correct = {'a', 'b', 'c', 'd'}

    if level not in valid_levels:
        flash('Nivel inválido. Usa nivel1, nivel2 o nivel3.', 'error')
        return redirect(url_for('question.edit_question', question_id=question_id))

    if round_type not in valid_rounds:
        flash('Ronda inválida. Usa octavos, cuartos, semifinal o final.', 'error')
        return redirect(url_for('question.edit_question', question_id=question_id))

    if correct not in valid_correct:
        flash('La respuesta correcta debe ser a, b, c o d.', 'error')
        return redirect(url_for('question.edit_question', question_id=question_id))

    if not option_a or not option_b or not option_c or not option_d:
        flash('Debes completar las 4 opciones.', 'error')
        return redirect(url_for('question.edit_question', question_id=question_id))

    if question_image_file and question_image_file.filename:
        success_upload, upload_message, uploaded_url = upload_question_image_to_storage(question_image_file)

        if not success_upload:
            flash(upload_message, 'error')
            return redirect(url_for('question.edit_question', question_id=question_id))

        question_image = uploaded_url

    question_data = {
        'level': level,
        'round': round_type,
        'question_text': question_text,
        'question_image': question_image,
        'option_a': option_a,
        'option_b': option_b,
        'option_c': option_c,
        'option_d': option_d,
        'correct': correct
    }

    success, message = question_service.update_question(question_id, question_data)

    flash(message, 'success' if success else 'error')
    return redirect(url_for('question.manage_questions'))


@question_bp.route('/delete-question/<question_id>', methods=['POST'])
@login_required
@handle_errors
def delete_question(question_id):
    """
    Elimina una pregunta.
    """
    question_service = get_question_service()

    success, message = question_service.delete_question(question_id)
    flash(message, 'success' if success else 'error')

    return redirect(url_for('question.manage_questions'))