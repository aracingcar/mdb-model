"""Copy the car module, its stylesheet and the licence of the driving model it adapts into the GitHub Pages docs bundle."""
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC_CAR = ROOT / "docs" / "car"


def publish_assets():
    PUBLIC_CAR.mkdir(parents=True, exist_ok=True)
    for name in ("car.js", "car.css", "LICENSE-carphysics2d"):
        shutil.copy2(HERE / name, PUBLIC_CAR / name)


if __name__ == "__main__":
    publish_assets()
