from pathlib import Path

from ragstudio.services.domain_metadata_service import DomainMetadataService


def test_builtin_profiles_are_loaded_from_json_templates(tmp_path):
    profiles = DomainMetadataService(tmp_path).list_profiles()
    ids = {profile.id for profile in profiles}

    assert "hadith" in ids
    assert "quran_tafseer" in ids
    assert Path("backend/src/ragstudio/domain_profiles/builtin_profiles.json").exists()
