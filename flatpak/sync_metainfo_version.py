#!/usr/bin/env python3
"""
Sincroniza (ou apenas valida) a versão declarada em
usr/share/metainfo/io.github.narayanls.PorAi.metainfo.xml
com a versão real do release.

No POR.ai essa versão tem dois usos:

  1. é o que aparece em `flatpak info` (o flatpak-builder lê o <release> mais
     recente desse XML);
  2. o manifesto grava esse mesmo valor em /app/share/por-ai/version.txt, e é
     ele que o core/updater.py compara com a última release do GitHub.

Se o metainfo ficar para trás, o Flatpak novo sai "carimbado" com a versão
antiga e passa a oferecer a própria atualização em loop.

Use a mesma versão da tag do GitHub (sem o "v"). A versão é sempre passada
explicitamente via --version, nunca lida de outro arquivo.

Uso, ANTES do flatpak-builder, a partir da pasta do manifesto
(~/Github/flatpak/por-ai):

    # Modo padrão: sincroniza (insere um <release> novo se necessário)
    python3 sync_metainfo_version.py --version 0.1.9.4

    # Modo estrito: só valida e falha (exit 1) se estiver desatualizado,
    # sem alterar o arquivo — útil como "gate" antes do build real
    python3 sync_metainfo_version.py --version 0.1.9.4 --check
"""

import argparse
import datetime as dt
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# ── Configuração ─────────────────────────────────────────────────────
# O script fica na raiz da pasta do Flatpak, ao lado do manifesto .yml
# (não dentro de usr/, para não ir junto para dentro do app).
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_METAINFO_PATH = (
    SCRIPT_DIR / "usr" / "share" / "metainfo" / "io.github.narayanls.PorAi.metainfo.xml"
)


def parse_keeping_comments(path: Path) -> ET.ElementTree:
    """Lê o XML preservando os comentários (o parser padrão os descarta, e o
    arquivo seria regravado sem eles)."""
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    return ET.parse(path, parser=parser)


def get_latest_metainfo_version(tree: ET.ElementTree) -> str | None:
    """Retorna a versão do primeiro <release> (convenção AppStream:
    mais recente primeiro)."""
    releases = tree.getroot().find("releases")
    if releases is None:
        return None
    first = releases.find("release")
    if first is None:
        return None
    return first.get("version")


def sync_metainfo(metainfo_path: Path, version: str, date: str, check_only: bool) -> bool:
    """Retorna True se já estava sincronizado, False se precisou (ou
    precisaria, em modo --check) de atualização."""
    if not metainfo_path.is_file():
        sys.exit(f"ERRO: metainfo não encontrado em {metainfo_path}")

    tree = parse_keeping_comments(metainfo_path)
    latest = get_latest_metainfo_version(tree)

    if latest == version:
        print(f"[sync_metainfo_version] OK: metainfo já está em {version}.")
        return True

    print(
        f"[sync_metainfo_version] DIVERGÊNCIA: metainfo tem "
        f"'{latest}', versão de release informada é '{version}'."
    )

    if check_only:
        return False

    root = tree.getroot()
    releases = root.find("releases")
    if releases is None:
        releases = ET.SubElement(root, "releases")

    # Evita duplicar se essa versão já existir em algum ponto do histórico
    for rel in releases.findall("release"):
        if rel.get("version") == version:
            print(
                f"[sync_metainfo_version] Versão {version} já existe no "
                f"histórico; nada a inserir."
            )
            return False

    new_release = ET.Element("release", {"version": version, "date": date})
    releases.insert(0, new_release)

    # Reindenta o XML inteiro para manter o arquivo legível
    ET.indent(tree, space="  ")
    tree.write(metainfo_path, encoding="UTF-8", xml_declaration=True)

    content = metainfo_path.read_text(encoding="utf-8")
    if not content.endswith("\n"):
        metainfo_path.write_text(content + "\n", encoding="utf-8")

    print(f"[sync_metainfo_version] Inserido <release version=\"{version}\" date=\"{date}\"/>.")
    return False


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Versão do release do flatpak (ex: 0.1.9.4). Sempre explícita.",
    )
    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="Data do release no formato YYYY-MM-DD (padrão: hoje)",
    )
    parser.add_argument(
        "--metainfo",
        default=str(DEFAULT_METAINFO_PATH),
        help="Caminho do metainfo.xml (padrão: %(default)s)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Não modifica o arquivo; sai com código 1 se estiver desatualizado "
             "(use isso como gate antes de rodar o flatpak-builder)",
    )
    args = parser.parse_args()

    version = args.version.lstrip("v")
    print(f"[sync_metainfo_version] Versão de release informada: {version}")

    up_to_date = sync_metainfo(Path(args.metainfo), version, args.date, args.check)

    if args.check and not up_to_date:
        sys.exit(
            "\n[sync_metainfo_version] FALHA: metainfo.xml está desatualizado. "
            "Rode sem --check para corrigir, ou o build vai gerar um pacote "
            "com a versão errada em `flatpak info` e no atualizador do app."
        )


if __name__ == "__main__":
    main()
