from pathlib import Path

from app.agents.parser import build_chunks, chunk_text_by_tokens, parse_raw_file, parsed_json


def test_chunk_text_by_tokens_creates_target_sized_chunks() -> None:
    text = " ".join(f"word{i}" for i in range(2500))

    chunks = chunk_text_by_tokens(text)

    assert len(chunks) == 3
    assert all(800 <= len(chunk.split()) <= 1200 for chunk in chunks[:-1])


def test_parse_html_extracts_text_and_table_metadata(tmp_path: Path) -> None:
    html_path = tmp_path / "report.html"
    html_path.write_text(
        """
        <html>
          <head><title>Labor Report</title></head>
          <body>
            <h1>Labor Report</h1>
            <p>Methodology: employment rate is defined as employed workers divided by labor force.</p>
            <table><caption>Indicators</caption><tr><th>Name</th><th>Value</th></tr><tr><td>Employment</td><td>60%</td></tr></table>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    parsed = parse_raw_file(html_path, "html", "text/html")
    chunks = build_chunks("report-1", parsed)

    assert "employment rate" in parsed.text.lower()
    assert parsed.metadata["html_table_count"] == 1
    assert "Labor Report" in parsed_json(parsed)
    assert chunks[0]["page_number"] is None
    assert chunks[0]["metadata"]["table_placeholders"][0]["kind"] == "html_table"
