"""Open VacuGlide from the existing Director entry point."""
from .vacuglide_editor import show_editor


def show_vacuglide_panel(app):
    show_editor(app)
