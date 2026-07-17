from chipseeker.ultra_audit import (
    audit_candidates,
    band_relation,
    build_evidence_snapshot,
    compare_paper_sets,
)


def test_band_relation_requires_positive_width_overlap():
    assert band_relation((2, 4), (4, 8))["relation"] == "endpoint_only"
    partial = band_relation((3, 6), (4, 8))
    assert partial["relation"] == "partial_overlap"
    assert partial["positive_width_overlap_ghz"] == 2
    assert band_relation("about 3-9 GHz", (4, 8))["relation"] == "full_cover"


def test_evidence_snapshot_classifies_receiver_with_explicit_lna():
    paper = {
        "title": "A Cryogenic SiGe Receiver IC for Qubit Readout",
        "abstract": "The receiver includes a three-stage SiGe HBT LNA designed for 4-8 GHz and measured at 4 K.",
    }

    evidence = build_evidence_snapshot(paper, target_band=(4, 8))

    assert evidence["record_type_hint"] == "receiver_or_soc_with_explicit_lna"
    assert evidence["evidence_axes"] == {
        "technology": "evidenced",
        "cryogenic": "evidenced",
        "circuit": "evidenced",
        "frequency": "evidenced",
    }


def test_evidence_snapshot_recovers_corrupted_range_separator():
    evidence = build_evidence_snapshot(
        {"title": "Cryogenic SiGe LNA from 0.3每3 GHz", "abstract": "Measured at 4 K."},
        target_band=(2, 4),
    )

    assert evidence["best_target_frequency_relation"]["positive_width_overlap_ghz"] == 1.0
    assert "suspected_corrupted_frequency_range_separator" in evidence["metadata_quality_flags"]


def test_evidence_snapshot_does_not_guess_technology_or_lna_from_generic_terms():
    evidence = build_evidence_snapshot(
        {
            "title": "A Cryogenic HEMT Receiver",
            "abstract": "A low-noise front-end operates from 4-8 GHz at 4 K.",
        },
        target_band=(4, 8),
    )

    assert evidence["technology_mentions"] == []
    assert evidence["evidence_axes"]["circuit"] == "unknown"
    assert evidence["record_type_hint"] == "receiver_or_soc_with_low_noise_frontend"


def test_audit_reports_missing_evidence_and_prior_regression():
    prior = [{"title": "Old paper", "year": "2020", "doi": "10.example/old"}]
    current = [
        {
            "title": "New paper",
            "year": "2024",
            "doi": "10.example/new",
            "screening_decision": "include",
        }
    ]

    response = audit_candidates(current, target_band=(4, 8), prior=prior)

    assert response["included_with_missing_evidence_count"] == 1
    assert response["comparison"]["added_count"] == 1
    assert response["comparison"]["removed_count"] == 1


def test_compare_paper_sets_retains_same_doi_case_insensitively():
    comparison = compare_paper_sets(
        [{"title": "Paper", "doi": "10.EXAMPLE/ONE"}],
        [{"title": "Different metadata", "doi": "10.example/one"}],
    )
    assert comparison["retained_count"] == 1


def test_compare_paper_sets_reports_local_corpus_recall_separately():
    prior = [
        {"title": "Local", "doi": "10.example/local", "source_in_current_corpus": True},
        {"title": "External", "doi": "10.example/external", "source_in_current_corpus": False},
    ]
    current = [{"title": "Local", "doi": "10.example/local", "source_in_current_corpus": True}]

    comparison = compare_paper_sets(current, prior)

    assert comparison["corpus_resident_recall"] == 1.0
    assert comparison["removed_external_or_corpus_gap_count"] == 1
