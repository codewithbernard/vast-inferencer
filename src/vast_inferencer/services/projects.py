from vast_inferencer.registry import ProjectConfig, resolve_project


def get_project(project_id: str) -> ProjectConfig:
    return resolve_project(project_id)
