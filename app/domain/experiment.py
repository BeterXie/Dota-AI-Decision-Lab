type AiDecisionLaneKey = tuple[str, str, str, str, str]
type AiExperimentKey = tuple[str, str, str, str, str, str]

STATIC_EXECUTION_CONFIG_VERSION = "static-v1"


def execution_config_version_for_provider(provider: object) -> str:
    version = getattr(provider, "runtime_execution_config_version", None)
    if isinstance(version, str) and version:
        return version
    return STATIC_EXECUTION_CONFIG_VERSION


def ai_experiment_key(
    lane: AiDecisionLaneKey,
    execution_config_version: str,
) -> AiExperimentKey:
    return (*lane, execution_config_version)
