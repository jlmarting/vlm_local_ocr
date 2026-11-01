from __future__ import annotations

from vlm_ocr import paths


def test_linux_usa_xdg_y_config_home(tmp_path):
    env = {"XDG_DATA_HOME": str(tmp_path / "d")}
    assert paths.data_dir("linux", env, tmp_path) == tmp_path / "d" / "vlm-local-ocr"
    assert paths.config_dir("linux", env, tmp_path) == tmp_path / ".config" / "vlm-local-ocr"


def test_linux_sin_xdg_cae_a_home(tmp_path):
    assert (
        paths.data_dir("linux", {}, tmp_path)
        == tmp_path / ".local" / "share" / "vlm-local-ocr"
    )
    assert paths.config_dir("linux", {}, tmp_path) == tmp_path / ".config" / "vlm-local-ocr"


def test_windows_usa_localappdata_y_appdata(tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path / "L"), "APPDATA": str(tmp_path / "A")}
    assert paths.data_dir("win32", env, tmp_path) == tmp_path / "L" / "vlm-local-ocr"
    assert paths.config_dir("win32", env, tmp_path) == tmp_path / "A" / "vlm-local-ocr"


def test_windows_sin_variables_cae_al_legado(tmp_path):
    assert (
        paths.data_dir("win32", {}, tmp_path)
        == tmp_path / ".local" / "share" / "vlm-local-ocr"
    )
    assert paths.config_dir("win32", {}, tmp_path) == tmp_path / ".config" / "vlm-local-ocr"


def test_darwin_usa_application_support(tmp_path):
    esperado = tmp_path / "Library" / "Application Support" / "vlm-local-ocr"
    assert paths.data_dir("darwin", {}, tmp_path) == esperado
    assert paths.config_dir("darwin", {}, tmp_path) == esperado


def test_prefiere_legado_si_existe_y_el_nuevo_esta_vacio(tmp_path):
    legado = tmp_path / ".local" / "share" / "vlm-local-ocr"
    legado.mkdir(parents=True)
    (legado / "templates").mkdir()
    env = {"LOCALAPPDATA": str(tmp_path / "L")}
    assert paths.data_dir("win32", env, tmp_path) == legado


def test_prefiere_legado_si_el_nuevo_existe_vacio(tmp_path):
    legado = tmp_path / ".config" / "vlm-local-ocr"
    legado.mkdir(parents=True)
    (legado / "catalog.json").write_text("{}", encoding="utf-8")
    nuevo = tmp_path / "A" / "vlm-local-ocr"
    nuevo.mkdir(parents=True)
    env = {"APPDATA": str(tmp_path / "A")}
    assert paths.config_dir("win32", env, tmp_path) == legado


def test_no_prefiere_legado_si_el_nuevo_tiene_contenido(tmp_path):
    legado = tmp_path / ".local" / "share" / "vlm-local-ocr"
    legado.mkdir(parents=True)
    nuevo = tmp_path / "L" / "vlm-local-ocr"
    nuevo.mkdir(parents=True)
    (nuevo / "templates").mkdir()
    env = {"LOCALAPPDATA": str(tmp_path / "L")}
    assert paths.data_dir("win32", env, tmp_path) == nuevo


def test_no_prefiere_legado_vacio(tmp_path):
    legado = tmp_path / ".local" / "share" / "vlm-local-ocr"
    legado.mkdir(parents=True)
    env = {"LOCALAPPDATA": str(tmp_path / "L")}
    assert paths.data_dir("win32", env, tmp_path) == tmp_path / "L" / "vlm-local-ocr"


def test_linux_legado_igual_que_nuevo(tmp_path):
    legado = tmp_path / ".local" / "share" / "vlm-local-ocr"
    legado.mkdir(parents=True)
    assert paths.data_dir("linux", {}, tmp_path) == legado
