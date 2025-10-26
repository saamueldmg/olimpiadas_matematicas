"""
Funciones de validación para el sistema
"""
from flask import current_app


def allowed_file(filename):
    """Verifica si el archivo tiene una extensión permitida"""
    if not filename or '.' not in filename:
        return False
    extension = filename.rsplit('.', 1)[1].lower()
    return extension in current_app.config['ALLOWED_EXTENSIONS']


def validate_file_upload(file):
    """
    Valida un archivo subido
    Returns: (es_válido, mensaje_error)
    """
    if not file or file.filename == '':
        return False, "No se seleccionó ningún archivo"

    if not allowed_file(file.filename):
        extensions = ', '.join(current_app.config['ALLOWED_EXTENSIONS'])
        return False, f"Formato no permitido. Use: {extensions}"

    return True, ""


def validate_team_selection(team1, team2, level):
    """Valida la selección de equipos para el quiz"""
    if not team1 or not team2 or not level:
        return False, "Falta seleccionar equipos o nivel"

    if team1 == team2:
        return False, "No puedes seleccionar el mismo equipo dos veces"

    return True, ""
