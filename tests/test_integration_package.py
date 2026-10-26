"""Release packaging must be deterministic and incapable of including lab secrets."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('integration_release', ROOT / 'tools/check_integration.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class IntegrationReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / 'custom_components/mower_coordinator', self.root / 'custom_components/mower_coordinator', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for name in ('hacs.json', 'LICENSE'):
            shutil.copyfile(ROOT / name, self.root / name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_reproducible_archive_excludes_lab_and_ignored_outputs(self):
        for name in ('lab/.evidence/auth.json', 'local/settings.json', 'build/private.json'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('private test marker')
        first, second = self.root / 'one.zip', self.root / 'two.zip'
        self.assertEqual(release.build_archive(first, self.root), release.build_archive(second, self.root))
        with zipfile.ZipFile(first) as archive:
            self.assertTrue(all(name.startswith(release.PREFIX) for name in archive.namelist()))
            self.assertFalse(any(b'private test marker' in archive.read(name) for name in archive.namelist()))
            self.assertIsNone(archive.testzip())

    def test_unexpected_component_file_is_rejected(self):
        path = self.root / 'custom_components/mower_coordinator/secrets.env'
        path.write_text('not published')
        with self.assertRaisesRegex(ValueError, 'Unexpected release file'):
            release.component_files(self.root)

    def test_symlink_is_rejected(self):
        path = self.root / 'custom_components/mower_coordinator/linked.py'
        path.symlink_to(self.root / 'LICENSE')
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            release.component_files(self.root)

    def test_archive_extra_file_is_rejected(self):
        path = self.root / 'release.zip'
        release.build_archive(path, self.root)
        with zipfile.ZipFile(path, 'a') as archive:
            archive.writestr('lab/auth.json', '{}')
        with self.assertRaisesRegex(ValueError, 'file list'):
            release.validate_archive(path, self.root)

    def test_stale_translation_is_rejected(self):
        path = self.root / 'custom_components/mower_coordinator/translations/en.json'
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'English translation'):
            release.validate_metadata(self.root)
