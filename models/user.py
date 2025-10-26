"""
Modelo de Usuario para el sistema
"""
from flask_login import UserMixin
from werkzeug.security import check_password_hash


class User(UserMixin):
    """Clase de usuario para autenticación"""

    def __init__(self, username):
        self.id = username
        self.username = username

    def get_id(self):
        """Retorna el ID del usuario"""
        return str(self.id)

    def __repr__(self):
        return f'<User {self.username}>'
