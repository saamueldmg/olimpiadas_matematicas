"""
Servicio para gestión de preguntas
Olimpiadas Matemáticas - Tuluá
"""
from firebase_admin import firestore, storage
from werkzeug.utils import secure_filename
import uuid


class QuestionService:
    """Servicio para operaciones con preguntas"""

    def __init__(self, db):
        self.db = db

    def get_questions_by_level(self, level):
        """Obtener todas las preguntas de un nivel específico"""
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

    def get_question_by_id(self, question_id):
        """Obtener una pregunta específica por ID"""
        try:
            doc = self.db.collection('questions').document(question_id).get()
            if doc.exists:
                question = doc.to_dict()
                question['id'] = doc.id
                return question
            return None
        except Exception as e:
            print(f"Error al obtener pregunta: {e}")
            return None

    def add_question(self, level, question_image_url, options, correct):
        """Agregar una nueva pregunta"""
        try:
            questions_ref = self.db.collection('questions')

            question_data = {
                'level': level,
                'question_image': question_image_url,
                'options': options,
                'correct': correct
            }

            questions_ref.add(question_data)

            return True, "Pregunta agregada correctamente"
        except Exception as e:
            return False, f"Error al agregar pregunta: {str(e)}"

    def delete_question(self, question_id):
        """Eliminar una pregunta"""
        try:
            question_ref = self.db.collection(
                'questions').document(question_id)
            question_ref.delete()

            return True, "Pregunta eliminada correctamente"
        except Exception as e:
            return False, f"Error al eliminar pregunta: {str(e)}"

    def upload_image(self, file):
        """
        Subir imagen a Firebase Storage

        Args:
            file: Archivo de imagen desde el formulario

        Returns:
            tuple: (url_publica, error)
        """
        try:
            if not file:
                return None, "No se proporcionó archivo"

            # Validar tipo de archivo
            allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
            filename = secure_filename(file.filename)

            if '.' not in filename:
                return None, "El archivo debe tener una extensión válida"

            file_ext = filename.rsplit('.', 1)[1].lower()
            if file_ext not in allowed_extensions:
                return None, f"Extensión no permitida. Usa: {', '.join(allowed_extensions)}"

            # Generar nombre único
            unique_filename = f"{uuid.uuid4()}_{filename}"

            # Obtener bucket de Firebase Storage
            bucket = storage.bucket()

            # Crear blob (referencia al archivo)
            blob = bucket.blob(f"questions/{unique_filename}")

            # Subir archivo
            blob.upload_from_string(
                file.read(),
                content_type=file.content_type
            )

            # Hacer público el archivo
            blob.make_public()

            # Retornar URL pública
            return blob.public_url, None

        except Exception as e:
            print(f"Error detallado al subir imagen: {e}")
            return None, f"Error al subir imagen: {str(e)}"
