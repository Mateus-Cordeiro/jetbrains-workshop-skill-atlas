import pytest

from skill_atlas.application.documents import Documents, MissingSkill, StaleSkill
from skill_atlas.errors import RepositoryError


def test_documents_validate_identity_and_decode_without_writes(scan_result):
    skill = scan_result.skills[0]

    class Catalog:
        def skill(self, repository, path):
            return skill if path == skill.path else None

    class Reader:
        content = b"\xef\xbb\xbf# Document"
        reads = 0

        def read_document(self, selected):
            assert selected == skill
            self.reads += 1
            return self.content

    reader = Reader()
    documents = Documents(Catalog(), reader)
    with pytest.raises(MissingSkill):
        documents.load(skill.repository, "missing", skill.commit_sha)
    with pytest.raises(StaleSkill):
        documents.load(skill.repository, skill.path, "b" * 40)
    assert reader.reads == 0
    assert documents.load(skill.repository, skill.path, skill.commit_sha).source == "# Document"
    reader.content = b"\xff"
    with pytest.raises(RepositoryError, match="UTF-8"):
        documents.load(skill.repository, skill.path, skill.commit_sha)
