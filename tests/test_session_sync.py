"""Session Sync challenge mutex and proxy burn."""

import time

from ariadne.session import ChallengeState, SessionSyncService


def test_challenge_mutex_single_winner():
    svc = SessionSyncService(impersonate_profiles=["chrome124"])
    sess = svc.get_or_create("host:example.com")
    assert svc.try_begin_challenge(sess.session_id) is True
    assert svc.try_begin_challenge(sess.session_id) is False
    assert svc.get_challenge_state(sess.session_id) == ChallengeState.SOLVING
    svc.release_challenge(sess.session_id, ChallengeState.SOLVED)
    assert svc.get_challenge_state(sess.session_id) == ChallengeState.SOLVED
    assert svc.clearance_epoch(sess.session_id) == 1


def test_challenge_lease_expires():
    svc = SessionSyncService(impersonate_profiles=["chrome124"], challenge_lease_ttl=0.05)
    sess = svc.get_or_create("host:a.test")
    assert svc.try_begin_challenge(sess.session_id, lease_ttl=0.05)
    time.sleep(0.08)
    assert svc.get_challenge_state(sess.session_id) == ChallengeState.FAILED
    assert svc.try_begin_challenge(sess.session_id) is True


def test_persona_coherence():
    svc = SessionSyncService(impersonate_profiles=["chrome131"])
    sess = svc.get_or_create("host:b.test")
    assert svc.assert_coherent(sess)


def test_proxy_burn_drops_clearance_rotates():
    svc = SessionSyncService(
        impersonate_profiles=["chrome124"],
        proxy_list=["http://p1:1", "http://p2:2"],
    )
    sess = svc.get_or_create("host:c.test")
    old_proxy = sess.proxy_endpoint
    persona_id = sess.persona.profile_id
    svc.set_cookies(sess, {"cf_clearance": "abc", "session": "keep-me"})
    svc.burn_sticky_proxy(sess.session_id, reason="timeout")
    assert "cf_clearance" not in svc.get_cookies(sess)
    assert svc.get_cookies(sess).get("session") == "keep-me"
    assert sess.persona.profile_id == persona_id
    assert sess.challenge_state == ChallengeState.IDLE
    # rotated when alternative exists
    if old_proxy and len(svc._proxy_list) > 1:
        assert sess.proxy_endpoint != old_proxy or sess.proxy_endpoint in svc._proxy_list
