"""Post-solve sibling stagger — prevent micro-herd cadence burns."""

import time

from ariadne.session import ChallengeState, SessionSyncService


def test_wake_index_increments_after_solve():
    svc = SessionSyncService(impersonate_profiles=["chrome124"])
    sess = svc.get_or_create("host:wake.test")
    assert svc.try_begin_challenge(sess.session_id)
    svc.release_challenge(sess.session_id, ChallengeState.SOLVED)
    assert svc.clearance_age_seconds(sess.session_id) is not None
    assert svc.clearance_age_seconds(sess.session_id) < 1.0
    assert svc.next_sibling_wake_index(sess.session_id) == 0
    assert svc.next_sibling_wake_index(sess.session_id) == 1
    assert svc.next_sibling_wake_index(sess.session_id) == 2


def test_wake_index_resets_on_new_solve():
    svc = SessionSyncService(impersonate_profiles=["chrome124"])
    sess = svc.get_or_create("host:wake2.test")
    svc.try_begin_challenge(sess.session_id)
    svc.release_challenge(sess.session_id, ChallengeState.SOLVED)
    svc.next_sibling_wake_index(sess.session_id)
    svc.next_sibling_wake_index(sess.session_id)
    # New solve epoch resets counter
    assert svc.try_begin_challenge(sess.session_id)
    svc.release_challenge(sess.session_id, ChallengeState.SOLVED)
    assert svc.next_sibling_wake_index(sess.session_id) == 0


def test_stagger_delay_when_fresh():
    from scrapy.http import Request

    from ariadne.downloadermiddlewares.session_sync import SessionSyncMiddleware

    class FakeSettings:
        def getint(self, k, default=None):
            return default

        def getfloat(self, k, default=None):
            defaults = {
                "ARIADNE_CLEARANCE_WAIT_DELAY": 2.0,
                "ARIADNE_CLEARANCE_FRESH_WINDOW": 5.0,
                "ARIADNE_SIBLING_STAGGER_BASE": 0.5,
                "ARIADNE_SIBLING_STAGGER_MAX": 5.0,
            }
            return defaults.get(k, default)

        def getbool(self, k, default=None):
            if k == "ARIADNE_SIBLING_STAGGER_JITTER":
                return False
            return default

        def get(self, k, default=None):
            return default

    class FakeCrawler:
        settings = FakeSettings()

    mw = SessionSyncMiddleware(FakeCrawler())
    svc = SessionSyncService(impersonate_profiles=["chrome124"])
    sess = svc.get_or_create("host:stagger.test")
    svc.try_begin_challenge(sess.session_id)
    svc.release_challenge(sess.session_id, ChallengeState.SOLVED)

    req = Request("https://stagger.test/")
    d0 = mw._sibling_stagger_delay(svc, sess.session_id, req)
    d1 = mw._sibling_stagger_delay(svc, sess.session_id, req)
    assert d0 == 0.0  # index 0 → 0.5*0
    assert d1 == 0.5  # index 1 → 0.5*1

    # After fresh window, no stagger
    sess.clearance_solved_at = time.time() - 10.0
    assert mw._sibling_stagger_delay(svc, sess.session_id, req) == 0.0
