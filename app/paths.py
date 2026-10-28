"""Separate immutable package resources from the user's writable workspace."""

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    resource_root: Path
    data_dir: Path
    model_dir: Path
    report_dir: Path

    @classmethod
    def discover(cls, data_dir: Path | None = None, model_dir: Path | None = None) -> 'RuntimePaths':
        data = Path(data_dir if data_dir is not None else os.environ.get('ZHIXU_DATA_DIR') or Path.cwd() / 'data').expanduser().resolve()
        models = Path(model_dir if model_dir is not None else os.environ.get('ZHIXU_MODEL_DIR') or data.parent / 'models').expanduser().resolve()
        reports = Path(os.environ.get('ZHIXU_REPORT_DIR') or data.parent / 'reports').expanduser().resolve()
        return cls(Path(__file__).resolve().parent.parent, data, models, reports)

    @property
    def demo_dir(self) -> Path:
        return self.resource_root / 'app' / 'resources' / 'demo'

    @property
    def evaluation_dir(self) -> Path:
        return self.resource_root / 'app' / 'resources' / 'evaluation'

    @property
    def config_template_path(self) -> Path:
        return self.resource_root / 'app' / 'resources' / 'env.example'

    @property
    def static_dir(self) -> Path:
        return self.resource_root / 'app' / 'static'
