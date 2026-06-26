from firebase_admin import firestore


class QuestionService:
    def __init__(self):
        self.collection_name = 'questions'

    @property
    def db(self):
        return firestore.client()

    @property
    def collection(self):
        return self.db.collection(self.collection_name)

    def add_question(self, question_data, doc_id=None):
        """
        Agrega una pregunta manualmente.
        """
        try:
            payload = {
                'level': question_data.get('level', '').strip().lower(),
                'round': question_data.get('round', '').strip().lower(),
                'question_text': question_data.get('question_text', '').strip(),
                'question_image': question_data.get('question_image', '').strip(),
                'options': question_data.get('options', {}),
                'correct': question_data.get('correct', '').strip().lower(),
                'created_at': firestore.SERVER_TIMESTAMP
            }

            if doc_id:
                self.collection.document(doc_id).set(payload, merge=True)
                return True, f'Pregunta "{doc_id}" guardada correctamente.'

            self.collection.document().set(payload)
            return True, 'Pregunta guardada correctamente.'

        except Exception as e:
            return False, f'Error al guardar pregunta: {str(e)}'

    def get_question_by_id(self, question_id):
        """
        Obtiene una pregunta por ID.
        """
        try:
            doc = self.collection.document(question_id).get()

            if not doc.exists:
                return None

            data = doc.to_dict() or {}
            data['id'] = doc.id
            return data

        except Exception as e:
            print(f"Error al obtener pregunta por id: {e}")
            return None

    def get_questions_by_level_and_round(self, level, round_type):
        """
        Obtiene preguntas por nivel y ronda.
        """
        try:
            docs = (
                self.collection
                .where('level', '==', level)
                .where('round', '==', round_type)
                .stream()
            )

            questions = []

            for doc in docs:
                data = doc.to_dict() or {}
                data['id'] = doc.id
                questions.append(data)

            return questions

        except Exception as e:
            print(f"Error al obtener preguntas por nivel/ronda: {e}")
            return []

    def get_all_questions(self):
        """
        Obtiene todas las preguntas.
        """
        try:
            docs = self.collection.stream()
            questions = []

            for doc in docs:
                data = doc.to_dict() or {}
                data['id'] = doc.id
                questions.append(data)

            return questions

        except Exception as e:
            print(f"Error al obtener todas las preguntas: {e}")
            return []

    def update_question(self, question_id, question_data):
        """
        Actualiza una pregunta existente.
        """
        try:
            if not question_id:
                return False, "No se proporcionó el ID de la pregunta."

            doc_ref = self.collection.document(question_id)
            doc = doc_ref.get()

            if not doc.exists:
                return False, "La pregunta no existe."

            payload = {
                'level': question_data.get('level', '').strip().lower(),
                'round': question_data.get('round', '').strip().lower(),
                'question_text': question_data.get('question_text', '').strip(),
                'question_image': question_data.get('question_image', '').strip(),
                'options': {
                    'a': question_data.get('option_a', '').strip(),
                    'b': question_data.get('option_b', '').strip(),
                    'c': question_data.get('option_c', '').strip(),
                    'd': question_data.get('option_d', '').strip(),
                },
                'correct': question_data.get('correct', '').strip().lower(),
                'updated_at': firestore.SERVER_TIMESTAMP
            }

            doc_ref.set(payload, merge=True)
            return True, f'Pregunta "{question_id}" actualizada correctamente.'

        except Exception as e:
            return False, f'Error al actualizar pregunta: {str(e)}'

    def delete_question(self, question_id):
        """
        Elimina una pregunta por ID.
        """
        try:
            if not question_id:
                return False, "No se proporcionó el ID de la pregunta."

            doc_ref = self.collection.document(question_id)
            doc = doc_ref.get()

            if not doc.exists:
                return False, "La pregunta no existe o ya fue eliminada."

            doc_ref.delete()
            return True, f'Pregunta "{question_id}" eliminada correctamente.'

        except Exception as e:
            return False, f'Error al eliminar pregunta: {str(e)}'