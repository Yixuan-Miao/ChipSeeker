from chipseeker.literature_relevance import is_relevant_literature, relevance_labels


def test_relevance_covers_ic_ai_hardware_and_quantum_computing():
    assert "chips" in relevance_labels("A 4-8-GHz cryogenic CMOS low-noise amplifier")
    assert "ai_hardware" in relevance_labels("A compute-in-memory accelerator for edge AI")
    assert "quantum_computing" in relevance_labels("High-fidelity readout of a superconducting qubit")


def test_relevance_keeps_core_ai_but_rejects_domain_application():
    assert is_relevant_literature("Artificial intelligence learns to reason")
    assert not is_relevant_literature("Deep learning predicts wetland water quality")
    assert not is_relevant_literature("A foundation model for antimicrobial peptide discovery")


def test_relevance_rejects_biological_circuit_language():
    assert not is_relevant_literature("Machine learning of a neural circuit", "Brain circuit activity")
