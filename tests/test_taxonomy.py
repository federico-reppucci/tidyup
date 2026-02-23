"""Tests for taxonomy module."""

from tidydownloads.taxonomy import discover_taxonomy


def test_discover_taxonomy(sample_documents):
    taxonomy = discover_taxonomy(sample_documents.documents_dir)
    folder_names = [f.name for f in taxonomy.folders]
    assert "02 Finance" in folder_names
    assert "03 Work" in folder_names


def test_taxonomy_subfolders(sample_documents):
    taxonomy = discover_taxonomy(sample_documents.documents_dir)
    finance = next(f for f in taxonomy.folders if f.name == "02 Finance")
    assert "Investments" in finance.subfolders
    assert "Mortgage" in finance.subfolders


def test_taxonomy_prompt_text(sample_documents):
    taxonomy = discover_taxonomy(sample_documents.documents_dir)
    text = taxonomy.to_prompt_text()
    assert "02 Finance/" in text
    assert "Investments/" in text


def test_taxonomy_empty_documents(tmp_config):
    taxonomy = discover_taxonomy(tmp_config.documents_dir)
    assert taxonomy.folders == []


def test_taxonomy_nonexistent_dir(tmp_config):
    tmp_config.documents_dir = tmp_config.documents_dir / "nonexistent"
    taxonomy = discover_taxonomy(tmp_config.documents_dir)
    assert taxonomy.folders == []
