"""项目路径与配置集中管理"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"

QLIB_DATA_DIR = PROJECT_ROOT / "qlib_data" / "cn_data"
UZI_SKILL_DIR = PROJECT_ROOT / "UZI-Skill"
UZI_SCRIPTS_DIR = UZI_SKILL_DIR / "skills" / "deep-analysis" / "scripts"

SEQUOIA_X_DIR = PROJECT_ROOT / "Sequoia-X"
SEQUOIA_X_DB = SEQUOIA_X_DIR / "data" / "sequoia_v2.db"

OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

QLIB_MODEL_DIR = PROJECT_ROOT / "models"
QLIB_MODEL_DIR.mkdir(exist_ok=True)
