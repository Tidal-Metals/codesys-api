"""Package the AutomationDirect (vendor 1767) CODESYS 3 device descriptions as a CODESYS 4 extension.

CODESYS 4 1.0 loads device descriptions only from installed extensions (cdsV3Devs/<type>/<id>/<version>/).
This builds an unsigned TidalMetals.P2CDS622.Ext.<version>.nupkg with the same layout as the shipped
device extensions, for `c4-pkm install`. Read-only on the CODESYS 3 device repository.

Usage: python build_p2_extension.py <out dir> [version]
"""
import sys
import zipfile
from pathlib import Path

DEVICES = Path(r"C:\ProgramData\CODESYS\Devices")
PACKAGE_ID = "TidalMetals.P2CDS622.Ext"

NUSPEC = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://schemas.microsoft.com/packaging/2011/08/nuspec.xsd">
  <metadata>
    <id>{id}</id>
    <version>{version}</version>
    <title>AutomationDirect P2CDS-622 devices (repackaged for evaluation)</title>
    <authors>Tidal Metals</authors>
    <description>AutomationDirect P2CDS-622 CPU, bases and P2 I/O module device descriptions copied from the CODESYS 3 device repository, for a CODESYS 4 compatibility test.</description>
    <packageTypes>
      <packageType name="CODESYS-4-Extension" />
    </packageTypes>
  </metadata>
</package>
"""
CONTENT_TYPES = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml" />
  <Default Extension="nuspec" ContentType="application/octet" />
  <Default Extension="json" ContentType="application/octet" />
  <Default Extension="xml" ContentType="application/octet" />
  <Default Extension="ico" ContentType="application/octet" />
  <Default Extension="png" ContentType="application/octet" />
</Types>
"""
RELS = """<?xml version="1.0" encoding="utf-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Type="http://schemas.microsoft.com/packaging/2010/07/manifest" Target="/{id}.nuspec" Id="R1" />
</Relationships>
"""


def automationdirect_device_dirs():
    for version_dir in sorted(d for d in DEVICES.glob("*/1767 */*")):
        if version_dir.is_dir() and (version_dir / "device.xml").exists():
            yield version_dir


def main(out_dir, version="1.0.0"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    package = out / f"{PACKAGE_ID}.{version}.nupkg"
    count = 0
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as nupkg:
        nupkg.writestr(f"{PACKAGE_ID}.nuspec", NUSPEC.format(id=PACKAGE_ID, version=version))
        nupkg.writestr("[Content_Types].xml", CONTENT_TYPES)
        nupkg.writestr("_rels/.rels", RELS.format(id=PACKAGE_ID))
        nupkg.writestr("c4Pkg.json", '{\n  "components": [\n  ]\n}')
        for version_dir in automationdirect_device_dirs():
            relative = version_dir.relative_to(DEVICES).as_posix()
            for file in version_dir.iterdir():
                if file.is_file():
                    nupkg.write(file, f"cdsV3Devs/{relative}/{file.name}")
            count += 1
    print(f"{package} ({count} device descriptions)")


if __name__ == "__main__":
    main(*sys.argv[1:])
