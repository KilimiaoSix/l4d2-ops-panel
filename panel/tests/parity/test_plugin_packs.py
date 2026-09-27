def test_plugin_pack_routes_auth_validation_and_no_read_side_effect(panel, api):
    routes = ['/api/plugin-packs/install', '/api/plugin-packs/recover', '/api/plugin-packs/cancel']
    assert panel.client().get('/api/plugin-packs').status_code == 401
    for route in routes: assert panel.client().post(route, json={}).status_code == 401
    result = api.get('/api/plugin-packs')
    assert result.status_code == 200 and result.json()['profiles']['minimal'] == ['minimal']
    assert result.json()['pending'] is None and result.headers['cache-control'] == 'no-store'
    for packs in (['unknown'], [], ['../../outside']):
        assert api.post('/api/plugin-packs/install', json={'packs': packs}).status_code == 400
    assert api.post('/api/plugin-packs/install', json={'url': 'https://invalid.test'}).status_code == 400
    assert api.post('/api/plugin-packs/install', json={'stop_game': 'true'}).status_code == 400
    assert api.post('/api/plugin-packs/install', json={}).status_code == 409
    assert api.post('/api/plugin-packs/cancel', json={}).status_code == 409
