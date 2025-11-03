"""
Servicio para gestión de preguntas
"""
from firebase_admin import firestore, storage
import os
from werkzeug.utils import secure_filename
from datetime import datetime


class QuestionService:
    def __init__(self):
        self.db = firestore.client()
        self.bucket = storage.bucket()

    def upload_image(self, image_file):
        """Subir imagen a Firebase Storage"""
        try:
            if not image_file:
                return None, "No se proporcionó ninguna imagen"

            filename = secure_filename(image_file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{timestamp}_{filename}"

            blob = self.bucket.blob(f'question_images/{filename}')
            blob.upload_from_file(
                image_file, content_type=image_file.content_type)
            blob.make_public()

            return blob.public_url, None
        except Exception as e:
            return None, f"Error al subir imagen: {str(e)}"

    def add_question(self, level, round_type, question_image_url, options, correct):
        """Agregar una nueva pregunta CON RONDA"""
        try:
            questions_ref = self.db.collection('questions')

            question_data = {
                'level': level,
                'round': round_type,  # NUEVO: Campo de ronda
                'question_image': question_image_url,
                'options': options,
                'correct': correct
            }

            questions_ref.add(question_data)

            return True, "Pregunta agregada correctamente"
        except Exception as e:
            return False, f"Error al agregar pregunta: {str(e)}"

    def get_all_questions(self):
        """Obtener todas las preguntas"""
        try:
            questions_ref = self.db.collection('questions')
            questions = questions_ref.stream()

            result = []
            for doc in questions:
                question = doc.to_dict()
                question['id'] = doc.id
                result.append(question)

            return result
        except Exception as e:
            print(f"Error al obtener preguntas: {e}")
            return []

    def get_questions_by_level(self, level):
        """Obtener preguntas por nivel (sin filtro de ronda)"""
        try:
            questions_ref = self.db.collection('questions')
            questions_query = questions_ref.where(
                'level', '==', level).stream()

            questions = []
            for doc in questions_query:
                question = doc.to_dict()
                question['id'] = doc.id
                questions.append(question)

            return questions
        except Exception as e:
            print(f"Error al obtener preguntas: {e}")
            return []

    def get_questions_by_level_and_round(self, level, round_type):
        """Obtener preguntas de un nivel Y ronda específica"""
        try:
            questions_ref = self.db.collection('questions')
            questions_query = questions_ref.where('level', '==', level).where(
                'round', '==', round_type).stream()

            questions = []
            for doc in questions_query:
                question = doc.to_dict()
                question['id'] = doc.id
                questions.append(question)

            return questions
        except Exception as e:
            print(f"Error al obtener preguntas: {e}")
            return []

    def get_question_by_id(self, question_id):
        """Obtener una pregunta por su ID"""
        try:
            question_ref = self.db.collection(
                'questions').document(question_id)
            question = question_ref.get()

            if question.exists:
                question_data = question.to_dict()
                question_data['id'] = question.id
                return question_data
            return None
        except Exception as e:
            print(f"Error al obtener pregunta: {e}")
            return None

    def delete_question(self, question_id):
        """Eliminar una pregunta"""
        try:
            question_ref = self.db.collection(
                'questions').document(question_id)
            question = question_ref.get()

            if not question.exists:
                return False, "Pregunta no encontrada"

            # Eliminar imagen de Storage si existe
            question_data = question.to_dict()
            if 'question_image' in question_data:
                try:
                    image_url = question_data['question_image']
                    # Extraer nombre del archivo de la URL
                    filename = image_url.split('/')[-1].split('?')[0]
                    blob = self.bucket.blob(f'question_images/{filename}')
                    if blob.exists():
                        blob.delete()
                except Exception as img_error:
                    print(f"Error al eliminar imagen: {img_error}")

            # Eliminar documento
            question_ref.delete()

            return True, "Pregunta eliminada correctamente"
        except Exception as e:
            return False, f"Error al eliminar pregunta: {str(e)}"

    def update_question(self, question_id, level, round_type, question_image_url, options, correct):
        """Actualizar una pregunta existente"""
        try:
            question_ref = self.db.collection(
                'questions').document(question_id)

            update_data = {
                'level': level,
                'round': round_type,  # NUEVO: Actualizar ronda
                'options': options,
                'correct': correct
            }

            if question_image_url:
                update_data['question_image'] = question_image_url

            question_ref.update(update_data)

            return True, "Pregunta actualizada correctamente"
        except Exception as e:
            return False, f"Error al actualizar pregunta: {str(e)}"
