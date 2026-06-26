from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from models.user import User

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Login solo para administrador.
    """
    if current_user.is_authenticated:
        return redirect(url_for('quiz.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            flash('Debes ingresar usuario y contraseña', 'error')
            return render_template('login.html')

        if (
            username == current_app.config['ADMIN_USERNAME'] and
            password == current_app.config['ADMIN_PASSWORD']
        ):
            user = User(username)
            login_user(user)
            flash('Inicio de sesión exitoso', 'success')
            return redirect(url_for('quiz.dashboard'))

        flash('Credenciales incorrectas', 'error')

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """
    Cerrar sesión del usuario autenticado.
    """
    logout_user()
    session.clear()
    flash('Sesión cerrada exitosamente', 'success')
    return redirect(url_for('auth.login'))