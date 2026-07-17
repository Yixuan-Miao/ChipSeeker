import Science_Grabber as sg


def _item(title, abstract="", venue="Science"):
    return {
        "title": [title],
        "abstract": abstract,
        "container-title": [venue],
        "subject": [],
    }


def test_science_relevance_covers_broad_ai_and_quantum_computing():
    assert sg.is_relevant_record(_item("A foundation model for scientific discovery"))
    assert sg.is_relevant_record(_item("A fault-tolerant quantum algorithm"))
    assert sg.is_relevant_record(_item("A CMOS sensor interface chip"))


def test_science_relevance_rejects_biological_circuit_false_positive():
    assert not sg.is_relevant_record(_item("Machine learning of a neural circuit", "Brain circuit activity"))
