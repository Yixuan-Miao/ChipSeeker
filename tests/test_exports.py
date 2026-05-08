from chipseeker.exports import build_bibtex, paper_authors_display


def test_author_display_uses_full_available_author_list():
    paper = {"authors": ["Y. Zeng", "J. Stenarson", "P. Sobis", "J. Grahn"]}

    assert paper_authors_display(paper) == "Y. Zeng; J. Stenarson; P. Sobis; J. Grahn"


def test_ieee_style_bibtex_uses_full_author_list_and_metadata():
    paper = {
        "title": "Pulsed HEMT LNA Operation for Qubit Readout",
        "authors": ["Y. Zeng", "J. Stenarson", "P. Sobis", "J. Grahn"],
        "venue": "IEEE Transactions on Microwave Theory and Techniques",
        "year": "2025",
        "volume": "73",
        "number": "9",
        "pages": "6539-6553",
        "ieee_terms": ["Noise", "Qubit", "HEMTs"],
        "keywords": ["Cryogenic", "low-noise amplifier (LNA)", "qubit readout"],
        "doi": "10.1109/TMTT.2025.3556982",
        "article_number": "10969553",
    }

    bibtex = build_bibtex([paper])

    assert "@ARTICLE{10969553," in bibtex
    assert "author={Y. Zeng and J. Stenarson and P. Sobis and J. Grahn}," in bibtex
    assert "journal={IEEE Transactions on Microwave Theory and Techniques}," in bibtex
    assert "title={Pulsed HEMT LNA Operation for Qubit Readout}," in bibtex
    assert "volume={73}," in bibtex
    assert "number={9}," in bibtex
    assert "pages={6539-6553}," in bibtex
    assert "keywords={Noise;Qubit;HEMTs;Cryogenic;low-noise amplifier (LNA);qubit readout}," in bibtex
    assert "doi={10.1109/TMTT.2025.3556982}" in bibtex
