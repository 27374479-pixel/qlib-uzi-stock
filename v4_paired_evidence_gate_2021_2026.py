"""Apply the standard V4 paired evidence gate to the 2021-2026 run."""
from pathlib import Path
import v4_paired_evidence_gate as gate

ROOT = Path(__file__).resolve().parent
gate.INPUT = ROOT / "output" / "v4_paired_execution_2021_2026.json"
gate.OUTPUT = ROOT / "output" / "v4_paired_evidence_gate_2021_2026.json"

if __name__ == "__main__":
    gate.main()
