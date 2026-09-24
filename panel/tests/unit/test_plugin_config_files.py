from concurrent.futures import ThreadPoolExecutor
import hashlib

import pytest

from l4d2panel.integrations.plugin_config import ConfigFiles, ConfigProblem, validate_updates


STANDARD = '// ConVars for plugin "sample.smx"\n// Delay in seconds\n// Default: "1"\n// Minimum: "0.000000"\n// Maximum: "10.000000"\n  sample_delay   "1"  // keep me\n\n// Label\n// Default: ""\nsample_label ""\n'


@pytest.fixture
def configs(tmp_path):
    root = tmp_path / 'game/cfg/sourcemod'
    root.mkdir(parents=True)
    (root / 'sample.cfg').write_text(STANDARD)
    return ConfigFiles(root, tmp_path / 'backups'), root


def test_read_metadata_and_save_preserves_bom_crlf_unknown_lines_mode(configs):
    files, root = configs
    original = b'\xef\xbb\xbf' + (STANDARD + '// Keep this comment\n').replace('\n', '\r\n').encode()
    path = root / 'sample.cfg'
    path.write_bytes(original)
    path.chmod(0o640)
    doc = files.read('sample.cfg')
    assert doc['revision'] == hashlib.sha256(original).hexdigest()
    assert doc['encoding'] == 'utf-8-sig'
    delay, label = doc['parameters']
    assert delay == {'name': 'sample_delay', 'value': '1', 'default': '1', 'min': '0.000000', 'max': '10.000000', 'description': 'Delay in seconds', 'type': 'number', 'editable': True, 'reason': None}
    assert label['type'] == 'text' and label['value'] == ''
    saved, backup = files.save('sample.cfg', doc['revision'], {'sample_delay': '0', 'sample_label': 'hello world'})
    assert backup and saved['backups'][0]['id'] == backup
    assert isinstance(saved['backups'][0]['created'], (int, float))
    assert path.read_bytes() == original.replace(b'sample_delay   "1"', b'sample_delay   "0"').replace(b'sample_label ""', b'sample_label "hello world"')
    assert path.stat().st_mode & 0o777 == 0o640
    restored, _ = files.restore('sample.cfg', saved['revision'], backup)
    assert path.read_bytes() == original and restored['revision'] == doc['revision']


@pytest.mark.parametrize('value', ['-1', '10.01', 'NaN', 'Infinity', '', '1_0', '1;quit', 'a"b', 'a\\b', 'a\nb', '\x00', '中', 'x' * 255])
def test_invalid_updates_never_write(configs, value):
    files, root = configs
    doc = files.read('sample.cfg')
    with pytest.raises(ConfigProblem):
        files.save('sample.cfg', doc['revision'], {'sample_delay': value})
    assert (root / 'sample.cfg').read_text() == STANDARD
    assert files.read('sample.cfg')['backups'] == []


def test_empty_string_and_zero_bounds_are_valid_and_noop_has_no_backup(configs):
    files, _ = configs
    doc = files.read('sample.cfg')
    assert validate_updates(doc, {'sample_label': '', 'sample_delay': '0'}) == {'sample_label': '', 'sample_delay': '0'}
    assert files.save('sample.cfg', doc['revision'], {'sample_label': ''})[1] is None
    for bad in ({'unknown': '1'}, {'sample_label': 1}, [], {'sample_label': 'a;quit'}):
        with pytest.raises(ConfigProblem):
            validate_updates(doc, bad)


def test_duplicates_mixed_commands_and_unproven_values_are_readonly(configs):
    files, root = configs
    (root / 'sample.cfg').write_text(STANDARD + 'sample_delay "2"\n// Default: "1"\nunsafe "1"; quit\nplain "0"\n// Default: "x"\nexec "other.cfg"\n')
    doc = files.read('sample.cfg')
    params = {p['name']: p for p in doc['parameters']}
    assert not params['sample_delay']['editable']
    assert not params['unsafe']['editable']
    assert not params['plain']['editable']
    assert 'exec' not in params
    for key in ('sample_delay', 'unsafe', 'plain', 'exec'):
        with pytest.raises(ConfigProblem):
            validate_updates(doc, {key: '1'})


def test_revision_conflicts_and_concurrent_writers(configs):
    files, _ = configs
    doc = files.read('sample.cfg')
    def save(value):
        try:
            files.save('sample.cfg', doc['revision'], {'sample_delay': value})
            return 'ok'
        except ConfigProblem as error:
            return error.kind
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(save, ['2', '3'])) == ['conflict', 'ok']
    with pytest.raises(ConfigProblem) as error:
        files.restore('sample.cfg', doc['revision'], files.read('sample.cfg')['backups'][0]['id'])
    assert error.value.kind == 'conflict'


@pytest.mark.parametrize('name', ['../server.cfg', '/server.cfg', 'sub/../sample.cfg', 'x.txt', 'a\\sample.cfg', '', './sample.cfg'])
def test_path_escape_rejected(configs, name):
    files, _ = configs
    with pytest.raises(ConfigProblem):
        files.read(name)


def test_symlink_files_and_directories_rejected(configs, tmp_path):
    files, root = configs
    external = tmp_path / 'external'
    external.mkdir()
    (external / 'sample.cfg').write_text(STANDARD)
    (root / 'link.cfg').symlink_to(external / 'sample.cfg')
    (root / 'linked').symlink_to(external, target_is_directory=True)
    for file in ('link.cfg', 'linked/sample.cfg'):
        with pytest.raises(ConfigProblem):
            files.read(file)
    assert files.discover('sample.smx') == [{'name': 'sample.cfg', 'source': 'header'}]


def test_discovery_header_precedence_filename_fallback_and_nested(configs):
    files, root = configs
    (root / 'sample.cfg').write_text('// ConVars for plugin "other.smx"\n')
    (root / 'custom.cfg').write_text(STANDARD)
    (root / 'nested').mkdir()
    (root / 'nested/sample.cfg').write_text('// fallback\n')
    assert files.discover('sample.smx') == [{'name': 'custom.cfg', 'source': 'header'}, {'name': 'nested/sample.cfg', 'source': 'filename'}]


def test_encoding_size_missing_and_backup_binding(configs):
    files, root = configs
    doc = files.read('sample.cfg')
    saved, backup = files.save('sample.cfg', doc['revision'], {'sample_delay': '2'})
    (root / 'other.cfg').write_text(STANDARD)
    for name, data in [('latin.cfg', b'// caf\xe9'), ('huge.cfg', b'x' * (512 * 1024 + 1))]:
        (root / name).write_bytes(data)
        with pytest.raises(ConfigProblem):
            files.read(name)
    with pytest.raises(ConfigProblem) as error:
        files.read('missing.cfg')
    assert error.value.kind == 'missing'
    for target, revision, identifier in [('other.cfg', doc['revision'], backup), ('sample.cfg', saved['revision'], '../x')]:
        with pytest.raises(ConfigProblem):
            files.restore(target, revision, identifier)


def test_backup_retention_keeps_twenty_without_removing_unknown_files(configs):
    files, _ = configs
    doc = files.read('sample.cfg')
    doc, _ = files.save('sample.cfg', doc['revision'], {'sample_label': 'initial'})
    directory = next(files.backup_root.iterdir())
    foreign = directory / 'manual-backup.cfg'
    foreign.write_text('keep')
    for i in range(25):
        doc, _ = files.save('sample.cfg', doc['revision'], {'sample_label': str(i)})
    assert len(doc['backups']) == 20
    assert foreign.read_text() == 'keep'


@pytest.mark.parametrize('metadata', ['// Minimum: "NaN"', '// Minimum: "2"\n// Maximum: "1"', '// Minimum: nope', '// Default: "2"'])
def test_ambiguous_metadata_is_readonly(configs, metadata):
    files, root = configs
    (root / 'sample.cfg').write_text('// Default: "1"\n' + metadata + '\nsetting "1"\n')
    assert not files.read('sample.cfg')['parameters'][0]['editable']


def test_case_variant_duplicate_and_quoted_unknown_syntax_are_readonly(configs):
    files, root = configs
    path = root / 'sample.cfg'
    path.write_text(STANDARD + 'SAMPLE_DELAY "2"\n')
    assert not files.read('sample.cfg')['parameters'][0]['editable']
    path.write_text(STANDARD + '"sample_delay" "2"\n')
    assert not files.read('sample.cfg')['parameters'][0]['editable']


def test_unquoted_parameter_and_no_numeric_inference_from_default(configs):
    files, root = configs
    path = root / 'sample.cfg'
    path.write_text('// Default: "0"\nflag 0 // note')
    doc = files.read('sample.cfg')
    assert doc['parameters'][0]['type'] == 'text'
    files.save('sample.cfg', doc['revision'], {'flag': ''})
    assert path.read_text() == '// Default: "0"\nflag "" // note'


@pytest.mark.parametrize('command', ['exec other.cfg', 'sm_cvar sample_delay 5', 'sample_label "a";sample_delay 5', '/*\nsample_delay 5\n*/'])
def test_files_with_commands_are_entirely_readonly(configs, command):
    files, root = configs
    (root / 'sample.cfg').write_text(STANDARD + command + '\n')
    assert all(not p['editable'] for p in files.read('sample.cfg')['parameters'])


def test_cleanup_failure_does_not_turn_successful_write_into_failure(configs, monkeypatch):
    files, root = configs
    doc = files.read('sample.cfg')
    for i in range(20):
        doc, _ = files.save('sample.cfg', doc['revision'], {'sample_label': str(i)})
    def fail(*args, **kwargs):
        raise OSError('read-only backup directory')
    monkeypatch.setattr(type(root), 'unlink', fail)
    saved, backup = files.save('sample.cfg', doc['revision'], {'sample_label': 'latest'})
    assert backup and 'sample_label "latest"' in (root / 'sample.cfg').read_text()
    assert any('未能清理' in warning for warning in saved['warnings'])


def test_replacement_failure_preserves_original_and_leaves_no_backup(configs, monkeypatch):
    files, root = configs
    doc = files.read('sample.cfg')
    def fail(*args):
        raise OSError('disk failure')
    monkeypatch.setattr('l4d2panel.integrations.plugin_config.os.replace', fail)
    with pytest.raises(OSError, match='disk failure'):
        files.save('sample.cfg', doc['revision'], {'sample_delay': '2'})
    assert (root / 'sample.cfg').read_text() == STANDARD
    assert files.read('sample.cfg')['backups'] == []
    assert list(root.iterdir()) == [root / 'sample.cfg']


def test_discovery_ignores_unsupported_encoding_and_rejects_unbounded_scan(configs):
    files, root = configs
    (root / 'bad.cfg').write_bytes(b'\xff')
    assert len(files.discover('sample.smx')) == 1
    for i in range(511):
        (root / f'extra{i}.cfg').write_text('')
    with pytest.raises(ConfigProblem, match='512'):
        files.discover('sample.smx')
