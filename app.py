from flask import Flask, render_template, redirect, url_for
from flask_login import LoginManager, current_user, logout_user
from whitenoise import WhiteNoise
import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

from config import config
from models.user import User

from routes.auth_routes import auth_bp
from routes.quiz_routes import quiz_bp
from routes.team_routes import team_bp
from routes.question_routes import question_bp
from routes.bracket_routes import bracket_bp


def create_app(config_name=None):
    app = Flask(__name__)

    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
    app.config.from_object(config[config_name])

    STATIC_ROOT = os.path.join(os.path.dirname(
        os.path.abspath(__file__)), 'static')
    app.wsgi_app = WhiteNoise(app.wsgi_app, root=STATIC_ROOT, prefix="static/")

    initialize_firebase(app)
    setup_login_manager(app)
    register_blueprints(app)
    setup_context_processors(app)
    setup_error_handlers(app)

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            logout_user()
        return redirect(url_for('auth.login'))

    return app


def initialize_firebase(app):
    """
    Inicializa Firebase Admin SDK
    Soporta:
    - Variable de entorno FIREBASE_CREDENTIALS (JSON string) para producción (Render.com)
    - Archivo local firebase_credentials.json para desarrollo local
    """
    try:
        # Verificar si ya está inicializado
        if firebase_admin._apps:
            app.logger.info("Firebase ya estaba inicializado")
            return

        # OPCIÓN 1: Variable de entorno (PRODUCCIÓN - Render.com)
        firebase_creds_json = os.getenv('FIREBASE_CREDENTIALS')

        if firebase_creds_json:
            app.logger.info(
                "Usando credenciales de Firebase desde variable de entorno")
            try:
                cred_dict = json.loads(firebase_creds_json)
                cred = credentials.Certificate(cred_dict)

                # Inicializar con bucket
                firebase_admin.initialize_app(cred, {
                    'storageBucket': 'olympic-math.firebasestorage.app'
                })

                print("=" * 60)
                print("Firebase inicializado desde VARIABLE DE ENTORNO")
                print(f"Bucket: olympic-math.firebasestorage.app")
                print("=" * 60)

            except json.JSONDecodeError as e:
                app.logger.error(
                    f"Error al parsear JSON de credenciales: {e}")
                raise
        else:
            # OPCIÓN 2: Archivo local (DESARROLLO)
            app.logger.info(
                "Usando credenciales de Firebase desde archivo local")
            cred_path = app.config.get('FIREBASE_CREDENTIALS',
                                       os.path.join(os.path.dirname(__file__), 'firebase_credentials.json'))

            if not os.path.exists(cred_path):
                raise FileNotFoundError(
                    f"No se encontró el archivo de credenciales: {cred_path}\n"
                    f"Tampoco está configurada la variable de entorno FIREBASE_CREDENTIALS"
                )

            cred = credentials.Certificate(cred_path)

            # Inicializar con bucket
            firebase_admin.initialize_app(cred, {
                'storageBucket': 'olympic-math.firebasestorage.app'
            })

            print("=" * 60)
            print("Firebase inicializado desde ARCHIVO LOCAL")
            print(f"Archivo: {cred_path}")
            print(f"Bucket: olympic-math.firebasestorage.app")
            print("=" * 60)

        app.logger.info("Firebase inicializado correctamente")

    except Exception as e:
        app.logger.error(f"Error crítico al inicializar Firebase: {str(e)}")
        raise


def setup_login_manager(app):
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = "Por favor, inicia sesión para acceder."
    login_manager.login_message_category = "error"

    @login_manager.user_loader
    def load_user(user_id):
        if user_id == app.config['ADMIN_USERNAME']:
            return User(user_id)
        return None


def register_blueprints(app):
    app.register_blueprint(auth_bp)
    app.register_blueprint(quiz_bp)
    app.register_blueprint(team_bp)
    app.register_blueprint(question_bp)
    app.register_blueprint(bracket_bp)

    app.logger.info("Blueprints registrados correctamente")


def setup_context_processors(app):
    """Registrar funciones helper para templates"""
    # Importar aquí después de que Firebase esté inicializado
    from services.bracket_service import get_team_name

    @app.context_processor
    def utility_processor():
        return dict(
            get_team_name=get_team_name
        )

    app.logger.info("Context processors registrados correctamente")


def setup_error_handlers(app):

    @app.errorhandler(404)
    def not_found(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f'Error 500: {error}')
        return render_template('errors/500.html'), 500

    @app.errorhandler(413)
    def too_large(error):
        from flask import flash, redirect
        flash('El archivo es demasiado grande. Máximo 5MB.', 'error')
        return redirect(url_for('question.add_question'))


app = create_app()


if __name__ == '__main__':
    is_production = os.environ.get(
        'RENDER', False) or os.environ.get('DYNO', False)
    port = int(os.environ.get('PORT', 5000))
    debug = not is_production

    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not debug:
        print("=" * 60)
        print("OLIMPIADAS MATEMATICAS - BOSCOTECHLAB")
        print("=" * 60)
        print(f"Puerto: {port}")
        print(f"Modo: {'Producción' if is_production else 'Desarrollo'}")
        print(f"Debug: {'Activado' if debug else 'Desactivado'}")
        print("=" * 60)
        print(f"Desarrollador: Ing. Samuel David Moreno")
        print("=" * 60)

    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug
    )
