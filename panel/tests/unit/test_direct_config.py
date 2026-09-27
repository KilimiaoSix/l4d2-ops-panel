import pytest

from l4d2panel.integrations.game_mode_config import direct_assignments, rewrite_direct, ModeConfigError


def test_empty_password_roundtrip_and_omission_preserve_other_bytes():
    original = b'\xef\xbb\xbf// \xff legacy comment\r\nsv_password "old" // secret\r\nsm_cvar SV_PASSWORD second\r\nhostname "Old Name"\r\n'
    cleared = rewrite_direct(original, {'sv_password': '', 'hostname': 'New Name'})
    assert cleared == original.replace(b'"old"', b'""').replace(b'second', b'""').replace(b'Old Name', b'New Name')
    assert [row[2] for row in direct_assignments(cleared, 'sv_password')] == ['', '']
    reset = rewrite_direct(cleared, {'sv_password': 'a password / allowed'})
    assert [row[2] for row in direct_assignments(reset, 'sv_password')] == ['a password / allowed'] * 2
    assert rewrite_direct(reset, {'sv_region': '255'}).startswith(reset)
    assert rewrite_direct(reset, {'sv_password': 'a password / allowed'}) == reset


@pytest.mark.parametrize('value', ['bad;quit', 'bad"quote', 'bad\\escape', 'bad\nnewline', 'bad\x00null', '中文'])
def test_direct_values_reject_injection_before_rewriting(value):
    with pytest.raises(ModeConfigError): rewrite_direct(b'sv_password ""\n', {'sv_password': value})


@pytest.mark.parametrize('source', [b'sv_password a; quit\n', b'echo x; sv_password a\n',
    b'sv_password "unterminated\n', b'/* sv_password a */\n', b'sm_cvar sv_password a b\n'])
def test_direct_password_ambiguous_syntax_is_not_silently_rewritten(source):
    with pytest.raises(ModeConfigError): rewrite_direct(source, {'sv_password': 'new'})


def test_comments_and_quoted_other_commands_are_not_assignments():
    source = b'echo "sv_password example"\n// sv_password example\nhostname "A // B"\n'
    assert direct_assignments(source, 'sv_password') == []
    assert direct_assignments(source, 'hostname')[0][2] == 'A // B'
    assert rewrite_direct(source, {'sv_password': ''}) == source + b'sv_password ""\n'
    with pytest.raises(ModeConfigError): rewrite_direct(source, {'exec': 'bad.cfg'})
