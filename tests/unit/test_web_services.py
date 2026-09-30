from dataclasses import replace
from threading import Event
from time import monotonic, sleep

import pytest

from skill_atlas.documents import Document, Documents, MissingSkill, StaleSkill
from skill_atlas.errors import RepositoryError
from skill_atlas.jobs import QueueFull, ScanJobs
from skill_atlas.models import Repository
from skill_atlas.web.rendering import render


def await_state(jobs, job_id, state):
    deadline = monotonic() + 3
    while monotonic() < deadline:
        job = jobs.get(job_id)
        if job and job.state == state:
            return job
        sleep(0.005)
    pytest.fail(f"Job did not reach {state}: {jobs.get(job_id)}")


def test_job_worker_deduplicates_limits_and_cleans_up(scan_result):
    entered, release = Event(), Event()

    def scan(repository):
        entered.set()
        assert release.wait(3)
        return replace(scan_result, repository=repository)

    jobs = ScanJobs(scan, capacity=1, retention=1)
    jobs.start()
    try:
        first = jobs.submit(scan_result.repository)
        assert entered.wait(3)
        assert jobs.get(first.id).state == "running"
        assert jobs.submit(Repository("acme", "skills")).id == first.id
        second = jobs.submit(Repository("acme", "second"))
        assert second.state == "queued"
        with pytest.raises(QueueFull, match="full"):
            jobs.submit(Repository("acme", "third"))
        release.set()
        assert await_state(jobs, second.id, "succeeded").skill_count == 2
        assert jobs.get(first.id) is None
        assert len(jobs.recent()) == 1
    finally:
        release.set()
        jobs.close()
    with pytest.raises(QueueFull, match="stopping"):
        jobs.submit(scan_result.repository)


def test_worker_recovers_from_expected_and_unexpected_failures(scan_result):
    outcomes = iter([RepositoryError("Permission denied"), RuntimeError("secret"), scan_result])

    def scan(repository):
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        return result

    jobs = ScanJobs(scan)
    jobs.start()
    try:
        first = jobs.submit(scan_result.repository)
        assert await_state(jobs, first.id, "failed").error == "Permission denied"
        second = jobs.submit(scan_result.repository)
        assert "secret" not in await_state(jobs, second.id, "failed").error
        third = jobs.submit(scan_result.repository)
        assert await_state(jobs, third.id, "succeeded").commit_sha == scan_result.commit_sha
    finally:
        jobs.close()


def test_shutdown_discards_queued_jobs(scan_result):
    jobs = ScanJobs(lambda repository: scan_result)
    job = jobs.submit(scan_result.repository)
    jobs.close()
    assert jobs.get(job.id) is None


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


def test_rendering_escapes_html_pins_links_and_never_embeds_images(scan_result):
    skill = scan_result.skills[0]
    source = """---
name: example
---
# Example
<script>alert(1)</script>

[relative](../guide%20book.md?q=1#part)
[root](/README.md)
[fragment](#example)
[external](https://example.org)
[unsafe](javascript:alert(1))
![diagram](image.png)
<img src="https://evil.test/tracker">
"""
    output = render(Document(skill, source))
    assert output.frontmatter == "---\nname: example\n---\n"
    assert "<script>" not in output.html
    assert "<img" not in output.html
    assert 'href="javascript:' not in output.html
    assert f"{skill.repository.url}/blob/{skill.commit_sha}/guide%20book.md?q=1#part" in output.html
    assert f"{skill.repository.url}/blob/{skill.commit_sha}/README.md" in output.html
    assert f"{skill.repository.url}/blob/{skill.commit_sha}/review/image.png" in output.html
    assert 'href="#example"' in output.html
    assert 'href="https://example.org"' in output.html
    assert "diagram (image)" in output.html
    assert render(Document(skill, "Plain text")).frontmatter == ""
