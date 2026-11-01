#!/usr/bin/env python3
"""
Gera o python3-requirements.yaml do Flatpak a partir do requirements.txt.

Uso:
    python3 gerar_yaml.py                 # lê requirements.txt, grava o YAML
    python3 gerar_yaml.py --atualizar     # ignora os "==" e pega as últimas versões

Para cada dependência direta do requirements.txt o script consulta o PyPI,
resolve as dependências transitivas PARA O PYTHON DO RUNTIME (não o do seu
sistema) e escolhe o melhor arquivo de cada pacote:

    wheel nativo (cp313 manylinux) > wheel abi3 > wheel puro (py3-none-any) > sdist

Só cai no sdist (.tar.gz) quando o pacote não publica wheel — nesse caso ele é
compilado dentro do flatpak-builder com o setuptools do SDK.

Ajuste as três constantes abaixo se trocar de runtime ou de arquitetura.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

try:
    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.specifiers import SpecifierSet
    from packaging.tags import compatible_tags, cpython_tags
    from packaging.utils import canonicalize_name, parse_wheel_filename
    from packaging.version import InvalidVersion, Version
except ImportError:  # sem python-packaging: usa a cópia embutida no pip
    from pip._vendor.packaging.markers import default_environment
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.specifiers import SpecifierSet
    from pip._vendor.packaging.tags import compatible_tags, cpython_tags
    from pip._vendor.packaging.utils import canonicalize_name, parse_wheel_filename
    from pip._vendor.packaging.version import InvalidVersion, Version

# === Configuração da plataforma de destino ===================================
# org.gnome.Platform 49 e 50 (freedesktop-sdk 25.08) = Python 3.13
# org.gnome.Platform 51      (freedesktop-sdk 26.08) = confira com:
#   flatpak run --command=python3 org.gnome.Sdk//51 --version
PYTHON_VERSION = (3, 13)
ARCH = "x86_64"            # ou "aarch64"
GLIBC_MAX = (2, 40)        # maior manylinux_2_XX aceito (glibc do runtime >= isso)
# =============================================================================

REQUIREMENTS_FILE = "requirements.txt"
OUTPUT_FILE = "python3-requirements.yaml"

# Pacotes que o runtime já fornece: nunca entram no YAML.
PROVIDED_BY_RUNTIME = {"pygobject", "pycairo", "pip", "setuptools", "wheel"}

# Dependências que o PyPI não informa. Pacotes antigos publicados só como
# sdist (caso do odfpy) declaram o install_requires apenas dentro do setup.py,
# então a API do PyPI devolve "requires_dist: null" e o pip falharia no build
# com "No matching distribution found". Declare aqui o que faltar.
EXTRA_DEPS = {
    "odfpy": ["defusedxml"],
}


def target_tags() -> dict:
    """Tags de wheel aceitas no runtime, mapeadas para a prioridade (0 = melhor)."""
    platforms = [
        f"manylinux_{GLIBC_MAX[0]}_{minor}_{ARCH}"
        for minor in range(GLIBC_MAX[1], 16, -1)
    ]
    platforms += [f"manylinux2014_{ARCH}", f"manylinux_2_12_{ARCH}",
                  f"manylinux2010_{ARCH}", f"manylinux_2_5_{ARCH}",
                  f"manylinux1_{ARCH}", f"linux_{ARCH}"]
    interpreter = f"cp{PYTHON_VERSION[0]}{PYTHON_VERSION[1]}"
    # cpython_tags já inclui, nesta ordem: cp313-cp313, cp313-abi3 e cp3X-abi3.
    tags = list(cpython_tags(PYTHON_VERSION, [interpreter], platforms))
    tags += list(compatible_tags(PYTHON_VERSION, interpreter, platforms))
    return {tag: rank for rank, tag in reversed(list(enumerate(tags)))}


def marker_environment() -> dict:
    """Ambiente usado para avaliar marcadores ("; python_version < '3.11'" etc.)."""
    env = default_environment()
    full = f"{PYTHON_VERSION[0]}.{PYTHON_VERSION[1]}.0"
    env.update({
        "python_version": f"{PYTHON_VERSION[0]}.{PYTHON_VERSION[1]}",
        "python_full_version": full,
        "implementation_name": "cpython",
        "implementation_version": full,
        "platform_python_implementation": "CPython",
        "sys_platform": "linux",
        "platform_system": "Linux",
        "os_name": "posix",
        "platform_machine": ARCH,
        "extra": "",
    })
    return env


TAGS = target_tags()
MARKER_ENV = marker_environment()
PYTHON_FULL = Version(MARKER_ENV["python_full_version"])
_cache: dict = {}


def pypi(path: str) -> dict:
    if path not in _cache:
        url = f"https://pypi.org/pypi/{path}/json"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                _cache[path] = json.load(response)
        except (urllib.error.URLError, TimeoutError) as exc:
            sys.exit(f"ERRO: não foi possível consultar {url}: {exc}")
    return _cache[path]


def best_file(files: list) -> dict | None:
    """Melhor arquivo de uma release para o runtime, ou None se nenhum serve."""
    best, best_rank = None, None
    sdist = None
    for info in files:
        if info.get("yanked"):
            continue
        requires_python = info.get("requires_python")
        if requires_python:
            try:
                if PYTHON_FULL not in SpecifierSet(requires_python):
                    continue
            except Exception:  # especificador malformado em releases antigas
                pass
        name = info["filename"]
        if name.endswith(".whl"):
            try:
                wheel_tags = parse_wheel_filename(name)[3]
            except Exception:
                continue
            ranks = [TAGS[tag] for tag in wheel_tags if tag in TAGS]
            if ranks and (best_rank is None or min(ranks) < best_rank):
                best, best_rank = info, min(ranks)
        elif info.get("packagetype") == "sdist" and name.endswith((".tar.gz", ".zip")):
            sdist = sdist or info
    return best or sdist


def choose(name: str, specifier: SpecifierSet) -> tuple:
    """(versão, arquivo) da release mais nova que atende ao especificador."""
    releases = pypi(name)["releases"]
    versions = {}
    for raw in releases:
        try:
            versions[Version(raw)] = raw
        except InvalidVersion:
            continue
    allowed = set(specifier.filter(versions))  # pré-releases só se pedidas
    for version in sorted(allowed, reverse=True):
        info = best_file(releases[versions[version]])
        if info is not None:
            return version, info
    sys.exit(f"ERRO: nenhuma versão de '{name}' atende a '{specifier}' "
             f"para cp{PYTHON_VERSION[0]}{PYTHON_VERSION[1]}/{ARCH}.")


class Resolver:
    """Resolvedor guloso: a primeira versão escolhida de cada pacote vale para
    todos. Se uma dependência posterior exigir outra versão, o script para e
    pede para você fixar a versão no requirements.txt."""

    def __init__(self) -> None:
        self.pinned: dict = {}      # nome canônico -> (nome, versão, arquivo)
        self._visiting: set = set() # protege contra dependências circulares

    def resolve(self, req: Requirement, wanted_by: str, order: list) -> None:
        key = canonicalize_name(req.name)
        if key in PROVIDED_BY_RUNTIME:
            return
        if key in self.pinned:
            _, version, _ = self.pinned[key]
            if not req.specifier.contains(version, prereleases=True):
                sys.exit(
                    f"ERRO: conflito em '{req.name}': já escolhi {version}, mas "
                    f"{wanted_by} exige '{req.specifier}'.\n"
                    f"      Fixe uma versão compatível de '{req.name}' no "
                    f"{REQUIREMENTS_FILE}.")
        else:
            version, info = choose(req.name, req.specifier)
            self.pinned[key] = (req.name, version, info)
        if key in order or key in self._visiting:
            return
        self._visiting.add(key)
        _, version, _ = self.pinned[key]
        metadata = pypi(f"{req.name}/{version}")["info"]
        declared = list(metadata.get("requires_dist") or []) + EXTRA_DEPS.get(key, [])
        for raw in declared:
            dep = Requirement(raw)
            if dep.marker is not None and not any(
                dep.marker.evaluate({**MARKER_ENV, "extra": extra})
                for extra in (req.extras or {""})
            ):
                continue
            self.resolve(dep, f"{req.name} {version}", order)
        self._visiting.discard(key)
        order.append(key)       # dependências primeiro, o pacote por último


def read_requirements(path: str, upgrade: bool) -> list:
    requirements = []
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError as exc:
        sys.exit(f"ERRO: não consegui ler {path}: {exc}")
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        req = Requirement(line)
        if upgrade:
            req = Requirement(req.name)
        requirements.append(req)
    if not requirements:
        sys.exit(f"ERRO: {path} não tem nenhuma dependência.")
    return requirements


def module_yaml(name: str, version: Version, files: list) -> str:
    out = [
        f"  - name: python3-{name}",
        "    buildsystem: simple",
        "    build-commands:",
        '      - pip3 install --verbose --exists-action=i --no-index --find-links="file://${PWD}"',
        f'        --prefix=${{FLATPAK_DEST}} "{name}=={version}" --no-build-isolation',
        "    sources:",
    ]
    for info in files:
        out += ["      - type: file",
                f"        url: {info['url']}",
                f"        sha256: {info['digests']['sha256']}"]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--atualizar", action="store_true",
                        help="ignora as versões fixadas e usa as mais recentes")
    args = parser.parse_args()

    pytag = f"cp{PYTHON_VERSION[0]}{PYTHON_VERSION[1]}"
    print(f"Alvo: {pytag} / {ARCH} / manylinux até {GLIBC_MAX[0]}.{GLIBC_MAX[1]}")
    print("Consultando o PyPI…\n")

    resolver = Resolver()
    modules, sdists = [], []
    for req in read_requirements(REQUIREMENTS_FILE, args.atualizar):
        order: list = []
        resolver.resolve(req, REQUIREMENTS_FILE, order)
        if not order:
            print(f"  – {req.name}: já vem no runtime, ignorado")
            continue
        files = [resolver.pinned[key][2] for key in order]
        name, version, _ = resolver.pinned[order[-1]]
        modules.append(module_yaml(name, version, files))
        print(f"  ✓ {name} {version}")
        for key in order:
            _, dep_version, info = resolver.pinned[key]
            print(f"      {info['filename']}")
            if not info["filename"].endswith(".whl"):
                sdists.append(f"{resolver.pinned[key][0]} {dep_version}")

    header = (
        "# Gerado automaticamente por gerar_yaml.py — não edite à mão.\n"
        f"# Python: {pytag} | Arch: {ARCH}\n"
        f"# Para regenerar: python3 gerar_yaml.py   (versões em {REQUIREMENTS_FILE})\n"
        "name: python3-requirements\n"
        "buildsystem: simple\n"
        "build-commands: []\n"
        "modules:\n"
    )
    with open(OUTPUT_FILE, "w", encoding="utf-8") as handle:
        handle.write(header + "\n".join(modules) + "\n")

    print(f"\n✓ {OUTPUT_FILE} gerado ({len(resolver.pinned)} pacotes, "
          f"{len(modules)} módulos).")
    if sdists:
        print("\nSem wheel no PyPI (serão compilados com o setuptools do SDK): "
              + ", ".join(sorted(set(sdists))))
    if args.atualizar:
        print(f"\nVersões escolhidas — copie para o {REQUIREMENTS_FILE} se quiser fixá-las:")
        for req in read_requirements(REQUIREMENTS_FILE, True):
            key = canonicalize_name(req.name)
            if key in resolver.pinned:
                print(f"  {req.name}=={resolver.pinned[key][1]}")


if __name__ == "__main__":
    main()
