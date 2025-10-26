"""
Servicio para gestión de equipos
Olimpiadas Matemáticas - Tulua
"""
from firebase_admin import firestore


class TeamService:
    """Servicio para operaciones con equipos"""

    def __init__(self, db):
        self.db = db
        self.cache = {}
        self.cache_timestamp = 0

    def get_all_teams(self, use_cache=True):
        """Obtener todos los equipos"""
        import time

        # Usar caché si está disponible y tiene menos de 30 segundos
        if use_cache and self.cache and (time.time() - self.cache_timestamp < 30):
            return self.cache.get('teams', [])

        try:
            teams_ref = self.db.collection('teams')
            teams = []
            for doc in teams_ref.stream():
                team = doc.to_dict()
                team['id'] = doc.id
                teams.append(team)

            # Actualizar caché
            self.cache['teams'] = teams
            self.cache_timestamp = time.time()
            return teams
        except Exception as e:
            print(f"Error al obtener equipos: {e}")
            return []

    def add_team(self, name, level):
        """Agregar un nuevo equipo"""
        try:
            teams_ref = self.db.collection('teams')

            # Verificar si ya existe
            existing = teams_ref.where('name', '==', name).limit(1).stream()
            if any(existing):
                return False, "El equipo ya existe"

            # Crear nuevo equipo
            team_data = {
                'name': name,
                'level': level,
                'score': 0,
                'total_score': 0
            }
            teams_ref.add(team_data)

            # Limpiar caché
            self.cache.clear()
            return True, "Equipo agregado correctamente"
        except Exception as e:
            return False, f"Error al agregar equipo: {str(e)}"

    def update_team(self, team_id, name, level):
        """Actualizar un equipo existente"""
        try:
            team_ref = self.db.collection('teams').document(team_id)
            team_ref.update({
                'name': name,
                'level': level
            })

            # Limpiar caché
            self.cache.clear()
            return True, "Equipo actualizado correctamente"
        except Exception as e:
            return False, f"Error al actualizar equipo: {str(e)}"

    def delete_team(self, team_id):
        """Eliminar un equipo"""
        try:
            team_ref = self.db.collection('teams').document(team_id)
            team_ref.delete()

            # Limpiar caché
            self.cache.clear()
            return True, "Equipo eliminado correctamente"
        except Exception as e:
            return False, f"Error al eliminar equipo: {str(e)}"

    def reset_scores(self):
        """Reiniciar puntajes de todos los equipos usando batch update (más rápido)"""
        try:
            teams_ref = self.db.collection('teams')
            batch = self.db.batch()

            count = 0
            for doc in teams_ref.stream():
                # Agregar al batch en lugar de hacer update individual
                batch.update(doc.reference, {
                    'score': 0,
                    'total_score': 0
                })
                count += 1

                # Firestore tiene límite de 500 operaciones por batch
                if count % 500 == 0:
                    batch.commit()
                    batch = self.db.batch()

            # Commit final si quedaron operaciones pendientes
            if count % 500 != 0:
                batch.commit()

            # Limpiar caché
            self.cache.clear()
            return True, f"Puntajes reiniciados correctamente ({count} equipos)"
        except Exception as e:
            return False, f"❌ Error al reiniciar puntajes: {str(e)}"

    def update_team_score(self, team_name, points):
        """Actualizar el score de un equipo sumando puntos"""
        try:
            teams_ref = self.db.collection('teams')
            query = teams_ref.where('name', '==', team_name).limit(1).stream()

            for doc in query:
                current_score = doc.to_dict().get('score', 0)
                current_total = doc.to_dict().get('total_score', 0)

                new_score = current_score + points
                new_total = current_total + points

                doc.reference.update({
                    'score': new_score,
                    'total_score': new_total
                })

                # Limpiar caché
                self.cache.clear()
                return True

            return False
        except Exception as e:
            print(f"Error al actualizar score: {e}")
            return False
