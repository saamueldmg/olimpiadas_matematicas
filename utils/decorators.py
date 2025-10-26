"""
Decoradores personalizados para rutas
"""
from functools import wraps
from flask import flash, redirect, url_for, session, current_app
import traceback


def handle_errors(f):
    """Maneja errores de forma centralizada en las rutas"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as e:
            current_app.logger.error(f'ValueError en {f.__name__}: {str(e)}')
            flash(f'Error de validación: {str(e)}', 'error')
            return redirect(url_for('quiz.dashboard'))
        except Exception as e:
            current_app.logger.error(f'Error en {f.__name__}: {str(e)}')
            current_app.logger.error(traceback.format_exc())
            flash('Ocurrió un error inesperado. Por favor, intenta de nuevo.', 'error')
            return redirect(url_for('quiz.dashboard'))
    return decorated_function


def require_quiz_session(f):
    """Verifica que existe una sesión de quiz válida"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'quiz_level' not in session or 'quiz_teams' not in session:
            flash('No hay una sesión de quiz activa', 'error')
            return redirect(url_for('quiz.select_level'))
        return f(*args, **kwargs)
    return decorated_function
