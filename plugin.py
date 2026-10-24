"""Ultimate Mapper controls contributed to Lutris play actions."""
from playlite.providers import GenericPlugin
from . import mapper


def library_path(action):
    from pathlib import Path
    from playlite.lutris_library import library_databases
    database = action.get('LutrisDatabase')
    if database:
        return Path(database).expanduser().resolve()
    databases = library_databases()
    if len(databases) != 1:
        raise ValueError('Select a Lutris library for this play action.')
    return databases[0]


class Plugin(GenericPlugin):
    def create_action_settings(self, action, parent=None):
        if action.get('Integration') == 'LutrisIntegration':
            return mapper.ActionSettings(action, library_path, parent)
        return None

    def save_action_settings(self, game):
        return mapper.save_actions(game, library_path)

    def before_action_launch(self, window, game, action):
        if action.get('Integration') == 'LutrisIntegration':
            if mapper.configured_for_mapper(library_path(action), action.get('GameId')):
                mapper.ensure_controller(window)
        return True
