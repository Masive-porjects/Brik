"""
AudioMind Intelligence — Knowledge Core Schemas

Modelos Pydantic que definen la estructura de datos del Knowledge Core.
SOLO definen esquemas — no conectan a BD, no implementan lógica.

Módulos:
- preset_knowledge: PresetKnowledge — presets de mastering
- plugin_knowledge: PluginKnowledge — plugins DSP
- genre_knowledge: GenreKnowledge — perfiles de género
- experiment_knowledge: ExperimentKnowledge — experimentos I+D
- idea_knowledge: IdeaKnowledge — ideas de producto/ingeniería
"""

from .experiment_knowledge import (
    ExperimentChanges,
    ExperimentDesign,
    ExperimentKnowledge,
    ExperimentResults,
    TechnicalMetrics,
)
from .genre_knowledge import (
    BPMRange,
    DetectionFeatures,
    DSPRecommendation,
    DynamicsProfile,
    EnergyProfile,
    GenreKnowledge,
    PresetCompatibility,
    ReferenceTrack,
    SubgenreVariant,
    TonalBalance,
)
from .idea_knowledge import IdeaKnowledge, IdeaReference
from .plugin_knowledge import (
    PluginInteraction,
    PluginKnowledge,
    PluginParameter,
    SonicImpact,
    UsageExample,
)
from .preset_knowledge import (
    PluginRef,
    PresetGenreCompatibility,
    PresetKnowledge,
    PresetMetrics,
)

__all__ = [
    # Preset
    "PresetKnowledge", "PluginRef", "PresetMetrics", "PresetGenreCompatibility",
    # Plugin
    "PluginKnowledge", "PluginParameter", "SonicImpact", "PluginInteraction", "UsageExample",
    # Genre
    "GenreKnowledge", "BPMRange", "EnergyProfile", "TonalBalance", "DynamicsProfile",
    "DSPRecommendation", "PresetCompatibility", "DetectionFeatures", "ReferenceTrack", "SubgenreVariant",
    # Experiment
    "ExperimentKnowledge", "ExperimentDesign", "ExperimentChanges", "ExperimentResults", "TechnicalMetrics",
    # Idea
    "IdeaKnowledge", "IdeaReference",
]