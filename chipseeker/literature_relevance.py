import re


def _normalize(*values):
    text = " ".join(str(value or "") for value in values).lower()
    text = text.replace("–", "-").replace("—", "-").replace("‑", "-")
    return re.sub(r"\s+", " ", text).strip()


def _contains(text, terms):
    return any(term in text for term in terms)


CIRCUIT_TERMS = (
    "integrated circuit",
    "integrated electronics",
    "microelectronic",
    "cmos",
    "bicmos",
    "sige",
    "rfic",
    "mmic",
    "mixed-signal",
    "mixed signal",
    "analog circuit",
    "radio-frequency circuit",
    "radio frequency circuit",
    "millimeter-wave circuit",
    "millimetre-wave circuit",
    "mm-wave circuit",
    "low-noise amplifier",
    "power amplifier",
    "data converter",
    "analog-to-digital converter",
    "digital-to-analog converter",
    "phase-locked loop",
    "system-on-chip",
    "system on chip",
    "semiconductor chip",
    "semiconductor device",
    "transistor",
    "sram",
    "dram",
    "rram",
    "mram",
    "fefet",
    "memristor",
    "phase-change memory",
    "chiplet",
    "advanced packaging",
    "heterogeneous integration",
    "3d integration",
    "monolithic 3d",
    "wafer-scale",
    "mems",
)

AI_HARDWARE_TERMS = (
    "ai accelerator",
    "artificial intelligence accelerator",
    "machine learning accelerator",
    "neural accelerator",
    "neural processing unit",
    "tensor accelerator",
    "transformer accelerator",
    "llm accelerator",
    "ai chip",
    "compute-in-memory",
    "compute in memory",
    "in-memory computing",
    "in memory computing",
    "processing-in-memory",
    "processing in memory",
    "near-memory computing",
    "near memory computing",
    "in-sensor computing",
    "in sensor computing",
    "neuromorphic",
    "spiking neural network hardware",
    "photonic neural network",
    "optical neural network",
    "plasmonic artificial neural network",
    "photonic computing",
    "electronics for artificial intelligence",
    "electronics for ai",
    "analog computing",
    "analog computer",
    "memristive computing",
    "content-addressable memory",
    "content addressable memory",
    "hardware-software co-design",
    "hardware software co-design",
)

PHOTONIC_HARDWARE_TERMS = (
    "integrated photonic",
    "silicon photonic",
    "photonic integrated circuit",
    "on-chip photonic",
    "photonic chip",
    "photonic processor",
    "photonic computing",
    "photonic neural network",
    "optical neural network",
    "optical phased array",
)

QUANTUM_COMPUTING_TERMS = (
    "quantum computer",
    "quantum computing",
    "quantum processor",
    "quantum chip",
    "qubit",
    "transmon",
    "quantum gate",
    "quantum error correction",
    "fault-tolerant quantum",
    "quantum algorithm",
    "quantum learning",
    "quantum simulation",
    "quantum anneal",
    "quantum control",
    "qubit control",
    "qubit readout",
    "quantum readout",
    "cryogenic electronics",
    "cryo-cmos",
    "cryogenic cmos",
    "rf reflectometry",
    "josephson junction",
    "superconducting circuit",
    "superconducting processor",
    "quantum interconnect",
    "quantum network",
    "quantum memory",
    "quantum internet",
    "trapped-ion",
    "trapped ion",
)

AI_CORE_TERMS = (
    "artificial intelligence",
    "foundation model",
    "large language model",
    "language model",
    "generative ai",
    "machine reasoning",
    "reinforcement learning",
    "self-supervised learning",
    "unsupervised learning",
    "vision-language model",
    "multimodal model",
    "robot learning",
)

AI_METHOD_TERMS = (
    "model",
    "algorithm",
    "architecture",
    "reason",
    "training",
    "learning",
    "agent",
    "benchmark",
    "generalization",
    "generalisation",
    "scaling",
    "inference",
)

AI_APPLICATION_NOISE = (
    "protein",
    "peptide",
    "antimicrobial",
    "cancer",
    "tumor",
    "tumour",
    "glioblastoma",
    "clinical",
    "patient",
    "physician",
    "biomedical",
    "medical imaging",
    "molecular",
    "genomic",
    "genome",
    "methylome",
    "mrna",
    "transcriptomic",
    "pathology",
    "drug",
    "enzyme",
    "chemical",
    "catalyst",
    "synthesis",
    "alloy",
    "precipitation",
    "river",
    "wetland",
    "forest",
    "crop",
    "battery",
    "productivity effects",
    "governance",
    "democracy",
    "citizens' assemblies",
    "societal issues",
    "political",
    "taxation",
    "textile",
    "clothing",
    "makes a splash",
)

BIOLOGICAL_FALSE_POSITIVES = (
    "neural circuit",
    "brain circuit",
    "immune circuit",
    "gene circuit",
    "biochemical circuit",
    "cryo-em",
    "cryo electron microscopy",
    "cryo-electron microscopy",
)


def relevance_labels(title, abstract="", keywords="", venue=""):
    title_text = _normalize(title)
    combined = _normalize(title, abstract, keywords)
    venue_text = _normalize(venue)
    labels = set()

    if _contains(combined, BIOLOGICAL_FALSE_POSITIVES):
        return labels

    if _contains(title_text, CIRCUIT_TERMS) or _contains(title_text, PHOTONIC_HARDWARE_TERMS):
        labels.add("chips")
    elif _contains(combined, CIRCUIT_TERMS):
        labels.add("chips")

    if _contains(title_text, AI_HARDWARE_TERMS) or _contains(combined, AI_HARDWARE_TERMS):
        labels.update(("chips", "ai_hardware"))

    if _contains(title_text, QUANTUM_COMPUTING_TERMS) or _contains(combined, QUANTUM_COMPUTING_TERMS):
        labels.add("quantum_computing")

    title_has_core_ai = _contains(title_text, AI_CORE_TERMS)
    if title_has_core_ai and _contains(title_text, AI_METHOD_TERMS):
        if not _contains(title_text, AI_APPLICATION_NOISE):
            labels.add("ai_core")

    if "nature electronics" in venue_text and _contains(
        combined,
        CIRCUIT_TERMS + AI_HARDWARE_TERMS + PHOTONIC_HARDWARE_TERMS + QUANTUM_COMPUTING_TERMS,
    ):
        labels.add("chips")

    return labels


def is_relevant_literature(title, abstract="", keywords="", venue="", scopes=None):
    labels = relevance_labels(title, abstract=abstract, keywords=keywords, venue=venue)
    requested = set(scopes or ("chips", "ai_hardware", "ai_core", "quantum_computing"))
    return bool(labels & requested)
