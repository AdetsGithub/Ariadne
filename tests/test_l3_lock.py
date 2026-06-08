"""L3 locked_to_mode — Franken-session prevention."""

from ariadne.session import SessionSyncService
from ariadne.unlockers import L3_MODE, build_unlocker_request_url


def test_lock_to_mode_forces_effective_transport():
    svc = SessionSyncService(impersonate_profiles=["chrome124"])
    sess = svc.get_or_create("host:l3.test")
    assert svc.effective_transport(sess.session_id, "L1_impersonate") == "L1_impersonate"
    svc.lock_to_mode(sess.session_id, L3_MODE)
    assert sess.locked_to_mode == L3_MODE
    assert svc.effective_transport(sess.session_id, "L1_impersonate") == L3_MODE
    assert svc.effective_transport(sess.session_id, "L2_browser") == L3_MODE


def test_l3_cookies_isolated_from_l1_jar():
    svc = SessionSyncService(impersonate_profiles=["chrome124"])
    sess = svc.get_or_create("host:iso.test")
    svc.set_cookies(sess, {"session": "ok"})
    svc.lock_to_mode(sess.session_id, L3_MODE)
    svc.set_l3_cookies(sess, {"cf_clearance": "vendor-bound"})
    assert svc.get_cookies(sess) == {"session": "ok"}
    assert "cf_clearance" not in svc.get_cookies(sess)
    assert sess.l3_cookie_jar["cf_clearance"] == "vendor-bound"


def test_burn_session_required_to_leave_l3():
    svc = SessionSyncService(impersonate_profiles=["chrome124"])
    sess = svc.get_or_create("host:burn.test")
    svc.lock_to_mode(sess.session_id, L3_MODE)
    svc.set_l3_cookies(sess, {"cf_clearance": "x"})
    svc.burn_session(sess.session_id, reason="leave_l3")
    fresh = svc.get_or_create("host:burn.test")
    assert fresh.locked_to_mode is None
    assert fresh.l3_cookie_jar == {}
    assert svc.effective_transport(fresh.session_id, "L1_impersonate") == "L1_impersonate"


def test_unlocker_url_template():
    url = build_unlocker_request_url(
        "https://target.example/path",
        "https://api.example/?key=K&url={url}",
    )
    assert "target.example" in url
    assert url.startswith("https://api.example/")
