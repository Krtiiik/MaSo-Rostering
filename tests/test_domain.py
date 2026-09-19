from rostering.domain import Preference, Role, normalize_name


def test_role_values_have_diacritics():
    assert Role.Menic.value == "Měnič"
    assert Role.Kreslic.value == "Kreslič"


def test_preference_ordering():
    assert Preference.Ano > Preference.Klidne > Preference.Nevadi > Preference.Spise_ne > Preference.Ne


def test_normalize_name_strips_diacritics_and_whitespace():
    assert normalize_name("Měnič") == normalize_name("menic")
    assert normalize_name("Malá Strana") == normalize_name("mala_strana")
    assert normalize_name(None) == ""
