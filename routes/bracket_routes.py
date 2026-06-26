from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required
from firebase_admin import firestore

from services.team_service import TeamService
from utils.decorators import handle_errors

bracket_bp = Blueprint('bracket', __name__, url_prefix='/brackets')


@bracket_bp.route('/manage', methods=['GET', 'POST'])
@login_required
@handle_errors
def manage_brackets():
    """
    Seleccionar 8 equipos para generar el bracket.
    Actualmente maneja Nivel I y Nivel II.
    """
    db = firestore.client()
    team_service = TeamService(db)

    if request.method == 'POST':
        level = request.form.get('level')  # nivel1 o nivel2
        selected_teams = request.form.getlist('selected_teams')

        if len(selected_teams) != 8:
            flash(
                f'Debes seleccionar exactamente 8 equipos. Seleccionaste {len(selected_teams)}.',
                'error'
            )
            return redirect(url_for('bracket.manage_brackets'))

        session[f'bracket_{level}_quarters'] = selected_teams
        session[f'bracket_{level}_semis'] = []
        session[f'bracket_{level}_final'] = []
        session[f'bracket_{level}_champion'] = None
        session.modified = True

        flash('Bracket creado exitosamente', 'success')
        return redirect(url_for('bracket.manage_brackets'))

    all_teams = team_service.get_all_teams(use_cache=False)

    teams_n1 = [t for t in all_teams if t.get('level') == 'Nivel I']
    teams_n2 = [t for t in all_teams if t.get('level') == 'Nivel II']

    return render_template(
        'manage_brackets.html',
        teams_n1=teams_n1,
        teams_n2=teams_n2
    )


@bracket_bp.route('/advance', methods=['POST'])
@login_required
@handle_errors
def advance_team():
    """
    Avanzar un equipo a la siguiente fase.
    """
    level = request.form.get('level')      # nivel1 o nivel2
    phase = request.form.get('phase')      # quarters, semis, final
    winner = request.form.get('winner')    # nombre del equipo

    if not level or not phase or not winner:
        flash('Datos incompletos para avanzar equipo.', 'error')
        return redirect(url_for('bracket.view_brackets'))

    if phase == 'quarters':
        semis = session.get(f'bracket_{level}_semis', [])
        if len(semis) < 4:
            semis.append(winner)
            session[f'bracket_{level}_semis'] = semis
            session.modified = True
            flash(f'{winner} avanzó a semifinales!', 'success')

    elif phase == 'semis':
        final = session.get(f'bracket_{level}_final', [])
        if len(final) < 2:
            final.append(winner)
            session[f'bracket_{level}_final'] = final
            session.modified = True
            flash(f'{winner} avanzó a la final!', 'success')

    elif phase == 'final':
        session[f'bracket_{level}_champion'] = winner
        session.modified = True
        flash(f'¡{winner} es el campeón de {level.upper()}!', 'success')

    return redirect(url_for('bracket.view_brackets'))


@bracket_bp.route('/view')
@login_required
@handle_errors
def view_brackets():
    """
    Visualizar los brackets generados.
    """
    bracket_n1_quarters = session.get('bracket_nivel1_quarters', [])
    bracket_n1_semis = session.get('bracket_nivel1_semis', [])
    bracket_n1_final = session.get('bracket_nivel1_final', [])
    bracket_n1_champion = session.get('bracket_nivel1_champion', None)

    bracket_n2_quarters = session.get('bracket_nivel2_quarters', [])
    bracket_n2_semis = session.get('bracket_nivel2_semis', [])
    bracket_n2_final = session.get('bracket_nivel2_final', [])
    bracket_n2_champion = session.get('bracket_nivel2_champion', None)

    return render_template(
        'brackets.html',
        bracket_n1_quarters=bracket_n1_quarters,
        bracket_n1_semis=bracket_n1_semis,
        bracket_n1_final=bracket_n1_final,
        bracket_n1_champion=bracket_n1_champion,
        bracket_n2_quarters=bracket_n2_quarters,
        bracket_n2_semis=bracket_n2_semis,
        bracket_n2_final=bracket_n2_final,
        bracket_n2_champion=bracket_n2_champion
    )


@bracket_bp.route('/reset/<level>', methods=['GET', 'POST'])
@login_required
@handle_errors
def reset_bracket(level):
    """
    Resetear un bracket completo.
    """
    try:
        session[f'bracket_{level}_quarters'] = []
        session[f'bracket_{level}_semis'] = []
        session[f'bracket_{level}_final'] = []
        session[f'bracket_{level}_champion'] = None
        session.modified = True

        flash(f'Bracket de {level} reiniciado correctamente', 'success')
    except Exception as e:
        flash(f'Error al reiniciar: {str(e)}', 'error')

    return redirect(url_for('bracket.view_brackets'))