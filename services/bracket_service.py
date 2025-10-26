"""
Servicio para gestión de brackets
Olimpiadas Matemáticas - Tuluá
"""
from datetime import datetime

# Variable global para db (se inicializa después)
_db = None

BRACKET_COLLECTION = 'brackets'


def get_db():
    """Obtener instancia de Firestore de forma lazy"""
    global _db
    if _db is None:
        import firebase_admin
        _db = firebase_admin.firestore.client()
    return _db


def get_or_create_bracket(team_ids=None):
    """Obtener bracket actual o crear uno nuevo"""
    try:
        db = get_db()
        brackets_ref = db.collection(BRACKET_COLLECTION)
        active_brackets = brackets_ref.where(
            'status', '==', 'active').limit(1).get()

        if active_brackets:
            bracket_doc = list(active_brackets)[0]
            bracket_data = bracket_doc.to_dict()
            bracket_data['id'] = bracket_doc.id
            return bracket_data

        # Si no hay bracket activo y se proporcionan equipos, crear uno nuevo
        if team_ids and len(team_ids) == 8:
            return create_new_bracket(team_ids)

        return None

    except Exception as e:
        print(f"Error en get_or_create_bracket: {e}")
        return None


def create_new_bracket(team_ids):
    """Crear un nuevo bracket con 8 equipos"""
    try:
        db = get_db()

        # Estructura del bracket: Cuartos, Semifinales, Final
        bracket_structure = {
            'status': 'active',
            'created_at': datetime.now().isoformat(),
            'current_round': 'quarterfinals',
            'quarterfinals': {
                'match1': {
                    'team1': team_ids[0],
                    'team2': team_ids[1],
                    'winner': None,
                    'completed': False
                },
                'match2': {
                    'team1': team_ids[2],
                    'team2': team_ids[3],
                    'winner': None,
                    'completed': False
                },
                'match3': {
                    'team1': team_ids[4],
                    'team2': team_ids[5],
                    'winner': None,
                    'completed': False
                },
                'match4': {
                    'team1': team_ids[6],
                    'team2': team_ids[7],
                    'winner': None,
                    'completed': False
                }
            },
            'semifinals': {
                'match1': {
                    'team1': None,  # Ganador quarterfinal match1
                    'team2': None,  # Ganador quarterfinal match2
                    'winner': None,
                    'completed': False
                },
                'match2': {
                    'team1': None,  # Ganador quarterfinal match3
                    'team2': None,  # Ganador quarterfinal match4
                    'winner': None,
                    'completed': False
                }
            },
            'final': {
                'team1': None,  # Ganador semifinal match1
                'team2': None,  # Ganador semifinal match2
                'winner': None,
                'completed': False
            },
            'champion': None
        }

        doc_ref = db.collection(BRACKET_COLLECTION).add(bracket_structure)
        bracket_id = doc_ref[1].id

        bracket_structure['id'] = bracket_id
        return bracket_structure

    except Exception as e:
        print(f"Error en create_new_bracket: {e}")
        return None


def advance_team(match_id, winner_team_id):
    """Avanzar un equipo ganador a la siguiente ronda"""
    try:
        db = get_db()
        bracket = get_or_create_bracket()
        if not bracket:
            return False

        bracket_id = bracket['id']
        bracket_ref = db.collection(BRACKET_COLLECTION).document(bracket_id)

        # Determinar en qué ronda está el match
        round_name, match_key = match_id.split('_')

        # Actualizar el ganador del match actual
        update_data = {
            f'{round_name}.{match_key}.winner': winner_team_id,
            f'{round_name}.{match_key}.completed': True
        }

        # Determinar dónde avanza el ganador
        if round_name == 'quarterfinals':
            # Avanzar a semifinales
            match_num = int(match_key.replace('match', ''))
            if match_num <= 2:
                semi_match = 'match1'
                team_position = 'team1' if match_num == 1 else 'team2'
            else:
                semi_match = 'match2'
                team_position = 'team1' if match_num == 3 else 'team2'

            update_data[f'semifinals.{semi_match}.{team_position}'] = winner_team_id

            # Verificar si todos los cuartos están completos
            all_quarters_complete = True
            for i in range(1, 5):
                if not bracket['quarterfinals'][f'match{i}'].get('completed', False):
                    all_quarters_complete = False
                    break

            if all_quarters_complete:
                update_data['current_round'] = 'semifinals'

        elif round_name == 'semifinals':
            # Avanzar a la final
            match_num = int(match_key.replace('match', ''))
            team_position = 'team1' if match_num == 1 else 'team2'

            update_data[f'final.{team_position}'] = winner_team_id

            # Verificar si ambas semifinales están completas
            if bracket['semifinals']['match1'].get('completed', False) and bracket['semifinals']['match2'].get('completed', False):
                update_data['current_round'] = 'final'

        elif round_name == 'final':
            # Establecer campeón
            update_data['champion'] = winner_team_id
            update_data['status'] = 'completed'
            update_data['completed_at'] = datetime.now().isoformat()

        bracket_ref.update(update_data)
        return True

    except Exception as e:
        print(f"Error en advance_team: {e}")
        return False


def get_bracket_status():
    """Obtener estado completo del bracket"""
    try:
        bracket = get_or_create_bracket()
        if not bracket:
            return {'status': 'not_created'}

        return {
            'status': bracket.get('status'),
            'current_round': bracket.get('current_round'),
            'champion': bracket.get('champion')
        }

    except Exception as e:
        print(f"Error en get_bracket_status: {e}")
        return {'status': 'error', 'message': str(e)}


def reset_bracket():
    """Reiniciar/eliminar el bracket actual"""
    try:
        db = get_db()
        brackets_ref = db.collection(BRACKET_COLLECTION)
        active_brackets = brackets_ref.where('status', '==', 'active').get()

        for bracket in active_brackets:
            bracket.reference.delete()

        return True

    except Exception as e:
        print(f"Error en reset_bracket: {e}")
        return False


def get_team_name(team_id):
    """Obtener nombre del equipo por ID"""
    try:
        if not team_id or team_id == 'None':
            return 'TBD'

        db = get_db()
        team_ref = db.collection('teams').document(team_id)
        team = team_ref.get()
        if team.exists:
            return team.to_dict().get('school_name', 'Equipo Desconocido')
        return 'Equipo Desconocido'
    except Exception as e:
        print(f"Error en get_team_name: {e}")
        return 'Equipo Desconocido'
