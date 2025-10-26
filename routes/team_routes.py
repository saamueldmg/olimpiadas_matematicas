from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from firebase_admin import firestore

from services.team_service import TeamService
from utils.decorators import handle_errors

team_bp = Blueprint('team', __name__)


def get_team_service():
    db = firestore.client()
    return TeamService(db)


@team_bp.route('/manage-teams', methods=['GET', 'POST'])
@login_required
@handle_errors
def manage_teams():
    team_service = get_team_service()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            name = request.form.get('name')
            level = request.form.get('level')

            if not name or not level:
                flash('Debes completar todos los campos', 'error')
                return redirect(url_for('team.manage_teams'))

            success, message = team_service.add_team(name, level)
            flash(message, 'success' if success else 'error')

        elif action == 'update':
            team_id = request.form.get('team_id')
            name = request.form.get('name')
            level = request.form.get('level')

            if not team_id or not name or not level:
                flash('Datos incompletos', 'error')
                return redirect(url_for('team.manage_teams'))

            success, message = team_service.update_team(team_id, name, level)
            flash(message, 'success' if success else 'error')

        elif action == 'delete':
            team_id = request.form.get('team_id')

            if not team_id:
                flash('ID de equipo no válido', 'error')
                return redirect(url_for('team.manage_teams'))

            success, message = team_service.delete_team(team_id)
            flash(message, 'success' if success else 'error')

        elif action == 'reset':
            success, message = team_service.reset_scores()
            flash(message, 'success' if success else 'error')
            # ← REDIRIGIR AL SCOREBOARD
            return redirect(url_for('quiz.scoreboard'))

        return redirect(url_for('team.manage_teams'))

    teams = team_service.get_all_teams(use_cache=False)
    return render_template('manage_teams.html', teams=teams)
