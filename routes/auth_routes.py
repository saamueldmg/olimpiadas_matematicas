from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from models.user import User

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('quiz.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        from flask import current_app

        if username == current_app.config['ADMIN_USERNAME'] and \
           password == current_app.config['ADMIN_PASSWORD']:
            user = User(username)
            login_user(user)
            return redirect(url_for('quiz.dashboard'))
        else:
            flash('Credenciales incorrectas', 'error')

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    flash('Sesión cerrada exitosamente', 'success')
    return redirect(url_for('auth.login'))
