"""
Configuración centralizada de la aplicación
Olimpiadas Matemáticas - Tuluá
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuración base de la aplicación"""

    # Seguridad
    SECRET_KEY = os.environ.get(
        'SECRET_KEY', 'alejandro-diego-gerardo-bosco-tech-2024')

    # Firebase
    FIREBASE_CREDENTIALS = os.environ.get(
        'FIREBASE_CREDENTIALS', 'serviceAccountKey.json')

    # ✅✅✅ BUCKET CORRECTO (NUEVO)
    STORAGE_BUCKET = 'olympic-math.firebasestorage.app'

    # Admin
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'bosco@tech%')

    # Upload settings
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB máximo
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

    # Quiz settings
    QUIZ_DURATION = 300  # 5 minutos
    QUESTIONS_PER_QUIZ = 10

    # Session
    SESSION_PERMANENT = False


class DevelopmentConfig(Config):
    """Configuración para desarrollo"""
    DEBUG = True


class ProductionConfig(Config):
    """Configuración para producción"""
    DEBUG = False


# Configuración activa
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
