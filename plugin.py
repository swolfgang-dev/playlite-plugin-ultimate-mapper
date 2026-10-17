"""Ultimate Mapper controls contributed to Lutris play actions."""
import importlib
from playlite.providers import GenericPlugin, discover_plugins
from . import mapper


def lutris_runtime():
    integration = discover_plugins().get('LutrisIntegration')
    if integration is None:
        raise ValueError('Lutris Integration must be installed and enabled to use Ultimate Mapper.')
    return importlib.import_module(type(integration).__module__ + '.runtime')


class Plugin(GenericPlugin):
    def create_action_settings(self, action, parent=None):
        if action.get('Integration') == 'LutrisIntegration':
            return mapper.ActionSettings(action, lutris_runtime().library_path(), parent)
        return None

    def save_action_settings(self, game):
        return mapper.save_actions(game, lutris_runtime().library_path())

    def before_action_launch(self, window, game, action):
        if action.get('Integration') == 'LutrisIntegration':
            if mapper.configured_for_mapper(lutris_runtime().library_path(), action.get('GameId')):
                mapper.ensure_controller(window)
        return True
