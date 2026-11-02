import copy
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "smartctl"


def cargar(nombre):
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


@pytest.fixture
def nvme_real():
    return cargar("nvme_real.json")


@pytest.fixture
def base_sintetica():
    """Copia de sintetico_precaucion.json reparada para quedar en BUENO; cada test la altera."""
    datos = copy.deepcopy(cargar("sintetico_precaucion.json"))
    datos["nvme_smart_health_information_log"].update(media_errors=0, percentage_used=3)
    return datos
