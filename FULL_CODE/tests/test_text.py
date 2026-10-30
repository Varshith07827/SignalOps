import pandas as pd

from voice_of_store.text import detect_language, normalise, resolve_stores


def test_normalise_drops_call_centre_greeting():
    text = "Agent: Namaste, Saffron care, how may I help? Customer: Freezer NOT cold   since Monday"
    assert normalise(text) == "freezer not cold since monday"


def test_normalise_keeps_plain_text():
    assert normalise("  Milk OVER by 9am ") == "milk over by 9am"


def test_resolve_prefers_store_id_then_locality(stores):
    feedback = pd.DataFrame(
        {
            "store_id": ["ST-CCCCC", None, None, None, None],
            "text": [
                "at Kothrud the fridge broke",  # store_id wins over the named locality
                "Saffron Express VASHI, milk finished",
                "kothrud and vashi both bad",  # two localities: ambiguous, stays unknown
                "no store named here",
                "kothrudxyz is not a locality",  # word boundary: no partial matches
            ],
        }
    )
    resolved = resolve_stores(feedback, stores)
    assert resolved[:2].tolist() == ["ST-CCCCC", "ST-BBBBB"]
    assert resolved[2:].isna().all()


def test_resolve_multiword_locality(stores):
    feedback = pd.DataFrame({"store_id": [None], "text": ["queue at the MG Road store was long"]})
    assert resolve_stores(feedback, stores).tolist() == ["ST-CCCCC"]


def test_detect_language_varieties():
    assert detect_language("The freezer was not cold and milk was sour") == "english"
    assert detect_language("doodh khatam hai aur koi staff nahi tha") == "hinglish"
    assert detect_language("inga stock illa, romba mosam, sollunga") == "tamil"
    assert detect_language("dudh sampla aahe ani staff kahi madat nahi kara") == "marathi"


def test_detect_language_empty_text_is_english():
    assert detect_language("") == "english"
