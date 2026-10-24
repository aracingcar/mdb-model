"""Download the MDBA surface water SDL resource unit outlines (Basin Plan 2012) into data/input/sdl/.

Source: data.gov.au, "Surface Water SDL Resource Units" (MDBA, CC BY 4.0). Run with python 1_masking/download_sdl_units.py.
"""
import io
import urllib.request
import zipfile

from config import SDL_FILE

URL = ("https://data.gov.au/data/dataset/4afa3227-8557-4bb6-944a-6494b28ae160/resource/"
       "988ae947-f4dc-4f75-9773-536df71b03ad/download/surface-water-sdl-resource-units.zip")

if __name__ == "__main__":
    SDL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(URL, timeout=120) as r:
        zipfile.ZipFile(io.BytesIO(r.read())).extractall(SDL_FILE.parent)
    print(f"Saved SDL resource units to {SDL_FILE.parent}")
