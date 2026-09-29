from rostering.ingest.mapping import building_keys


def test_building_keys_ignore_diacritics_case_and_spacing():
    assert building_keys("Malá Strana") == building_keys("mala strana")
    assert building_keys("Karlín") == building_keys("Karlin")


def test_building_keys_treat_troja_and_impakt_troja_as_the_same_building():
    assert building_keys("Troja") & building_keys("Impakt + Troja")


def test_building_keys_of_different_buildings_are_disjoint():
    assert building_keys("Karlov").isdisjoint(building_keys("Karlín"))
    assert building_keys("Malá Strana").isdisjoint(building_keys("Troja"))


def test_building_keys_fall_back_to_normalized_text_for_unknown_names():
    assert building_keys("Nová Budova") == building_keys("nova_budova")
    assert building_keys("Nová Budova").isdisjoint(building_keys("Karlov"))
