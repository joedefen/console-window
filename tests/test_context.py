import warnings

import pytest

from console_window import Context


def test_abut_is_an_explicit_attribute():
    assert Context().abut is None
    assert Context(abut=[-5, 3]).abut == [-5, 3]
    assert Context(abut=-3).abut == -3


def test_decor_genre_is_not_pickable():
    assert Context(genre='DECOR').pickable is False


def test_other_genres_honour_pickable():
    assert Context(genre='app').pickable is True
    assert Context(genre='app', pickable=False).pickable is False


def test_custom_attributes_allowed_without_warning():
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        ctx = Context(genre='app', app_name='firefox', installed=True, item=object())
    assert ctx.app_name == 'firefox'
    assert ctx.installed is True
    assert hasattr(ctx, 'item')


def test_near_miss_typo_of_genre_warns():
    with pytest.warns(UserWarning):
        ctx = Context(genere='app')
    # The attribute is still attached (behaviour preserved), but loudly flagged.
    assert ctx.genere == 'app'


def test_near_miss_typo_of_abut_warns():
    with pytest.warns(UserWarning):
        Context(abutt=[-5, 3])


def test_known_attrs_contains_engine_fields():
    assert Context.KNOWN_ATTRS == frozenset({'genre', 'pickable', 'abut'})
