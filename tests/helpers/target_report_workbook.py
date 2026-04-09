from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def write_target_report_workbook(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>
""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
""",
        )
        archive.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Position" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="H1" t="inlineStr"><is><t>Category</t></is></c>
      <c r="I1" t="inlineStr"><is><t>Ticker</t></is></c>
      <c r="J1" t="inlineStr"><is><t>Name</t></is></c>
      <c r="L1" t="inlineStr"><is><t>Multiplier</t></is></c>
      <c r="M1" t="inlineStr"><is><t>Price</t></is></c>
      <c r="O1" t="inlineStr"><is><t>Type</t></is></c>
      <c r="P1" t="inlineStr"><is><t>duration (FUT_EQV_MOD_DUR_BASED_ON_CTD)</t></is></c>
    </row>
    <row r="2">
      <c r="H2" t="inlineStr"><is><t>DMEQ</t></is></c>
      <c r="I2" t="inlineStr"><is><t>LON:SPYL</t></is></c>
      <c r="J2" t="inlineStr"><is><t>US</t></is></c>
      <c r="L2"><v>1</v></c>
      <c r="O2" t="inlineStr"><is><t>ETF</t></is></c>
      <c r="P2"><v>1</v></c>
    </row>
    <row r="3">
      <c r="H3" t="inlineStr"><is><t>FI</t></is></c>
      <c r="I3" t="inlineStr"><is><t>ZNW00:CBOT</t></is></c>
      <c r="J3" t="inlineStr"><is><t>10Y TF</t></is></c>
      <c r="L3"><v>1000</v></c>
      <c r="O3" t="inlineStr"><is><t>Futures</t></is></c>
      <c r="P3"><v>8</v></c>
    </row>
    <row r="4">
      <c r="H4" t="inlineStr"><is><t>CASH</t></is></c>
      <c r="I4" t="inlineStr"><is><t>CASH (SGD value)</t></is></c>
      <c r="J4" t="inlineStr"><is><t>Cash</t></is></c>
      <c r="L4"><v>1</v></c>
      <c r="O4" t="inlineStr"><is><t>CASH</t></is></c>
    </row>
  </sheetData>
</worksheet>
""",
        )

    return path
