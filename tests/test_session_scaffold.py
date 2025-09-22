def test_session_scaffold_symbols_exist():
    from app.session.store import SessionStore
    from app.session.merge import extract_codes, merge_message, is_ready_for_confirmation, is_ready_to_search

    assert callable(SessionStore)
    assert callable(extract_codes)
    assert callable(merge_message)
    assert callable(is_ready_for_confirmation)
    assert callable(is_ready_to_search)

