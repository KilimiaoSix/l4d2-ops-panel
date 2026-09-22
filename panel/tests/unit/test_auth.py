import time

from l4d2panel.services.auth import LoginLimiter, hash_pw, verify_pw


def test_password_hash_roundtrip_and_legacy_format():
    h = hash_pw('secret'); assert h.startswith('pbkdf2$200000$') and verify_pw('secret', h) and not verify_pw('Secret', h)
    legacy = hash_pw('pw', salt='00' * 16, it=1000)
    assert legacy == 'pbkdf2$1000$' + '00' * 16 + '$' + legacy.split('$')[-1] and verify_pw('pw', legacy)
    assert not verify_pw('pw', 'garbage') and not verify_pw('pw', '')


def test_login_limiter():
    lim = LoginLimiter(limit=3, window=0.3)
    for _ in range(2): lim.failed('1.1.1.1')
    assert not lim.locked('1.1.1.1')
    lim.failed('1.1.1.1'); assert lim.locked('1.1.1.1') and not lim.locked('2.2.2.2')
    time.sleep(0.35); assert not lim.locked('1.1.1.1')          # the lock expires
    lim.failed('1.1.1.1'); lim.reset('1.1.1.1'); assert not lim.locked('1.1.1.1')
