def test_user_stats_page_includes_badges_context(auth_client):
    resp = auth_client.get("/user_stats")
    assert resp.status_code == 200
    # The word "Badges" should appear in the page (heading)
    assert b"Badges" in resp.data
