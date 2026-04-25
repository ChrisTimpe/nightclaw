from nightclaw_monitor.store import Store


def test_apply_snapshot_populates_opstimeline_and_defaults_selection():
    store = Store()
    store.apply_snapshot({
        'sessions': [{'runid': 'RUN-1'}],
        'scrlast': None,
        'steptimes': {'RUN-1': ['a']},
        'opstimeline': {'RUN-1': [{'tier': 'T1', 'cmd': 'dispatch', 'ts': 'x'}]},
        'bridgeport': 8765,
        'privilege': 'rw',
    })
    assert store.state.selected_runid == 'RUN-1'
    assert store.state.opstimeline['RUN-1'][0]['cmd'] == 'dispatch'
