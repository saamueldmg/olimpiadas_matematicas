"""
Decoradores personalizados para rutas
"""

from functools import wraps
from flask import flash, redirect, url_for, session, current_app, request, jsonify
import traceback


PUBLIC_ENDPOINTS = {
    'quiz.versus',
    'quiz.versus_level',
    'quiz.versus_state',
    'quiz.versus_level_state',
    'quiz.submit_public_answer',
    'quiz.scoreboard',
}


def _is_ajax_request():
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _is_public_endpoint():
    return request.endpoint in PUBLIC_ENDPOINTS


def handle_errors(f):
    """Maneja errores de forma centralizada en las rutas."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)

        except ValueError as e:
            current_app.logger.error(f'ValueError en {f.__name__}: {str(e)}')
            current_app.logger.error(traceback.format_exc())

            if _is_ajax_request():
                return jsonify({
                    'success': False,
                    'message': f'Error de validación: {str(e)}'
                }), 400

            if _is_public_endpoint():
                flash(f'Error de validación: {str(e)}', 'error')
                return redirect(url_for('quiz.versus'))

            flash(f'Error de validación: {str(e)}', 'error')
            return redirect(url_for('quiz.dashboard'))

        except Exception as e:
            current_app.logger.error(f'Error en {f.__name__}: {str(e)}')
            current_app.logger.error(traceback.format_exc())

            if _is_ajax_request():
                return jsonify({
                    'success': False,
                    'message': 'Ocurrió un error inesperado. Por favor, intenta de nuevo.'
                }), 500

            if _is_public_endpoint():
                flash('Ocurrió un error inesperado. Por favor, intenta de nuevo.', 'error')
                return redirect(url_for('quiz.versus'))

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