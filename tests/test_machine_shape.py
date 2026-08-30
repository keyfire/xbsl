from xbsl.translation.machine.shape import identifier

TERMS = {"task": "Task", "assignee": "Assignee"}


def test_prose_becomes_camel_case():
    assert identifier("Site address", TERMS, set()) == ("SiteAddress", "")


def test_articles_and_prepositions_go_away():
    assert identifier("the address of the site", TERMS, set()) == ("AddressSite", "")


def test_project_terms_win_over_the_service():
    assert identifier("software card", {"software": "Program"}, set()) == ("ProgramCard", "")


def test_american_spelling():
    assert identifier("colour catalogue", {}, set()) == ("ColorCatalog", "")


def test_a_taken_name_is_refused_with_a_reason():
    name, reason = identifier("Site address", TERMS, {"SiteAddress"})
    assert name == ""
    assert "SiteAddress" in reason


def test_what_cannot_become_an_identifier_is_refused():
    name, reason = identifier("42 %", {}, set())
    assert name == ""
    assert reason


def test_taken_name_in_different_case():
    name, reason = identifier("Site address", TERMS, {"siteaddress"})
    assert name == ""
    assert "siteaddress" in reason


def test_similar_name_in_different_case_is_not_taken():
    name, reason = identifier("Site address", TERMS, {"siteAddr"})
    assert name == "SiteAddress"
    assert reason == ""
