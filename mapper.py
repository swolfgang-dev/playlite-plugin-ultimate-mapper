"""Play-action controller isolation stored in that entry's Lutris configuration."""
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
from contextlib import closing, contextmanager

import yaml
from PyQt6.QtCore import QSaveFile, QIODevice

ENVIRONMENT = {'PROTON_USE_SDL': '1',
               'SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT': '0x0001/0x0001'}
MARKER = 'playlite_ultimate_mapper'


def configuration_path(root, identity):
    identity = str(identity or '')
    if not identity.isascii() or not identity.isdigit() or int(identity) < 1:
        raise ValueError('Save a valid Lutris game ID before changing Ultimate Mapper.')
    root = Path(root)
    with closing(sqlite3.connect((root / 'pga.db').as_uri() + '?mode=ro', uri=True)) as db:
        row = db.execute('SELECT runner,configpath FROM games WHERE id=?', (int(identity),)).fetchone()
    if row is None or row[0] != 'wine':
        raise ValueError('Ultimate Mapper is available only for Windows/Wine play actions.')
    name = row[1]
    if not isinstance(name, str) or not name or Path(name).name != name or '\\' in name:
        raise ValueError('Invalid Lutris configuration path.')
    path = root / 'games' / (name + '.yml')
    if path.is_symlink() or path.resolve().parent != (root / 'games').resolve():
        raise ValueError('Unsafe Lutris configuration path.')
    return path


def read_configuration(path):
    config = yaml.safe_load(path.read_text())
    if (not isinstance(config, dict) or not isinstance(config.get('system', {}), dict)
            or not isinstance(config.get('system', {}).get('env', {}), dict)):
        raise ValueError('Invalid Lutris launch environment.')
    return config


def enabled(config):
    environment = config.get('system', {}).get('env', {})
    return all(str(environment.get(key, '')) == value for key, value in ENVIRONMENT.items())


def configured_for_mapper(root, identity):
    # Existing native entries and old Lutris databases keep their normal launch path.
    try:
        path = configuration_path(root, identity)
    except (ValueError, sqlite3.OperationalError):
        return False
    return enabled(read_configuration(path))


def update_configuration(path, use_mapper):
    original = path.read_bytes()
    config = read_configuration(path)
    if enabled(config) == use_mapper:
        return
    environment = config.setdefault('system', {}).setdefault('env', {})
    if use_mapper:
        prior = {key: environment.get(key) for key in ENVIRONMENT}
        marker = config.get(MARKER)
        if isinstance(marker, dict) and isinstance(marker.get('previous_environment'), dict):
            prior = {**prior, **marker['previous_environment']}
        config[MARKER] = {'previous_environment': prior}
        environment.update(ENVIRONMENT)
    else:
        marker = config.get(MARKER, {})
        prior = marker.get('previous_environment', {}) if isinstance(marker, dict) else {}
        for key, value in ENVIRONMENT.items():
            # Preserve a subsequently edited value instead of overwriting it.
            if str(environment.get(key, '')) != value:
                continue
            if key in prior and prior[key] is not None:
                environment[key] = prior[key]
            else:
                environment.pop(key, None)
        config.pop(MARKER, None)
        if not environment:
            config['system'].pop('env', None)
    if path.read_bytes() != original:
        raise ValueError('Lutris settings changed while saving. Reopen the play action and retry.')
    output = QSaveFile(str(path))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    encoded = yaml.safe_dump(config, sort_keys=False).encode()
    if output.write(encoded) != len(encoded):
        output.cancelWriting()
        raise OSError(output.errorString())
    if not output.commit():
        raise OSError(output.errorString())


def controller_available(root=Path('/sys/class/input')):
    for entry in root.glob('event*'):
        device = entry / 'device'
        try:
            if ((device / 'name').read_text().strip() == 'Ultimate Mapper Virtual Gamepad'
                    and int((device / 'id/vendor').read_text().strip(), 16) == 1
                    and int((device / 'id/product').read_text().strip(), 16) == 1):
                return True
        except (OSError, ValueError):
            continue
    return False


def start_mapper():
    from .plugin import lutris_runtime
    environment = lutris_runtime().environment
    command = shutil.which('ultimate-mapper')
    if command:
        return subprocess.Popen([command], start_new_session=True, env=environment())
    host = environment()
    home = Path(host.get('HOME', str(Path.home())))
    roots = [Path(host.get('XDG_DATA_HOME', str(home / '.local/share')))]
    roots.extend(Path(item) for item in host.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':') if item)
    desktop = next((str(root / 'applications/ultimate-mapper.desktop') for root in roots
                    if (root / 'applications/ultimate-mapper.desktop').is_file()), None)
    gio = shutil.which('gio')
    if not desktop or not gio:
        raise ValueError('Ultimate Mapper is not installed. Start it manually, then try again.')
    return subprocess.Popen([gio, 'launch', desktop], start_new_session=True, env=environment())


def ensure_controller(parent=None):
    if controller_available():
        return
    from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog
    from PyQt6.QtCore import Qt
    answer = QMessageBox.question(parent, 'Ultimate Mapper is not ready',
        'The virtual controller is unavailable. Start Ultimate Mapper before launching?',
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Yes)
    if answer != QMessageBox.StandardButton.Yes:
        raise ValueError('Launch cancelled. Enable Ultimate Mapper output or disable it for this play action.')
    start_mapper()
    progress = QProgressDialog('Waiting for Ultimate Mapper’s virtual controller…', 'Cancel', 0, 0, parent)
    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
    progress.setMinimumDuration(0)
    progress.show()
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if progress.wasCanceled():
                raise ValueError('Launch cancelled while waiting for Ultimate Mapper.')
            if controller_available():
                return
            time.sleep(.05)
        raise ValueError('The virtual controller did not become available. Connect the controller and enable Ultimate Mapper output, then try again.')
    finally:
        progress.close()


@contextmanager
def save_actions(game, root):
    changes = {}
    for action in game.get('PlayActions', []):
        if action.get('Integration') != 'LutrisIntegration' or 'UltimateMapper' not in action:
            continue
        checked = action['UltimateMapper']
        if type(checked) is not bool:
            raise ValueError('Ultimate Mapper must be enabled or disabled.')
        path = configuration_path(root, action.get('GameId'))
        read_configuration(path)
        if path in changes and changes[path] != checked:
            raise ValueError('Actions sharing a Lutris entry must use the same Ultimate Mapper setting.')
        changes[path] = checked
    originals = {}
    try:
        for path, checked in changes.items():
            original = path.read_bytes()
            update_configuration(path, checked)
            current = path.read_bytes()
            if current != original:
                originals[path] = (original, current)
        yield
    except BaseException:
        for path, (original, written) in reversed(list(originals.items())):
            if path.read_bytes() != written:
                raise ValueError('Lutris configuration changed during save; the newer changes were preserved.')
            output = QSaveFile(str(path))
            if not output.open(QIODevice.OpenModeFlag.WriteOnly):
                raise OSError(output.errorString())
            if output.write(original) != len(original):
                output.cancelWriting()
                raise OSError(output.errorString())
            if not output.commit():
                raise OSError(output.errorString())
        raise


from PyQt6.QtWidgets import QWidget, QCheckBox, QVBoxLayout


class ActionSettings(QWidget):
    action_settings_position = 'primary'

    def __init__(self, action, root, parent=None):
        super().__init__(parent)
        from playlite.theme import set_style
        self.setObjectName('ultimateMapperActionSettings')
        set_style(self, 'QWidget#ultimateMapperActionSettings, '
                        'QWidget#ultimateMapperActionSettings QCheckBox {'
                        'background: transparent; border: none;}')
        self.action = action
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.use_ultimate_mapper = QCheckBox('Use Ultimate Mapper for this play action')
        try:
            path = configuration_path(root, action.get('GameId'))
            self.initial_mapper = enabled(read_configuration(path))
            self.use_ultimate_mapper.setChecked(self.initial_mapper)
        except (OSError, ValueError, sqlite3.Error, yaml.YAMLError) as failure:
            self.initial_mapper = False
            self.use_ultimate_mapper.setEnabled(False)
            self.use_ultimate_mapper.setToolTip(str(failure))
        layout.addWidget(self.use_ultimate_mapper)

    def collect(self):
        if self.use_ultimate_mapper.isEnabled() and (
                self.use_ultimate_mapper.isChecked() != self.initial_mapper or 'UltimateMapper' in self.action):
            return {'UltimateMapper': self.use_ultimate_mapper.isChecked()}
        return {}
