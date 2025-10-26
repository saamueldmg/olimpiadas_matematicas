from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from firebase_admin import firestore

from services.question_service import QuestionService
from utils.decorators import handle_errors

question_bp = Blueprint('question', __name__)


def get_question_service():
    db = firestore.client()
    return QuestionService(db)


@question_bp.route('/manage-questions')
@login_required
@handle_errors
def manage_questions():
    question_service = get_question_service()

    nivel1 = question_service.get_questions_by_level('nivel1')
    nivel2 = question_service.get_questions_by_level('nivel2')
    nivel3 = question_service.get_questions_by_level('nivel3')

    return render_template('manage_questions.html',
                           questions_n1=nivel1,
                           questions_n2=nivel2,
                           questions_n3=nivel3)


@question_bp.route('/add-question', methods=['GET', 'POST'])
@login_required
@handle_errors
def add_question():
    if request.method == 'POST':
        question_service = get_question_service()

        level = request.form.get('level')
        image_file = request.files.get('question_image')
        option_a = request.form.get('option_a')
        option_b = request.form.get('option_b')
        option_c = request.form.get('option_c')
        option_d = request.form.get('option_d')
        correct = request.form.get('correct')

        # Validaciones
        if not all([level, image_file, option_a, option_b, option_c, option_d, correct]):
            flash('Debes completar todos los campos', 'error')
            return redirect(url_for('question.add_question'))

        # Subir imagen
        image_url, error = question_service.upload_image(image_file)
        if error:
            flash(error, 'error')
            return redirect(url_for('question.add_question'))

        # Crear opciones
        options = {
            'a': option_a,
            'b': option_b,
            'c': option_c,
            'd': option_d
        }

        # Agregar pregunta
        success, message = question_service.add_question(
            level, image_url, options, correct)

        flash(message, 'success' if success else 'error')
        return redirect(url_for('question.manage_questions'))

    return render_template('add_question.html')


@question_bp.route('/delete-question/<question_id>', methods=['POST'])
@login_required
@handle_errors
def delete_question(question_id):
    question_service = get_question_service()

    success, message = question_service.delete_question(question_id)
    flash(message, 'success' if success else 'error')

    return redirect(url_for('question.manage_questions'))
