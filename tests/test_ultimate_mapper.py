"""Per-action persisted mapper settings and launch readiness."""
from contextlib import closing
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml
from PyQt6.QtWidgets import QApplication

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mapper_plugin_test', root / '__init__.py', submodule_search_locations=[str(root)])
module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
from mapper_plugin_test import mapper
from mapper_plugin_test.plugin import Plugin


class MapperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'games').mkdir()
        self.path = self.root / 'games/example.yml'
        self.config = {'game': {'exe': '/games/example.exe', 'prefix': '/prefix/example'},
                       'system': {'env': {'KEEP': 'yes'}, 'gamemode': False}, 'wine': {'version': 'ge-proton'}}
        self.path.write_text(yaml.safe_dump(self.config))
        self.other = self.root / 'games/other.yml'; self.other.write_bytes(self.path.read_bytes())
        with closing(sqlite3.connect(self.root / 'pga.db')) as db, db:
            db.execute('CREATE TABLE games(id INTEGER, runner TEXT, configpath TEXT)')
            db.executemany('INSERT INTO games VALUES(?,?,?)', [(1, 'wine', 'example'), (2, 'wine', 'other'), (3, 'linux', 'other')])

    def test_toggle_waits_for_save_and_reopens(self):
        original_other = self.other.read_bytes()
        with patch('mapper_plugin_test.plugin.lutris_runtime') as runtime:
            runtime.return_value.library_path.return_value = self.root
            editor = Plugin().create_action_settings({'GameId': '1', 'Integration': 'LutrisIntegration'})
            editor.use_ultimate_mapper.setChecked(True)
            action = dict(editor.collect(), Integration='LutrisIntegration', GameId='1')
            self.assertFalse(mapper.configured_for_mapper(self.root, 1))
            with mapper.save_actions({'PlayActions': [action]}, self.root):
                pass
            self.assertTrue(mapper.configured_for_mapper(self.root, 1))
            self.assertEqual(self.other.read_bytes(), original_other)
            reopened = Plugin().create_action_settings({'GameId': '1', 'Integration': 'LutrisIntegration'})
            self.assertTrue(reopened.use_ultimate_mapper.isChecked())
            reopened.use_ultimate_mapper.setChecked(False)
            self.assertTrue(mapper.configured_for_mapper(self.root, 1))
            action = dict(reopened.collect(), Integration='LutrisIntegration', GameId='1')
            with mapper.save_actions({'PlayActions': [action]}, self.root):
                pass
            self.assertEqual(yaml.safe_load(self.path.read_text()), self.config)
            editor.close(); reopened.close()

    def test_existing_environment_restored(self):
        config = yaml.safe_load(self.path.read_text())
        config['system']['env']['PROTON_USE_SDL'] = '0'
        config['system']['env']['SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT'] = '0xabcd/0x1234'
        self.path.write_text(yaml.safe_dump(config))
        mapper.update_configuration(self.path, True)
        self.assertTrue(mapper.enabled(yaml.safe_load(self.path.read_text())))
        mapper.update_configuration(self.path, False)
        self.assertEqual(yaml.safe_load(self.path.read_text()), config)

    def test_legacy_elden_ring_settings_are_detected_and_can_be_disabled(self):
        config = yaml.safe_load(self.path.read_text()); config['system']['env'].update(mapper.ENVIRONMENT)
        self.path.write_text(yaml.safe_dump(config))
        self.assertTrue(mapper.configured_for_mapper(self.root, 1))
        mapper.update_configuration(self.path, False)
        self.assertEqual(yaml.safe_load(self.path.read_text()), self.config)

    def test_native_games_and_unsafe_paths_are_excluded(self):
        self.assertFalse(mapper.configured_for_mapper(self.root, 3))
        with closing(sqlite3.connect(self.root / 'pga.db')) as db, db:
            db.execute("UPDATE games SET configpath='../unsafe' WHERE id=1")
        with self.assertRaises(ValueError): mapper.configuration_path(self.root, 1)
        with self.assertRaises(ValueError): mapper.configuration_path(self.root, 'bad')

    def test_launch_checks_only_the_selected_enabled_lutris_action(self):
        plugin = Plugin()
        with patch('mapper_plugin_test.plugin.lutris_runtime') as runtime, \
             patch.object(mapper, 'ensure_controller') as ready:
            runtime.return_value.library_path.return_value = self.root
            other = {'Integration': 'LutrisIntegration', 'GameId': '2'}
            selected = {'Integration': 'LutrisIntegration', 'GameId': '1'}
            self.assertTrue(plugin.before_action_launch(None, {}, other))
            ready.assert_not_called()
            mapper.update_configuration(self.path, True)
            self.assertTrue(plugin.before_action_launch(None, {}, selected))
            ready.assert_called_once_with(None)
            ready.side_effect = ValueError('cancelled')
            with self.assertRaises(ValueError): plugin.before_action_launch(None, {}, selected)
            self.assertTrue(plugin.before_action_launch(None, {}, {'Integration': 'SteamIntegration'}))

    def test_controller_detection_requires_name_and_id(self):
        device = self.root / 'event1/device'; (device / 'id').mkdir(parents=True)
        (device / 'name').write_text('Ultimate Mapper Virtual Gamepad')
        (device / 'id/vendor').write_text('0001'); (device / 'id/product').write_text('0001')
        self.assertTrue(mapper.controller_available(self.root))
        (device / 'id/product').write_text('0002')
        self.assertFalse(mapper.controller_available(self.root))

    def test_cancel_discards_toggle_without_writing(self):
        original = self.path.read_bytes()
        with patch('mapper_plugin_test.plugin.lutris_runtime') as runtime:
            runtime.return_value.library_path.return_value = self.root
            editor = Plugin().create_action_settings({'GameId': '1', 'Integration': 'LutrisIntegration'})
        editor.use_ultimate_mapper.setChecked(True)
        editor.collect()
        editor.close()
        self.assertEqual(self.path.read_bytes(), original)

    def test_missing_controller_cancel_does_not_start_mapper(self):
        from PyQt6.QtWidgets import QMessageBox
        with patch.object(mapper, 'controller_available', return_value=False), \
             patch('PyQt6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Cancel), \
             patch.object(mapper, 'start_mapper') as start:
            with self.assertRaises(ValueError): mapper.ensure_controller()
            start.assert_not_called()

    def test_missing_controller_can_be_started_before_launch(self):
        from PyQt6.QtWidgets import QMessageBox
        with patch.object(mapper, 'controller_available', side_effect=[False, True]), \
             patch('PyQt6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
             patch.object(mapper, 'start_mapper') as start:
            mapper.ensure_controller()
            start.assert_called_once()

    def test_later_user_environment_edits_are_not_overwritten(self):
        mapper.update_configuration(self.path, True)
        config = yaml.safe_load(self.path.read_text())
        config['system']['env']['CUSTOM'] = 'preserve'
        self.path.write_text(yaml.safe_dump(config))
        mapper.update_configuration(self.path, False)
        result = yaml.safe_load(self.path.read_text())
        self.assertEqual(result['system']['env'], {'KEEP': 'yes', 'CUSTOM': 'preserve'})

    def test_changed_action_id_updates_only_new_entry_on_save(self):
        original = self.path.read_bytes()
        with patch('mapper_plugin_test.plugin.lutris_runtime') as runtime:
            runtime.return_value.library_path.return_value = self.root
            editor = Plugin().create_action_settings({'GameId': '1', 'Integration': 'LutrisIntegration'})
        editor.use_ultimate_mapper.setChecked(True)
        action = dict(editor.collect(), Integration='LutrisIntegration', GameId='2')
        with mapper.save_actions({'PlayActions': [action]}, self.root):
            pass
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(mapper.configured_for_mapper(self.root, 2))
        editor.close()

    def test_failed_library_save_rolls_back_lutris_config(self):
        from playlite.editor import _save_game
        original = self.path.read_bytes()
        action = {'Integration': 'LutrisIntegration', 'GameId': '1', 'UltimateMapper': True}
        plugin = Plugin()
        with patch('mapper_plugin_test.plugin.lutris_runtime') as runtime, \
             patch('playlite.providers.discover_plugins', return_value={'UltimateMapper': plugin}), \
             patch('playlite.editor._persist_game', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                runtime.return_value.library_path.return_value = self.root
                _save_game(self.root / 'library', [], {'PlayActions': [action]})
        self.assertEqual(self.path.read_bytes(), original)

    def test_library_save_commits_action_and_configuration(self):
        import json
        from playlite.editor import save_game
        action = {'Integration': 'LutrisIntegration', 'GameId': '1', 'UltimateMapper': True}
        game = {'Id': 'test-game', 'Name': 'Example', 'PlayActions': [action]}
        plugin = Plugin()
        with patch('mapper_plugin_test.plugin.lutris_runtime') as runtime, \
             patch('playlite.providers.discover_plugins', return_value={'UltimateMapper': plugin}):
            runtime.return_value.library_path.return_value = self.root
            save_game(self.root / 'library', [], game)
        self.assertTrue(mapper.configured_for_mapper(self.root, 1))
        saved = json.loads((self.root / 'library/library.json').read_text())[0]
        self.assertTrue(saved['PlayActions'][0]['UltimateMapper'])

    def test_conflicting_actions_are_rejected_before_writing(self):
        original = self.path.read_bytes()
        actions = [{'Integration': 'LutrisIntegration', 'GameId': '1', 'UltimateMapper': value}
                   for value in (True, False)]
        with self.assertRaises(ValueError):
            with mapper.save_actions({'PlayActions': actions}, self.root):
                pass
        self.assertEqual(self.path.read_bytes(), original)

    def test_contribution_is_primary_transparent_and_lutris_only(self):
        from PyQt6.QtWidgets import QLabel
        plugin = Plugin()
        self.assertIsNone(plugin.create_action_settings({'Integration': 'SteamIntegration'}))
        with patch('mapper_plugin_test.plugin.lutris_runtime') as runtime:
            runtime.return_value.library_path.return_value = self.root
            widget = plugin.create_action_settings({'Integration': 'LutrisIntegration', 'GameId': '1'})
        self.assertEqual(widget.action_settings_position, 'primary')
        self.assertFalse(widget.findChildren(QLabel))
        self.assertIn('transparent', widget.styleSheet())
        widget.close()

    def test_manifest_declares_lutris_dependency(self):
        import json
        from playlite.plugin_dependencies import dependencies, missing_dependencies
        manifest = json.loads((root / 'manifest.json').read_text())
        dependency = list(dependencies(manifest))[0]
        self.assertEqual(dependency['id'], 'LutrisIntegration')
        self.assertEqual(missing_dependencies(manifest, []), [dependency])
        installed = [{'id': 'LutrisIntegration', 'version': dependency['minimum_version'],
                      'repository': dependency['repository'], 'enabled': True}]
        self.assertEqual(missing_dependencies(manifest, installed), [])

    def test_primary_toggle_stays_visible_and_labels_are_transparent(self):
        from playlite.play_actions import PlayActionsEditor
        from playlite.providers import GameProvider
        from PyQt6.QtWidgets import QLabel
        provider = GameProvider(); provider.id = 'LutrisIntegration'; provider.name = 'Lutris Integration'
        plugin = Plugin()
        action = {'Name': 'Play Example', 'Integration': 'LutrisIntegration', 'GameId': '1'}
        with patch('playlite.providers.discover_plugins', return_value={'LutrisIntegration': provider, 'UltimateMapper': plugin}), \
             patch('mapper_plugin_test.plugin.lutris_runtime') as runtime:
            runtime.return_value.library_path.return_value = self.root
            editor = PlayActionsEditor({'PlayActions': [action]}, [provider])
        editor.resize(900, 500); editor.show(); self.app.processEvents()
        card = editor.cards[0]
        contribution = card.settings.contributions[0]
        self.assertTrue(contribution.use_ultimate_mapper.isVisible())
        self.assertFalse(card.settings.settings.advanced_button.isChecked())
        self.assertFalse(contribution.findChildren(QLabel))
        self.assertIn('transparent', card.default.styleSheet())
        self.assertIn('transparent', card.game_id_label.styleSheet())
        self.assertIn('transparent', card.settings.styleSheet())
        editor.close()
